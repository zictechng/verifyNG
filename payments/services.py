
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
        transaction.failure_reason = str(exc)
        transaction.save(update_fields=['status', 'failure_reason', 'updated_at'])
        logger.error("Paystack initialize failed (ref=%s): %s", reference, exc)
        raise RuntimeError(f"Payment gateway unavailable: {exc}") from exc

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
        _activate_subscription(transaction, paystack_data)
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
    """Return the user's current active subscription or None."""
    return Subscription.objects.filter(
        user=user,
        status='active',
        current_period_end__gt=timezone.now(),
    ).select_related('plan').first()


def check_user_entitlement(user, service: str = 'check', cost: int = 1) -> tuple[bool, str, dict]:
    """
    Universal service-by-service credit & subscription entitlement checker.
    Evaluates:
      1. Fraud Reporting exception (permanently free for all users).
      2. Global Free Mode (platform-wide promotional switch).
      3. Staff / Superuser administrative bypass.
      4. Per-User & Per-Agency granular service matrix (exempt_services).
      5. Per-Organization granular service matrix (EmployerProfile.exempt_services).
      6. Active Commercial Subscription & Free Tier Quotas.
    """
    # 1. Fraud Reporting is ALWAYS complimentary for everyone
    if service == 'fraud_report':
        return True, 'fraud_report_free', {
            'message': 'Fraud reporting is complimentary for all users.',
            'remaining': 'unlimited',
        }
    # 2. Global Platform Free Mode (Master Switch)
    try:
        config = PlatformConfiguration.get()
        if config.free_access_mode:
            return True, 'free_platform_mode', {
                'message': 'Platform is operating in free access mode. All services are complimentary.',
                'remaining': 'unlimited',
            }
    except Exception as e:
        logger.warning("Could not check PlatformConfiguration free_access_mode: %s", e)
    # 3. Staff / Superuser privileges
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False):
        return True, 'staff_bypass', {
            'message': 'Staff administrative privileges active.',
            'remaining': 'unlimited',
        }
    # 4. Per-User / Agency Granular Service Exemption
    user_master_exempt = getattr(user, 'is_billing_exempt', False)
    user_exempt_services = getattr(user, 'exempt_services', None) or []
    if user_master_exempt or service in user_exempt_services:
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
            if org_master_exempt or service in org_exempt_services:
                return True, 'organization_service_free_granted', {
                    'message': f'Complimentary {service} access granted to {employer.company_name}.',
                    'remaining': 'unlimited',
                    'service': service,
                    'notes': employer.billing_exempt_notes,
                }
    except Exception as e:
        logger.warning("Could not check organization service exemption: %s", e)
    # 6. Active Commercial Subscription Check
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
        if current_used + cost <= limit:
            return True, 'subscribed', {
                'plan': sub.plan.name,
                'remaining': max(0, limit - (current_used + cost)),
                'limit': limit,
                'used': current_used,
            }
        else:
            return False, 'subscription_quota_exceeded', {
                'plan': sub.plan.name,
                'remaining': max(0, limit - current_used),
                'limit': limit,
                'used': current_used,
            }
    # 4. Standard Free Tier Quota (unsubscribed users)
    quota = FreeUsageQuota.for_user(user)
    site_settings = SiteSettings.get()
    limit = site_settings.free_check_limit
    if quota.checks_used + cost <= limit:
        return True, 'free_tier', {
            'remaining': max(0, limit - (quota.checks_used + cost)),
            'limit': limit,
            'used': quota.checks_used,
        }
    return False, 'quota_exceeded', {
        'remaining': 0,
        'limit': limit,
        'used': quota.checks_used,
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
    if service == 'fraud_report':
        return True
    try:
        config = PlatformConfiguration.get()
        if config.free_access_mode:
            return True
    except Exception:
        pass
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False):
        return True
    # Per-user or per-agency service exemption skips deduction
    user_master_exempt = getattr(user, 'is_billing_exempt', False)
    user_exempt_services = getattr(user, 'exempt_services', None) or []
    if user_master_exempt or service in user_exempt_services:
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
            if org_master_exempt or service in org_exempt_services:
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

