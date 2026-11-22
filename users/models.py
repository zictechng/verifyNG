from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
import uuid
from core.storage import private_evidence_storage


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
    ID_TYPE_CHOICES = (
        ('nin', 'National Identity Number (NIN)'),
        ('bvn', 'Bank Verification Number (Legacy BVN)'),
        ('voters_card', 'Permanent Voter Card (PVC)'),
        ('passport', 'International Passport'),
        ('drivers_license', "Driver's License"),
        ('ghana_card', 'Ghana Card (NIA)'),
        ('cip', "Certificat d'Identification Personnelle (CIP)"),
        ('cni', "Carte Nationale d'Identité (CNI)"),
        ('national_id', 'National Identity Card'),
    )

    ASSURANCE_LEVEL_CHOICES = (
        ('unverified', 'Unverified'),
        ('basic_verified', 'Basic Identity Evidence Reviewed'),
        ('enhanced_verified', 'Enhanced Identity Verified'),
    )

    ID_STATUS_CHOICES = (
        ('unverified', 'Unverified'),
        ('pending', 'Pending Compliance Review'),
        ('verified', 'Verified'),
        ('rejected', 'Declined'),
        ('suspended', 'Temporarily Suspended'),
        ('expired', 'Expired'),
    )

    country = models.CharField(
        max_length=2,
        null=True,
        blank=True,
        db_index=True,
        help_text="ISO-2 country code of citizenship or residence (e.g. NG, GH, BJ, SN, KE)"
    )
    state = models.CharField(
        max_length=100,
        blank=True,
        default='',
        db_index=True,
        help_text="State, Province, or Region of residence"
    )
    lga = models.CharField(
        max_length=100,
        blank=True,
        default='',
        db_index=True,
        help_text="Local Government Area, County, or District of residence"
    )
    assurance_level = models.CharField(
        max_length=25,
        choices=ASSURANCE_LEVEL_CHOICES,
        default='unverified',
        db_index=True,
        help_text="Identity assurance tier established by reviewed evidence"
    )

    id_type = models.CharField(
        max_length=30,
        choices=ID_TYPE_CHOICES,
        blank=True,
        default='',
        help_text="Type of official government identity provided"
    )
    id_number = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="Official ID number provided by user"
    )
    id_document = models.FileField(
        upload_to='identity_proofs/%Y/%m/',
        blank=True,
        null=True,
        help_text="Uploaded scan/photo of government ID"
    )
    id_selfie_image = models.FileField(
        upload_to='identity_selfies/%Y/%m/',
        blank=True,
        null=True,
        help_text="Live camera selfie photo captured for government ID face matching"
    )
    phone_number = models.CharField(
        max_length=30,
        blank=True,
        default='',
        help_text="User phone number (E.164 international format)"
    )
    phone_verified = models.BooleanField(
        default=False,
        help_text="Designates whether the user's phone number has been verified via OTP."
    )
    email_verified = models.BooleanField(
        default=False,
        help_text="Designates whether the user's email address has been verified."
    )
    id_verification_status = models.CharField(
        max_length=20,
        choices=ID_STATUS_CHOICES,
        default='unverified',
        db_index=True,
        help_text="Current identity verification review status"
    )
    id_rejection_reason = models.TextField(
        blank=True,
        default='',
        help_text="Reason provided by compliance officer if rejected"
    )
    id_submitted_at = models.DateTimeField(null=True, blank=True)
    id_verified_at = models.DateTimeField(null=True, blank=True)
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
        help_text="Master toggle: when True, all platform service fees are waived for this specific user/agency account."
    )
    exempt_services = models.JSONField(
        default=list,
        blank=True,
        help_text="Granular list of complimentary service keys for this user/agency (e.g. ['check', 'verification'])"
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
    can_publish_reports = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Designates whether compliance has approved this user to publish community reports."
    )
    @property
    def has_selfie(self):
        return bool(self.id_selfie_image and hasattr(self.id_selfie_image, 'name') and self.id_selfie_image.name)

    @property
    def is_email_verified(self):
        if self.email_verified:
            return True
        try:
            from allauth.account.models import EmailAddress
            return EmailAddress.objects.filter(user=self, verified=True).exists()
        except Exception:
            return False

    @property
    def has_id_document(self):
        return bool(self.id_document and hasattr(self.id_document, 'name') and self.id_document.name)

    @property
    def id_document_is_pdf(self):
        if not self.has_id_document:
            return False
        return self.id_document.name.lower().endswith('.pdf')

    @property
    def id_document_filename(self):
        if not self.has_id_document:
            return ""
        import os
        return os.path.basename(self.id_document.name)

    @property
    def masked_id_number(self):
        if not self.id_number:
            return ""
        val = str(self.id_number).strip()
        if len(val) <= 4:
            return val
        return "*" * (len(val) - 4) + val[-4:]

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
        if not isinstance(self.can_publish_reports, bool):
            self.can_publish_reports = False
        if not isinstance(self.is_billing_exempt, bool):
            self.is_billing_exempt = False
        if not isinstance(self.is_active, bool):
            self.is_active = bool(self.is_active)
        if not isinstance(self.phone_verified, bool):
            self.phone_verified = False
        if not isinstance(self.email_verified, bool):
            self.email_verified = False
        if self.role in ('moderator', 'officer'):
            self.is_staff = True
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

    @property
    def was_successful(self) -> bool:
        return self.status == 'success'


