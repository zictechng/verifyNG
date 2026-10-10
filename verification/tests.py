from unittest.mock import patch
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.core import mail
from django.db import transaction

from users.models import User
from identities.models import SubjectEntity, Identifier
from identities.utils import hash_identifier_value
from verification.models import VerificationRequest, VerificationResult
from verification.services import (
    create_verification_request,
    claim_verification_request,
    complete_verification_request,
    reject_verification_request,
    generate_verification_reference_number,
)
from reports.models import AuditLog


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
)
class VerificationWorkflowTestCase(TestCase):
    def setUp(self):
        mail.outbox = []
        self.requester = User.objects.create_user(
            username='client_user', email='client@example.com', password='password123', role='individual'
        )
        self.other_user = User.objects.create_user(
            username='stranger_user', email='stranger@example.com', password='password123', role='individual'
        )
        self.officer = User.objects.create_user(
            username='officer_user', email='officer@example.com', password='password123', role='officer'
        )
        self.moderator = User.objects.create_user(
            username='mod_user', email='mod@example.com', password='password123', role='moderator'
        )
        self.superuser = User.objects.create_superuser(
            username='admin_user', email='admin@example.com', password='password123'
        )

    def tearDown(self):
        mail.outbox = []

    def test_reference_format(self):
        ref = generate_verification_reference_number()
        self.assertTrue(ref.startswith('VNG-VR-'))
        parts = ref.split('-')
        self.assertEqual(len(parts), 4)
        self.assertEqual(len(parts[2]), 8)  # YYYYMMDD
        self.assertEqual(len(parts[3]), 4)  # 4 hex chars

    def test_create_verification_request_service_and_email(self):
        with self.captureOnCommitCallbacks(execute=True):
            req = create_verification_request(
                requester=self.requester,
                subject_name="Apex Global Tech",
                subject_type="business",
                verification_type="identity",
                notes="Please verify CAC status"
            )
        self.assertEqual(req.status, 'pending')
        self.assertEqual(req.target_subject.name, "Apex Global Tech")
        self.assertEqual(req.target_subject.type, "business")

        # Verify audit log recorded
        audit = AuditLog.objects.filter(action="VERIFICATION_REQUEST_CREATED").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.performed_by, self.requester)
        self.assertEqual(audit.details['verification_reference'], req.reference_number)

        # Verify on_commit email dispatched
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['client@example.com'])
        self.assertIn(req.reference_number, mail.outbox[0].subject)

    def test_deduplication_via_identifier_hash(self):
        # Create an existing entity with an identifier
        phone_raw = "08012345678"
        p_hash = hash_identifier_value('phone', phone_raw)
        existing_subject = SubjectEntity.objects.create(name="Existing Merchant", type="person")
        Identifier.objects.create(subject=existing_subject, type='phone', value_hash=p_hash)

        # Submit request referencing that phone
        req = create_verification_request(
            requester=self.requester,
            subject_name="Existing Merchant Different Label",
            subject_type="person",
            verification_type="full_check",
            identifier_type='phone',
            identifier_value=phone_raw
        )
        # Should link to existing_subject
        self.assertEqual(req.target_subject.id, existing_subject.id)

    def test_officer_claim_transition(self):
        req = create_verification_request(
            requester=self.requester,
            subject_name="Test Entity",
            subject_type="person",
            verification_type="identity"
        )
        claimed = claim_verification_request(req.reference_number, self.officer)
        self.assertEqual(claimed.status, 'in_progress')

        # Claiming again raises ValidationError
        with self.assertRaises(ValidationError):
            claim_verification_request(req.reference_number, self.officer)

    def test_complete_verification_with_result_and_overwrite_protection(self):
        req = create_verification_request(
            requester=self.requester,
            subject_name="Acme Corp",
            subject_type="business",
            verification_type="credential"
        )
        claim_verification_request(req.reference_number, self.officer)
        mail.outbox = []

        with self.captureOnCommitCallbacks(execute=True):
            result = complete_verification_request(
                reference_number=req.reference_number,
                officer_user=self.officer,
                outcome='verified',
                summary='Company exists in active standing.',
                details={'rc_number': 'RC123456', 'status': 'ACTIVE'}
            )
        self.assertEqual(result.outcome, 'verified')
        self.assertEqual(result.verified_by, self.officer)

        req.refresh_from_db()
        self.assertEqual(req.status, 'completed')

        # Email notification to requester sent on commit without leaking raw details
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Completed", mail.outbox[0].subject)
        self.assertNotIn("RC123456", mail.outbox[0].body)

        # Prevent duplicate result overwrites
        with self.assertRaises(ValidationError):
            complete_verification_request(
                reference_number=req.reference_number,
                officer_user=self.officer,
                outcome='unverified',
                summary='Duplicate attempt'
            )

    def test_reject_verification_service(self):
        req = create_verification_request(
            requester=self.requester,
            subject_name="Suspicious Actor",
            subject_type="person",
            verification_type="identity",
            notes="Original requester instructions"
        )
        claim_verification_request(req.reference_number, self.officer)
        mail.outbox = []

        with self.captureOnCommitCallbacks(execute=True):
            rejected = reject_verification_request(
                reference_number=req.reference_number,
                officer_user=self.officer,
                reason="Insufficient documentation provided to verify subject"
            )
        self.assertEqual(rejected.status, 'rejected')
        # Ensure requester original notes were not overwritten
        self.assertEqual(rejected.notes, "Original requester instructions")

        # Rejection reason stored in audit
        audit = AuditLog.objects.filter(action="VERIFICATION_REQUEST_REJECTED").first()
        self.assertIsNotNone(audit)
        self.assertIn("Insufficient documentation", audit.details['rejection_reason'])

        # Email notice dispatched
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Declined", mail.outbox[0].subject)

    def test_invalid_state_transitions(self):
        req = create_verification_request(
            requester=self.requester,
            subject_name="Test Entity",
            subject_type="person",
            verification_type="identity"
        )
        # Attempting to complete pending request directly fails
        with self.assertRaises(ValidationError):
            complete_verification_request(
                reference_number=req.reference_number,
                officer_user=self.officer,
                outcome='verified',
                summary='Illegal jump'
            )

        # Attempting to reject pending request directly fails
        with self.assertRaises(ValidationError):
            reject_verification_request(
                reference_number=req.reference_number,
                officer_user=self.officer,
                reason='Premature reject'
            )

    def test_email_rollback_on_transaction_failure(self):
        mail.outbox = []
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    create_verification_request(
                        requester=self.requester,
                        subject_name="Rollback Entity",
                        subject_type="person",
                        verification_type="identity"
                    )
                    raise RuntimeError("Simulated DB failure")
            except RuntimeError:
                pass

        # Since transaction rolled back, on_commit email must NOT have fired
        self.assertEqual(len(mail.outbox), 0)

    def test_least_privilege_object_level_access(self):
        req = create_verification_request(
            requester=self.requester,
            subject_name="Private Inquiry",
            subject_type="person",
            verification_type="identity"
        )
        detail_url = reverse('verification:detail', kwargs={'reference_number': req.reference_number})

        # Anonymous redirected to login
        res = self.client.get(detail_url)
        self.assertEqual(res.status_code, 302)

        # Unrelated user gets 403 Forbidden
        self.client.force_login(self.other_user)
        res = self.client.get(detail_url)
        self.assertEqual(res.status_code, 403)

        # Moderator (not officer/superuser) gets 403 Forbidden under least privilege
        self.client.force_login(self.moderator)
        res = self.client.get(detail_url)
        self.assertEqual(res.status_code, 403)

        # Requester can view
        self.client.force_login(self.requester)
        res = self.client.get(detail_url)
        self.assertEqual(res.status_code, 200)

        # Officer can view
        self.client.force_login(self.officer)
        res = self.client.get(detail_url)
        self.assertEqual(res.status_code, 200)

        # Superuser can view
        self.client.force_login(self.superuser)
        res = self.client.get(detail_url)
        self.assertEqual(res.status_code, 200)

    def test_officer_queue_and_actions_rbac(self):
        queue_url = reverse('verification:officer_queue')

        # Regular user denied
        self.client.force_login(self.requester)
        res = self.client.get(queue_url)
        self.assertEqual(res.status_code, 403)

        # Moderator denied
        self.client.force_login(self.moderator)
        res = self.client.get(queue_url)
        self.assertEqual(res.status_code, 403)

        # Officer allowed
        self.client.force_login(self.officer)
        res = self.client.get(queue_url)
        self.assertEqual(res.status_code, 200)

