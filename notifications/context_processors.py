
# notifications/context_processors.py
"""
Injects the unread notification count into every template context
for authenticated users. Powers the dashboard notification bell.
"""
import logging

logger = logging.getLogger(__name__)


def unread_notification_count(request):
    """
    Returns {'unread_notification_count': <int>} for authenticated users.
    Returns 0 on any DB error to prevent context processor from breaking pages.
    """
    if not request.user.is_authenticated:
        return {'unread_notification_count': 0}
    try:
        from notifications.models import Notification
        count = Notification.objects.filter(
            recipient=request.user,
            is_read=False,
            is_active=True,
        ).count()
        return {'unread_notification_count': count}
    except Exception as exc:
        logger.warning("unread_notification_count context processor error: %s", exc)
        return {'unread_notification_count': 0}

