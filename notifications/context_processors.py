# notifications/context_processors.py
"""
Injects the unread notification count and pending allegations count
into every template context for authenticated users.
Powers the dashboard notification bell and dispute badges.
"""
import logging

logger = logging.getLogger(__name__)


def unread_notification_count(request):
    """
    Returns {'unread_notification_count': <int>, 'pending_allegations_count': <int>}
    for authenticated users. Returns 0 on any DB error to prevent breaking pages.
    """
    if not request.user.is_authenticated:
        return {'unread_notification_count': 0, 'pending_allegations_count': 0}
    try:
        from notifications.models import Notification
        count = Notification.objects.filter(
            recipient=request.user,
            is_read=False,
            is_active=True,
        ).count()
    except Exception as exc:
        logger.warning("unread_notification_count context processor error: %s", exc)
        count = 0

    try:
        from reports.services import get_pending_allegations_count_for_user
        pending_allegations = get_pending_allegations_count_for_user(request.user)
    except Exception as exc:
        logger.warning("pending_allegations_count context processor error: %s", exc)
        pending_allegations = 0

    return {
        'unread_notification_count': count,
        'pending_allegations_count': pending_allegations,
    }
