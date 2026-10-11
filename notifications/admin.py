
# notifications/admin.py
from django.contrib import admin
from notifications.models import Notification, NotificationPreference


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'recipient', 'event_type', 'title', 'is_read',
        'email_sent', 'email_provider_used', 'created_at',
    )
    list_filter = ('event_type', 'is_read', 'email_sent', 'email_provider_used')
    search_fields = ('recipient__username', 'recipient__email', 'title', 'object_reference')
    readonly_fields = (
        'id', 'recipient', 'event_type', 'title', 'body',
        'object_reference', 'email_provider_used', 'email_sent', 'created_at',
    )
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False  # Notifications are system-generated only

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'email_report_submitted', 'email_broadcast', 'updated_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at')

