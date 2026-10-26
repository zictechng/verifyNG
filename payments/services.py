
# payments/services.py
"""
Paystack API service layer.
All HTTP calls to Paystack live here — views never call Paystack directly.
"""
import hashlib
import hmac
import logging
import uuid

import requests
from django.conf import settings
from django.utils import timezone

from .models import Plan, Subscription, Transaction, SiteSettings, FreeUsageQuota, PaymentAuditLog, PlatformConfiguration
from django.db.models import F
logger = logging.getLogger(__name__)

PAYSTACK_BASE_URL = 'https://api.paystack.co'


def _headers():
    return {
        'Authorization': f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        'Content-Type': 'application/json',
    }


def generate_reference():
    """Generate a unique VerifyNG transaction reference."""
    return f"VNG-{uuid.uuid4().hex[:16].upper()}"


def initialize_transaction(user, plan: Plan) -> dict:
    """
    Initialize a Paystack transaction for the given user and plan.

    Returns:
        {
            'authorization_url': str,  # redirect user here
            'reference': str,          # our reference stored in Transaction
            'access_code': str,
        }
    Raises:
        RuntimeError on Paystack API failure.
    """
    reference = generate_reference()

    # Create a pending Transaction record before redirecting
    transaction = Transaction.objects.create(
        user=user,
        plan=plan,
        reference=reference,
        amount_kobo=plan.price_kobo,
        currency=plan.currency,
        status='pending',
    )

    payload = {
        'email': user.email,
        'amount': plan.price_kobo,
        'currency': plan.currency,
        'reference': reference,
        'callback_url': _build_callback_url(),
        'metadata': {
            'user_id': user.id,
            'plan_id': plan.id,
            'plan_name': plan.name,
            'transaction_id': str(transaction.id),
        },
    }

    # For recurring plans, attach the Paystack plan code
    if plan.interval in ('monthly', 'yearly') and plan.paystack_plan_code:
        payload['plan'] = plan.paystack_plan_code

    try:
        response = requests.post(
            f'{PAYSTACK_BASE_URL}/transaction/initialize',
            json=payload,
            headers=_headers(),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        transaction.status = 'failed'
        err_msg = str(exc)
        if hasattr(exc, 'response') and exc.response is not None and exc.response.status_code == 401:
            err_msg = (
                "Paystack API Authentication Failed (HTTP 401 Unauthorized): "
                "The PAYSTACK_SECRET_KEY in your environment (.env) was rejected as invalid by Paystack. "
                "Please update your .env with an active Secret Key from your Paystack Dashboard."
            )
        transaction.failure_reason = err_msg
        transaction.save(update_fields=['status', 'failure_reason', 'updated_at'])
        logger.error("Paystack initialize failed (ref=%s): %s", reference, err_msg)
        raise RuntimeError(f"Payment gateway error: {err_msg}") from exc

    if not data.get('status'):
        transaction.status = 'failed'
        transaction.failure_reason = data.get('message', 'Unknown Paystack error')
        transaction.save(update_fields=['status', 'failure_reason', 'updated_at'])
        raise RuntimeError(data.get('message', 'Payment initialization failed'))

    result = data['data']
    transaction.paystack_reference = result.get('reference', '')
    transaction.paystack_response = data
    transaction.save(update_fields=['paystack_reference', 'paystack_response', 'updated_at'])

    return {
        'authorization_url': result['authorization_url'],
        'reference': reference,
        'access_code': result.get('access_code', ''),
    }


def _build_callback_url():
    from django.urls import reverse
    from django.conf import settings as django_settings
    base = getattr(django_settings, 'SITE_BASE_URL', 'http://localhost:8000')
    return base + reverse('payments:callback')


def verify_transaction(reference: str) -> dict:
    """
    Verify a transaction with Paystack and update the local Transaction record.

    Returns the Transaction object with updated status.
    Raises Transaction.DoesNotExist if reference not found locally.
    """
    transaction = Transaction.objects.select_related('user', 'plan').get(reference=reference)

    try:
        response = requests.get(
            f'{PAYSTACK_BASE_URL}/transaction/verify/{reference}',
            headers=_headers(),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.error("Paystack verify failed (ref=%s): %s", reference, exc)
        raise RuntimeError(f"Verification failed: {exc}") from exc

    paystack_data = data.get('data', {})
    paystack_status = paystack_data.get('status', 'failed')

    transaction.paystack_response = data
    transaction.paystack_reference = paystack_data.get('reference', '')

    if paystack_status == 'success':
        transaction.status = 'success'
        transaction.save(update_fields=['status', 'paystack_reference', 'paystack_response', 'updated_at'])
        if transaction.plan:
            _activate_subscription(transaction, paystack_data)
        else:
            _fulfill_payg_transaction(transaction, paystack_data)
    else:
        transaction.status = 'failed'
        transaction.failure_reason = paystack_data.get('gateway_response', 'Payment not successful')
        transaction.save(update_fields=['status', 'failure_reason', 'paystack_reference', 'paystack_response', 'updated_at'])

    return transaction


def _activate_subscription(transaction: Transaction, paystack_data: dict):
    """Create or update a Subscription when a transaction succeeds."""
    if not transaction.plan:
        return

    plan = transaction.plan
    now = timezone.now()

    # Calculate period end based on plan interval
    if plan.interval == 'monthly':
        from dateutil.relativedelta import relativedelta
        period_end = now + relativedelta(months=1)
    elif plan.interval == 'yearly':
        from dateutil.relativedelta import relativedelta
        period_end = now + relativedelta(years=1)
    else:
        # one_time — grant access for 30 days by default
        from datetime import timedelta
        period_end = now + timedelta(days=30)

    # Deactivate any existing active subscriptions for this user
    Subscription.objects.filter(
        user=transaction.user,
        status='active'
    ).update(status='expired', updated_at=now)

    subscription = Subscription.objects.create(
        user=transaction.user,
        plan=plan,
        status='active',
        paystack_customer_code=paystack_data.get('customer', {}).get('customer_code', ''),
        paystack_subscription_code=paystack_data.get('subscription_code', ''),
        current_period_start=now,
        current_period_end=period_end,
    )

    # Link subscription back to transaction
    transaction.subscription = subscription
    transaction.save(update_fields=['subscription', 'updated_at'])

    logger.info(
        "Subscription activated (user=%s, plan=%s, expires=%s)",
        transaction.user.username,
        plan.name,
        period_end.date(),
    )
    PaymentAuditLog.objects.create(
        action='SUBSCRIPTION_ACTIVATED',
        user=transaction.user,
        transaction=transaction,
        subscription=subscription,
        details={
            'plan_name': plan.name,
            'plan_id': plan.id,
            'period_end': str(period_end.date()),
        },
    )


def verify_webhook_signature(payload_bytes: bytes, paystack_signature: str) -> bool:
    """
    Verify Paystack webhook HMAC-SHA512 signature.
    Must be called before processing any webhook event.
    """
    secret = settings.PAYSTACK_SECRET_KEY.encode('utf-8')
    expected = hmac.new(secret, payload_bytes, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, paystack_signature)

def process_webhook_event(event: dict):
    """
    Process a verified Paystack webhook event.
    Idempotent — safe to call multiple times for the same event.
    """
    event_type = event.get('event', '')
    data = event.get('data', {})

    logger.info("Processing Paystack webhook event: %s", event_type)

    PaymentAuditLog.objects.create(
        action='WEBHOOK_RECEIVED',
        details={'event_type': event_type},
    )

    if event_type == 'charge.success':
        reference = data.get('reference', '')
        try:
            transaction = Transaction.objects.get(reference=reference)
            if transaction.status != 'success':
                verify_transaction(reference)
        except Transaction.DoesNotExist:
            logger.warning("Webhook charge.success for unknown reference: %s", reference)

    elif event_type == 'subscription.disable':
        sub_code = data.get('subscription_code', '')
        Subscription.objects.filter(
            paystack_subscription_code=sub_code
        ).update(status='cancelled', cancel_at_period_end=True, updated_at=timezone.now())
        PaymentAuditLog.objects.create(
            action='WEBHOOK_SUBSCRIPTION_DISABLED',
            details={'subscription_code': sub_code},
        )

    elif event_type == 'invoice.payment_failed':
        sub_code = data.get('subscription', {}).get('subscription_code', '')
        Subscription.objects.filter(
            paystack_subscription_code=sub_code
        ).update(status='past_due', updated_at=timezone.now())
        PaymentAuditLog.objects.create(
            action='WEBHOOK_PAYMENT_FAILED',
            details={'subscription_code': sub_code},
        )

def get_active_subscription(user) -> Subscription | None:
    """
    Return the user's current active subscription or None.
    If the user is a team member in an active employer organization,
    checks the organization owner's active subscription.
    """
    sub = Subscription.objects.filter(
        user=user,
        status='active',
        current_period_end__gt=timezone.now(),
    ).select_related('plan').first()
    if sub:
        return sub
    # Check team membership in employer organization
    try:
        memberships = getattr(user, 'employer_memberships', None)
        if memberships:
            mem = memberships.filter(is_active=True).select_related('employer__user').first()
            if mem and mem.employer and mem.employer.user:
                return Subscription.objects.filter(
                    user=mem.employer.user,
                    status='active',
                    current_period_end__gt=timezone.now(),
                ).select_related('plan').first()
    except Exception:
        pass
    return None


def check_user_entitlement(user, service: str = 'check', cost: int = 1) -> tuple[bool, str, dict]:
    """
    Universal service-by-service credit & subscription entitlement checker.
    Evaluates:
      1. Staff / Superuser administrative bypass.
      2. Service-level Account Restrictions (UserServiceAccess).
      3. Statutory Free Services (fraud_report, certificate_verify).
      4. Global Free Mode (PlatformConfiguration.free_access_mode).
      5. Per-User & Per-Agency VIP Waivers (User.is_billing_exempt / exempt_services).
      6. Per-Organization VIP Waivers (EmployerProfile.is_billing_exempt / exempt_services).
      7. Global Service Master Switch (SiteSettings.is_service_free).
      8. Active Commercial Subscription (Subscription check quota).
      9. Standard Free Tier Quota (FreeUsageQuota).
    """
    # 1. Staff / Superuser administrative bypass
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False):
        return True, 'staff_bypass', {
            'message': 'Staff administrative privileges active.',
            'remaining': 'unlimited',
        }

    # 2. Check if user or employer organization has an active administrative restriction
    try:
        from users.models import UserServiceAccess
        target_users = [user]
        employer = getattr(user, 'employer_profile', None)
        if not employer:
            membership = getattr(user, 'employer_memberships', None)
            if membership:
                active_mem = membership.filter(is_active=True).select_related('employer__user').first()
                if active_mem and active_mem.employer and active_mem.employer.user:
                    target_users.append(active_mem.employer.user)

        # Determine service key and aliases for access check
        check_services = [service]
        if service in ('quick_check', 'person_check'):
            check_services.extend(['person_check', 'quick_check'])
        elif service == 'staff_check':
            check_services.append('staff_check')
        elif service in ('public_check', 'check'):
            check_services.extend(['public_check', 'check'])
        elif service in ('certificate_creation', 'trustpass', 'certificate'):
            check_services.extend(['certificate', 'certificate_creation', 'trustpass'])
        elif service == 'certificate_verify':
            check_services.append('certificate_verify')
        elif service in ('business_verification', 'verification'):
            check_services.extend(['verification', 'business_verification'])
        elif service in ('bulk_check', 'bulk_upload'):
            check_services.extend(['bulk_upload', 'bulk_check'])
        elif service in ('misconduct_report',):
            check_services.append('misconduct_report')
        elif service in ('monitoring',):
            check_services.append('monitoring')
        elif service in ('fraud_report',):
            check_services.append('fraud_report')

        if UserServiceAccess.objects.filter(user__in=target_users, service__in=check_services, is_restricted=True).exists():
            return False, 'service_restricted', {
                'message': f'Access to this service has been restricted for your account by platform administration.',
                'remaining': 0,
            }
    except Exception as exc:
        logger.warning("Could not evaluate UserServiceAccess: %s", exc)

    # 3. Statutory Free Services (Fraud Crime Reporting & Staff Misconduct Reporting)
    if service in ('fraud_report', 'misconduct_report'):
        return True, 'statutory_free', {
            'message': 'Complimentary access for statutory service.',
            'remaining': 'unlimited',
        }

    # 4. Global Platform Free Mode (Master Switch)
    try:
        config = PlatformConfiguration.get()
        if config.free_access_mode:
            return True, 'free_platform_mode', {
                'message': 'Platform is operating in free access mode. All services are complimentary.',
                'remaining': 'unlimited',
            }
    except Exception as e:
        logger.warning("Could not check PlatformConfiguration free_access_mode: %s", e)
    # 4. Per-User / Agency Granular Service Exemption
    user_master_exempt = getattr(user, 'is_billing_exempt', False)
    user_exempt_services = getattr(user, 'exempt_services', None) or []
    if user_master_exempt or any(s in user_exempt_services for s in check_services):
        return True, 'service_free_granted', {
            'message': f'Complimentary access granted for {service}.',
            'remaining': 'unlimited',
            'service': service,
            'notes': getattr(user, 'billing_exempt_notes', ''),
        }
    # 5. Per-Organization Granular Service Exemption (Employer & Team Members)
    try:
        employer = getattr(user, 'employer_profile', None)
        if not employer:
            membership = getattr(user, 'employer_memberships', None)
            if membership:
                active_mem = membership.filter(is_active=True).select_related('employer').first()
                if active_mem:
                    employer = active_mem.employer
        if employer:
            org_master_exempt = getattr(employer, 'is_billing_exempt', False)
            org_exempt_services = getattr(employer, 'exempt_services', None) or []
            if org_master_exempt or any(s in org_exempt_services for s in check_services):
                return True, 'organization_service_free_granted', {
                    'message': f'Complimentary {service} access granted to {employer.company_name}.',
                    'remaining': 'unlimited',
                    'service': service,
                    'notes': employer.billing_exempt_notes,
                }
    except Exception as e:
        logger.warning("Could not check organization service exemption: %s", e)
    # 6. Global Service-by-Service Free Master Switch (SiteSettings)
    site_settings = SiteSettings.get()
    if site_settings.is_service_free(service):
        return True, 'service_globally_free', {
            'message': f'Service {service} is globally complimentary.',
            'remaining': 'unlimited',
        }

    # 7. Active Commercial Subscription Check
    sub = get_active_subscription(user)
    if sub:
        # Unlimited Plan
        if sub.plan.has_unlimited_checks:
            return True, 'unlimited', {
                'plan': sub.plan.name,
                'remaining': 'unlimited',
            }
        # Capped Plan
        current_used = getattr(sub, 'checks_used', 0)
        limit = sub.plan.check_limit
        remaining = max(0, limit - current_used)
        if current_used + cost <= limit:
            return True, 'subscribed', {
                'plan': sub.plan.name,
                'remaining': remaining,
                'limit': limit,
                'used': current_used,
            }
        else:
            return False, 'subscription_quota_exceeded', {
                'plan': sub.plan.name,
                'remaining': remaining,
                'limit': limit,
                'used': current_used,
            }

    # 8. Standard Free Tier Quota (unsubscribed users)
    if not site_settings.free_tier_enabled:
        return False, 'free_tier_disabled', {
            'message': 'Free check quota is currently disabled. Please subscribe to continue.',
            'remaining': 0,
            'limit': 0,
            'used': 0,
        }

    quota = FreeUsageQuota.for_user(user)
    limit = site_settings.free_check_limit
    remaining = max(0, limit - quota.checks_used)
    if quota.checks_used + cost <= limit:
        return True, 'free_tier', {
            'remaining': remaining,
            'limit': limit,
            'used': quota.checks_used,
        }
    return False, 'quota_exceeded', {
        'remaining': 0,
        'limit': limit,
        'used': quota.checks_used,
        'message': f'You have used your {limit} free check(s). Please upgrade your plan to continue.',
    }
def user_can_perform_check(user) -> tuple[bool, str]:
    """
    Backwards-compatible wrapper matching original 2-tuple signature (allowed, reason).
    """
    allowed, reason, _ = check_user_entitlement(user, cost=1)
    return allowed, reason


def consume_user_entitlement(user, service: str = 'check', cost: int = 1) -> bool:
    """
    Deducts check entitlement after an operation succeeds.
    - If service is exempt (global free mode, staff bypass, or per-service waiver): no deduction.
    - Active subscribers with capped plans: increments subscription.checks_used.
    - Free tier users: increments FreeUsageQuota.checks_used.
    """
    if service in ('fraud_report', 'certificate_verify', 'misconduct_report'):
        return True
    # If service is globally complimentary in SiteSettings, skip deduction
    site_settings = SiteSettings.get()
    if site_settings.is_service_free(service):
        return True
    try:
        config = PlatformConfiguration.get()
        if config.free_access_mode:
            return True
    except Exception:
        pass
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False):
        return True

    check_services = [service]
    if service in ('quick_check', 'person_check'):
        check_services.extend(['person_check', 'quick_check', 'check'])
    elif service == 'staff_check':
        check_services.extend(['staff_check', 'check'])
    elif service in ('public_check', 'check'):
        check_services.extend(['public_check', 'check'])
    elif service in ('certificate_creation', 'trustpass', 'certificate'):
        check_services.extend(['certificate', 'certificate_creation', 'trustpass'])
    elif service in ('business_verification', 'verification'):
        check_services.extend(['verification', 'business_verification'])
    elif service in ('bulk_check', 'bulk_upload'):
        check_services.extend(['bulk_upload', 'bulk_check'])

    # Per-user or per-agency service exemption skips deduction
    user_master_exempt = getattr(user, 'is_billing_exempt', False)
    user_exempt_services = getattr(user, 'exempt_services', None) or []
    if user_master_exempt or any(s in user_exempt_services for s in check_services):
        return True
    # Per-organization service exemption skips deduction
    try:
        employer = getattr(user, 'employer_profile', None)
        if not employer:
            membership = getattr(user, 'employer_memberships', None)
            if membership:
                active_mem = membership.filter(is_active=True).select_related('employer').first()
                if active_mem:
                    employer = active_mem.employer
        if employer:
            org_master_exempt = getattr(employer, 'is_billing_exempt', False)
            org_exempt_services = getattr(employer, 'exempt_services', None) or []
            if org_master_exempt or any(s in org_exempt_services for s in check_services):
                return True
    except Exception:
        pass
    sub = get_active_subscription(user)
    if sub:
        if sub.plan.has_unlimited_checks:
            return True
       
        Subscription.objects.filter(pk=sub.pk).update(checks_used=F('checks_used') + cost)
        return True
    # Free tier deduction
    quota = FreeUsageQuota.for_user(user)
    
    FreeUsageQuota.objects.filter(pk=quota.pk).update(checks_used=F('checks_used') + cost)
    return True



