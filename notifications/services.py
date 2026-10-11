
# notifications/services.py
"""
Notification creation service.

All signal receivers and views should call functions in this module
rather than creating Notification objects or dispatching tasks directly.

This module:
  - Creates the Notification record (always, for in-app bell)
  - Checks NotificationPreference for email opt-out
  - Dispatches send_notification_email_task via Celery if email is enabled
"""

import logging
from typing import Optional

from users.models import User
from notifications.models import Notification, NotificationPreference

logger = logging.getLogger(__name__)


def dispatch_notification(
    recipient: User,
    event_type: str,
    title: str,
    body: str,
    object_reference: str = "",
    subject: Optional[str] = None,
    html_body: Optional[str] = None,
    text_body: Optional[str] = None,
) -> Optional[Notification]:
    """
    Create a Notification record and optionally enqueue an email delivery task.

    Args:
        recipient:        The User to notify.
        event_type:       One of Notification.EVENT_TYPES keys.
        title:            Short in-app notification title.
        body:             In-app notification body text.
        object_reference: Related object reference number (optional).
        subject:          Email subject. Required if email delivery is desired.
        html_body:        HTML email body. Required for email delivery.
        text_body:        Plain-text fallback. Auto-derived from html_body if omitted.

    Returns:
        The created Notification instance, or None if recipient has no email
        and in-app only is appropriate (record still created).
    """
    if not recipient or not recipient.pk:
        logger.warning("dispatch_notification called with no valid recipient; skipping.")
        return None

    # Always create the in-app notification record
    notification = Notification.objects.create(
        recipient=recipient,
        event_type=event_type,
        title=title,
        body=body,
        object_reference=object_reference,
    )

    # Only dispatch email if:
    # 1. recipient has an email address
    # 2. email content was provided
    # 3. user's NotificationPreference allows this event type
    if recipient.email and subject and html_body:
        prefs = NotificationPreference.for_user(recipient)
        if prefs.email_enabled_for(event_type):
            from notifications.tasks import send_notification_email_task
            send_notification_email_task.delay(
                notification_id=str(notification.id),
                to_email=recipient.email,
                subject=subject,
                html_body=html_body,
                text_body=text_body or "",
            )
        else:
            logger.debug(
                "Email suppressed by preference for user=%s event=%s",
                recipient.username,
                event_type,
            )

    return notification

