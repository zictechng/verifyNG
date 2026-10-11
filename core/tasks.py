# core/tasks.py
import logging
import socket
import smtplib
from celery import shared_task

logger = logging.getLogger(__name__)

# Kept for backwards-compat import by other modules that reference this symbol
TRANSIENT_NETWORK_ERRORS = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    socket.timeout,
    TimeoutError,
    ConnectionRefusedError,
    ConnectionResetError,
)


def _mask_email(email: str) -> str:
    """Privacy-safe email mask for logs."""
    if not email or '@' not in email:
        return '***'
    user_part, domain_part = email.split('@', 1)
    masked_user = user_part[0] + '***' if user_part else '***'
    return f"{masked_user}@{domain_part}"


@shared_task(bind=True, name="core.tasks.ping_celery_task")
def ping_celery_task(self):
    """Health check smoke-test task."""
    logger.info("Celery ping task executed (task_id=%s)", self.request.id)
    return {"status": "pong", "task_id": self.request.id}


@shared_task(
    bind=True,
    name="core.tasks.send_email_notification_task",
    max_retries=3,
    default_retry_delay=60,
)
def send_email_notification_task(self, recipient_email: str, subject: str, message_body: str):
    """
    Admin broadcast email task (used by AdminCommunicationsView).
    Delegates to the three-gate notifications.email_service.
    Retries up to 3 times on transient errors.
    """
    from notifications.email_service import send_email

    html_body = f"<p>{message_body}</p>"
    text_body = message_body

    try:
        result = send_email(
            to_email=recipient_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )
        logger.info(
            "Admin broadcast email delivered via %s → %s (task_id=%s)",
            result.get("provider_used"),
            _mask_email(recipient_email),
            self.request.id,
        )
        return {"status": "sent", "provider_used": result.get("provider_used")}

    except RuntimeError as exc:
        # All three gates failed — log but do not retry further
        logger.error(
            "All email gates exhausted for broadcast to %s (task_id=%s): %s",
            _mask_email(recipient_email),
            self.request.id,
            exc,
        )
        return {"status": "all_gates_failed", "error": str(exc)}

    except TRANSIENT_NETWORK_ERRORS as exc:
        logger.warning(
            "Transient network error in broadcast task (task_id=%s). Retrying.",
            self.request.id,
        )
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.error(
            "Unexpected error in broadcast email task (task_id=%s): %s",
            self.request.id,
            exc,
        )
        raise self.retry(exc=exc)