def initialize_service_checkout(
    user,
    service: str,
    tier: str = 'standard',
    amount_naira: int = None,
    metadata: dict = None,
    callback_url: str = None,
) -> dict:
    """
    Initialize a direct Paystack Pay-As-You-Go checkout for any single platform service
    (e.g., TrustPass certificate, staff background check, person quick-check, CAC verification, etc.).

    Returns:
        {
            'authorization_url': str,  # Paystack checkout redirect URL
            'reference': str,          # Transaction reference
            'access_code': str,
            'amount_naira': int,
        }
    """
    site_settings = SiteSettings.get()
    if amount_naira is None:
        amount_naira = site_settings.get_service_price(service, tier)

    amount_kobo = int(amount_naira * 100)
    if amount_kobo <= 0:
        raise ValueError(f"Service '{service}' (tier: '{tier}') is complimentary or priced at ₦0.")

    reference = generate_reference()

    transaction = Transaction.objects.create(
        user=user,
        plan=None,
        subscription=None,
        reference=reference,
        amount_kobo=amount_kobo,
        currency='NGN',
        status='pending',
    )

    cb_url = callback_url or _build_callback_url()

    meta = {
        'type': 'pay_as_you_go',
        'service': service,
        'tier': tier,
        'user_id': user.id,
        'username': user.username,
        'email': user.email,
        'transaction_id': str(transaction.id),
    }
    if metadata:
        meta.update(metadata)

    payload = {
        'email': user.email,
        'amount': amount_kobo,
        'currency': 'NGN',
        'reference': reference,
        'callback_url': cb_url,
        'metadata': meta,
    }

    try:
        response = requests.post(
            f'{PAYSTACK_BASE_URL}/transaction/initialize',
            json=payload,
            headers=_headers(),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        transaction.status = 'failed'
        err_msg = str(exc)
        if hasattr(exc, 'response') and exc.response is not None and exc.response.status_code == 401:
            err_msg = (
                "Paystack API Authentication Failed (HTTP 401 Unauthorized): "
                "The PAYSTACK_SECRET_KEY in your environment (.env) was rejected as invalid by Paystack. "
                "Please update your .env with an active Secret Key from your Paystack Dashboard."
            )
        transaction.failure_reason = err_msg
        transaction.save(update_fields=['status', 'failure_reason', 'updated_at'])
        logger.error("Paystack PAYG initialize failed (ref=%s, service=%s): %s", reference, service, err_msg)
        raise RuntimeError(f"Payment gateway error: {err_msg}") from exc

    if not data.get('status'):
        transaction.status = 'failed'
        transaction.failure_reason = data.get('message', 'Unknown Paystack error')
        transaction.save(update_fields=['status', 'failure_reason', 'updated_at'])
        raise RuntimeError(data.get('message', 'Payment initialization failed'))

    result = data['data']
    transaction.paystack_reference = result.get('reference', '')
    transaction.paystack_response = data
    transaction.save(update_fields=['paystack_reference', 'paystack_response', 'updated_at'])

    PaymentAuditLog.objects.create(
        action='CHECKOUT_INITIATED',
        user=user,
        transaction=transaction,
        details={'service': service, 'tier': tier, 'amount_naira': amount_naira, 'reference': reference},
    )

    return {
        'authorization_url': result['authorization_url'],
        'reference': reference,
        'access_code': result.get('access_code', ''),
        'amount_naira': amount_naira,
    }


def _fulfill_payg_transaction(transaction: Transaction, paystack_data: dict):
    """
    Fulfill a completed Pay-As-You-Go payment for a platform service.
    Unlocks certificates, initiates staff checks, or activates continuous monitoring.
    Idempotent and safe to run on webhooks or callback redirects.
    """
    meta = (
        paystack_data.get('metadata')
        or transaction.paystack_response.get('data', {}).get('metadata')
        or {}
    )
    service = meta.get('service', '')
    tier = meta.get('tier', 'standard')

    # 1. TrustPass Certificate
    if service == 'certificate':
        cert_id = meta.get('certificate_id')
        if cert_id:
            from verification.models import VerificationCertificate
            from reports.models import AuditLog
            cert = VerificationCertificate.objects.filter(certificate_id=cert_id).first()
            if cert and cert.status == 'pending_payment':
                cert.status = 'pending'
                cert.save(update_fields=['status', 'updated_at'])
                try:
                    AuditLog.objects.create(
                        report=None,
                        action="TRUSTPASS_PAYG_PAYMENT_SUCCESS",
                        performed_by=transaction.user,
                        details={
                            "certificate_id": cert_id,
                            "reference": transaction.reference,
                            "amount_naira": transaction.amount_naira,
                        }
                    )
                except Exception:
                    pass
                logger.info("TrustPass certificate %s unlocked and moved to pending review after payment %s", cert_id, transaction.reference)

    # 2. Staff Background Check
    elif service == 'staff_check':
        check_id = meta.get('staff_check_id')
        if check_id:
            from employer.models import StaffCheckRequest
            from employer.tasks import process_single_staff_check_task
            check = StaffCheckRequest.objects.filter(id=check_id).first()
            if check and check.status == 'pending_payment':
                check.status = 'pending'
                check.save(update_fields=['status', 'updated_at'])
                try:
                    process_single_staff_check_task.delay(str(check.id))
                except Exception:
                    try:
                        process_single_staff_check_task(str(check.id))
                    except Exception as e:
                        logger.warning("Failed to dispatch staff check task %s inline: %s", check.id, e)
                logger.info("Staff check %s unlocked and processing after payment %s", check_id, transaction.reference)

    # 3. Document / CAC Verification
    elif service in ('verification', 'business_verification'):
        req_ref = meta.get('verification_reference')
        if req_ref:
            from verification.models import VerificationRequest
            v_req = VerificationRequest.objects.filter(reference_number=req_ref).first()
            if v_req and v_req.status == 'pending_payment':
                v_req.status = 'pending'
                v_req.save(update_fields=['status', 'updated_at'])
                try:
                    from verification.tasks import notify_verification_request_created
                    notify_verification_request_created.delay(v_req.id)
                except Exception:
                    pass
                logger.info("Verification request %s unlocked after payment %s", req_ref, transaction.reference)

    # 4. Continuous Monitoring
    elif service == 'monitoring':
        cert_id = meta.get('certificate_id')
        staff_check_id = meta.get('staff_check_id')
        if cert_id:
            from verification.models import VerificationCertificate
            cert = VerificationCertificate.objects.filter(certificate_id=cert_id).first()
            if cert:
                cert.is_monitoring_active = True
                cert.monitoring_activated_at = timezone.now()
                from dateutil.relativedelta import relativedelta
                cert.monitoring_expires_at = timezone.now() + relativedelta(years=1)
                cert.save(update_fields=['is_monitoring_active', 'monitoring_activated_at', 'monitoring_expires_at', 'updated_at'])
                logger.info("Monitoring activated for certificate %s after payment %s", cert_id, transaction.reference)
        if staff_check_id:
            from employer.models import StaffCheckRequest, StaffCheckMonitor
            check = StaffCheckRequest.objects.filter(id=staff_check_id).first()
            if check:
                monitor, _ = StaffCheckMonitor.objects.get_or_create(
                    check_request=check,
                    defaults={'employer': check.employer, 'monitor_status': 'active'}
                )
                monitor.monitor_status = 'active'
                monitor.save(update_fields=['monitor_status', 'updated_at'])
                logger.info("Staff check monitor %s activated after payment %s", staff_check_id, transaction.reference)
