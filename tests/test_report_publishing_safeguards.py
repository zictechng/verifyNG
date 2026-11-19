import io
from datetime import timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone
from django.contrib.messages.storage.fallback import FallbackStorage
from ninja.errors import HttpError

from core.permissions import (
    can_user_publish_reports,
    has_strict_path_a_evidence,
    ACCEPTABLE_PATH_A_DOCUMENTS,
)
from reports.services import create_fraud_report
from reports.views import ReportCreateView
from api.api import create_report, ReportSubmitRequest
from users.models import AlternativeVerificationSubmission, UserServiceAccess

User = get_user_model()


class ReportPublishingSafeguardsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.now = timezone.now()

        # Base unverified user
        self.unverified_user = User.objects.create_user(
            username='unverified_user',
            email='unverified@example.com',
            password='TestPassword123!',
            can_publish_reports=False,
            id_verification_status='unverified',
            identity_verified=False,
        )

        # Qualifying Path A user
        self.path_a_user = User.objects.create_user(
            username='path_a_user',
            email='path_a@example.com',
            password='TestPassword123!',
            can_publish_reports=True,
            id_verification_status='verified',
            identity_verified=True,
            id_type='nin',
            id_document='identities/documents/nin_test.jpg',
            id_verified_at=self.now,
            assurance_level='basic_verified',
        )

        # Approved Path B user (no government ID)
        self.path_b_user = User.objects.create_user(
            username='path_b_user',
            email='path_b@example.com',
            password='TestPassword123!',
            can_publish_reports=True,
            id_verification_status='unverified',
            identity_verified=False,
        )
        self.path_b_submission = AlternativeVerificationSubmission.objects.create(
            user=self.path_b_user,
            status='approved',
            evidence_type='community_reference',
            selfie_image='private_evidence/selfies/test.jpg',
            residential_country='NG',
            residential_address='123 Test St, Lagos',
            declaration_statement='I solemnly declare my identity is genuine.',
            reviewed_at=self.now,
        )

    def _setup_request_session_and_messages(self, request, user):
        request.user = user
        request.session = 'session'
        messages = FallbackStorage(request)
        setattr(request, '_messages', messages)
        return request

    # --------------------------------------------------------------------------
    # 1. Unverified User Blocking Across Layers
    # --------------------------------------------------------------------------
    def test_unverified_user_cannot_publish_service_layer(self):
        """Service layer rejects unverified users with PermissionDenied."""
        with self.assertRaises(PermissionDenied):
            create_fraud_report(
                reporter=self.unverified_user,
                subject_name="Scammer John",
                subject_type="individual",
                title="Fake investment scheme",
                allegation="Took money and disappeared.",
            )

    def test_unverified_user_cannot_publish_web_view(self):
        """Web view redirects unverified users with a warning message."""
        request = self.factory.get(reverse('reports:create'))
        self._setup_request_session_and_messages(request, self.unverified_user)

        response = ReportCreateView.as_view()(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('users:profile'), response.url)

    def test_unverified_user_cannot_publish_api(self):
        """JSON API raises HttpError(403) for unverified users."""
        request = self.factory.post('/api/v1/reports/')
        request.user = self.unverified_user
        payload = ReportSubmitRequest(
            subject_name="Scammer John",
            subject_type="individual",
            title="Fake investment scheme",
            allegation="Took money and disappeared.",
        )
        with self.assertRaises(HttpError) as ctx:
            create_report(request, payload)
        self.assertEqual(ctx.exception.status_code, 403)

    # --------------------------------------------------------------------------
    # 2. Path A Rigorous Evidence Checks
    # --------------------------------------------------------------------------
    def test_legacy_user_with_boolean_flag_only_cannot_publish_path_a(self):
        """A user with identity_verified=True but no document cannot publish through Path A."""
        legacy_user = User.objects.create_user(
            username='legacy_user',
            email='legacy@example.com',
            password='TestPassword123!',
            can_publish_reports=True,
            id_verification_status='verified',
            identity_verified=True,
            id_type='nin',
            id_document='',  # Missing document file
            id_verified_at=self.now,
        )
        res = can_user_publish_reports(legacy_user)
        self.assertFalse(res.allowed)
        self.assertIn("document file is required", res.reason)

    def test_verified_bvn_user_cannot_publish_path_a(self):
        """BVN is strictly excluded from acceptable Path A physical document types."""
        bvn_user = User.objects.create_user(
            username='bvn_user',
            email='bvn@example.com',
            password='TestPassword123!',
            can_publish_reports=True,
            id_verification_status='verified',
            identity_verified=True,
            id_type='bvn',  # Excluded document type
            id_document='identities/bvn.jpg',
            id_verified_at=self.now,
        )
        res = can_user_publish_reports(bvn_user)
        self.assertFalse(res.allowed)
        self.assertIn("qualifying physical government identity document", res.reason)

    def test_user_without_verification_timestamp_cannot_publish_path_a(self):
        """Path A requires an explicit verification timestamp."""
        no_timestamp_user = User.objects.create_user(
            username='no_ts_user',
            email='nots@example.com',
            password='TestPassword123!',
            can_publish_reports=True,
            id_verification_status='verified',
            identity_verified=True,
            id_type='nin',
            id_document='identities/nin.jpg',
            id_verified_at=None,
        )
        res = can_user_publish_reports(no_timestamp_user)
        self.assertFalse(res.allowed)
        self.assertIn("timestamp is missing", res.reason)

    def test_qualifying_path_a_user_can_publish(self):
        """Qualifying Path A user passes permission checks across all layers."""
        res = can_user_publish_reports(self.path_a_user)
        self.assertTrue(res.allowed)

        # Service layer
        report = create_fraud_report(
            reporter=self.path_a_user,
            subject_name="Fraudster Alpha",
            subject_type="individual",
            title="Online scam",
            allegation="Sold non-existent items.",
            suspect_phone="08012345678",
        )
        self.assertIsNotNone(report.pk)
        self.assertEqual(report.reporter, self.path_a_user)

    # --------------------------------------------------------------------------
    # 3. Path B Independence & Subsequent Submissions
    # --------------------------------------------------------------------------
    def test_approved_path_b_user_can_publish_without_identity_flags(self):
        """Approved Path B user can publish even with identity_verified=False and unverified ID."""
        res = can_user_publish_reports(self.path_b_user)
        self.assertTrue(res.allowed)

        report = create_fraud_report(
            reporter=self.path_b_user,
            subject_name="Fraudster Beta",
            subject_type="individual",
            title="Rental scam",
            allegation="Collected rent for someone else's apartment.",
            suspect_phone="08098765432",
        )
        self.assertIsNotNone(report.pk)
        self.assertEqual(report.reporter, self.path_b_user)

    def test_approved_path_b_preserves_publishing_when_newer_submission_pending(self):
        """Approved Path B remains valid when a newer submission is pending."""
        AlternativeVerificationSubmission.objects.create(
            user=self.path_b_user,
            status='pending',
            evidence_type='employment_proof',
            selfie_image='private_evidence/selfies/test2.jpg',
            residential_country='NG',
            residential_address='456 Test Ave, Abuja',
            declaration_statement='Submitting updated evidence.',
        )
        res = can_user_publish_reports(self.path_b_user)
        self.assertTrue(res.allowed)

    def test_approved_path_b_preserves_publishing_when_newer_submission_rejected(self):
        """Approved Path B remains valid when a newer submission is rejected."""
        AlternativeVerificationSubmission.objects.create(
            user=self.path_b_user,
            status='rejected',
            evidence_type='employment_proof',
            selfie_image='private_evidence/selfies/test3.jpg',
            residential_country='NG',
            residential_address='789 Test Rd, Port Harcourt',
            declaration_statement='Submitting additional proof.',
            rejection_reason='Unclear image.',
            reviewed_at=self.now,
        )
        res = can_user_publish_reports(self.path_b_user)
        self.assertTrue(res.allowed)

    def test_path_a_ordinary_rejection_does_not_invalidate_approved_path_b(self):
        """Path A ordinary document rejection does not invalidate an approved Path B standing."""
        self.path_b_user.id_verification_status = 'rejected'
        self.path_b_user.save()

        res = can_user_publish_reports(self.path_b_user)
        self.assertTrue(res.allowed)

    # --------------------------------------------------------------------------
    # 4. Path B Revocation & Dual-Pathway Fallback
    # --------------------------------------------------------------------------
    def test_revoking_path_b_blocks_publishing_when_no_valid_path_a(self):
        """Revoking Path B blocks publishing when the user has no independent Path A standing."""
        # Revoke all approved Path B submissions and reset can_publish_reports
        self.path_b_user.alternative_verification_submissions.filter(status='approved').update(status='revoked')
        self.path_b_user.can_publish_reports = False
        self.path_b_user.save()

        res = can_user_publish_reports(self.path_b_user)
        self.assertFalse(res.allowed)

    def test_revoking_path_b_preserves_publishing_when_valid_path_a_exists(self):
        """If user has both Path A and Path B, revoking Path B preserves publishing via Path A."""
        # Grant qualifying Path A evidence to path_b_user
        self.path_b_user.id_verification_status = 'verified'
        self.path_b_user.identity_verified = True
        self.path_b_user.id_type = 'passport'
        self.path_b_user.id_document = 'identities/passport.jpg'
        self.path_b_user.id_verified_at = self.now
        self.path_b_user.assurance_level = 'basic_verified'
        self.path_b_user.save()

        # Revoke Path B submissions
        self.path_b_user.alternative_verification_submissions.filter(status='approved').update(status='revoked')

        # Since Path A is independently valid, user can still publish
        res = can_user_publish_reports(self.path_b_user)
        self.assertTrue(res.allowed)

    # --------------------------------------------------------------------------
    # 5. Security Suspensions & Administrative Restrictions Override All Pathways
    # --------------------------------------------------------------------------
    def test_identity_security_suspension_overrides_all_pathways(self):
        """id_verification_status='suspended' strictly blocks report publishing for any pathway."""
        # Suspended Path A user
        self.path_a_user.id_verification_status = 'suspended'
        self.path_a_user.save()
        res_a = can_user_publish_reports(self.path_a_user)
        self.assertFalse(res_a.allowed)
        self.assertIn("suspended", res_a.reason)

        # Suspended Path B user
        self.path_b_user.id_verification_status = 'suspended'
        self.path_b_user.save()
        res_b = can_user_publish_reports(self.path_b_user)
        self.assertFalse(res_b.allowed)
        self.assertIn("suspended", res_b.reason)

    def test_account_suspension_overrides_all_pathways(self):
        """is_suspended=True strictly blocks report publishing."""
        self.path_a_user.is_suspended = True
        self.path_a_user.save()
        res = can_user_publish_reports(self.path_a_user)
        self.assertFalse(res.allowed)
        self.assertIn("suspended", res.reason)

    def test_user_service_access_restriction_overrides_all_pathways(self):
        """UserServiceAccess(service='fraud_report', is_restricted=True) blocks publishing."""
        UserServiceAccess.objects.create(
            user=self.path_a_user,
            service='fraud_report',
            is_restricted=True,
        )
        res = can_user_publish_reports(self.path_a_user)
        self.assertFalse(res.allowed)
        self.assertIn("restricted", res.reason)

    def test_service_restriction_blocks_service_layer_before_storage_upload(self):
        """create_fraud_report() rejects restricted users before calling storage upload."""
        UserServiceAccess.objects.create(
            user=self.path_a_user,
            service='fraud_report',
            is_restricted=True,
        )
        dummy_file = SimpleUploadedFile("evidence.jpg", b"fake_evidence_bytes", content_type="image/jpeg")

        with patch('reports.services.get_storage_service') as mock_get_storage:
            with self.assertRaises(PermissionDenied):
                create_fraud_report(
                    reporter=self.path_a_user,
                    subject_name="Suspicious Trader",
                    subject_type="individual",
                    title="Defective Goods",
                    allegation="Refused refund on fake goods.",
                    evidence_file=dummy_file,
                )
            # Crucial: Storage service was never called because check failed upfront
            mock_get_storage.assert_not_called()

    # --------------------------------------------------------------------------
    # 6. Staff & Superuser Accountability
    # --------------------------------------------------------------------------
    def test_staff_and_superusers_must_satisfy_publishing_requirements_when_filing_reports(self):
        """Staff members filing personal community reports must hold valid verification."""
        staff_user = User.objects.create_user(
            username='staff_member',
            email='staff@example.com',
            password='TestPassword123!',
            is_staff=True,
            can_publish_reports=False,
            id_verification_status='unverified',
        )
        res = can_user_publish_reports(staff_user)
        self.assertFalse(res.allowed)
        self.assertIn("Report publishing eligibility required", res.reason)
