
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

from .models import Plan, Subscription, Transaction, SiteSettings

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

    elif event_type == 'invoice.payment_failed':
        sub_code = data.get('subscription', {}).get('subscription_code', '')
        Subscription.objects.filter(
            paystack_subscription_code=sub_code
        ).update(status='past_due', updated_at=timezone.now())


def get_active_subscription(user) -> Subscription | None:
    """Return the user's current active subscription or None."""
    return Subscription.objects.filter(
        user=user,
        status='active',
        current_period_end__gt=timezone.now(),
    ).select_related('plan').first()


def user_can_perform_check(user) -> tuple[bool, str]:
    """
    Check if user has quota for a check.
    Returns (allowed: bool, reason: str).
    """
    # Active subscribers always allowed
    sub = get_active_subscription(user)
    if sub:
        if sub.plan.has_unlimited_checks:
            return True, 'unlimited'
        # Check count-based limit (future: track per-subscription usage)
        return True, 'subscribed'

    # Free tier check
    quota = FreeUsageQuota.for_user(user)
    site_settings = SiteSettings.get()
    if quota.checks_used < site_settings.free_check_limit:
        return True, 'free_tier'

    return False, 'quota_exceeded'

