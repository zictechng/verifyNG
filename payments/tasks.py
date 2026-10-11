
# payments/tasks.py
import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, name='payments.tasks.expire_subscriptions')
def expire_subscriptions(self):
    """
    Celery periodic task — expires subscriptions whose period_end has passed.
    Run daily via Celery Beat.
    """
    from .models import Subscription
    now = timezone.now()
    expired = Subscription.objects.filter(
        status='active',
        current_period_end__lt=now,
    )
    count = expired.count()
    expired.update(status='expired', updated_at=now)
    logger.info("Expired %d subscriptions (task_id=%s)", count, self.request.id)
    return {'expired_count': count}


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

