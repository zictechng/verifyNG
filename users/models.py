from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
import uuid

class User(AbstractUser):
    ROLE_CHOICES = (
        ('individual', 'Individual'),
        ('employer', 'Employer'),
        ('business', 'Business Entity'),
        ('moderator', 'Moderator'),
        ('officer', 'Verification Officer'),
        ('agency', 'Authorized Agency'),
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='individual',
        db_index=True,
        help_text="Primary RBAC role assignment"
    )
    email = models.EmailField(
    unique=True,
    help_text="Required. Must be unique across all accounts.",
    )
    identity_verified = models.BooleanField(
        default=False,
        help_text="User identity verification status"
    )
    is_billing_exempt = models.BooleanField(
        default=False,
        help_text="When True, check and verification fees are waived for this specific user/agency account."
    )
    billing_exempt_notes = models.CharField(
        max_length=255,
        blank=True,
        help_text="Reason for billing exemption (e.g. 'Security Agency Exemption', 'Official Regulator')"
    )
    is_suspended = models.BooleanField(
        default=False,
        help_text=(
            "Suspended users can still log in but cannot perform any platform actions. "
            "Use is_active=False to fully block login."
        ),
    )
    public_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True,
        help_text="Public-facing user identifier — never expose the integer PK"
    )
    def is_individual(self):
        return self.role == 'individual'

    def is_employer(self):
        return self.role == 'employer'

    def is_business_user(self):
        return self.role == 'business'

    def is_moderator(self):
        return self.role == 'moderator'

    def is_verification_officer(self):
        return self.role == 'officer'

    def is_authorized_agency(self):
        return self.role == 'agency'
    def save(self, *args, **kwargs):
    # Django 5.1 creates functools.partial descriptors for BooleanFields
    # which can leak into instance attributes during save(). Force bool types.
        if not isinstance(self.identity_verified, bool):
            self.identity_verified = False
        if not isinstance(self.is_billing_exempt, bool):
            self.is_billing_exempt = False
        if not isinstance(self.is_active, bool):
            self.is_active = bool(self.is_active)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
    
   


class LoginAudit(models.Model):
    STATUS_CHOICES = (
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('blocked', 'Blocked / Suspended'),
    )

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='login_audits'
    )
    username_attempted = models.CharField(
        max_length=150,
        db_index=True
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True
    )
    user_agent = models.TextField(
        blank=True
    )
    device_type = models.CharField(
        max_length=50,
        default='Desktop'
    )
    browser = models.CharField(
        max_length=50,
        default='Unknown'
    )
    os = models.CharField(
        max_length=50,
        default='Unknown'
    )
    location_country = models.CharField(
        max_length=100,
        default='Nigeria'
    )
    location_city = models.CharField(
        max_length=100,
        default='Lagos'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='success',
        db_index=True
    )
    failure_reason = models.CharField(
        max_length=255,
        blank=True
    )
    timestamp = models.DateTimeField(
        default=timezone.now,
        db_index=True
    )

    class Meta:
        verbose_name = 'Login Audit'
        verbose_name_plural = 'Login Audits'
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.username_attempted} ({self.status}) at {self.timestamp}"


class UserServiceAccess(models.Model):
    """
    Per-user service-level access control.
    When is_restricted=True for a service, that user cannot use that service
    even if their account is otherwise active.
    This is separate from full account suspension.
    """

    SERVICE_CHOICES = (
        ('check',        'Search / Check'),
        ('fraud_report', 'Fraud Reporting'),
        ('verification', 'Identity Verification'),
        ('certificate',  'Certificate Application'),
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='service_access_rules',
    )
    service = models.CharField(
        max_length=30,
        choices=SERVICE_CHOICES,
        db_index=True,
    )
    is_restricted = models.BooleanField(
        default=False,
        help_text='True = user is blocked from this service only.',
    )
    restricted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_restrictions_applied',
    )
    restricted_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Service Access'
        verbose_name_plural = 'User Service Access Rules'
        unique_together = [('user', 'service')]
        ordering = ['user', 'service']

    def __str__(self):
        state = 'RESTRICTED' if self.is_restricted else 'allowed'
        return f"{self.user.username} → {self.service}: {state}"