class UserServiceAccess(models.Model):
    """
    Per-user service-level access control.
    When is_restricted=True for a service, that user cannot use that service
    even if their account is otherwise active.
    This is separate from full account suspension.
    """

    SERVICE_CHOICES = (
        ('public_check',       'Public Record Check (/check/)'),
        ('person_check',       'Person Quick-Check'),
        ('staff_check',        'Staff Background Check'),
        ('bulk_upload',        'Bulk CSV Screening'),
        ('verification',       'Business / CAC Verification'),
        ('certificate',        'TrustPass Certificate Application'),
        ('certificate_verify', 'Verify Workforce Certificate (TrustPass)'),
        ('monitoring',         'Certificate Monitoring Services (TrustPass)'),
        ('fraud_report',       'Fraud Crime Reporting'),
        ('misconduct_report',  'Staff Misconduct Reporting'),
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


class AlternativeVerificationSubmission(models.Model):
    """
    Submission and review record for Alternative Person Verification (Path B).
    Completely decoupled from government identity verification (Path A).
    Allows individuals without government ID to establish personhood for community reporting.
    """
    STATUS_CHOICES = (
        ('pending', 'Pending Compliance Review'),
        ('approved', 'Approved for Report Publishing'),
        ('rejected', 'Declined — Resubmission Allowed'),
        ('revoked', 'Revoked by Compliance'),
    )

    EVIDENCE_TYPE_CHOICES = (
        ('selfie_card', 'Manual Selfie Challenge with Date/Verification Card'),
        ('video_challenge', 'Recorded Video Prompt (Extensible)'),
        ('third_party_liveness', 'External Certified Liveness Check (Extensible)'),
    )

    user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='alternative_verification_submissions',
        help_text="Applicant account"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    evidence_type = models.CharField(
        max_length=30,
        choices=EVIDENCE_TYPE_CHOICES,
        default='selfie_card',
        help_text="Format of personhood evidence submitted (manual review baseline)"
    )

    # Evidence Uploads (Restricted private storage; no public URLs)
    selfie_image = models.FileField(
        storage=private_evidence_storage,
        upload_to='alternative_proofs/%Y/%m/',
        help_text="Selfie challenge image showing user holding handwritten verification card"
    )
    supporting_document = models.FileField(
        storage=private_evidence_storage,
        upload_to='alternative_proofs/%Y/%m/',
        blank=True,
        null=True,
        help_text="Optional non-ID proof of address, workplace letter, or utility bill"
    )

    # Residential & Personhood Declaration
    residential_country = models.CharField(
        max_length=2,
        help_text="ISO-2 country code of physical residence"
    )
    residential_address = models.TextField(
        help_text="Declared physical residential address"
    )
    declaration_statement = models.TextField(
        blank=True,
        default='',
        help_text="Applicant statement confirming truthfulness of identity"
    )

    # Review & Lifecycle Attribution
    submitted_at = models.DateTimeField(
        default=timezone.now,
        db_index=True
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True
    )
    reviewed_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='alternative_verifications_reviewed',
        help_text="Compliance officer who evaluated the submission"
    )
    rejection_reason = models.TextField(
        blank=True,
        default='',
        help_text="Feedback provided by compliance officer if declined"
    )

    class Meta:
        verbose_name = "Alternative Verification Submission"
        verbose_name_plural = "Alternative Verification Submissions"
        ordering = ['-submitted_at', '-id']

    def __str__(self):
        return f"Path B Submission for {self.user.username} ({self.status}) at {self.submitted_at:%Y-%m-%d}"


