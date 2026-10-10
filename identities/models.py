from django.db import models
from django.utils import timezone
from users.models import User

class SubjectEntity(models.Model):
    ENTITY_TYPES = (
        ('person', 'Person'),
        ('business', 'Business'),
    )
    type = models.CharField(max_length=20, choices=ENTITY_TYPES, default='person')
    name = models.CharField(max_length=255, db_index=True)
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