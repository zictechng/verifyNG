import logging
import smtplib
import socket
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)

# Specific transient connection and timeout failures (excluding broad OSError and duplicate socket.error)
TRANSIENT_NETWORK_ERRORS = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    socket.timeout,
    TimeoutError,
    ConnectionRefusedError,
    ConnectionResetError,
)


def _mask_email(email: str) -> str:
    """Masks recipient email for privacy-safe logging (e.g. u***@example.com)."""
    if not email or '@' not in email:
        return '***'
    user_part, domain_part = email.split('@', 1)
    masked_user = user_part[0] + '***' if user_part else '***'
    return f"{masked_user}@{domain_part}"


@shared_task(bind=True, name="core.tasks.ping_celery_task")
def ping_celery_task(self):
    """
    Health check and smoke test task to verify Celery broker and worker execution.
    """
    logger.info("Celery ping task executed (task_id=%s)", self.request.id)
    return {"status": "pong", "task_id": self.request.id}


@shared_task(
    bind=True,
    name="core.tasks.send_email_notification_task",
    max_retries=3,
    default_retry_delay=60
)
def send_email_notification_task(self, recipient_email, subject, message_body):
    """
    Asynchronous task for delivering transactional notifications.
    Retries up to 3 times on transient transport/network failures with a 60-second delay.
    Permanent SMTP 5xx errors and configuration errors propagate immediately without retrying.
    """
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'webmaster@localhost')

    try:
        sent_count = send_mail(
            subject=subject,
            message=message_body,
            from_email=from_email,
            recipient_list=[recipient_email],
            fail_silently=False,
        )
        logger.info(
            "Notification email dispatched (recipient=%s, task_id=%s)",
            _mask_email(recipient_email),
            self.request.id
        )
        return {"status": "sent", "count": sent_count}

    except smtplib.SMTPResponseException as exc:
        # Transient SMTP 4xx errors trigger retry
        if 400 <= exc.smtp_code < 500:
            logger.warning(
                "Transient SMTP 4xx error (code=%s, recipient=%s, task_id=%s). Retrying.",
                exc.smtp_code,
                _mask_email(recipient_email),
                self.request.id
            )
            raise self.retry(exc=exc)
        # Permanent SMTP 5xx errors propagate immediately
        logger.error(
            "Permanent SMTP 5xx rejection (code=%s, recipient=%s, task_id=%s). Task will not retry.",
            exc.smtp_code,
            _mask_email(recipient_email),
            self.request.id
        )
        raise exc

    except TRANSIENT_NETWORK_ERRORS as exc:
        logger.warning(
            "Transient network error during email dispatch (error=%s, recipient=%s, task_id=%s). Retrying.",
            type(exc).__name__,
            _mask_email(recipient_email),
            self.request.id
        )
        raise self.retry(exc=exc)
