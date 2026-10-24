from django.db import models
from django.utils import timezone
from users.models import User

class SubjectEntity(models.Model):
    ENTITY_TYPES = (
        ('person', 'Person / Individual'),
        ('business', 'Business / Company / Estate Developer'),
        ('property', 'Property / Real Estate / Land'),
        ('vehicle', 'Vehicle / Automobile'),
        ('asset', 'Asset / Contract / Credential'),
    )
    type = models.CharField(max_length=20, choices=ENTITY_TYPES, default='person')
    name = models.CharField(max_length=255, db_index=True)
    photo = models.ImageField(
        upload_to='subjects/photos/',
        null=True,
        blank=True,
        help_text="Optional photo of the subject. Displayed on report detail page.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Subject Entity'
        verbose_name_plural = 'Subject Entities'

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"


class Identifier(models.Model):
    IDENTIFIER_TYPES = (
        ('phone', 'Phone Number'),
        ('nin', 'NIN Hash'),
        ('bvn', 'BVN Hash'),
        ('account', 'Bank Account'),
        ('cac', 'CAC/RC Number'),
        ('email', 'Email Address'),
        ('plate_vin', 'Vehicle Plate / VIN Number'),
        ('property_ref', 'Land / Title / C of O Number'),
        ('cert_no', 'Certificate / Matric Number'),
    )
    subject = models.ForeignKey(SubjectEntity, on_delete=models.CASCADE, related_name='identifiers')
    type = models.CharField(max_length=20, choices=IDENTIFIER_TYPES)
    value_hash = models.CharField(max_length=255, unique=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Identifier'
        verbose_name_plural = 'Identifiers'

    def __str__(self):
        return f"{self.get_type_display()} for {self.subject.name}"


class BusinessProfile(models.Model):
    subject = models.OneToOneField(SubjectEntity, on_delete=models.CASCADE, related_name='business_profile')
    registration_number = models.CharField(max_length=100, blank=True, help_text="e.g. CAC RC/BN Number")
    official_name = models.CharField(max_length=255)
    address = models.TextField(blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=50, blank=True)
    is_verified_business = models.BooleanField(default=False, help_text="Application-controlled verification status")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Business Profile'
        verbose_name_plural = 'Business Profiles'

    def __str__(self):
        return self.official_name
    
# ─── ADD AT BOTTOM OF identities/models.py

class TrustScore(models.Model):
    """
    Computed trust score for a SubjectEntity.
    OneToOne — one score record per subject.
    Never computed inline on request; always pre-computed and stored.
    Recalculated by identities.trust_score.recalculate_trust_score() when:
      - A FraudReport transitions to 'published' or 'restricted'
      - A Dispute is resolved
      - A VerificationResult is created
    """

    subject = models.OneToOneField(
        'identities.SubjectEntity',
        on_delete=models.CASCADE,
        related_name='trust_score',
    )

    # Composite score 0–1000
    score = models.PositiveSmallIntegerField(default=500)

    # Component breakdowns (stored for transparency / audit)
    identity_score      = models.PositiveSmallIntegerField(default=0)   # max 300
    conduct_score       = models.PositiveSmallIntegerField(default=0)   # max 300
    reports_score       = models.PositiveSmallIntegerField(default=0)   # max 250
    longevity_score     = models.PositiveSmallIntegerField(default=0)   # max 150

    # Metadata
    published_reports_count  = models.PositiveSmallIntegerField(default=0)
    disputed_reports_count   = models.PositiveSmallIntegerField(default=0)
    restricted_reports_count = models.PositiveSmallIntegerField(default=0)
    is_identity_verified     = models.BooleanField(default=False)
    completed_verifications  = models.PositiveSmallIntegerField(default=0)

    calculated_at = models.DateTimeField(auto_now=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name      = 'Trust Score'
        verbose_name_plural = 'Trust Scores'

    def __str__(self):
        return f"TrustScore({self.subject.name}: {self.score}/1000)"

    @property
    def label(self):
        """Human-readable trust band for public display."""
        if self.score >= 800:
            return 'High Trust'
        elif self.score >= 600:
            return 'Moderate Trust'
        elif self.score >= 400:
            return 'Low Trust'
        elif self.score >= 200:
            return 'At Risk'
        return 'High Risk'

    @property
    def label_colour(self):
        """Bootstrap colour class for the trust band badge."""
        mapping = {
            'High Trust':     'success',
            'Moderate Trust': 'primary',
            'Low Trust':      'warning',
            'At Risk':        'orange',
            'High Risk':      'danger',
        }
        return mapping.get(self.label, 'secondary')