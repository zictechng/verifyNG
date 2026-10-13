
# employer/models.py
import uuid
from django.db import models
from django.utils import timezone
from users.models import User


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
    industry = models.CharField(max_length=100, blank=True)
    company_address = models.TextField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    is_verified = models.BooleanField(
        default=False,
        help_text="True when VerifyNG has confirmed the company identity"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Employer Profile'
        verbose_name_plural = 'Employer Profiles'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.company_name} ({self.user.username})"


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

