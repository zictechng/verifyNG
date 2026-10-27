
# payments/views.py
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from core.rate_limiting import get_client_ip
from core.rate_limiting import check_rate_limit

from .models import FreeUsageQuota, Plan, SiteSettings, Subscription, Transaction, PaymentAuditLog
from .services import (
    get_active_subscription,
    get_user_prepaid_balance,
    initialize_transaction,
    process_webhook_event,
    verify_transaction,
    verify_webhook_signature,
)
from .tasks import verify_pending_transaction
from core.rate_limiting import get_client_ip

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public — Plans listing
# ---------------------------------------------------------------------------

def plans_list(request):
    """
    Mobile-first pricing page.
    Loads all active plans + their features.  Admin controls everything.
    """
    site_settings = SiteSettings.get()

    if site_settings.maintenance_mode:
        return render(request, 'payments/maintenance.html')

    plans = (
        Plan.objects.filter(is_active=True)
        .prefetch_related('features')
        .order_by('display_order', 'price_kobo')
    )

    active_subscription = None
    free_quota = None
    user_balance = 0

    if request.user.is_authenticated:
        active_subscription = get_active_subscription(request.user)
        free_quota = FreeUsageQuota.for_user(request.user)
        from .services import get_user_prepaid_balance
        user_balance = get_user_prepaid_balance(request.user)

    context = {
        'plans': plans,
        'active_subscription': active_subscription,
        'free_quota': free_quota,
        'user_balance': user_balance,
        'site_settings': site_settings,
        'page_title': 'Plans & Pricing',
    }
    return render(request, 'payments/plans.html', context)


@login_required
def dismiss_prepaid_banner(request):
    """Marks the dashboard pre-paid reminder banner as dismissed in user session."""
    request.session['dismissed_prepaid_banner'] = True
    request.session['dismissed_employer_prepaid_banner'] = True
    from django.http import JsonResponse
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        return JsonResponse({'ok': True})
    next_url = request.GET.get('next') or request.META.get('HTTP_REFERER') or '/'
    return redirect(next_url)


# ---------------------------------------------------------------------------
# Authenticated — Checkout Review & Confirmation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Authenticated — Service-Level Pay-As-You-Go Review & Execution
# ---------------------------------------------------------------------------

