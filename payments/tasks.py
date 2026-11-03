# payments/tasks.py
import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, name='payments.tasks.check_subscription_and_merchant_expirations')
def check_subscription_and_merchant_expirations(self):
    """
    Industrial-standard Celery periodic task — runs daily.
    1. Checks MerchantProfile free trials:
       - Sends proactive Paystack renewal reminders at 3 days and 1 day before expiration.
       - If trial expired (trial_ends_at < now) without active renewal, suspends badge and notifies owner.
    2. Checks Plan Subscriptions (Subscription):
       - Sends renewal reminders at 3 days and 1 day before expiration.
       - If current_period_end < now, transitions status to 'expired' and dispatches expiry notice.
    All reminder dispatches are strictly idempotent via Notification object_reference locks.
    """
    from .models import Subscription, MerchantProfile
    from notifications.models import Notification
    from notifications.services import dispatch_notification
    from notifications.email_templates import (
        build_subscription_expiring,
        build_subscription_expired,
        build_merchant_trial_expiring,
        build_merchant_badge_revoked,
    )

    now = timezone.now()
    results = {
        'merchant_reminders_sent': 0,
        'merchants_suspended': 0,
        'subscription_reminders_sent': 0,
        'subscriptions_expired': 0,
    }

    # ─────────────────────────────────────────────────────────────
    # 1. MERCHANT PROFILES (Free Trial & Badge Renewal Monitoring)
    # ─────────────────────────────────────────────────────────────
    active_merchants = MerchantProfile.objects.filter(
        status__in=['active', 'disputed', 'under_dispute'],
        trial_ends_at__isnull=False,
    ).select_related('user')

    for merchant in active_merchants:
        try:
            delta = merchant.trial_ends_at - now
            total_seconds = delta.total_seconds()

            if total_seconds <= 0:
                # Trial has ended
                merchant.status = 'suspended'
                reason_text = "Complimentary trial period ended. Renew your trust badge to restore active verification."
                merchant.rejection_reason = reason_text
                merchant.save(update_fields=['status', 'rejection_reason', 'updated_at'])

                lock_ref = f"merchant_trial_expired_{merchant.id}"
                if not Notification.objects.filter(recipient=merchant.user, object_reference=lock_ref).exists():
                    subject, html_body, text_body = build_merchant_badge_revoked(
                        store_name=merchant.store_name,
                        username=merchant.user.username,
                        reason=reason_text,
                    )
                    dispatch_notification(
                        recipient=merchant.user,
                        event_type='BROADCAST',
                        title=f"Trial Ended: Verified Seal Suspended ({merchant.store_name})",
                        body=reason_text,
                        object_reference=lock_ref,
                        subject=subject,
                        html_body=html_body,
                        text_body=text_body,
                        force_email=True,
                    )
                results['merchants_suspended'] += 1
                logger.info("Merchant %s (%s) trial expired and suspended.", merchant.store_name, merchant.id)

            else:
                # Expiring soon milestone detection
                days_left = None
                if 0 < total_seconds <= 86400 * 1.2:
                    days_left = 1
                elif 86400 * 1.2 < total_seconds <= 86400 * 3.2:
                    days_left = 3

                if days_left:
                    lock_ref = f"merchant_trial_remind_{days_left}d_{merchant.id}"
                    if not Notification.objects.filter(recipient=merchant.user, object_reference=lock_ref).exists():
                        subject, html_body, text_body = build_merchant_trial_expiring(
                            store_name=merchant.store_name,
                            username=merchant.user.username,
                            days_left=days_left,
                            amount_naira=4900.0,
                        )
                        dispatch_notification(
                            recipient=merchant.user,
                            event_type='BROADCAST',
                            title=f"Action Required: Trial Badge Renews in {days_left}d ({merchant.store_name})",
                            body=f"Your Verified Merchant Trust Seal trial expires in {days_left} day(s). Renew to avoid seal downtime.",
                            object_reference=lock_ref,
                            subject=subject,
                            html_body=html_body,
                            text_body=text_body,
                            force_email=True,
                        )
                        results['merchant_reminders_sent'] += 1
                        logger.info("Merchant %s sent %d-day renewal reminder.", merchant.store_name, days_left)
        except Exception as exc:
            logger.error("Error processing merchant %s expiration: %s", merchant.id, exc, exc_info=True)

    # ─────────────────────────────────────────────────────────────
    # 2. PLAN SUBSCRIPTIONS (Billing Cycle & Renewal Monitoring)
    # ─────────────────────────────────────────────────────────────
    active_subscriptions = Subscription.objects.filter(
        status='active',
        current_period_end__isnull=False,
    ).select_related('user', 'plan')

    for sub in active_subscriptions:
        try:
            delta = sub.current_period_end - now
            total_seconds = delta.total_seconds()

            if total_seconds <= 0:
                # Subscription expired
                sub.status = 'expired'
                sub.save(update_fields=['status', 'updated_at'])

                lock_ref = f"sub_expired_{sub.id}"
                if not Notification.objects.filter(recipient=sub.user, object_reference=lock_ref).exists():
                    subject, html_body, text_body = build_subscription_expired(
                        subscription=sub,
                        username=sub.user.username,
                    )
                    dispatch_notification(
                        recipient=sub.user,
                        event_type='BROADCAST',
                        title=f"Subscription Expired: {sub.plan.name}",
                        body=f"Your {sub.plan.name} subscription period has expired. Renew your plan to restore quota benefits.",
                        object_reference=lock_ref,
                        subject=subject,
                        html_body=html_body,
                        text_body=text_body,
                        force_email=True,
                    )
                results['subscriptions_expired'] += 1
                logger.info("Subscription %s for user %s marked expired.", sub.id, sub.user.username)

            else:
                # Expiring soon milestone detection
                days_left = None
                if 0 < total_seconds <= 86400 * 1.2:
                    days_left = 1
                elif 86400 * 1.2 < total_seconds <= 86400 * 3.2:
                    days_left = 3

                if days_left:
                    lock_ref = f"sub_remind_{days_left}d_{sub.id}"
                    if not Notification.objects.filter(recipient=sub.user, object_reference=lock_ref).exists():
                        subject, html_body, text_body = build_subscription_expiring(
                            subscription=sub,
                            username=sub.user.username,
                            days_left=days_left,
                        )
                        dispatch_notification(
                            recipient=sub.user,
                            event_type='BROADCAST',
                            title=f"Subscription Notice: {sub.plan.name} Renews in {days_left}d",
                            body=f"Your {sub.plan.name} subscription will expire in {days_left} day(s). Renew today to avoid interruption.",
                            object_reference=lock_ref,
                            subject=subject,
                            html_body=html_body,
                            text_body=text_body,
                            force_email=True,
                        )
                        results['subscription_reminders_sent'] += 1
                        logger.info("Subscription %s sent %d-day renewal reminder.", sub.id, days_left)
        except Exception as exc:
            logger.error("Error processing subscription %s expiration: %s", sub.id, exc, exc_info=True)

    logger.info("Expiration check complete: %s (task_id=%s)", results, getattr(self.request, 'id', 'local'))
    return results


@shared_task(bind=True, name='payments.tasks.expire_subscriptions')
def expire_subscriptions(self):
    """
    Backwards-compatible wrapper delegating to check_subscription_and_merchant_expirations.
    """
    return check_subscription_and_merchant_expirations()


@shared_task(bind=True, name='payments.tasks.verify_pending_transaction', max_retries=3, default_retry_delay=30)
def verify_pending_transaction(self, reference: str):
    """
    Async task to verify a Paystack transaction.
    Retries up to 3 times on transient failures.
    """
    from .services import verify_transaction
    try:
        transaction = verify_transaction(reference)
        return {'status': transaction.status, 'reference': reference}
    except Exception as exc:
        logger.warning("verify_pending_transaction failed (ref=%s): %s", reference, exc)
        raise self.retry(exc=exc)
