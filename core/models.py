from django.db import models
from django.core.exceptions import ValidationError


class SiteConfigurationQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError("SiteConfiguration records cannot be deleted.")


class SiteConfigurationManager(models.Manager):
    def get_queryset(self):
        return SiteConfigurationQuerySet(self.model, using=self._db)


class SiteConfiguration(models.Model):
    """
    Singleton configuration model for global site branding and metadata.
    Enforces a single database record at pk=1 at both application and database engine levels.

    All values here are injected into every web template via core.context_processors
    and into every email via core.email_utils.render_email().
    Update once in Django admin → everywhere reflects immediately.
    """

    # ── Branding ─────────────────────────────────────────────────────────────
    site_name = models.CharField(
        max_length=100,
        default='VerifyNG',
        help_text="Public platform name displayed in navigation, title tags, emails, and footer.",
    )
    site_tagline = models.CharField(
        max_length=255,
        default='Public Trust & Safety Platform',
        help_text="Short descriptive tagline for headers and meta description.",
    )
    logo = models.ImageField(
        upload_to='branding/',
        blank=True,
        null=True,
        help_text="Upload brand logo (PNG, WEBP, JPEG). Displays at 32px height in navbar.",
    )
    favicon = models.ImageField(
        upload_to='branding/',
        blank=True,
        null=True,
        help_text="Browser tab icon (ICO, PNG).",
    )

    # ── Contact & Identity ────────────────────────────────────────────────────
    base_url = models.URLField(
        blank=True,
        default='',
        help_text=(
            "Canonical site URL used in emails and generated links. "
            "No trailing slash. Example: https://verifyng.com"
        ),
    )
    support_email = models.EmailField(
        default='support@verifyng.com',
        help_text="Support email address shown in emails, footer, and generated documents.",
    )
    company_reg_number = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="Company registration number shown on issued VerifyNG documents.",
    )
    company_address = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="Physical or registered address shown in email footer.",
    )

    # ── Social Links ──────────────────────────────────────────────────────────
    twitter_url = models.URLField(
        blank=True,
        default='',
        help_text="Twitter / X profile URL. Leave blank to hide in footer.",
    )
    facebook_url = models.URLField(
        blank=True,
        default='',
        help_text="Facebook page URL. Leave blank to hide in footer.",
    )
    instagram_url = models.URLField(
        blank=True,
        default='',
        help_text="Instagram profile URL. Leave blank to hide in footer.",
    )
    linkedin_url = models.URLField(
        blank=True,
        default='',
        help_text="LinkedIn company page URL. Leave blank to hide in footer.",
    )
    youtube_url = models.URLField(
        blank=True,
        default='',
        help_text="YouTube channel URL. Leave blank to hide in footer.",
    )
    whatsapp_number = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text="WhatsApp contact number in international format, e.g. +2348012345678.",
    )

    # ── Footer ────────────────────────────────────────────────────────────────
    footer_text = models.CharField(
        max_length=255,
        default='Built for a safer Nigerian digital ecosystem.',
        help_text="Custom text displayed in the website footer.",
    )

    # ── Meta ──────────────────────────────────────────────────────────────────
    updated_at = models.DateTimeField(auto_now=True)

    objects = SiteConfigurationManager()

    class Meta:
        verbose_name = 'Site Configuration'
        verbose_name_plural = 'Site Configuration'
        constraints = [
            models.CheckConstraint(
                check=models.Q(pk=1),
                name='site_configuration_single_row_check',
            )
        ]

    def __str__(self):
        return f"{self.site_name} Configuration"

    def clean(self):
        if self.pk is not None and self.pk != 1:
            raise ValidationError("SiteConfiguration record must have primary key 1.")
        record_exists = SiteConfiguration.objects.filter(pk=1).exists()
        if self._state.adding and record_exists:
            raise ValidationError(
                "A SiteConfiguration record already exists. Duplicate creation is prohibited."
            )

    def save(self, *args, **kwargs):
        if self.pk is not None and self.pk != 1:
            raise ValidationError("SiteConfiguration record must have primary key 1.")

        record_exists = SiteConfiguration.objects.filter(pk=1).exists()

        if self._state.adding:
            if record_exists:
                raise ValidationError(
                    "A SiteConfiguration record already exists. Duplicate creation is prohibited."
                )
            if self.pk is None:
                self.pk = 1
        else:
            if self.pk != 1:
                raise ValidationError("SiteConfiguration record must have primary key 1.")

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("SiteConfiguration cannot be deleted.")

    @property
    def dynamic_base_url(self) -> str:
        from core.site_utils import get_dynamic_base_url
        return get_dynamic_base_url()

    @classmethod
    def get_solo(cls):
        """
        Retrieves or initialises the singleton configuration record (pk=1).
        Always use this method — never SiteConfiguration.objects.get(pk=1) directly.
        """
        config, _ = cls.objects.get_or_create(pk=1)
        return config
