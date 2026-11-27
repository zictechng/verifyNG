
# employer/models.py
import uuid
from django.db import models
from django.utils import timezone
from users.models import User
import hashlib
import secrets as _secrets

class EmployerProfile(models.Model):
    """
    Extended profile for employer-role users.
    One-to-one with User. Created on first employer dashboard visit.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='employer_profile',
    )
    company_name = models.CharField(max_length=200)
    company_rc_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="CAC Registration Number (RC/BN)"
    )
    country = models.CharField(
        max_length=2,
        null=True,
        blank=True,
        db_index=True,
        help_text="ISO-2 country code of legal business registration (e.g. NG, GH, BJ, SN, KE)"
    )
    REGISTRATION_TYPE_CHOICES = (
        ('cac', 'Nigeria Corporate Affairs Commission (CAC)'),
        ('orc', 'Ghana Office of the Registrar of Companies (ORC)'),
        ('rccm', 'OHADA Commercial Registry (RCCM)'),
        ('brs', 'Kenya Business Registration Service (BRS)'),
        ('other', 'Other National Company Registry'),
    )
    registration_type = models.CharField(
        max_length=20,
        choices=REGISTRATION_TYPE_CHOICES,
        blank=True,
        default='',
        help_text="Official registry authority where the corporate entity is registered"
    )
    tax_identification_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text="National Tax Identification Number (TIN/IFU/PIN)"
    )
    industry = models.CharField(max_length=100, blank=True)
    business_nature = models.TextField(blank=True, default='', help_text="Summary of business operations and services")
    company_address = models.TextField(blank=True)
    company_website = models.URLField(blank=True, default='', help_text="Official company website or domain")
    contact_phone = models.CharField(max_length=20, blank=True)

    # ── Authorized Representative Particulars ──────────────────────────────
    representative_name = models.CharField(max_length=200, blank=True, default='', help_text="Full legal name of authorized representative")
    representative_title = models.CharField(max_length=100, blank=True, default='', help_text="Job title or role in organization (e.g. Director, HR Manager)")
    representative_email = models.EmailField(blank=True, default='', help_text="Official work email address")
    representative_phone = models.CharField(max_length=30, blank=True, default='', help_text="Direct phone number of representative")
    representative_id_type = models.CharField(max_length=50, blank=True, default='', help_text="Type of official identification document")
    representative_id_number = models.CharField(max_length=50, blank=True, default='', help_text="ID document number")
    representative_id_document = models.FileField(
        upload_to='rep_documents/%Y/%m/',
        blank=True,
        null=True,
        help_text="Photo page or front view of representative's ID"
    )

    # ── Stepper Flow State ────────────────────────────────────────────────
    current_step = models.PositiveSmallIntegerField(default=1, help_text="Current step in onboarding stepper wizard")
    VERIFICATION_STATUS_CHOICES = (
        ('unverified', 'Unverified'),
        ('pending', 'Pending Review'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
        ('suspended', 'Temporarily Suspended'),
        ('expired', 'Expired'),
    )
    cac_document = models.FileField(
        upload_to='cac_certificates/%Y/%m/',
        blank=True,
        null=True,
        help_text="Uploaded CAC Certificate or Status Report"
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default='unverified',
        help_text="Current compliance verification review status"
    )
    rejection_reason = models.TextField(
        blank=True,
        default='',
        help_text="Reason provided by compliance team if CAC verification is declined"
    )
    cac_uploaded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when CAC document was uploaded"
    )
    is_verified = models.BooleanField(
        default=False,
        help_text="True when VerifyNG has confirmed the company identity"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    is_billing_exempt = models.BooleanField(
        default=False,
        help_text="Master toggle: when True, all platform service fees are waived for this company."
    )
    exempt_services = models.JSONField(
        default=list,
        blank=True,
        help_text="Granular list of complimentary service keys (e.g. ['check', 'bulk_upload', 'monitoring'])"
    )
    billing_exempt_notes = models.CharField(
        max_length=255,
        blank=True,
        help_text="Reason for billing exemption (e.g. 'Law Enforcement MoU', 'Enterprise Pilot')"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Employer Profile'
        verbose_name_plural = 'Employer Profiles'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.company_name} ({self.user.username})"
    
    @property
    def public_id(self):
        """Return the unique UUID public_id of the associated user."""
        return self.user.public_id

    @property
    def organization_type(self):
        """Return the raw role code ('employer', 'agency', 'business')."""
        return getattr(self.user, 'role', 'employer')
    @property
    def organization_type_display(self):
        """Human-readable entity type for badges and UI headers."""
        role = getattr(self.user, 'role', 'employer')
        labels = {
            'employer': 'Employer',
            'agency': 'Authorized Agency',
            'business': 'Business Entity',
        }
        return labels.get(role, 'Organization')

    @property
    def has_cac_document(self):
        return bool(self.cac_document and hasattr(self.cac_document, 'name') and self.cac_document.name)

    @property
    def cac_document_is_pdf(self):
        if not self.has_cac_document:
            return False
        return self.cac_document.name.lower().endswith('.pdf')

    @property
    def cac_filename(self):
        if not self.has_cac_document:
            return ""
        import os
        return os.path.basename(self.cac_document.name)

    @property
    def has_representative_document(self):
        return bool(self.representative_id_document and hasattr(self.representative_id_document, 'name') and self.representative_id_document.name)

    @property
    def representative_document_is_pdf(self):
        if not self.has_representative_document:
            return False
        return self.representative_id_document.name.lower().endswith('.pdf')

    @property
    def representative_document_filename(self):
        if not self.has_representative_document:
            return ""
        import os
        return os.path.basename(self.representative_id_document.name)


class TeamMember(models.Model):
    """
    Secondary users who can run checks on behalf of the employer account.
    Invited by the primary employer user.
    """
    ROLE_CHOICES = (
        ('admin', 'Team Admin'),
        ('checker', 'Checker'),
        ('viewer', 'Viewer'),
    )

    employer = models.ForeignKey(
        EmployerProfile,
        on_delete=models.CASCADE,
        related_name='team_members',
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='employer_memberships',
    )
    team_role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='checker',
    )
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='employer_invitations_sent',
    )
    joined_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Team Member'
        verbose_name_plural = 'Team Members'
        unique_together = [('employer', 'user')]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} → {self.employer.company_name} ({self.get_team_role_display()})"


class BulkCheckUpload(models.Model):
    """
    A CSV/spreadsheet uploaded by an employer for bulk verification.
    Each row in the file becomes a BulkCheckRow.
    """
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employer = models.ForeignKey(
        EmployerProfile,
        on_delete=models.CASCADE,
        related_name='bulk_uploads',
    )
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='bulk_check_uploads',
    )
    original_filename = models.CharField(max_length=255)
    file_path = models.CharField(
        max_length=500,
        blank=True,
        help_text="Cloudinary public_id or S3 key — never a local filesystem path"
    )
    row_count = models.PositiveIntegerField(default=0)
    processed_count = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
    )
    error_summary = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Bulk Check Upload'
        verbose_name_plural = 'Bulk Check Uploads'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.original_filename} — {self.employer.company_name} ({self.get_status_display()})"

    @property
    def progress_pct(self) -> int:
        if not self.row_count:
            return 0
        return int((self.processed_count / self.row_count) * 100)


class BulkCheckRow(models.Model):
    """
    One candidate row within a BulkCheckUpload.
    Status tracks processing lifecycle per row.
    """
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('checking', 'Checking'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped — insufficient data'),
    )

    upload = models.ForeignKey(
        BulkCheckUpload,
        on_delete=models.CASCADE,
        related_name='rows',
    )
    row_number = models.PositiveIntegerField()
    full_name = models.CharField(max_length=200, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    nin_hash = models.CharField(
        max_length=64,
        blank=True,
        help_text="SHA-256 hash of NIN — never store raw NIN"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
    )
    result_summary = models.TextField(blank=True)
    result_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Structured check result for this row"
    )
    checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Bulk Check Row'
        verbose_name_plural = 'Bulk Check Rows'
        ordering = ['row_number']
        unique_together = [('upload', 'row_number')]

    def __str__(self):
        return f"Row {self.row_number} — {self.full_name or 'unnamed'} ({self.get_status_display()})"


# ── BATCH 1: Staff Check Request ─────────────────────────────────────────────

def _hash_nin(raw_nin: str) -> str:
    """SHA-256 hash of a raw NIN string. Never store raw NIN."""
    return hashlib.sha256(raw_nin.strip().encode('utf-8')).hexdigest()


class StaffCheckRequest(models.Model):
    """
    A single background check request submitted by an employer for one staff member.
    NIN is stored only as SHA-256 hash — never in plain text.
    """
    CHECK_TYPES = (
        ('standard', 'Standard Check'),
        ('enhanced', 'Enhanced Check'),
    )
    STATUS_CHOICES = (
        ('pending',     'Pending'),
        ('pending_payment', 'Pending Payment'),
        ('processing',  'Processing'),
        ('completed',   'Completed'),
        ('failed',      'Failed'),
        ('cancelled',   'Cancelled'),
    )

    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employer       = models.ForeignKey(
        EmployerProfile,
        on_delete=models.CASCADE,
        related_name='staff_checks',
    )
    requested_by   = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='staff_check_requests',
    )
    full_name      = models.CharField(max_length=200)
    phone_number   = models.CharField(max_length=20, blank=True)
    nin_hash       = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="SHA-256 hash of NIN — never store raw NIN",
    )
    email          = models.EmailField(blank=True)
    check_type     = models.CharField(
        max_length=20,
        choices=CHECK_TYPES,
        default='standard',
        db_index=True,
    )
    purpose        = models.CharField(
        max_length=200,
        blank=True,
        help_text="e.g. Driver role, Security Officer, Care Worker",
    )
    status         = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
    )
    result_summary = models.TextField(blank=True)
    result_data    = models.JSONField(default=dict, blank=True)
    fraud_flags    = models.PositiveSmallIntegerField(
        default=0,
        help_text="Count of published fraud reports matched to this subject",
    )
    notes          = models.TextField(blank=True)
    completed_at   = models.DateTimeField(null=True, blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)
    is_active      = models.BooleanField(default=True)

    class Meta:
        verbose_name        = 'Staff Check Request'
        verbose_name_plural = 'Staff Check Requests'
        ordering            = ['-created_at']
        indexes             = [
            models.Index(fields=['employer', 'status']),
            models.Index(fields=['nin_hash']),
        ]

    def __str__(self):
        return f"{self.full_name} — {self.employer.company_name} ({self.get_status_display()})"


class StaffCheckMonitor(models.Model):
    """
    Ongoing monitoring record for a staff member after their initial check.
    When active, VerifyNG re-checks this subject periodically and alerts the employer
    if their fraud flag count or certificate status changes.
    """
    MONITOR_STATUS = (
        ('active',    'Active — monitoring'),
        ('paused',    'Paused'),
        ('cancelled', 'Cancelled'),
    )

    check_request  = models.OneToOneField(
        StaffCheckRequest,
        on_delete=models.CASCADE,
        related_name='monitor',
    )
    employer       = models.ForeignKey(
        EmployerProfile,
        on_delete=models.CASCADE,
        related_name='staff_monitors',
    )
    monitor_status = models.CharField(
        max_length=20,
        choices=MONITOR_STATUS,
        default='active',
        db_index=True,
    )
    alert_on_change = models.BooleanField(
        default=True,
        help_text="Notify employer by email when this staff member's status changes",
    )
    last_checked   = models.DateTimeField(null=True, blank=True)
    next_check     = models.DateTimeField(null=True, blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)
    is_active      = models.BooleanField(default=True)

    class Meta:
        verbose_name        = 'Staff Check Monitor'
        verbose_name_plural = 'Staff Check Monitors'
        ordering            = ['-created_at']

    def __str__(self):
        return f"Monitor: {self.check_request.full_name} — {self.get_monitor_status_display()}"



# ── BATCH 3: Team Invitations ─────────────────────────────────────────────────

class TeamInvite(models.Model):
    """
    A pending invitation email sent to a new team member.
    Token is a URL-safe 48-character random string.
    Expires 7 days after creation.
    """
    STATUS_CHOICES = (
        ('pending',  'Pending — not yet accepted'),
        ('accepted', 'Accepted'),
        ('expired',  'Expired'),
        ('revoked',  'Revoked'),
    )
    ROLE_CHOICES = (
        ('admin',   'Team Admin'),
        ('checker', 'Checker'),
        ('viewer',  'Viewer'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employer = models.ForeignKey(
        EmployerProfile,
        on_delete=models.CASCADE,
        related_name='invitations',
    )
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='invitations_sent',
    )
    email = models.EmailField(db_index=True)
    team_role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='checker')
    token = models.CharField(max_length=64, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    accepted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invitations_accepted',
    )
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Team Invitation'
        verbose_name_plural = 'Team Invitations'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['employer', 'status']),
        ]

    def __str__(self):
        return f"Invite → {self.email} ({self.employer.company_name}) [{self.get_status_display()}]"

    @classmethod
    def generate_token(cls) -> str:
        return _secrets.token_urlsafe(36)

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone
        return self.expires_at < timezone.now()

    @property
    def is_usable(self) -> bool:
        return self.status == 'pending' and not self.is_expired





