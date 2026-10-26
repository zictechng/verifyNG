
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

    if request.user.is_authenticated:
        active_subscription = get_active_subscription(request.user)
        free_quota = FreeUsageQuota.for_user(request.user)

    context = {
        'plans': plans,
        'active_subscription': active_subscription,
        'free_quota': free_quota,
        'site_settings': site_settings,
        'page_title': 'Plans & Pricing',
    }
    return render(request, 'payments/plans.html', context)


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


def _route_payg_success(request, transaction):
    meta = (
        transaction.paystack_response.get('data', {}).get('metadata')
        or {}
    )
    service = meta.get('service', '')
    if service == 'certificate':
        cert_id = meta.get('certificate_id')
        if cert_id:
            messages.success(
                request,
                f"Payment of ₦{transaction.amount_naira:,.0f} verified successfully! "
                f"Your TrustPass Clearance Application [{cert_id}] has been submitted for review."
            )
            return redirect('verification:my_certificate', certificate_id=cert_id)
    elif service == 'staff_check':
        check_id = meta.get('staff_check_id')
        if check_id:
            messages.success(
                request,
                f"Payment of ₦{transaction.amount_naira:,.0f} verified successfully! "
                "Your staff background check is now processing."
            )
            return redirect('employer:staff_check_detail', check_id=check_id)
    elif service in ('verification', 'business_verification'):
        req_ref = meta.get('verification_reference')
        if req_ref:
            messages.success(
                request,
                f"Payment of ₦{transaction.amount_naira:,.0f} verified successfully! "
                f"Verification request [{req_ref}] is now pending officer review."
            )
            return redirect('verification:detail', reference_number=req_ref)
    elif service in ('person_check', 'quick_check'):
        from django.urls import reverse
        query = meta.get('query') or request.session.pop('pending_person_check_query', '')
        messages.success(
            request,
            f"Payment of ₦{transaction.amount_naira:,.0f} verified successfully! Here is your quick-check result."
        )
        url = reverse('employer:person_check_search')
        if query:
            url += f"?paid_ref={transaction.reference}&query={query}"
        return redirect(url)
    elif service in ('public_check', 'check'):
        from django.urls import reverse
        id_type = meta.get('identifier_type', '')
        id_val = meta.get('identifier_value', '')
        messages.success(
            request,
            f"Payment of ₦{transaction.amount_naira:,.0f} verified successfully! Here is your trust search result."
        )
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
        messages.success(
            request,
            f"Payment of ₦{transaction.amount_naira:,.0f} verified! Here is your certificate status check."
        )
        url = reverse('employer:certificate_verify')
        if cert_id:
            url += f"?paid_ref={transaction.reference}&certificate_id={cert_id}&surname={surname}&date_of_birth={dob}"
        return redirect(url)
    elif service == 'monitoring':
        cert_id = meta.get('certificate_id')
        staff_check_id = meta.get('staff_check_id')
        if cert_id:
            request.session['update_service_cert_id'] = cert_id
            messages.success(
                request,
                f"Payment of ₦{transaction.amount_naira:,.0f} verified successfully! "
                "Your certificate is now registered on the Continuous Update Service."
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
    """Dashboard page showing the user's current subscription and recent transactions."""
    active_sub = get_active_subscription(request.user)
    recent_transactions = (
        Transaction.objects.filter(user=request.user)
        .select_related('plan')
        .order_by('-created_at')[:10]
    )
    free_quota = FreeUsageQuota.for_user(request.user)
    site_settings = SiteSettings.get()
    plans = Plan.objects.filter(is_active=True).order_by('display_order', 'price_kobo')

    context = {
        'active_subscription': active_sub,
        'recent_transactions': recent_transactions,
        'free_quota': free_quota,
        'site_settings': site_settings,
        'plans': plans,
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

