import logging
import socket
import smtplib
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)

# Specific transient connection and timeout failures
TRANSIENT_NETWORK_ERRORS = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    socket.timeout,
    TimeoutError,
    ConnectionRefusedError,
    ConnectionResetError,
)


def _mask_email(email: str) -> str:
    """Privacy-safe email mask for logs (e.g. u***@example.com)."""
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
def send_email_notification_task(
    self,
    recipient_email: str,
    subject: str,
    message_body: str,
    html_message: str = None,
):
    """
    Asynchronous task for delivering transactional notifications and broadcasts.
    Dispatches via Django's send_mail (which respects the configured EMAIL_BACKEND
    and populates mail.outbox during test runs).
    When html_message is provided, sends a multipart email with HTML and plain-text fallback.
    Retries up to 3 times on transient transport/network failures.
    """
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'webmaster@localhost')

    try:
        sent_count = send_mail(
            subject=subject,
            message=message_body,
            from_email=from_email,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(
            "Notification email dispatched (recipient=%s, task_id=%s)",
            _mask_email(recipient_email),
            self.request.id,
        )
        return {"status": "sent", "count": sent_count}

    except smtplib.SMTPResponseException as exc:
        # Transient SMTP 4xx errors trigger retry
        if 400 <= exc.smtp_code < 500:
            logger.warning(
                "Transient SMTP 4xx error (code=%s, recipient=%s, task_id=%s). Retrying.",
                exc.smtp_code,
                _mask_email(recipient_email),
                self.request.id,
            )
            raise self.retry(exc=exc)
        # Permanent SMTP 5xx errors propagate immediately
        logger.error(
            "Permanent SMTP 5xx rejection (code=%s, recipient=%s, task_id=%s). Task will not retry.",
            exc.smtp_code,
            _mask_email(recipient_email),
            self.request.id,
        )
        raise exc

    except TRANSIENT_NETWORK_ERRORS as exc:
        logger.warning(
            "Transient network error during email dispatch (error=%s, recipient=%s, task_id=%s). Retrying.",
            type(exc).__name__,
            _mask_email(recipient_email),
            self.request.id,
        )
        raise self.retry(exc=exc)

