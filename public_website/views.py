# public_website/views.py
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render

from core.rate_limiting import check_rate_limit, get_client_ip
from reports.forms import FraudReportSubmissionForm
from reports.services import create_fraud_report
from reports.storage_services import StorageError
from verification.forms import VerificationRequestCreateForm
from verification.services import create_verification_request
from core.models import SiteConfiguration
from django.conf import settings
from django.utils import timezone
from notifications.tasks import send_broadcast_email_task
from notifications.email_service import send_email
from core.email_utils import render_email

logger = logging.getLogger(__name__)


def home(request):
    return render(request, 'public/home.html')


def business(request):
    """
    Dedicated landing page for Small and Medium Enterprises (SMEs) across Africa.
    Features:
    - Initial fraud & trust problems faced by African SMEs (fake alerts, rogue vendors, dispatch theft).
    - Bridges provided by VerifyNG (Pre-trade verification, TrustPass™ business badge, staff due diligence).
    - Why SMEs rely on the platform daily for pan-African commerce & cross-border trade.
    """
    return render(request, 'public/business.html')


def check(request):
    is_limited, retry_after = check_rate_limit(request, namespace="web_check")
    if is_limited:
        response = HttpResponse(
            "Rate limit exceeded. Please wait before retrying.",
            status=429,
            content_type="text/plain; charset=utf-8"
        )
        response['Retry-After'] = str(retry_after)
        return response

    import uuid
    from payments.models import SiteSettings, Transaction
    from payments.services import (
        check_user_entitlement,
        initialize_service_checkout,
        get_user_prepaid_balance,
        deduct_user_prepaid_balance,
        get_topup_difference,
    )
    from django.contrib import messages
    from django.shortcuts import redirect
    site_settings = SiteSettings.get()
    payg_price = site_settings.get_service_price('public_check')

    user_balance = get_user_prepaid_balance(request.user) if request.user.is_authenticated else 0
    topup_needed = get_topup_difference(user_balance, payg_price) if request.user.is_authenticated else payg_price

    # Handle direct Paystack Pay-As-You-Go checkout submission
    if request.method == 'POST':
        action = request.POST.get('action', 'search')
        if action == 'payg':
            if not request.user.is_authenticated:
                messages.info(request, "Please sign in or create an account to proceed with checkout.")
                from django.urls import reverse
                return redirect(f"{reverse('users:login')}?next={request.get_full_path()}")

            id_type = request.POST.get('identifier_type', '').strip()
            id_val = request.POST.get('identifier_value', '').strip()

            # 1. Full coverage from user available account balance
            if user_balance >= payg_price:
                ok, rem_bal = deduct_user_prepaid_balance(request.user, payg_price, "Public Record Lookup")
                if ok:
                    paid_token = f"VNG-BAL-{uuid.uuid4().hex[:12].upper()}"
                    Transaction.objects.create(
                        user=request.user,
                        reference=paid_token,
                        amount_kobo=payg_price * 100,
                        status='success',
                        is_active=False,
                        paystack_response={
                            'data': {
                                'metadata': {
                                    'service': 'public_check',
                                    'identifier_type': id_type,
                                    'identifier_value': id_val,
                                    'payment_method': 'account_balance',
                                }
                            }
                        }
                    )
                    messages.success(
                        request,
                        f"₦{payg_price:,.0f} deducted from your account balance (Remaining balance: ₦{rem_bal:,.0f}). "
                        "Query unlocked."
                    )
                    from django.urls import reverse
                    url = reverse('check')
                    params = [f"paid_ref={paid_token}"]
                    if id_type:
                        params.append(f"type={id_type}")
                    if id_val:
                        params.append(f"q={id_val}")
                    return redirect(f"{url}?{'&'.join(params)}")

            # 2. Partial coverage from balance + top-up difference via Paystack
            checkout_amount = payg_price
            covered_amount = 0
            if 0 < user_balance < payg_price:
                covered_amount = user_balance
                checkout_amount = topup_needed
                deduct_user_prepaid_balance(request.user, user_balance, "Partial top-up for Public Search")

            try:
                checkout_data = initialize_service_checkout(
                    user=request.user,
                    service='public_check',
                    tier='standard',
                    amount_naira=checkout_amount,
                    metadata={
                        'service': 'public_check',
                        'identifier_type': id_type,
                        'identifier_value': id_val,
                        'covered_by_balance': covered_amount,
                    }
                )
                request.session['vng_pending_ref'] = checkout_data['reference']
                return redirect(checkout_data['authorization_url'])
            except Exception as e:
                # Refund partially deducted balance on checkout initialization failure
                if covered_amount > 0:
                    Transaction.objects.create(
                        user=request.user,
                        reference=f"VNG-REFUND-{uuid.uuid4().hex[:12].upper()}",
                        amount_kobo=covered_amount * 100,
                        status='success',
                        is_active=True,
                        paystack_response={
                            'data': {
                                'metadata': {
                                    'service': 'topup',
                                    'reason': 'Checkout initialization failure refund'
                                }
                            }
                        }
                    )
                logger.error("Public check PAYG checkout error (user=%s): %s", request.user.id, e)
                messages.error(request, f"Payment gateway error: {e}")

    # Check if user has a verified single query direct payment, unconsumed credit, or active account balance
    paid_ref = request.GET.get('paid_ref', '').strip()
    is_direct_paid = False

    if request.user.is_authenticated:
        if paid_ref:
            trx = Transaction.objects.filter(reference=paid_ref, user=request.user, status='success').first()
            if trx:
                meta = (trx.paystack_response or {}).get('data', {}).get('metadata', {})
                if meta.get('service') == 'public_check':
                    if trx.is_active or meta.get('payment_method') == 'account_balance':
                        is_direct_paid = True
        if not is_direct_paid and user_balance >= payg_price:
            is_direct_paid = True

    user_entitlement = None
    if request.user.is_authenticated:
        if paid_ref and is_direct_paid:
            user_entitlement = {
                'allowed': True,
                'reason': 'direct_paid',
                'details': {'remaining': 'Single Query Paid', 'used': 0, 'limit': 1},
            }
        else:
            allowed, reason, details = check_user_entitlement(request.user, service='public_check', cost=1)
            user_entitlement = {
                'allowed': allowed,
                'reason': reason,
                'details': details,
            }

    context = {
        'site_settings': site_settings,
        'payg_price': payg_price,
        'user_balance': user_balance,
        'topup_needed': topup_needed,
        'is_public_check_free': site_settings.is_service_free('public_check'),
        'user_entitlement': user_entitlement,
        'is_direct_paid': is_direct_paid,
        'paid_ref': paid_ref,
    }
    return render(request, 'public/check.html', context)



