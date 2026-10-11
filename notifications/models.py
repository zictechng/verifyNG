
# notifications/models.py
import uuid
from django.db import models
from django.utils import timezone
from users.models import User


class Notification(models.Model):
    """
    Persistent in-app notification record for a specific user.
    Created by signal receivers and Celery tasks. Never modified once created.
    """
    EVENT_TYPES = (
        ('REPORT_SUBMITTED', 'Fraud Report Submitted'),
        ('REPORT_PUBLISHED', 'Fraud Report Published'),
        ('REPORT_REJECTED', 'Fraud Report Rejected'),
        ('DISPUTE_OPENED', 'Dispute Opened'),
        ('DISPUTE_RESOLVED', 'Dispute Resolved'),
        ('VERIFICATION_COMPLETED', 'Verification Completed'),
        ('VERIFICATION_REJECTED', 'Verification Rejected'),
        ('BROADCAST', 'Admin Broadcast'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    event_type = models.CharField(
        max_length=50,
        choices=EVENT_TYPES,
        db_index=True
    )
    title = models.CharField(max_length=255)
    body = models.TextField()
    # Reference to the source object (report ref, verification ref, etc.)
    object_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="e.g. FraudReport reference_number or VerificationRequest reference_number"
    )
    is_read = models.BooleanField(default=False, db_index=True)
    # Track which email gate delivered (for observability)
    email_provider_used = models.CharField(
        max_length=50,
        blank=True,
        help_text="Which email gate succeeded: mailtrap_api | namecheap_smtp | gmail_smtp | none"
    )
    email_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read', 'created_at']),
        ]

    def __str__(self):
        return f"[{self.event_type}] → {self.recipient.username}: {self.title}"

    def mark_read(self):
        """Mark this notification as read."""
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=['is_read', 'updated_at'])


class NotificationPreference(models.Model):
    """
    Per-user opt-out flags for each notification event type.
    One record per user; created on first access.
    Email opt-out only — in-app notifications are always created.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )
    email_report_submitted = models.BooleanField(
        default=True,
        help_text="Receive email when your fraud report is received"
    )
    email_report_published = models.BooleanField(
        default=True,
        help_text="Receive email when your fraud report is published"
    )
    email_report_rejected = models.BooleanField(
        default=True,
        help_text="Receive email when your fraud report is rejected"
    )
    email_dispute_opened = models.BooleanField(
        default=True,
        help_text="Receive email when a dispute is filed on your report"
    )
    email_dispute_resolved = models.BooleanField(
        default=True,
        help_text="Receive email when your dispute is resolved"
    )
    email_verification_completed = models.BooleanField(
        default=True,
        help_text="Receive email when your verification request completes"
    )
    email_verification_rejected = models.BooleanField(
        default=True,
        help_text="Receive email when your verification request is rejected"
    )
    email_broadcast = models.BooleanField(
        default=True,
        help_text="Receive admin broadcast emails"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Notification Preference'
        verbose_name_plural = 'Notification Preferences'

    def __str__(self):
        return f"NotificationPreference for {self.user.username}"

    @classmethod
    def for_user(cls, user):
        """Get or create notification preferences for a user."""
        prefs, _ = cls.objects.get_or_create(user=user)
        return prefs

    def email_enabled_for(self, event_type: str) -> bool:
        """Return True if email is enabled for this event type."""
        mapping = {
            'REPORT_SUBMITTED': self.email_report_submitted,
            'REPORT_PUBLISHED': self.email_report_published,
            'REPORT_REJECTED': self.email_report_rejected,
            'DISPUTE_OPENED': self.email_dispute_opened,
            'DISPUTE_RESOLVED': self.email_dispute_resolved,
            'VERIFICATION_COMPLETED': self.email_verification_completed,
            'VERIFICATION_REJECTED': self.email_verification_rejected,
            'BROADCAST': self.email_broadcast,
        }
        return mapping.get(event_type, True)
