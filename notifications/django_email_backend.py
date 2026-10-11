
# notifications/django_email_backend.py
"""
Custom Django email backend that routes all outbound mail
(including password reset, OTP, and any django.core.mail.send_mail call)
through the existing three-gate VerifyNG email service.
"""

import logging
from django.core.mail.backends.base import BaseEmailBackend
from notifications.email_service import send_email

logger = logging.getLogger(__name__)


class VerifyNGEmailBackend(BaseEmailBackend):
    """
    Drop-in Django email backend adapter.
    Delegates every outbound message to send_email() — the three-gate
    failover service (Mailtrap API → Namecheap SMTP → Gmail SMTP).
    """

    def send_messages(self, email_messages):
        """
        Called by Django's mail system for every outbound message batch.
        Returns the number of messages successfully delivered.
        """
        delivered = 0

        for message in email_messages:
            # Resolve recipients — each message may have multiple
            for recipient in message.to:
                try:
                    # Prefer HTML alternative if present
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
                    # All three gates failed — log and continue
                    logger.error(
                        "VerifyNGEmailBackend: all gates failed for %s subject=%r — %s",
                        recipient, message.subject, exc,
                    )
                    if not self.fail_silently:
                        raise

        return delivered
