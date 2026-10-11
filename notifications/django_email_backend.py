"""
Bridge adapter: routes Django's internal mail system (PasswordResetView,
send_mail, etc.) through the three-gate VerifyNG email service.
"""
import logging

from django.core.mail.backends.base import BaseEmailBackend

from notifications.email_service import send_email

logger = logging.getLogger(__name__)


class VerifyNGEmailBackend(BaseEmailBackend):
    """
    Django email backend that delegates every outgoing message to the
    three-gate send_email() service (Mailtrap → Namecheap → Gmail).
    """

    def send_messages(self, email_messages):
        delivered = 0
        for message in email_messages:
            for recipient in message.to:
                try:
                    # Extract HTML alternative if present (e.g. from EmailMultiAlternatives)
                    html_body = None
                    if hasattr(message, 'alternatives'):
                        for content, mimetype in message.alternatives:
                            if mimetype == 'text/html':
                                html_body = content
                                break

                    send_email(
                        to_email=recipient,
                        subject=message.subject,
                        html_body=html_body or f"<pre>{message.body}</pre>",
                        text_body=message.body,
                    )
                    delivered += 1
                except RuntimeError as exc:
                    logger.error(
                        "VerifyNGEmailBackend: all gates failed for %s subject=%r — %s",
                        recipient, message.subject, exc,
                    )
                    if not self.fail_silently:
                        raise
        return delivered