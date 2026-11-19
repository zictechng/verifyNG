import io
from unittest.mock import patch
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.contrib.messages.storage.fallback import FallbackStorage

from users.forms import PathBAlternativeVerificationForm
from users.models import AlternativeVerificationSubmission
from core.permissions import can_user_publish_reports
from reports.models import AuditLog

User = get_user_model()

# Valid 1x1 GIF image bytes
TINY_GIF = (
    b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff'
    b'\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00'
    b'\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
)


class PathBFormTests(TestCase):
    def test_empty_declaration_statement_rejected(self):
        """Form strictly rejects an empty or whitespace declaration statement."""
        selfie = SimpleUploadedFile("selfie.jpg", TINY_GIF, content_type="image/jpeg")
        data = {
            'evidence_type': 'selfie_card',
            'residential_country': 'NG',
            'residential_address': '123 Lagos St, Victoria Island',
            'declaration_statement': '   ',
        }
        files = {'selfie_image': selfie}
        form = PathBAlternativeVerificationForm(data=data, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn('declaration_statement', form.errors)

    def test_short_declaration_statement_rejected(self):
        """Form strictly rejects declaration statements under 20 characters."""
        selfie = SimpleUploadedFile("selfie.jpg", TINY_GIF, content_type="image/jpeg")
        data = {
            'evidence_type': 'selfie_card',
            'residential_country': 'NG',
            'residential_address': '123 Lagos St, Victoria Island',
            'declaration_statement': 'I am real.',  # 10 chars
        }
        files = {'selfie_image': selfie}
        form = PathBAlternativeVerificationForm(data=data, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn('declaration_statement', form.errors)

    def test_non_image_selfie_rejected(self):
        """Form rejects non-image formats for selfie verification challenge."""
        txt_file = SimpleUploadedFile("selfie.txt", b"plain text selfie", content_type="text/plain")
        data = {
            'evidence_type': 'selfie_card',
            'residential_country': 'NG',
            'residential_address': '123 Lagos St, Victoria Island',
            'declaration_statement': 'I solemnly confirm that my identity is truthful and accurate.',
        }
        files = {'selfie_image': txt_file}
        form = PathBAlternativeVerificationForm(data=data, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn('selfie_image', form.errors)

    def test_selfie_file_size_limit(self):
        """Form rejects selfie files exceeding 5MB."""
        large_file = SimpleUploadedFile("huge.jpg", b"x" * (5 * 1024 * 1024 + 100), content_type="image/jpeg")
        data = {
            'evidence_type': 'selfie_card',
            'residential_country': 'NG',
            'residential_address': '123 Lagos St, Victoria Island',
            'declaration_statement': 'I solemnly confirm that my identity is truthful and accurate.',
        }
        files = {'selfie_image': large_file}
        form = PathBAlternativeVerificationForm(data=data, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn('selfie_image', form.errors)

    def test_valid_path_b_form_succeeds(self):
        """Form accepts valid submission with image and declaration."""
        selfie = SimpleUploadedFile("selfie.jpg", TINY_GIF, content_type="image/jpeg")
        doc = SimpleUploadedFile("bill.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        data = {
            'evidence_type': 'selfie_card',
            'residential_country': 'NG',
            'residential_address': '123 Marina Street, Lagos Island',
            'declaration_statement': 'I solemnly declare and confirm that my identity and residential address are authentic.',
        }
        files = {'selfie_image': selfie, 'supporting_document': doc}
        form = PathBAlternativeVerificationForm(data=data, files=files)
        self.assertTrue(form.is_valid(), form.errors)


class PathBViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='path_b_applicant',
            email='applicant@example.com',
            password='TestPassword123!',
            can_publish_reports=False,
            id_verification_status='unverified',
            identity_verified=False,
        )

    def _setup_request_session_and_messages(self, request, user):
        request.user = user
        request.session = 'session'
        messages = FallbackStorage(request)
        setattr(request, '_messages', messages)
        return request

    def test_unauthenticated_user_redirected(self):
        """Unauthenticated user cannot submit Path B verification."""
        from django.contrib.auth.models import AnonymousUser
        request = self.factory.post(reverse('users:verify_alternative_submit'))
        request.user = AnonymousUser()
        from users.views import PathBVerificationSubmitView
        response = PathBVerificationSubmitView.as_view()(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_suspended_user_cannot_submit(self):
        """Account suspension blocks submitting Path B application."""
        self.user.is_suspended = True
        self.user.save()

        selfie = SimpleUploadedFile("selfie.jpg", TINY_GIF, content_type="image/jpeg")
        data = {
            'evidence_type': 'selfie_card',
            'residential_country': 'NG',
            'residential_address': '123 Test Street, Lagos',
            'declaration_statement': 'I solemnly declare that my identity is truthful and accurate.',
            'selfie_image': selfie,
        }
        request = self.factory.post(reverse('users:verify_alternative_submit'), data=data)
        self._setup_request_session_and_messages(request, self.user)

        from users.views import PathBVerificationSubmitView
        response = PathBVerificationSubmitView.as_view()(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.user.alternative_verification_submissions.count(), 0)

    def test_duplicate_pending_submission_blocked(self):
        """User with an active pending application cannot submit another."""
        AlternativeVerificationSubmission.objects.create(
            user=self.user,
            status='pending',
            evidence_type='selfie_card',
            selfie_image='private_evidence/selfie.jpg',
            residential_country='NG',
            residential_address='Old Address',
            declaration_statement='Existing pending declaration.',
        )

        selfie = SimpleUploadedFile("selfie2.jpg", TINY_GIF, content_type="image/jpeg")
        data = {
            'evidence_type': 'selfie_card',
            'residential_country': 'NG',
            'residential_address': '123 New Street, Lagos',
            'declaration_statement': 'Submitting duplicate application.',
            'selfie_image': selfie,
        }
        request = self.factory.post(reverse('users:verify_alternative_submit'), data=data)
        self._setup_request_session_and_messages(request, self.user)

        from users.views import PathBVerificationSubmitView
        response = PathBVerificationSubmitView.as_view()(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.user.alternative_verification_submissions.count(), 1)

    def test_successful_path_b_submission(self):
        """Valid submission creates AlternativeVerificationSubmission with status='pending'."""
        selfie = SimpleUploadedFile("selfie_valid.jpg", TINY_GIF, content_type="image/jpeg")
        data = {
            'evidence_type': 'selfie_card',
            'residential_country': 'NG',
            'residential_address': '456 Verified Blvd, Ikeja, Lagos',
            'declaration_statement': 'I solemnly confirm and declare my personhood and details are authentic.',
            'selfie_image': selfie,
        }
        request = self.factory.post(reverse('users:verify_alternative_submit'), data=data)
        self._setup_request_session_and_messages(request, self.user)

        from users.views import PathBVerificationSubmitView
        response = PathBVerificationSubmitView.as_view()(request)
        self.assertEqual(response.status_code, 302)

        # Check submission created
        sub = self.user.alternative_verification_submissions.first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.status, 'pending')
        self.assertEqual(sub.evidence_type, 'selfie_card')
        self.assertEqual(sub.residential_country, 'NG')

        # Check audit log
        audit = AuditLog.objects.filter(
            action="USER_ALTERNATIVE_VERIFICATION_SUBMITTED",
            performed_by=self.user
        ).first()
        self.assertIsNotNone(audit)

        # Security invariant: does NOT alter identity_verified or id_verification_status
        self.user.refresh_from_db()
        self.assertFalse(self.user.identity_verified)
        self.assertEqual(self.user.id_verification_status, 'unverified')
        self.assertFalse(self.user.can_publish_reports)

        # Still cannot publish until approved
        res = can_user_publish_reports(self.user)
        self.assertFalse(res.allowed)