@login_required
def service_checkout_review(request, service_key):
    """
    Displays an Order Review & Confirmation screen for any Pay-As-You-Go service
    before redirecting off-site to Paystack.
    """
    site_settings = SiteSettings.get()
    tier = request.GET.get('tier', 'standard')

    service_catalog = {
        'public_check': {
            'name': 'Public Trust & Safety Search / Record Lookup',
            'badge': 'Single Record Search',
            'description': 'Real-time cryptographic database check for Phone Numbers, NIN, Bank Accounts, or CAC Registration numbers.',
            'coverage': 'Instant Search Result & Alert History',
            'price': site_settings.price_public_check,
            'tier': 'standard',
        },
        'person_check': {
            'name': 'Person Quick-Check / Tenant Screening',
            'badge': 'Single Person Query',
            'description': 'Instant phone / NIN reputation check, fraud allegations history, and trust clearance query.',
            'coverage': 'Instant Reputation & Alert Summary',
            'price': site_settings.price_person_check,
            'tier': 'standard',
        },
        'certificate_verify': {
            'name': 'Workforce Certificate Status Verification',
            'badge': 'Single Credential Check',
            'description': 'Employer 3-point credential validity confirmation and revocation check.',
            'coverage': 'Instant Verification Verdict',
            'price': site_settings.price_certificate_verify,
            'tier': 'standard',
        },
        'staff_check': {
            'name': 'Staff Background Investigation (Enhanced)' if tier == 'enhanced' else 'Staff Background Investigation (Standard)',
            'badge': 'Executive Due Diligence' if tier == 'enhanced' else 'Standard Pre-Employment Check',
            'description': 'Comprehensive executive screening including multi-registry check and physical vetting.' if tier == 'enhanced' else 'Standard single staff check verifying NIN, phone, adverse employment history, and fraud alerts.',
            'coverage': 'Official Officer Review & Downloadable Summary',
            'price': site_settings.price_staff_check_enhanced if tier == 'enhanced' else site_settings.price_staff_check_standard,
            'tier': tier,
        },
        'certificate': {
            'name': 'TrustPass Clearance Certificate (Enhanced - 3 Years)' if tier == 'enhanced' else 'TrustPass Clearance Certificate (Standard - 1 Year)',
            'badge': '3-Year Management Credential' if tier == 'enhanced' else '1-Year Workplace Credential',
            'description': 'Multi-identifier integrity clearance certificate with continuous monitoring eligibility.' if tier == 'enhanced' else 'Official candidate workplace integrity credential with tamper-evident QR verification code.',
            'coverage': 'Tamper-Evident Digital Certificate + PDF',
            'price': site_settings.price_trustpass_3yr if tier == 'enhanced' else site_settings.price_trustpass_1yr,
            'tier': tier,
        },
        'verification': {
            'name': (
                'Full Comprehensive Due Diligence (Property, Land & Vehicles)' if tier == 'full_check'
                else ('Corporate & CAC Business Due Diligence' if tier == 'business'
                else 'Document & Identity Verification (Basic)')
            ),
            'badge': (
                'Fieldwork & Multi-Registry Vetting' if tier == 'full_check'
                else ('CAC Company Investigation' if tier == 'business'
                else 'Identity & Address Document Diligence')
            ),
            'description': (
                'Officer search at Lands Bureau for C of O / Deeds, customs clearance status for vehicle VINs, or commercial contract vetting.' if tier == 'full_check'
                else ('Official CAC registry inspection for status report, listed directors, registered office, and active standing.' if tier == 'business'
                else 'Primary-source verification of government identity documents or utility address proof.')
            ),
            'coverage': 'Official Tamper-Evident Verification Report Issued by Officers',
            'price': site_settings.price_verification_business if tier in ('business', 'full_check') else site_settings.price_verification_basic,
            'tier': tier,
        },
        'monitoring': {
            'name': 'Certificate Monitoring Services (TrustPass)',
            'badge': '365-Day Active Verification Standing',
            'description': (
                'Continuous workforce trust assurance: real-time validation and active standing for your employed personnel.'
                if (request.user.is_authenticated and getattr(request.user, 'is_employer', False))
                else 'Enables employers and landlords to easily verify your active certificate and build trust, without paying for repeat checks each time you prove your integrity for jobs or tenancy.'
            ),
            'coverage': '1-Year Active Verification Standing',
            'price': site_settings.price_monitoring_annual,
            'tier': 'annual',
        },
    }

    item = service_catalog.get(service_key)
    if not item:
        messages.error(request, "Selected service is not recognized.")
        return redirect('payments:plans')

    if service_key == 'monitoring' and request.user.is_authenticated and not (request.user.is_staff or request.user.is_superuser):
        from core.permissions import is_employer
        if is_employer(request.user):
            messages.info(request, "Employers verify candidate certificates via the Verify Certificate tool. The Continuous Update Service is managed directly by the individual certificate holder.")
            return redirect('employer:certificate_verify')

    return render(request, 'payments/service_checkout_review.html', {
        'service_key': service_key,
        'item': item,
        'tier': tier,
        'site_settings': site_settings,
        'page_title': f'Review Order: {item["name"]}',
    })


@login_required
def service_checkout_execute(request, service_key):
    """
    Initiates Paystack checkout for a Pay-As-You-Go single service order
    and redirects the customer to Paystack.
    """
    tier = request.GET.get('tier') or request.POST.get('tier') or 'standard'
    site_settings = SiteSettings.get()
    if site_settings.maintenance_mode:
        messages.error(request, "Payments are temporarily unavailable. Please try again later.")
        return redirect('payments:plans')

    amount = site_settings.get_service_price(service_key, tier)
    if not amount or amount <= 0:
        messages.error(request, "Invalid service pricing.")
        return redirect('payments:plans')

    if service_key == 'monitoring' and not (request.user.is_staff or request.user.is_superuser):
        from core.permissions import is_employer
        if is_employer(request.user):
            messages.info(request, "Employers verify candidate certificates via the Verify Certificate tool. The Continuous Update Service is managed directly by the individual certificate holder.")
            return redirect('employer:certificate_verify')

    from payments.services import initialize_service_checkout
    try:
        checkout_data = initialize_service_checkout(
            user=request.user,
            service=service_key,
            tier=tier,
            amount_naira=amount,
            metadata={
                'service': service_key,
                'tier': tier,
            }
        )
        request.session['vng_pending_ref'] = checkout_data['reference']
        return redirect(checkout_data['authorization_url'])
    except Exception as exc:
        logger.exception("Failed to initialize service checkout for %s: %s", service_key, exc)
        messages.error(request, "We could not connect to Paystack payment gateway. Please try again.")
        return redirect('payments:plans')