def safety_security(request):
    """
    Comprehensive Platform Purpose, Safety, Security & Fraud Prevention Guide.
    Showcases:
    - National Mission: Why VerifyNG was designed (stopping financial fraud, impersonation, rogue actors).
    - Individual Protection Shield: Golden rules for online transactions and consumer safety.
    - Business & SME Shield: Supplier due diligence, worker verification, and TrustPass™ reputation.
    - Community Reporting: Evidence requirements, human moderation, due process, and dispute rights.
    - Quick & Reliable Verification: Step-by-step guidance on checking bank accounts, phones, CAC, certificates.
    """
    return render(request, 'public/safety_security.html')


def privacy_legal(request, tab=None):
    """
    Dual-tab Privacy Policy and Legal/Terms view with instant mobile tab switching.
    """
    active_tab = tab or request.GET.get('tab', 'privacy')
    if active_tab not in ('privacy', 'legal'):
        active_tab = 'privacy'
    return render(request, 'public/privacy_legal.html', {'active_tab': active_tab})


@login_required
def report(request):
    """
    GET  — render blank FraudReportSubmissionForm.
    POST — validate, delegate to create_fraud_report(), redirect on success.

    Authentication: @login_required — anonymous reports are rejected (CLAUDE.md §6).
    Error handling:
      StorageError  → evidence upload failed; surface as a field-level form error.
      ValidationError → service-level business rule violation; surface as non-field error.
      Exception     → unexpected; log and surface as non-field error.
    """
    if request.method == 'POST':
        form = FraudReportSubmissionForm(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                fraud_report = create_fraud_report(
                    reporter=request.user,
                    subject_name=cd['subject_name'],
                    subject_type=cd['subject_type'],
                    title=cd['title'],
                    allegation=cd['allegation'],
                    incident_date=cd.get('incident_date'),
                    evidence_file=cd.get('evidence_file'),
                    evidence_type=cd.get('evidence_type'),
                    evidence_description=cd.get('evidence_description', ''),
                    suspect_phone=cd.get('suspect_phone'),
                    suspect_bank_account=cd.get('suspect_bank_account'),
                    suspect_bank_name=cd.get('suspect_bank_name'),
                    suspect_cac_number=cd.get('suspect_cac_number'),
                    suspect_email=cd.get('suspect_email'),
                    suspect_location=cd.get('suspect_location'),
                    suspect_state=cd.get('suspect_state'),
                    suspect_city=cd.get('suspect_city'),
                )
                messages.success(
                    request,
                    f"Your report has been submitted. Reference: {fraud_report.reference_number}"
                )
                return redirect('reports:detail', pk=fraud_report.pk)

            except StorageError as e:
                logger.warning("Evidence upload failed for user %s: %s", request.user.id, e)
                form.add_error(
                    'evidence_file',
                    "Evidence upload failed. Please try again or submit without a file."
                )
            except ValidationError as e:
                logger.warning("ValidationError in report submission for user %s: %s", request.user.id, e)
                form.add_error(None, e.message if hasattr(e, 'message') else str(e))
            except Exception as e:
                logger.exception("Unexpected error in report submission for user %s", request.user.id)
                form.add_error(None, "An unexpected error occurred. Please try again.")
    else:
        form = FraudReportSubmissionForm()

    return render(request, 'public/report.html', {'form': form})


@login_required
def verify(request):
    """
    GET  — render blank VerificationRequestCreateForm.
    POST — validate, delegate to create_verification_request(), redirect on success.

    Authentication: @login_required — unauthenticated users cannot submit verification requests.
    The requester's IP address is captured for audit logging.
    Error handling:
      ValidationError → service-level business rule; surfaced as non-field error.
      Exception       → unexpected; logged and surfaced as non-field error.
    """
    if request.method == 'POST':
        form = VerificationRequestCreateForm(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                verification_request = create_verification_request(
                    requester=request.user,
                    subject_name=cd['subject_name'],
                    subject_type=cd['subject_type'],
                    verification_type=cd['verification_type'],
                    notes=cd.get('notes', ''),
                    identifier_type=cd.get('identifier_type') or None,
                    identifier_value=cd.get('identifier_value') or None,
                    ip_address=get_client_ip(request),
                    documents=cd.get('documents') or request.FILES.getlist('document'),
                )
                messages.success(
                    request,
                    f"Verification request submitted. Reference: {verification_request.reference_number}"
                )
                return redirect('verification:detail', reference_number=verification_request.reference_number)

            except ValidationError as e:
                logger.warning(
                    "ValidationError in verification submission for user %s: %s",
                    request.user.id, e
                )
                form.add_error(None, e.message if hasattr(e, 'message') else str(e))
            except Exception as e:
                logger.exception(
                    "Unexpected error in verification submission for user %s", request.user.id
                )
                form.add_error(None, "An unexpected error occurred. Please try again.")
    else:
        form = VerificationRequestCreateForm()

    return render(request, 'public/verify.html', {'form': form})


def help_support(request):
    """
    Dedicated Help & Support / Complaint submission view.
    Routes user inquiries directly to the platform Support Email configured in admin settings.
    """
    config = SiteConfiguration.get_solo()
    admin_support_email = config.support_email or getattr(settings, 'SUPPORT_EMAIL', 'support@verifyng.com')
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        category = request.POST.get('category', 'General Support').strip()
        subject = request.POST.get('subject', '').strip()
        message = request.POST.get('message', '').strip()
        if not name or not email or not message:
            messages.error(request, "Please fill in all required fields (Name, Email, and Message).")
            return render(request, 'public/help.html', {
                'name': name,
                'email': email,
                'category': category,
                'subject': subject,
                'message': message,
                'support_email': admin_support_email,
            })
        account_info = "Guest User (Unauthenticated)"
        if request.user.is_authenticated:
            account_info = (
                f"User: {request.user.username} | "
                f"Role: {request.user.get_role_display()} | "
                f"Public ID: {request.user.public_id}"
            )

        email_subject = f"[{config.site_name}] {category}: {subject or 'New Inquiry'}"
        submitted_at = timezone.now().strftime('%d %b %Y, %I:%M %p UTC')

        # 1. Render Admin Notification using the official VerifyNG email layout
        html_body, text_body = render_email('support_inquiry', {
            'sender_name': name,
            'sender_email': email,
            'category': category,
            'subject_line': subject,
            'account_context': account_info,
            'submitted_at': submitted_at,
            'message_content': message,
        })

        try:
            send_broadcast_email_task.delay(
                to_email=admin_support_email,
                subject=email_subject,
                html_body=html_body,
                text_body=text_body,
            )
        except Exception:
            try:
                send_email(
                    to_email=admin_support_email,
                    subject=email_subject,
                    html_body=html_body,
                    text_body=text_body,
                )
            except Exception as e:
                logger.exception("Failed to send support inquiry email: %s", e)
                messages.error(
                    request,
                    f"Unable to deliver your request right now. Please email us directly at {admin_support_email}."
                )
                return render(request, 'public/help.html', {
                    'name': name,
                    'email': email,
                    'category': category,
                    'subject': subject,
                    'message': message,
                    'support_email': admin_support_email,
                })

        # 2. Send an automated branded acknowledgment receipt to the user
        try:
            ack_html, ack_text = render_email('generic_notification', {
                'user_name': name,
                'heading': 'We Received Your Support Request',
                'body_html': f"""
                    <p>Thank you for contacting {config.site_name} Support.</p>
                    <p>We have received your inquiry regarding <strong>{category}</strong>. Our support team will review your message and reply directly to this email address ({email}) shortly.</p>
                    <div style="background:#f5f5f7;border-radius:10px;padding:14px 18px;margin:18px 0;font-size:14px;color:#444;">
                        <strong style="color:#1d1d1f;">Subject:</strong> {subject or 'N/A'}<br>
                        <strong style="color:#1d1d1f;">Reference Time:</strong> {submitted_at}
                    </div>
                """,
                'cta_url': config.base_url,
                'cta_label': f'Visit {config.site_name}',
                'subject': f'[{config.site_name}] Support Request Received',
            })
            send_broadcast_email_task.delay(
                to_email=email,
                subject=f'[{config.site_name}] Support Request Received: {category}',
                html_body=ack_html,
                text_body=ack_text,
            )
        except Exception:
            pass
            try:
                send_email(
                    to_email=admin_support_email,
                    subject=email_subject,
                    html_body=html_body,
                    text_body=text_body,
                )
            except Exception as e:
                logger.exception("Failed to send support inquiry email: %s", e)
                messages.error(
                    request,
                    f"Unable to deliver your request right now. Please email us directly at {admin_support_email}."
                )
                return render(request, 'public/help.html', {
                    'name': name,
                    'email': email,
                    'category': category,
                    'subject': subject,
                    'message': message,
                    'support_email': admin_support_email,
                })
        messages.success(
            request,
            "Your support request has been submitted successfully! Our support team will review it and get back to you shortly."
        )
        return redirect('help')
    default_name = ''
    default_email = ''
    if request.user.is_authenticated:
        default_name = request.user.get_full_name() or request.user.username
        default_email = request.user.email
    return render(request, 'public/help.html', {
        'name': default_name,
        'email': default_email,
        'support_email': admin_support_email,
    })


