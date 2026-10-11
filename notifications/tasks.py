
# notifications/tasks.py
"""
Celery tasks for the notifications app.

send_notification_email_task:
  - Wraps the three-gate email_service.send_email()
  - Retries up to 3 times on transient failures
  - Updates the Notification record with delivery outcome
  - Respects NotificationPreference opt-outs (checked before enqueueing,
    but double-checked here as a safety net)

send_email_notification_task (in core/tasks.py) delegates here for admin
broadcast dispatches — see core/tasks.py replacement below.
"""

import logging
import uuid
from celery import shared_task

from notifications.email_service import send_email

logger = logging.getLogger(__name__)

# Transient errors that should trigger a retry
_RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    ConnectionRefusedError,
    ConnectionResetError,
    OSError,
)


@shared_task(
    bind=True,
    name="notifications.tasks.send_notification_email_task",
    max_retries=3,
    default_retry_delay=60,
)
def send_notification_email_task(
    self,
    notification_id: str,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> dict:
    """
    Deliver a notification email through the three-gate failover service.
    Updates the Notification record on success or after permanent failure.
    notification_id is a UUID string (str form of Notification.id).
    """
    from notifications.models import Notification

    try:
        result = send_email(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )
        provider = result.get("provider_used", "unknown")

        # Update the Notification record
        Notification.objects.filter(id=notification_id).update(
            email_sent=True,
            email_provider_used=provider,
        )
        logger.info(
            "Notification email delivered (notification_id=%s, provider=%s)",
            notification_id,
            provider,
        )
        return {"status": "delivered", "provider_used": provider}

    except RuntimeError as exc:
        # All three gates failed — log as error, do not retry (gates already exhausted)
        Notification.objects.filter(id=notification_id).update(
            email_sent=False,
            email_provider_used="none",
        )
        logger.error(
            "All email gates exhausted for notification %s: %s",
            notification_id,
            exc,
        )
        # Do NOT raise — we don't want Celery to retry after all gates are spent
        return {"status": "all_gates_failed", "error": str(exc)}

    except _RETRYABLE_EXCEPTIONS as exc:
        logger.warning(
            "Transient error in notification task %s (%s). Retrying.",
            notification_id,
            type(exc).__name__,
        )
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.error(
            "Unexpected error in notification task %s: %s",
            notification_id,
            exc,
        )
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    name="notifications.tasks.send_broadcast_email_task",
    max_retries=3,
    default_retry_delay=60,
)
def send_broadcast_email_task(
    self,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> dict:
    """
    Deliver an admin broadcast email without an associated Notification record.
    Used by AdminCommunicationsView bulk dispatch.
    """
    try:
        result = send_email(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )
        logger.info("Broadcast email delivered via %s → %s", result.get("provider_used"), to_email[:3] + "***")
        return {"status": "delivered", "provider_used": result.get("provider_used")}

    except RuntimeError as exc:
        logger.error("All gates failed for broadcast to %s: %s", to_email[:3] + "***", exc)
        return {"status": "all_gates_failed"}

    except _RETRYABLE_EXCEPTIONS as exc:
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.error("Unexpected broadcast error: %s", exc)
        raise self.retry(exc=exc)