@login_required
def checkout_review(request, plan_slug):
    """
    Renders an Order Summary & Confirmation screen for the selected plan
    before the user proceeds to Paystack.
    """
    plan = get_object_or_404(Plan, slug=plan_slug, is_active=True)
    existing = get_active_subscription(request.user)
    if existing and existing.plan_id == plan.id:
        messages.info(request, f"You already have an active {plan.name} subscription.")
        return redirect('payments:my_subscription')

    site_settings = SiteSettings.get()
    return render(request, 'payments/checkout_review.html', {
        'plan': plan,
        'site_settings': site_settings,
        'page_title': f'Review Order: {plan.name}',
    })


# ---------------------------------------------------------------------------
# Authenticated — Checkout
# ---------------------------------------------------------------------------

@login_required
def checkout(request, plan_slug):
    """
    Initiates a Paystack payment for the chosen plan.
    Free plans are activated directly without a payment redirect.
    """
    # Rate limit: max 10 checkout attempts per hour per IP
    
    is_limited, retry_after = check_rate_limit(request, namespace='payments_checkout', limit=10, window=3600)
    if is_limited:
        messages.error(request, "Too many payment attempts. Please wait before trying again.")
        return redirect('payments:plans')

    site_settings = SiteSettings.get()
    if site_settings.maintenance_mode:
        messages.error(request, "Payments are temporarily unavailable. Please try again later.")
        return redirect('payments:plans')

    plan = get_object_or_404(Plan, slug=plan_slug, is_active=True)

    # Prevent double-paying for the same active plan
    existing = get_active_subscription(request.user)
    if existing and existing.plan_id == plan.id:
        messages.info(request, f"You already have an active {plan.name} subscription.")
        return redirect('payments:my_subscription')

    # Free plan — activate directly, no payment needed
    if plan.is_free:
        _activate_free_plan(request.user, plan)
        messages.success(request, f"You're now on the {plan.name} plan!")
        return redirect('payments:my_subscription')

    try:
        result = initialize_transaction(request.user, plan)
    except RuntimeError as exc:
        logger.error("checkout initialize_transaction failed: %s", exc)
        messages.error(request, "We could not connect to the payment gateway. Please try again.")
        return redirect('payments:plans')

    # Store reference in session so callback can verify without a GET param being tampered
    request.session['vng_pending_ref'] = result['reference']
    PaymentAuditLog.objects.create(
        action='CHECKOUT_INITIATED',
        user=request.user,
        ip_address=get_client_ip(request),
        details={'plan_name': plan.name, 'plan_slug': plan.slug, 'reference': result['reference']},
    )

    return redirect(result['authorization_url'])


def _activate_free_plan(user, plan: Plan):
    """Directly activate a free plan for a user."""
    from django.utils import timezone

    # Expire any existing active sub
    Subscription.objects.filter(user=user, status='active').update(
        status='expired', updated_at=timezone.now()
    )
    Subscription.objects.create(
        user=user,
        plan=plan,
        status='active',
        current_period_start=timezone.now(),
        current_period_end=None,  # Free plan — no expiry
    )
    PaymentAuditLog.objects.create(
        action='FREE_PLAN_ACTIVATED',
        user=user,
        details={'plan_name': plan.name, 'plan_id': plan.id},
    )
    logger.info("Free plan activated for user=%s plan=%s", user.username, plan.name)


# ---------------------------------------------------------------------------
# Payment Callback (Paystack redirects user here after payment)
# ---------------------------------------------------------------------------


