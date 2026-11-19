import io
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied

from users.models import AlternativeVerificationSubmission
from reports.models import AuditLog
from dashboard.admin_views import AdminAlternativeVerificationDocumentView, AdminUserDetailView
from core.permissions import can_user_publish_reports

User = get_user_model()

TINY_GIF = (
    b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff'
    b'\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00'
    b'\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
)


class AdminComplianceDeskTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.now = timezone.now()

        # Target applicant user
        self.applicant = User.objects.create_user(
            username='path_b_target',
            email='target@example.com',
            password='TestPassword123!',
            can_publish_reports=False,
            id_verification_status='unverified',
            identity_verified=False,
        )

        # Upload private selfie
        selfie_file = SimpleUploadedFile("selfie_challenge.jpg", TINY_GIF, content_type="image/jpeg")
        self.submission = AlternativeVerificationSubmission.objects.create(
            user=self.applicant,
            status='pending',
            evidence_type='selfie_card',
            selfie_image=selfie_file,
            residential_country='NG',
            residential_address='789 Broad Street, Lagos',
            declaration_statement='I solemnly confirm my personhood and details are authentic.',
        )

        # Compliance Officer with users.view_user permission
        self.officer = User.objects.create_user(
            username='compliance_officer',
            email='officer@verifyng.com',
            password='TestPassword123!',
            is_staff=True,
            role='officer',
        )
        perm = Permission.objects.get(codename='view_user', content_type__app_label='users')
        self.officer.user_permissions.add(perm)

        # Regular user without staff/officer permissions
        self.regular_user = User.objects.create_user(
            username='regular_joe',
            email='joe@example.com',
            password='TestPassword123!',
        )

    def _setup_request_session_and_messages(self, request, user):
        request.user = user
        request.session = 'session'
        messages = FallbackStorage(request)
        setattr(request, '_messages', messages)
        return request

    # --------------------------------------------------------------------------
    # 1. Private Document Streaming Proxy Access Controls
    # --------------------------------------------------------------------------
    def test_anonymous_user_blocked_from_document_streaming(self):
        """Unauthenticated user is redirected to login from private evidence stream."""
        from django.contrib.auth.models import AnonymousUser
        request = self.factory.get(
            reverse('admin_portal:alternative_verification_document', kwargs={'submission_id': self.submission.id, 'doc_field': 'selfie'})
        )
        request.user = AnonymousUser()
        response = AdminAlternativeVerificationDocumentView.as_view()(request, submission_id=self.submission.id, doc_field='selfie')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_unauthorized_non_staff_blocked_from_document_streaming(self):
        """Non-staff user is redirected to login by SuperAdminRequiredMixin."""
        request = self.factory.get(
            reverse('admin_portal:alternative_verification_document', kwargs={'submission_id': self.submission.id, 'doc_field': 'selfie'})
        )
        self._setup_request_session_and_messages(request, self.regular_user)
        response = AdminAlternativeVerificationDocumentView.as_view()(request, submission_id=self.submission.id, doc_field='selfie')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_staff_without_permission_receives_403(self):
        """Staff user without users.view_user permission receives HTTP 403 Access Denied."""
        staff_no_perm = User.objects.create_user(
            username='staff_no_perm',
            email='noperm@verifyng.com',
            password='TestPassword123!',
            is_staff=True,
        )
        request = self.factory.get(
            reverse('admin_portal:alternative_verification_document', kwargs={'submission_id': self.submission.id, 'doc_field': 'selfie'})
        )
        self._setup_request_session_and_messages(request, staff_no_perm)
        response = AdminAlternativeVerificationDocumentView.as_view()(request, submission_id=self.submission.id, doc_field='selfie')
        self.assertEqual(response.status_code, 403)

    def test_officer_can_stream_private_selfie(self):
        """Authorized compliance officer streams the private selfie with secure headers."""
        request = self.factory.get(
            reverse('admin_portal:alternative_verification_document', kwargs={'submission_id': self.submission.id, 'doc_field': 'selfie'})
        )
        self._setup_request_session_and_messages(request, self.officer)
        response = AdminAlternativeVerificationDocumentView.as_view()(request, submission_id=self.submission.id, doc_field='selfie')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-Frame-Options'], 'SAMEORIGIN')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertIn('inline', response['Content-Disposition'])

        # Check AuditLog entry
        audit = AuditLog.objects.filter(
            action="ADMIN_VIEW_ALTERNATIVE_VERIFICATION_DOCUMENT",
            performed_by=self.officer
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('submission_id'), self.submission.id)

    # --------------------------------------------------------------------------
    # 2. Officer Approval of Path B Alternative Verification
    # --------------------------------------------------------------------------
    def test_officer_approve_path_b_action(self):
        """Approving Path B grants publishing standing without claiming verified legal identity."""
        data = {
            'action': 'approve_path_b',
            'submission_id': self.submission.id,
        }
        request = self.factory.post(
            reverse('admin_portal:user_detail', kwargs={'public_id': self.applicant.public_id}),
            data=data
        )
        self._setup_request_session_and_messages(request, self.officer)

        response = AdminUserDetailView.as_view()(request, public_id=self.applicant.public_id)
        self.assertEqual(response.status_code, 302)

        # Verify submission updated
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'approved')
        self.assertEqual(self.submission.reviewed_by, self.officer)
        self.assertIsNotNone(self.submission.reviewed_at)

        # Verify user publishing eligibility conferred
        self.applicant.refresh_from_db()
        self.assertTrue(self.applicant.can_publish_reports)

        # Zero false claims: does NOT touch identity_verified or id_verification_status
        self.assertFalse(self.applicant.identity_verified)
        self.assertEqual(self.applicant.id_verification_status, 'unverified')

        # User is now allowed to publish
        res = can_user_publish_reports(self.applicant)
        self.assertTrue(res.allowed)

        # AuditLog recorded
        audit = AuditLog.objects.filter(
            action="ADMIN_APPROVE_ALTERNATIVE_VERIFICATION",
            performed_by=self.officer
        ).first()
        self.assertIsNotNone(audit)

    # --------------------------------------------------------------------------
    # 3. Officer Rejection of Path B Alternative Verification
    # --------------------------------------------------------------------------
    def test_officer_reject_path_b_action(self):
        """Declining Path B sets rejected status and reason, and disables report publishing."""
        data = {
            'action': 'reject_path_b',
            'submission_id': self.submission.id,
            'rejection_reason': 'Selfie card text was blurry and illegible.',
        }
        request = self.factory.post(
            reverse('admin_portal:user_detail', kwargs={'public_id': self.applicant.public_id}),
            data=data
        )
        self._setup_request_session_and_messages(request, self.officer)

        response = AdminUserDetailView.as_view()(request, public_id=self.applicant.public_id)
        self.assertEqual(response.status_code, 302)

        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'rejected')
        self.assertEqual(self.submission.rejection_reason, 'Selfie card text was blurry and illegible.')
        self.assertEqual(self.submission.reviewed_by, self.officer)

        self.applicant.refresh_from_db()
        self.assertFalse(self.applicant.can_publish_reports)

        res = can_user_publish_reports(self.applicant)
        self.assertFalse(res.allowed)

    # --------------------------------------------------------------------------
    # 4. Officer Revocation & Independent Path A Preservation
    # --------------------------------------------------------------------------
    def test_officer_revoke_path_b_disables_publishing_when_no_path_a(self):
        """Revoking Path B resets can_publish_reports=False when user has no Path A ID."""
        # Start approved
        self.submission.status = 'approved'
        self.submission.save()
        self.applicant.can_publish_reports = True
        self.applicant.save()

        data = {
            'action': 'revoke_path_b',
            'revocation_reason': 'Suspicious report pattern detected.',
        }
        request = self.factory.post(
            reverse('admin_portal:user_detail', kwargs={'public_id': self.applicant.public_id}),
            data=data
        )
        self._setup_request_session_and_messages(request, self.officer)

        response = AdminUserDetailView.as_view()(request, public_id=self.applicant.public_id)
        self.assertEqual(response.status_code, 302)

        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'revoked')

        self.applicant.refresh_from_db()
        self.assertFalse(self.applicant.can_publish_reports)

        res = can_user_publish_reports(self.applicant)
        self.assertFalse(res.allowed)

    def test_officer_revoke_path_b_preserves_publishing_when_path_a_qualifies(self):
        """Revoking Path B preserves can_publish_reports=True if user independently holds valid Path A."""
        # Start approved Path B
        self.submission.status = 'approved'
        self.submission.save()
        self.applicant.can_publish_reports = True

        # Grant qualifying Path A evidence to applicant
        self.applicant.id_verification_status = 'verified'
        self.applicant.identity_verified = True
        self.applicant.id_type = 'nin'
        self.applicant.id_document = 'identities/nin_valid.jpg'
        self.applicant.id_verified_at = self.now
        self.applicant.assurance_level = 'basic_verified'
        self.applicant.save()

        data = {
            'action': 'revoke_path_b',
            'revocation_reason': 'Path B review audit.',
        }
        request = self.factory.post(
            reverse('admin_portal:user_detail', kwargs={'public_id': self.applicant.public_id}),
            data=data
        )
        self._setup_request_session_and_messages(request, self.officer)

        response = AdminUserDetailView.as_view()(request, public_id=self.applicant.public_id)
        self.assertEqual(response.status_code, 302)

        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, 'revoked')

        # Crucial: can_publish_reports remains True because Path A is valid!
        self.applicant.refresh_from_db()
        self.assertTrue(self.applicant.can_publish_reports)

        res = can_user_publish_reports(self.applicant)
        self.assertTrue(res.allowed)

        # AuditLog confirms path_a_preserved was True
        audit = AuditLog.objects.filter(
            action="ADMIN_REVOKE_ALTERNATIVE_VERIFICATION",
            performed_by=self.officer
        ).first()
        self.assertIsNotNone(audit)
        self.assertTrue(audit.details.get('path_a_preserved'))
