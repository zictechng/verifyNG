
# payments/models.py
from django.conf import settings
import uuid
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from users.models import User


class SiteSettings(models.Model):
    """
    Singleton model — only one row ever exists.
    Admin edits this row to control global free-tier limits.
    """
    free_check_limit = models.PositiveIntegerField(
        default=3,
        help_text="Number of free checks an unsubscribed user gets per window."
    )
    free_check_window_days = models.PositiveIntegerField(
        default=30,
        help_text="Rolling window in days for the free check quota."
    )
    maintenance_mode = models.BooleanField(
        default=False,
        help_text="Put the payment system into maintenance mode (disables checkout)."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Site Settings'
        verbose_name_plural = 'Site Settings'

    def __str__(self):
        return f"Site Settings (free limit: {self.free_check_limit} per {self.free_check_window_days} days)"

    @classmethod
    def get(cls):
        """Always returns the singleton instance, creating it if absent."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class PlatformConfiguration(models.Model):
    """
    Singleton — platform-wide branding and configuration.
    One row only; use PlatformConfiguration.get() everywhere.
    """
    # Branding
    platform_name = models.CharField(max_length=100, default='VerifyNG')
    tagline = models.CharField(max_length=255, blank=True, default='Nigeria\'s Public Trust & Safety Platform')
    logo = models.ImageField(upload_to='platform/branding/', null=True, blank=True, help_text='Main platform logo')
    favicon = models.ImageField(upload_to='platform/branding/', null=True, blank=True, help_text='Browser favicon (32x32 ICO or PNG)')
    logo_alt_text = models.CharField(max_length=100, blank=True, default='VerifyNG Logo')

    # Contact & Identity
    company_name = models.CharField(max_length=200, blank=True, default='VerifyNG Limited')
    company_reg_number = models.CharField(max_length=50, blank=True, help_text='CAC Registration Number')
    support_email = models.EmailField(blank=True, default='support@verifyng.com')
    contact_phone = models.CharField(max_length=20, blank=True)
    contact_address = models.TextField(blank=True)

    # Social Links
    twitter_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    facebook_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)
    whatsapp_number = models.CharField(max_length=20, blank=True, help_text='WhatsApp business number (e.g. +2349012345678)')

    # SEO / Meta
    meta_description = models.TextField(blank=True, max_length=160)
    meta_keywords = models.TextField(blank=True, help_text='Comma-separated keywords')

    # System
    maintenance_mode = models.BooleanField(default=False)
    maintenance_message = models.TextField(blank=True, default='Platform undergoing scheduled maintenance. We\'ll be back shortly.')
        # ── Per-service kill switches ─────────────────────────────────────────────
    service_check_suspended = models.BooleanField(
        default=False,
        help_text="Suspend the public CHECK service platform-wide."
    )
    service_report_suspended = models.BooleanField(
        default=False,
        help_text="Suspend the REPORT (fraud report submission) service platform-wide."
    )
    service_verify_suspended = models.BooleanField(
        default=False,
        help_text="Suspend the VERIFY (trust profile) service platform-wide."
    )
    service_employment_suspended = models.BooleanField(
        default=False,
        help_text="Suspend the EMPLOYMENT verification service platform-wide."
    )
    service_suspension_message = models.TextField(
        blank=True,
        default='This service is temporarily unavailable. Please try again later.',
        help_text="Message shown to users when a service is suspended."
    )
    footer_copyright_text = models.CharField(max_length=255, blank=True, default='© 2024 VerifyNG Limited. All rights reserved.')

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        'users.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='platform_config_updates'
    )

    class Meta:
        verbose_name = 'Platform Configuration'
        verbose_name_plural = 'Platform Configuration'

    def __str__(self):
        return f"Platform Config: {self.platform_name}"

    @classmethod
    def get(cls):
        """Returns the singleton instance, creating defaults if absent."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Plan(models.Model):
    INTERVAL_CHOICES = (
        ('one_time', 'One-Time'),
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
    )

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    price_kobo = models.PositiveIntegerField(
        default=0,
        help_text="Price in kobo (100 kobo = ₦1). Set 0 for a free plan."
    )
    currency = models.CharField(max_length=3, default='NGN')
    interval = models.CharField(
        max_length=10,
        choices=INTERVAL_CHOICES,
        default='monthly'
    )
    check_limit = models.IntegerField(
        default=10,
        validators=[MinValueValidator(-1)],
        help_text="Number of checks allowed per period. -1 means unlimited."
    )
    paystack_plan_code = models.CharField(
        max_length=100,
        blank=True,
        help_text="Paystack plan code for recurring subscriptions (auto-populated)."
    )
    is_active = models.BooleanField(default=True, db_index=True)
    is_featured = models.BooleanField(
        default=False,
        help_text="Highlight this plan as recommended on the plans page."
    )
    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Lower numbers appear first."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active_record = models.BooleanField(default=True)

    class Meta:
        ordering = ['display_order', 'price_kobo']
        verbose_name = 'Plan'
        verbose_name_plural = 'Plans'

    def __str__(self):
        return f"{self.name} (₦{self.price_naira:,.0f}/{self.get_interval_display()})"

    @property
    def price_naira(self):
        return self.price_kobo / 100

    @property
    def is_free(self):
        return self.price_kobo == 0

    @property
    def has_unlimited_checks(self):
        return self.check_limit == -1


class PlanFeature(models.Model):
    """Bullet-point features displayed on the plan card. Fully admin-managed."""
    plan = models.ForeignKey(
        Plan,
        on_delete=models.CASCADE,
        related_name='features'
    )
    feature_text = models.CharField(max_length=200)
    is_included = models.BooleanField(
        default=True,
        help_text="False = feature is crossed out (not included in this plan)."
    )
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order']
        verbose_name = 'Plan Feature'
        verbose_name_plural = 'Plan Features'

    def __str__(self):
        prefix = '✓' if self.is_included else '✗'
        return f"{prefix} {self.feature_text} ({self.plan.name})"


class Subscription(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
        ('past_due', 'Past Due'),
        ('pending', 'Pending'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='subscriptions'
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name='subscriptions'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    paystack_subscription_code = models.CharField(max_length=100, blank=True)
    paystack_customer_code = models.CharField(max_length=100, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Subscription'
        verbose_name_plural = 'Subscriptions'

    def __str__(self):
        return f"{self.user.username} — {self.plan.name} ({self.get_status_display()})"

    @property
    def is_currently_active(self):
        if self.status != 'active':
            return False
        if self.current_period_end and timezone.now() > self.current_period_end:
            return False
        return True

    @property
    def days_remaining(self):
        if not self.current_period_end:
            return None
        delta = self.current_period_end - timezone.now()
        return max(0, delta.days)


class Transaction(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
        ('abandoned', 'Abandoned'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='transactions'
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )
    reference = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="VerifyNG-generated unique reference sent to Paystack."
    )
    paystack_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Paystack's own transaction reference."
    )
    amount_kobo = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default='NGN')
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    failure_reason = models.TextField(blank=True)
    paystack_response = models.JSONField(
        default=dict,
        blank=True,
        help_text="Full Paystack API response stored for audit."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Transaction'
        verbose_name_plural = 'Transactions'

    def __str__(self):
        return f"{self.reference} — ₦{self.amount_naira:,.0f} ({self.get_status_display()})"

    @property
    def amount_naira(self):
        return self.amount_kobo / 100


class FreeUsageQuota(models.Model):
    """
    Tracks free check usage per user.
    Reset logic driven by SiteSettings.free_check_window_days.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='free_quota'
    )
    checks_used = models.PositiveIntegerField(default=0)
    quota_period_start = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Free Usage Quota'
        verbose_name_plural = 'Free Usage Quotas'

    def __str__(self):
        return f"{self.user.username} — {self.checks_used} checks used"

    def reset_if_expired(self):
        settings = SiteSettings.get()
        window = settings.free_check_window_days
        elapsed = (timezone.now() - self.quota_period_start).days
        if elapsed >= window:
            self.checks_used = 0
            self.quota_period_start = timezone.now()
            self.save(update_fields=['checks_used', 'quota_period_start', 'updated_at'])

    @classmethod
    def for_user(cls, user):
        obj, _ = cls.objects.get_or_create(user=user)
        obj.reset_if_expired()
        return obj


class PaymentAuditLog(models.Model):
    """
    Immutable audit log for all payment-related events.
    Never delete or update rows — append only.
    """
    ACTION_CHOICES = (
        ('CHECKOUT_INITIATED', 'Checkout Initiated'),
        ('PAYMENT_SUCCESS', 'Payment Success'),
        ('PAYMENT_FAILED', 'Payment Failed'),
        ('SUBSCRIPTION_ACTIVATED', 'Subscription Activated'),
        ('SUBSCRIPTION_CANCELLED', 'Subscription Cancelled'),
        ('FREE_PLAN_ACTIVATED', 'Free Plan Activated'),
        ('WEBHOOK_RECEIVED', 'Webhook Event Received'),
        ('WEBHOOK_SUBSCRIPTION_DISABLED', 'Webhook: Subscription Disabled'),
        ('WEBHOOK_PAYMENT_FAILED', 'Webhook: Payment Failed'),
    )

    action = models.CharField(max_length=60, choices=ACTION_CHOICES, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_audit_logs',
    )
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Payment Audit Log'
        verbose_name_plural = 'Payment Audit Logs'

    def __str__(self):
        return f"{self.action} — {self.user} at {self.timestamp:%Y-%m-%d %H:%M}"