def _get_service_display_name(service: str, tier: str, amount_naira: float) -> str:
    if service in ('verification', 'business_verification'):
        if tier in ('full_check', 'business', 'business_cac', 'cac', 'corporate', 'property', 'vehicle', 'contract') or amount_naira >= 3500:
            return "Full Comprehensive Due Diligence Verification"
        return "Standard Identity Verification"
    elif service == 'certificate':
        if tier in ('standard', 'comprehensive') or amount_naira >= 3500:
            return "Comprehensive TrustPass Clearance Certificate"
        return "Basic TrustPass Clearance Certificate"
    elif service == 'staff_check':
        if tier == 'comprehensive' or amount_naira >= 2500:
            return "Comprehensive Staff Background Check"
        return "Standard Staff Background Check"
    elif service in ('public_check', 'check'):
        return "Public Record Lookup"
    elif service in ('person_check', 'quick_check'):
        return "Quick Identity Check"
    elif service == 'certificate_verify':
        return "Certificate Status Verification"
    return "Service Verification"


def _route_payg_success(request, transaction):
    meta = (
        transaction.paystack_response.get('data', {}).get('metadata')
        or {}
    )
    service = meta.get('service', '')
    tier = meta.get('tier', 'standard')

    service_title = _get_service_display_name(service, tier, transaction.amount_naira)
    success_msg = (
        f"Payment Successful! Your payment Reference {transaction.reference} "
        f"(₦{transaction.amount_naira:,.0f}) for {service_title} has been confirmed. "
        "You may now proceed with your request."
    )

    if service == 'certificate':
        cert_id = meta.get('certificate_id')
        messages.success(request, success_msg)
        if cert_id:
            return redirect('verification:my_certificate', certificate_id=cert_id)
        return redirect(f"/verification/certificate/apply/?paid_ref={transaction.reference}&level={tier}")

    elif service == 'staff_check':
        check_id = meta.get('staff_check_id')
        messages.success(request, success_msg)
        if check_id:
            return redirect('employer:staff_check_detail', check_id=check_id)
        return redirect(f"/employer/checks/new/?paid_ref={transaction.reference}&tier={tier}")

    elif service in ('verification', 'business_verification'):
        req_ref = meta.get('verification_reference')
        messages.success(request, success_msg)
        if req_ref:
            return redirect('verification:detail', reference_number=req_ref)
        return redirect(f"/verification/new/?paid_ref={transaction.reference}&type={tier}")

    elif service in ('person_check', 'quick_check'):
        from django.urls import reverse
        query = meta.get('query') or request.session.pop('pending_person_check_query', '')
        messages.success(request, success_msg)
        url = reverse('employer:person_check_search')
        if query:
            url += f"?paid_ref={transaction.reference}&query={query}"
        return redirect(url)

    elif service in ('public_check', 'check'):
        from django.urls import reverse
        id_type = meta.get('identifier_type', '')
        id_val = meta.get('identifier_value', '')
        messages.success(request, success_msg)
        url = reverse('check')
        params = [f"paid_ref={transaction.reference}"]
        if id_type:
            params.append(f"type={id_type}")
        if id_val:
            params.append(f"q={id_val}")
        return redirect(f"{url}?{'&'.join(params)}")

    elif service == 'certificate_verify':
        from django.urls import reverse
        cert_id = meta.get('certificate_id', '')
        surname = meta.get('surname', '')
        dob = meta.get('dob', '')
        messages.success(request, success_msg)
        url = reverse('employer:certificate_verify')
        if cert_id:
            url += f"?paid_ref={transaction.reference}&certificate_id={cert_id}&surname={surname}&date_of_birth={dob}"
        return redirect(url)
    elif service == 'monitoring':
        cert_id = meta.get('certificate_id')
        staff_check_id = meta.get('staff_check_id')
        if cert_id:
            from datetime import timedelta
            from django.utils import timezone
            from verification.models import VerificationCertificate
            from core.audit_utils import log_admin_action
            cert = VerificationCertificate.objects.filter(certificate_id=cert_id, is_active=True).first()
            if cert:
                cert.is_monitoring_active = True
                cert.monitoring_activated_at = timezone.now()
                cert.monitoring_expires_at = timezone.now() + timedelta(days=365)
                cert.save(update_fields=['is_monitoring_active', 'monitoring_activated_at', 'monitoring_expires_at', 'updated_at'])

                log_admin_action(
                    action='UPDATE_SERVICE_ENROLLED',
                    action_type='VERIFICATION',
                    performed_by=cert.holder or (request.user if request.user.is_authenticated else None),
                    request=request,
                    details={
                        'certificate_id': cert.certificate_id,
                        'transaction_reference': transaction.reference,
                        'amount_naira': float(transaction.amount_naira) if hasattr(transaction, 'amount_naira') else 0,
                        'expires_at': cert.monitoring_expires_at.isoformat(),
                        'phone_number': meta.get('phone', ''),
                        'residential_address': meta.get('address', ''),
                        'email': meta.get('email', ''),
                    }
                )

            request.session['update_service_cert_id'] = cert_id
            messages.success(
                request,
                f"Payment of ₦{transaction.amount_naira:,.0f} verified successfully! "
                "Your certificate is now registered on the Continuous Update Service for 1 year."
            )
            return redirect('verification:update_service_portal')
        elif staff_check_id:
            messages.success(
                request,
                f"Payment of ₦{transaction.amount_naira:,.0f} verified successfully! "
                "Certificate Monitoring Services (TrustPass) is now active."
            )
            return redirect('employer:staff_check_detail', check_id=staff_check_id)
        return redirect('employer:monitoring_list')
    return None