class VerificationReportDocumentTestCase(TestCase):

    def setUp(self):
        mail.outbox = []
        self.requester = User.objects.create_user(
            username='rep_client', email='rep_client@example.com', password='password123', role='individual'
        )
        self.other_user = User.objects.create_user(
            username='unrelated_user', email='unrelated@example.com', password='password123', role='individual'
        )
        self.officer = User.objects.create_user(
            username='verif_officer', email='officer@example.com', password='password123', role='officer'
        )
        self.moderator = User.objects.create_user(
            username='mod_person', email='mod@example.com', password='password123', role='moderator'
        )
        self.superuser = User.objects.create_superuser(
            username='root_admin', email='root@example.com', password='password123'
        )

        # Create a completed request with valid VerificationResult
        self.completed_req = create_verification_request(
            requester=self.requester,
            subject_name="Verified Entity Ltd",
            subject_type="business",
            verification_type="identity",
            notes="Client request notes"
        )
        claim_verification_request(self.completed_req.reference_number, self.officer)
        self.result = complete_verification_request(
            reference_number=self.completed_req.reference_number,
            officer_user=self.officer,
            outcome='verified',
            summary='Corporate registration active and confirmed.',
            details={
                'registry_status': 'Active Standing',
                'registration_number': 'RC987654',
                'internal_moderator_secret': 'SECRET_DO_NOT_EXPOSE',
                'private_password': 'SENSITIVE_CREDENTIAL',
            }
        )
        self.completed_req.refresh_from_db()

    def test_unauthenticated_redirects_to_login(self):
        report_url = reverse('verification:report', kwargs={'reference_number': self.completed_req.reference_number})
        res = self.client.get(report_url)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/users/login/', res.url)

    def test_unauthorized_users_denied_access(self):
        report_url = reverse('verification:report', kwargs={'reference_number': self.completed_req.reference_number})

        # 1. Unrelated regular user gets 403
        self.client.force_login(self.other_user)
        res = self.client.get(report_url)
        self.assertEqual(res.status_code, 403)

        # 2. Moderator gets 403 under least privilege
        self.client.force_login(self.moderator)
        res = self.client.get(report_url)
        self.assertEqual(res.status_code, 403)

    def test_authorized_users_can_view_report(self):
        report_url = reverse('verification:report', kwargs={'reference_number': self.completed_req.reference_number})

        # 1. Requester gets 200
        self.client.force_login(self.requester)
        res = self.client.get(report_url)
        self.assertEqual(res.status_code, 200)

        # 2. Verification Officer gets 200
        self.client.force_login(self.officer)
        res = self.client.get(report_url)
        self.assertEqual(res.status_code, 200)

        # 3. Superuser gets 200
        self.client.force_login(self.superuser)
        res = self.client.get(report_url)
        self.assertEqual(res.status_code, 200)

    def test_report_unavailable_for_non_completed_requests(self):
        # 1. Pending request returns 404
        pending_req = create_verification_request(
            requester=self.requester,
            subject_name="Pending Entity",
            subject_type="person",
            verification_type="identity"
        )
        pending_url = reverse('verification:report', kwargs={'reference_number': pending_req.reference_number})
        self.client.force_login(self.requester)
        res = self.client.get(pending_url)
        self.assertEqual(res.status_code, 404)

        # 2. In-progress request returns 404
        claim_verification_request(pending_req.reference_number, self.officer)
        res = self.client.get(pending_url)
        self.assertEqual(res.status_code, 404)

        # 3. Rejected request returns 404
        reject_verification_request(
            reference_number=pending_req.reference_number,
            officer_user=self.officer,
            reason="Unverifiable information"
        )
        res = self.client.get(pending_url)
        self.assertEqual(res.status_code, 404)

        # 4. Expired request returns 404
        pending_req.status = 'expired'
        pending_req.save(update_fields=['status'])
        res = self.client.get(pending_url)
        self.assertEqual(res.status_code, 404)

    def test_report_unavailable_if_completed_without_result(self):
        # Edge case: status marked completed but no result object exists
        orphan_req = create_verification_request(
            requester=self.requester,
            subject_name="Orphan Entity",
            subject_type="person",
            verification_type="identity"
        )
        orphan_req.status = 'completed'
        orphan_req.save(update_fields=['status'])

        orphan_url = reverse('verification:report', kwargs={'reference_number': orphan_req.reference_number})
        self.client.force_login(self.requester)
        res = self.client.get(orphan_url)
        self.assertEqual(res.status_code, 404)

    def test_audit_log_recorded_on_report_access(self):
        report_url = reverse('verification:report', kwargs={'reference_number': self.completed_req.reference_number})
        self.client.force_login(self.requester)

        AuditLog.objects.filter(action="VERIFICATION_REPORT_ACCESSED").delete()
        res = self.client.get(report_url, REMOTE_ADDR='192.168.1.100')
        self.assertEqual(res.status_code, 200)

        # Assert exactly one audit log created with verified IP and reference
        audits = AuditLog.objects.filter(action="VERIFICATION_REPORT_ACCESSED")
        self.assertEqual(audits.count(), 1)
        audit = audits.first()
        self.assertEqual(audit.performed_by, self.requester)
        self.assertEqual(audit.ip_address, '192.168.1.100')
        self.assertEqual(audit.details['verification_reference'], self.completed_req.reference_number)
        self.assertEqual(audit.details['outcome'], 'verified')

    def test_mandatory_disclaimer_and_neutral_content_rendered(self):
        report_url = reverse('verification:report', kwargs={'reference_number': self.completed_req.reference_number})
        self.client.force_login(self.requester)
        res = self.client.get(report_url)
        self.assertEqual(res.status_code, 200)

        content = res.content.decode('utf-8')

        # Assert mandatory disclaimer is present verbatim
        expected_disclaimer = (
            "This document is an independent VerifyNG Verification Report issued solely for factual vetting purposes. "
            "It does NOT constitute an official government certificate, police character certificate, statutory "
            "regulatory license, or UK DBS certificate."
        )
        self.assertIn(expected_disclaimer, content)

        # Assert neutral outcome label
        self.assertIn("Outcome: Verified", content)
        self.assertNotIn("OFFICIALLY VERIFIED", content)

        # Assert reference and subject
        self.assertIn(self.completed_req.reference_number, content)
        self.assertIn("Verified Entity Ltd", content)
        self.assertIn("Corporate registration active and confirmed.", content)

        # Assert neutral officer attribution
        self.assertIn("Assigned Verification Officer", content)
        self.assertNotIn(f"OFFICER-{self.officer.id}", content)

    def test_safe_structured_details_filtering(self):
        report_url = reverse('verification:report', kwargs={'reference_number': self.completed_req.reference_number})
        self.client.force_login(self.requester)
        res = self.client.get(report_url)
        content = res.content.decode('utf-8')

        # Approved safe keys must be displayed
        self.assertIn("Registry Status", content)
        self.assertIn("Active Standing", content)
        self.assertIn("Registration Number", content)
        self.assertIn("RC987654", content)

        # Non-whitelisted keys must NOT be displayed
        self.assertNotIn("SECRET_DO_NOT_EXPOSE", content)
        self.assertNotIn("SENSITIVE_CREDENTIAL", content)
        self.assertNotIn("internal_moderator_secret", content)

