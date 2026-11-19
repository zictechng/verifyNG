# tests/test_batch1_models_and_storage.py

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from users.models import User, AlternativeVerificationSubmission
from core.storage import private_evidence_storage, PrivateEvidenceStorage

VALID_GIF = (
    b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!'
    b'\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
)

class Batch1ModelsAndStorageTests(TestCase):

    def test_user_can_publish_reports_field_default_false(self):
        """Verify can_publish_reports defaults to False on newly created User instances."""
        user = User.objects.create_user(username='test_b1_user', email='b1@verifyng.com')
        self.assertFalse(user.can_publish_reports)

    def test_user_can_publish_reports_save_forces_bool(self):
        """Verify save() forces bool to prevent Django 5.1 descriptor leaks."""
        user = User.objects.create_user(username='test_b1_bool', email='bool@verifyng.com')
        user.can_publish_reports = 1  # Truthy integer
        user.save()
        user.refresh_from_db()
        self.assertIsInstance(user.can_publish_reports, bool)

    def test_alternative_verification_submission_creation_and_fields(self):
        """Verify AlternativeVerificationSubmission creation, status choices, and relationships."""
        user = User.objects.create_user(username='test_applicant', email='app@verifyng.com')
        sub = AlternativeVerificationSubmission.objects.create(
            user=user,
            status='pending',
            evidence_type='selfie_card',
            selfie_image=SimpleUploadedFile("selfie.gif", VALID_GIF, content_type="image/gif"),
            residential_country='NG',
            residential_address='Plot 12, Victoria Island, Lagos',
            declaration_statement='I solemnly declare my identity.'
        )
        self.assertIsNotNone(sub.pk)
        self.assertEqual(sub.status, 'pending')
        self.assertEqual(sub.evidence_type, 'selfie_card')
        self.assertEqual(sub.user, user)
        self.assertEqual(user.alternative_verification_submissions.count(), 1)
        self.assertTrue(str(sub).startswith(f"Path B Submission for {user.username} (pending)"))

    def test_alternative_verification_submission_status_choices(self):
        """Verify 'revoked' is among valid status choices."""
        valid_statuses = [choice[0] for choice in AlternativeVerificationSubmission.STATUS_CHOICES]
        self.assertIn('pending', valid_statuses)
        self.assertIn('approved', valid_statuses)
        self.assertIn('rejected', valid_statuses)
        self.assertIn('revoked', valid_statuses)

    def test_private_evidence_storage_configuration(self):
        """Verify PrivateEvidenceStorage sets base_url=None and restrictive permissions."""
        self.assertIsInstance(private_evidence_storage, PrivateEvidenceStorage)
        self.assertIsNone(private_evidence_storage.base_url)
        self.assertEqual(private_evidence_storage.file_permissions_mode, 0o600)
        self.assertEqual(private_evidence_storage.directory_permissions_mode, 0o700)

    def test_private_evidence_storage_blocks_public_urls(self):
        """Verify that private_evidence_storage raises ValueError on any .url() access."""
        user = User.objects.create_user(username='test_storage_user', email='st@verifyng.com')
        sub = AlternativeVerificationSubmission.objects.create(
            user=user,
            status='pending',
            selfie_image=SimpleUploadedFile("selfie.gif", VALID_GIF, content_type="image/gif"),
            residential_country='NG',
            residential_address='123 Test St, Lagos',
            declaration_statement='Valid statement.'
        )
        with self.assertRaises(ValueError):
            _ = sub.selfie_image.url

    def test_private_media_root_setting_configured(self):
        """Verify PRIVATE_MEDIA_ROOT setting points outside public media."""
        self.assertTrue(hasattr(settings, 'PRIVATE_MEDIA_ROOT'))
        self.assertTrue(str(settings.PRIVATE_MEDIA_ROOT).endswith('private_media'))
        self.assertNotEqual(settings.PRIVATE_MEDIA_ROOT, settings.MEDIA_ROOT)