@login_required
def payment_callback(request):
    """
    Paystack redirects the user here after payment.
    We verify with Paystack's API (never trust the URL params alone).
    """
    # Paystack sends ?reference=xxx or ?trxref=xxx
    reference = request.GET.get('reference') or request.GET.get('trxref', '')
    session_ref = request.session.pop('vng_pending_ref', '')

    # Use session ref as fallback; they must agree if both present
    if not reference:
        reference = session_ref
    elif session_ref and reference != session_ref:
        logger.warning(
            "Callback reference mismatch: GET=%s session=%s user=%s",
            reference, session_ref, request.user.id
        )
        messages.error(request, "Invalid payment reference. Please contact support.")
        return redirect('payments:plans')

    if not reference:
        messages.error(request, "No payment reference found.")
        return redirect('payments:plans')

    # Ensure the transaction belongs to this user
    try:
        transaction = Transaction.objects.select_related('plan').get(
            reference=reference,
            user=request.user,
        )
    except Transaction.DoesNotExist:
        messages.error(request, "Transaction not found.")
        return redirect('payments:plans')

    # If already verified (e.g. webhook beat us here), show result immediately
    if transaction.status == 'success':
        # Route certificate query payments to the dedicated result view
        if request.session.get('pending_cert_query', {}).get('transaction_reference') == reference:
            return redirect('verification:certificate_query_result')
        if not transaction.plan:
            payg_redirect = _route_payg_success(request, transaction)
            if payg_redirect:
                return payg_redirect
        return render(request, 'payments/callback.html', {
            'success': True,
            'transaction': transaction,
            'page_title': 'Payment Successful',
        })

    if transaction.status == 'failed':
        messages.error(
            request,
            f"Payment Unsuccessful: Your payment Reference {transaction.reference} could not be completed. No charge has been made to your account."
        )
        return render(request, 'payments/callback.html', {
            'success': False,
            'transaction': transaction,
            'page_title': 'Payment Failed',
        })

    # Verify with Paystack
    try:
        transaction = verify_transaction(reference)
    except Exception as exc:
        # Fire async retry just in case
        verify_pending_transaction.apply_async(args=[reference], countdown=5)
        logger.error("Callback verify failed (ref=%s): %s", reference, exc)
        messages.warning(
            request,
            "We're confirming your payment in the background. "
            "You'll receive an email once it's confirmed."
        )
        return redirect('payments:my_subscription')

    success = transaction.status == 'success'
    PaymentAuditLog.objects.create(
        action='PAYMENT_SUCCESS' if success else 'PAYMENT_FAILED',
        user=request.user,
        transaction=transaction,
        ip_address=get_client_ip(request),
        details={'reference': reference, 'plan_name': transaction.plan.name if transaction.plan else ''},
    )

    # If this payment was for a certificate query, route to the cert result view
    if success and request.session.get('pending_cert_query', {}).get('transaction_reference') == reference:
        return redirect('verification:certificate_query_result')

    if success and not transaction.plan:
        payg_redirect = _route_payg_success(request, transaction)
        if payg_redirect:
            return payg_redirect

    if not success:
        messages.error(
            request,
            f"Payment Unsuccessful: Your payment Reference {transaction.reference} could not be completed. No charge has been made to your account."
        )

    context = {
        'success': success,
        'transaction': transaction,
        'page_title': 'Payment Successful' if success else 'Payment Failed',
    }
    return render(request, 'payments/callback.html', context)


