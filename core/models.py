
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
    """
    site_name = models.CharField(
        max_length=100,
        default='VerifyNG',
        help_text="Public platform name displayed in navigation, title tags, and footer."
    )
    site_tagline = models.CharField(
        max_length=255,
        default='Public Trust & Safety Platform',
        help_text="Short descriptive tagline for headers and meta description."
    )
    logo = models.ImageField(
        upload_to='branding/',
        blank=True,
        null=True,
        help_text="Upload brand logo (PNG, WEBP, JPEG). Displays at 32px height in navbar."
    )
    favicon = models.ImageField(
        upload_to='branding/',
        blank=True,
        null=True,
        help_text="Browser tab icon (ICO, PNG)."
    )
    footer_text = models.CharField(
        max_length=255,
        default='Built for a safer Nigerian digital ecosystem.',
        help_text="Custom text displayed in the website footer."
    )
    updated_at = models.DateTimeField(auto_now=True)

    objects = SiteConfigurationManager()

    class Meta:
        verbose_name = 'Site Configuration'
        verbose_name_plural = 'Site Configuration'
        constraints = [
            models.CheckConstraint(
                check=models.Q(pk=1),
                name='site_configuration_single_row_check'
            )
        ]

    def __str__(self):
        return f"{self.site_name} Configuration"

    def clean(self):
        if self.pk is not None and self.pk != 1:
            raise ValidationError("SiteConfiguration record must have primary key 1.")
        record_exists = SiteConfiguration.objects.filter(pk=1).exists()
        if self._state.adding and record_exists:
            raise ValidationError("A SiteConfiguration record already exists. Duplicate creation is prohibited.")

    def save(self, *args, **kwargs):
        if self.pk is not None and self.pk != 1:
            raise ValidationError("SiteConfiguration record must have primary key 1.")

        record_exists = SiteConfiguration.objects.filter(pk=1).exists()

        if self._state.adding:
            if record_exists:
                raise ValidationError("A SiteConfiguration record already exists. Duplicate creation is prohibited.")
            if self.pk is None:
                self.pk = 1
        else:
            if self.pk != 1:
                raise ValidationError("SiteConfiguration record must have primary key 1.")

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("SiteConfiguration cannot be deleted.")

    @classmethod
    def get_solo(cls):
        """
        Retrieves or initializes the singleton configuration record (pk=1).
        """
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    