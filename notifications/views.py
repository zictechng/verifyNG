
# notifications/views.py
import logging
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from django.contrib import messages

from notifications.models import Notification, NotificationPreference

logger = logging.getLogger(__name__)


@login_required
def notification_list(request):
    """
    Full-page notification inbox for the current user.
    Renders the most recent 50 notifications, marking unread ones as read on view.
    """
    notifications_qs = (
        Notification.objects
        .filter(recipient=request.user, is_active=True)
        .order_by('-created_at')[:50]
    )
    # Batch mark unread as read
    unread_ids = [n.id for n in notifications_qs if not n.is_read]
    if unread_ids:
        Notification.objects.filter(id__in=unread_ids).update(is_read=True)

    prefs = NotificationPreference.for_user(request.user)

    # Add to notification_list view, before the render() call:
    prefs_fields = [
        ('email_report_submitted', 'Fraud report received confirmation'),
        ('email_report_published', 'Fraud report published'),
        ('email_report_rejected', 'Fraud report rejected'),
        ('email_dispute_opened', 'Dispute filed on your report'),
        ('email_dispute_resolved', 'Dispute resolved'),
        ('email_verification_completed', 'Verification completed'),
        ('email_verification_rejected', 'Verification rejected'),
        ('email_broadcast', 'Platform announcements'),
    ]
    return render(request, 'notifications/notification_list.html', {
        'notifications': notifications_qs,
        'prefs': prefs,
        'prefs_fields': prefs_fields,
    })

@login_required
@require_POST
def mark_notification_read(request, notification_id):
    """Mark a single notification as read. Returns JSON for AJAX callers."""
    notification = get_object_or_404(
        Notification, id=notification_id, recipient=request.user
    )
    notification.mark_read()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'ok'})
    return HttpResponseRedirect(reverse('notifications:list'))


@login_required
@require_POST
def mark_all_read(request):
    """Mark all unread notifications as read for the current user."""
    Notification.objects.filter(
        recipient=request.user, is_read=False
    ).update(is_read=True)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'ok'})
    return HttpResponseRedirect(reverse('notifications:list'))


@login_required
def update_preferences(request):
    """Save notification email preferences form. Redirects back to origin page."""
    if request.method != 'POST':
        return HttpResponseRedirect(reverse('notifications:list'))

    prefs = NotificationPreference.for_user(request.user)
    bool_fields = [
        'email_report_submitted', 'email_report_published', 'email_report_rejected',
        'email_dispute_opened', 'email_dispute_resolved',
        'email_verification_completed', 'email_verification_rejected', 'email_broadcast',
    ]
    for field in bool_fields:
        setattr(prefs, field, field in request.POST)
    prefs.save()

    messages.success(request, 'Email notification preferences saved.')

    # Return to whichever page submitted the form (Settings or Notifications)
    referer = request.META.get('HTTP_REFERER', '')
    from django.urls import reverse as url_reverse
    settings_url = url_reverse('users:password_change')
    if settings_url in referer:
        return HttpResponseRedirect(settings_url)
    return HttpResponseRedirect(reverse('notifications:list'))