# ---------------------------------------------------------------------------
# Paystack Webhook (server-to-server, CSRF exempt)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_POST
def paystack_webhook(request):
    """
    Receives and processes Paystack webhook events.
    HMAC-SHA512 signature verified before any processing.
    """
    signature = request.headers.get('X-Paystack-Signature', '')
    if not signature:
        return HttpResponse(status=400)

    payload_bytes = request.body
    if not verify_webhook_signature(payload_bytes, signature):
        logger.warning("Paystack webhook: invalid signature")
        return HttpResponse(status=401)

    try:
        event = json.loads(payload_bytes)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    try:
        process_webhook_event(event)
    except Exception as exc:
        logger.error("Webhook processing error (event=%s): %s", event.get('event'), exc)
        # Return 200 so Paystack doesn't retry endlessly for non-transient errors
        return HttpResponse(status=200)

    return HttpResponse(status=200)


# ---------------------------------------------------------------------------
# Authenticated — My Subscription
# ---------------------------------------------------------------------------

@login_required
def my_subscription(request):
    """Dashboard page showing the user's current subscription, available prepaid balance, and recent transactions."""
    active_sub = get_active_subscription(request.user)
    recent_transactions = (
        Transaction.objects.filter(user=request.user)
        .select_related('plan')
        .order_by('-created_at')[:10]
    )
    free_quota = FreeUsageQuota.for_user(request.user)
    site_settings = SiteSettings.get()
    plans = Plan.objects.filter(is_active=True).order_by('display_order', 'price_kobo')
    user_balance = get_user_prepaid_balance(request.user)

    context = {
        'active_subscription': active_sub,
        'recent_transactions': recent_transactions,
        'free_quota': free_quota,
        'site_settings': site_settings,
        'plans': plans,
        'user_balance': user_balance,
        'page_title': 'My Subscription',
    }
    return render(request, 'payments/my_subscription.html', context)


# ---------------------------------------------------------------------------
# Authenticated — Cancel Subscription
# ---------------------------------------------------------------------------

@login_required
@require_POST
def cancel_subscription(request):
    """
    Cancel the user's active subscription at period end.
    POST-only to prevent CSRF via GET.
    """
    from django.utils import timezone

    active_sub = get_active_subscription(request.user)
    if not active_sub:
        messages.error(request, "You don't have an active subscription to cancel.")
        return redirect('payments:my_subscription')

    active_sub.cancel_at_period_end = True
    active_sub.cancelled_at = timezone.now()
    active_sub.save(update_fields=['cancel_at_period_end', 'cancelled_at', 'updated_at'])
    
    PaymentAuditLog.objects.create(
        action='SUBSCRIPTION_CANCELLED',
        user=request.user,
        subscription=active_sub,
        ip_address=get_client_ip(request),
        details={'plan_name': active_sub.plan.name, 'period_end': str(active_sub.current_period_end)},
    )
    logger.info(
        "Subscription cancel_at_period_end set (user=%s, sub=%s)",
        request.user.username, active_sub.id
    )

    messages.success(
        request,
        f"Your {active_sub.plan.name} subscription will remain active until "
        f"{active_sub.current_period_end.strftime('%d %B %Y') if active_sub.current_period_end else 'the end of your period'}. "
        "It will not renew."
    )
    return redirect('payments:my_subscription')


# ---------------------------------------------------------------------------
# Authenticated — Transaction History
# ---------------------------------------------------------------------------

@login_required
def transaction_history(request):
    """Full paginated transaction history for the authenticated user."""
    from django.core.paginator import Paginator

    transactions_qs = (
        Transaction.objects.filter(user=request.user)
        .select_related('plan')
        .order_by('-created_at')
    )
    paginator = Paginator(transactions_qs, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'page_title': 'Transaction History',
    }
    return render(request, 'payments/transaction_history.html', context)

