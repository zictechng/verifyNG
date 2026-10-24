import io
import zipfile
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from users.models import User
from identities.models import SubjectEntity
from reports.models import FraudReport, ReportEvidence
from reports.services import generate_report_reference_number, create_fraud_report
from reports.forms import FraudReportSubmissionForm
from reports.storage_services import CloudinaryEvidenceStorage, StorageError, get_storage_service_for_provider


class ReferenceNumberTestCase(TestCase):
    def test_reference_format(self):
        ref = generate_report_reference_number()
        self.assertTrue(ref.startswith('VNG-'))
        parts = ref.split('-')
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[1]), 8)
        self.assertEqual(len(parts[2]), 4)


class FraudReportServiceTestCase(TestCase):
    def setUp(self):
        self.reporter = User.objects.create_user(
            username='reporter', email='reporter@test.com',
            password='Password123!', role='individual'
        )
        self.other = User.objects.create_user(
            username='other', email='other@test.com',
            password='Password123!', role='individual'
        )
        self.moderator = User.objects.create_user(
            username='mod', email='mod@test.com',
            password='Password123!', role='moderator'
        )
        self.staff = User.objects.create_user(
            username='staff', email='staff@test.com',
            password='Password123!', is_staff=True
        )

    @patch('reports.storage_services.CloudinaryEvidenceStorage.upload_evidence')
    def test_report_created_without_evidence(self, mock_upload):
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name='Scam Person',
            subject_type='person',
            title='Fake Loan',
            allegation='Took money'
        )
        self.assertEqual(report.state, 'submitted')
        self.assertEqual(report.evidence_files.count(), 0)
        mock_upload.assert_not_called()

    @patch('reports.storage_services.CloudinaryEvidenceStorage.upload_evidence')
    def test_report_created_with_evidence_metadata_persisted(self, mock_upload):
        mock_upload.return_value = {
            'provider': 'cloudinary',
            'public_id': 'evidence/2026/10/vng_ev_abc123.pdf',
            'resource_type': 'raw',
            'format': 'pdf',
            'bytes': 1024,
            'asset_id': 'asset_xyz'
        }
        file = SimpleUploadedFile("receipt.pdf", b'%PDF-1.4 test', content_type="application/pdf")
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name='Scam Biz',
            subject_type='business',
            title='Fake Investment',
            allegation='Ponzi scheme',
            evidence_file=file,
            evidence_type='receipt',
            evidence_description='Payment proof'
        )
        self.assertEqual(report.evidence_files.count(), 1)
        ev = report.evidence_files.first()
        self.assertEqual(ev.storage_provider, 'cloudinary')
        self.assertEqual(ev.storage_public_id, 'evidence/2026/10/vng_ev_abc123.pdf')
        self.assertEqual(ev.storage_resource_type, 'raw')
        self.assertEqual(ev.storage_format, 'pdf')
        self.assertTrue(ev.is_confidential)

    @patch('reports.storage_services.CloudinaryEvidenceStorage.delete_evidence')
    @patch('reports.storage_services.CloudinaryEvidenceStorage.upload_evidence')
    def test_cloud_cleanup_on_db_failure(self, mock_upload, mock_delete):
        mock_upload.return_value = {
            'provider': 'cloudinary',
            'public_id': 'evidence/2026/10/vng_ev_fail.pdf',
            'resource_type': 'raw',
            'format': 'pdf',
            'bytes': 1024,
            'asset_id': ''
        }
        file = SimpleUploadedFile("fail.pdf", b'%PDF fail', content_type="application/pdf")
        with patch('identities.models.SubjectEntity.objects.create', side_effect=Exception("DB Error")):
            with self.assertRaises(Exception):
                create_fraud_report(
                    reporter=self.reporter,
                    subject_name='Fail',
                    subject_type='person',
                    title='Fail',
                    allegation='Fail',
                    evidence_file=file
                )
        mock_delete.assert_called_once_with('evidence/2026/10/vng_ev_fail.pdf', 'raw')

    def test_report_access_permissions(self):
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name='Test Subject',
            subject_type='person',
            title='Test Report',
            allegation='Test allegation'
        )
        url = reverse('reports:detail', kwargs={'reference_number': report.reference_number})

        # Anonymous -> 403
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # Other user -> 403
        self.client.login(username='other', password='Password123!')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # Reporter -> 200
        self.client.login(username='reporter', password='Password123!')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Moderator -> 200
        self.client.login(username='mod', password='Password123!')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Staff -> 200
        self.client.login(username='staff', password='Password123!')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Published -> anonymous 200
        report.state = 'published'
        report.save()
        self.client.logout()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    @patch('reports.storage_services.CloudinaryEvidenceStorage.generate_signed_url')
    def test_evidence_download_permission_and_routing(self, mock_signed_url):
        mock_signed_url.return_value = 'https://res.cloudinary.com/signed-test-url'
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name='Evidence Test',
            subject_type='person',
            title='Test',
            allegation='Test'
        )
        ev = ReportEvidence.objects.create(
            report=report,
            file='evidence/2026/10/vng_ev_conf.pdf',
            is_confidential=True,
            storage_provider='cloudinary',
            storage_public_id='evidence/2026/10/vng_ev_conf.pdf',
            storage_resource_type='raw',
            storage_format='pdf'
        )
        url = reverse('reports:evidence_download', kwargs={'evidence_id': ev.id})

        # Other user -> 403
        self.client.login(username='other', password='Password123!')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # Reporter -> 302 to signed URL
        self.client.login(username='reporter', password='Password123!')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://res.cloudinary.com/signed-test-url')


class EvidenceFileValidationTestCase(TestCase):
    BASE_DATA = {
        'subject_name': 'Test Subject', 'subject_type': 'person',
        'title': 'Test Report', 'allegation': 'Test allegation text.',
    }

    def _make_form(self, file):
        files = {'evidence_file': file} if file else {}
        return FraudReportSubmissionForm(data=self.BASE_DATA, files=files)

    def test_valid_png_accepted(self):
        buf = io.BytesIO()
        Image.new('RGB', (10, 10)).save(buf, format='PNG')
        buf.seek(0)
        form = self._make_form(SimpleUploadedFile("photo.png", buf.read(), content_type="image/png"))
        self.assertTrue(form.is_valid(), form.errors)

    def test_valid_pdf_accepted(self):
        form = self._make_form(SimpleUploadedFile("doc.pdf", b'%PDF-1.4 content', content_type="application/pdf"))
        self.assertTrue(form.is_valid(), form.errors)

    def test_valid_doc_accepted(self):
        form = self._make_form(SimpleUploadedFile("doc.doc", b'\xd0\xcf\x11\xe0rest', content_type="application/msword"))
        self.assertTrue(form.is_valid(), form.errors)

    def test_valid_docx_accepted(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('[Content_Types].xml', '<Types/>')
            zf.writestr('word/document.xml', '<document/>')
        buf.seek(0)
        form = self._make_form(SimpleUploadedFile(
            "doc.docx", buf.read(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ))
        self.assertTrue(form.is_valid(), form.errors)

    def test_corrupted_image_rejected(self):
        form = self._make_form(SimpleUploadedFile("broken.png", b"\x89PNG\r\nGARBAGE", content_type="image/png"))
        self.assertFalse(form.is_valid())
        self.assertIn('evidence_file', form.errors)

    def test_fake_pdf_rejected(self):
        form = self._make_form(SimpleUploadedFile("fake.pdf", b"MZ\x90\x00not a pdf", content_type="application/pdf"))
        self.assertFalse(form.is_valid())
        self.assertIn('evidence_file', form.errors)

    def test_zip_without_docx_structure_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('random.txt', 'not a docx')
        buf.seek(0)
        form = self._make_form(SimpleUploadedFile(
            "fake.docx", buf.read(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ))
        self.assertFalse(form.is_valid())
        self.assertIn('evidence_file', form.errors)

    def test_unsupported_extension_rejected(self):
        form = self._make_form(SimpleUploadedFile("script.exe", b"MZ\x90\x00", content_type="application/octet-stream"))
        self.assertFalse(form.is_valid())
        self.assertIn('evidence_file', form.errors)

    def test_oversized_file_rejected(self):
        form = self._make_form(SimpleUploadedFile("big.pdf", b'%PDF ' + b'A' * (11 * 1024 * 1024), content_type="application/pdf"))
        self.assertFalse(form.is_valid())
        self.assertIn('evidence_file', form.errors)

    def test_no_evidence_accepted(self):
        form = self._make_form(None)
        self.assertTrue(form.is_valid(), form.errors)

    def test_file_pointer_reset_after_validation_failure(self):
        file = SimpleUploadedFile("fake.pdf", b"MZ\x90\x00not a pdf", content_type="application/pdf")
        form = FraudReportSubmissionForm(data=self.BASE_DATA, files={'evidence_file': file})
        form.is_valid()
        self.assertEqual(file.tell(), 0)


class StorageProviderFactoryTestCase(TestCase):
    def test_local_provider_raises_storage_error(self):
        with self.assertRaises(StorageError):
            get_storage_service_for_provider('local')

    def test_unknown_provider_raises_storage_error(self):
        with self.assertRaises(StorageError):
            get_storage_service_for_provider('s3')



from reports.services import transition_report_state
from reports.models import AuditLog


class AuditLoggingTestCase(TestCase):
    def setUp(self):
        self.reporter = User.objects.create_user(
            username='rep_user', email='rep@test.com', password='Password123!', role='individual'
        )
        self.moderator = User.objects.create_user(
            username='mod_user', email='mod@test.com', password='Password123!', role='moderator'
        )

    def test_report_submission_creates_single_audit_log(self):
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name='Target Corp',
            subject_type='business',
            title='Contract Scam',
            allegation='Unfulfilled job'
        )
        logs = AuditLog.objects.filter(report=report)
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().action, "REPORT_SUBMITTED")
        self.assertEqual(logs.first().performed_by, self.reporter)

    def test_service_transition_attribution_and_no_duplicate(self):
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name='Target Person',
            subject_type='person',
            title='Advance Fee Scam',
            allegation='Fee taken'
        )
        transition_report_state(
            report=report,
            new_state='under_review',
            actor=self.moderator,
            ip_address='192.168.1.100',
            moderation_notes='Under moderation investigation'
        )

        logs = AuditLog.objects.filter(report=report).order_by('timestamp')
        self.assertEqual(logs.count(), 2)
        transition_log = logs.last()
        self.assertEqual(transition_log.action, "STATE_TRANSITION_SUBMITTED_TO_UNDER_REVIEW")
        self.assertEqual(transition_log.performed_by, self.moderator)
        self.assertEqual(transition_log.ip_address, '192.168.1.100')
        self.assertEqual(transition_log.details['previous_state'], 'submitted')
        self.assertEqual(transition_log.details['new_state'], 'under_review')

    def test_update_fields_excluding_state_does_not_trigger_audit(self):
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name='Target Person',
            subject_type='person',
            title='Test Title',
            allegation='Test Allegation'
        )
        # Modify both state in memory and title, but persist ONLY title
        report.state = 'under_review'
        report.title = 'Updated Title'
        report.save(update_fields=['title'])

        # Verify database state remained unchanged
        report.refresh_from_db()
        self.assertEqual(report.state, 'submitted')
        self.assertEqual(report.title, 'Updated Title')

        # Verify no transition audit log was generated (only initial submission log exists)
        logs = AuditLog.objects.filter(report=report)
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().action, "REPORT_SUBMITTED")

    def test_reused_instance_preserves_subsequent_fallback_logging(self):
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name='Target Person',
            subject_type='person',
            title='Test Title',
            allegation='Test Allegation'
        )
        # transition_report_state sets _audit_logged = True, then post_save resets it to False
        transition_report_state(report=report, new_state='under_review')

        # Now do a direct model save on the same instance changing state
        report.state = 'published'
        report.save()

        logs = AuditLog.objects.filter(report=report)
        # 3 logs: submitted, under_review (via service), published (via fallback)
        self.assertEqual(logs.count(), 3)

        from unittest.mock import patch
from django.db import transaction, IntegrityError
from django.core import mail
from reports.models import Dispute, AuditLog
from reports.services import (
    transition_report_state,
    file_dispute_for_report,
    resolve_dispute,
)


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
)
class Phase7Batch72WorkflowTestCase(TestCase):
    def setUp(self):
        mail.outbox = []
        self.reporter = User.objects.create_user(
            username='rep_user', email='reporter@example.com', password='password123', role='individual'
        )
        self.disputant = User.objects.create_user(
            username='disp_user', email='disputant@example.com', password='password123', role='individual'
        )
        self.moderator = User.objects.create_user(
            username='mod_user', email='mod@example.com', password='password123', role='moderator'
        )
        self.unauthorized_user = User.objects.create_user(
            username='regular_user', email='regular@example.com', password='password123', role='individual'
        )
        self.report = create_fraud_report(
            reporter=self.reporter,
            subject_name='Dispute Target',
            subject_type='business',
            title='Unfulfilled Delivery',
            allegation='Payment made, no goods delivered.'
        )

    def tearDown(self):
        mail.outbox = []

    def test_moderator_transition_publishes_report_and_dispatches_email(self):
        # 1. Moderator moves submitted -> under_review
        transition_report_state(self.report, new_state='under_review', actor=self.moderator)
        self.assertEqual(self.report.state, 'under_review')

        # 2. Moderator approves under_review -> published with on_commit callback execution
        with self.captureOnCommitCallbacks(execute=True):
            transition_report_state(self.report, new_state='published', actor=self.moderator)

        self.assertEqual(self.report.state, 'published')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.reporter.email, mail.outbox[0].to)
        self.assertIn("Published", mail.outbox[0].subject)

    def test_transaction_rollback_does_not_dispatch_notification(self):
        # Test that rolling back a transaction discards on_commit notification callbacks
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    transition_report_state(self.report, new_state='published', actor=self.moderator)
                    raise IntegrityError("Simulated database failure")
            except IntegrityError:
                pass

        # Email must NOT have been sent
        self.assertEqual(len(mail.outbox), 0)

    def test_file_dispute_transitions_published_report_to_disputed(self):
        transition_report_state(self.report, new_state='published', actor=self.moderator)

        with self.captureOnCommitCallbacks(execute=True):
            dispute = file_dispute_for_report(
                report=self.report,
                disputant=self.disputant,
                reason="Goods were fully delivered via receipt #12345."
            )

        self.assertEqual(dispute.status, 'opened')
        self.report.refresh_from_db()
        self.assertEqual(self.report.state, 'disputed')
        # Reporter notified of dispute
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.reporter.email, mail.outbox[0].to)

    def test_file_dispute_fails_on_non_published_report(self):
        # Report is in 'archived' state where disputes are blocked
        self.report.state = 'archived'
        self.report.save(update_fields=['state'])
        with self.assertRaises(ValueError):
            file_dispute_for_report(
                report=self.report,
                disputant=self.disputant,
                reason="Dispute on archived report"
            )

    def test_moderator_accepts_dispute_restricting_report(self):
        transition_report_state(self.report, new_state='published', actor=self.moderator)
        dispute = file_dispute_for_report(
            report=self.report,
            disputant=self.disputant,
            reason="Confirmed full refund was issued."
        )

        with self.captureOnCommitCallbacks(execute=True):
            resolve_dispute(
                dispute=dispute,
                outcome='accepted',
                actor=self.moderator,
                resolution_notes="Disputant provided proof of full refund."
            )

        dispute.refresh_from_db()
        self.assertEqual(dispute.status, 'accepted')
        self.report.refresh_from_db()
        self.assertEqual(self.report.state, 'restricted')

    def test_moderator_rejects_dispute_restoring_published_report(self):
        transition_report_state(self.report, new_state='published', actor=self.moderator)
        dispute = file_dispute_for_report(
            report=self.report,
            disputant=self.disputant,
            reason="Frivolous denial."
        )

        with self.captureOnCommitCallbacks(execute=True):
            resolve_dispute(
                dispute=dispute,
                outcome='rejected',
                actor=self.moderator,
                resolution_notes="Counter-evidence lacked valid transaction ID."
            )

        dispute.refresh_from_db()
        self.assertEqual(dispute.status, 'rejected')
        self.report.refresh_from_db()
        self.assertEqual(self.report.state, 'published')

    def test_moderation_queue_view_rbac_protection(self):
        url = reverse('reports:moderation_queue')

        # 1. Anonymous -> redirects to login
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        # 2. Regular user -> 403 Forbidden
        self.client.login(username='regular_user', password='password123')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # 3. Moderator -> 200 OK
        self.client.login(username='mod_user', password='password123')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_dispute_create_view_requires_authentication(self):
        transition_report_state(self.report, new_state='published', actor=self.moderator)
        url = reverse('reports:create_dispute', kwargs={'reference_number': self.report.reference_number})

        # Anonymous -> redirects to login
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        # Authenticated -> 200 OK
        self.client.login(username='disp_user', password='password123')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


from identities.models import Identifier
from identities.utils import hash_identifier_value
from identities.services import lookup_public_record
from reports.services import transition_report_state


class FraudReportIdentifiersIntegrationTestCase(TestCase):
    def setUp(self):
        self.reporter = User.objects.create_user(
            username='reporter_id_test',
            email='reporter_id@test.com',
            password='Password123!',
            role='individual'
        )

    def test_fraud_report_with_suspect_identifiers_creates_hashes(self):
        """Verifies phone, bank account, CAC, and email are peppered, hashed, and linked to SubjectEntity."""
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name='Abuja Investment Syndicate',
            subject_type='business',
            title='Fake Mining Investment',
            allegation='Collected deposits without delivery.',
            suspect_phone='08012345678',
            suspect_bank_account='0123456789',
            suspect_bank_name='GTBank',
            suspect_cac_number='RC123456',
            suspect_email='syndicate@fakebiz.ng',
            suspect_location='Suite 12 Wuse 2',
            suspect_state='FCT - Abuja',
            suspect_city='Abuja'
        )
        self.assertEqual(report.state, 'submitted')
        subject = report.target_subject
        self.assertEqual(subject.name, 'Abuja Investment Syndicate')

        # Check all 4 identifiers registered
        self.assertEqual(subject.identifiers.count(), 4)

        phone_hash = hash_identifier_value('phone', '08012345678')
        account_hash = hash_identifier_value('account', '0123456789')
        cac_hash = hash_identifier_value('cac', 'RC123456')
        email_hash = hash_identifier_value('email', 'syndicate@fakebiz.ng')

        self.assertTrue(subject.identifiers.filter(type='phone', value_hash=phone_hash).exists())
        self.assertTrue(subject.identifiers.filter(type='account', value_hash=account_hash).exists())
        self.assertTrue(subject.identifiers.filter(type='cac', value_hash=cac_hash).exists())
        self.assertTrue(subject.identifiers.filter(type='email', value_hash=email_hash).exists())

        # Check audit log metadata
        log = report.audit_logs.filter(action="REPORT_SUBMITTED").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.details['suspect_context']['bank_name'], 'GTBank')
        self.assertEqual(log.details['suspect_context']['state'], 'FCT - Abuja')

    def test_fraud_report_deduplication_by_identifier(self):
        """Reports against an existing phone number bind to the same SubjectEntity."""
        phone = '08099887766'
        report1 = create_fraud_report(
            reporter=self.reporter,
            subject_name='Original Name',
            subject_type='person',
            title='Case 1',
            allegation='First offense',
            suspect_phone=phone
        )
        report2 = create_fraud_report(
            reporter=self.reporter,
            subject_name='Alias Name',
            subject_type='person',
            title='Case 2',
            allegation='Second offense with same phone',
            suspect_phone=phone
        )

        self.assertEqual(report1.target_subject.id, report2.target_subject.id)
        # Should not create duplicate Identifier rows
        self.assertEqual(report1.target_subject.identifiers.filter(type='phone').count(), 1)

    def test_published_report_resolvable_via_lookup_public_record(self):
        """Publishing a report makes its suspect phone resolvable via lookup_public_record()."""
        phone = '08055443322'
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name='Phishing Suspect',
            subject_type='person',
            title='Phishing SMS',
            allegation='Sent phishing links via SMS',
            suspect_phone=phone
        )
        phone_hash = hash_identifier_value('phone', phone)

        # Before publication, active flags count is 0
        record_pre = lookup_public_record(phone_hash)
        self.assertIsNotNone(record_pre)
        self.assertFalse(record_pre['has_active_flags'])
        self.assertEqual(record_pre['published_reports_count'], 0)

        # Transition report to published
        transition_report_state(report, 'published', actor=self.reporter)

        # After publication, public check finds 1 published report and flags True
        record_post = lookup_public_record(phone_hash)
        self.assertIsNotNone(record_post)
        self.assertTrue(record_post['has_active_flags'])
        self.assertEqual(record_post['published_reports_count'], 1)
        self.assertEqual(record_post['subject_name'], 'Phishing Suspect')

    def test_form_validation_for_identifiers(self):
        """Tests that forms validate and normalize phone & account while rejecting invalid formats."""
        # Valid data
        form_valid = FraudReportSubmissionForm(data={
            'subject_name': 'Valid Merchant',
            'subject_type': 'business',
            'title': 'Test Report',
            'allegation': 'Test allegation description.',
            'suspect_phone': '08012345678',
            'suspect_bank_account': '0123456789',
        })
        self.assertTrue(form_valid.is_valid(), form_valid.errors)
        self.assertEqual(form_valid.cleaned_data['suspect_phone'], '2348012345678')
        self.assertEqual(form_valid.cleaned_data['suspect_bank_account'], '0123456789')

        # Invalid phone
        form_invalid_phone = FraudReportSubmissionForm(data={
            'subject_name': 'Invalid Phone',
            'subject_type': 'person',
            'title': 'Test Report',
            'allegation': 'Test allegation description.',
            'suspect_phone': '12345',
        })
        self.assertFalse(form_invalid_phone.is_valid())
        self.assertIn('suspect_phone', form_invalid_phone.errors)

        # Invalid account length
        form_invalid_acct = FraudReportSubmissionForm(data={
            'subject_name': 'Invalid Account',
            'subject_type': 'person',
            'title': 'Test Report',
            'allegation': 'Test allegation description.',
            'suspect_bank_account': '12345',
        })
        self.assertFalse(form_invalid_acct.is_valid())
        self.assertIn('suspect_bank_account', form_invalid_acct.errors)


@patch('core.tasks.send_email_notification_task.delay')
@patch('notifications.services.dispatch_notification')
class DueProcessRebuttalCycleTestCase(TestCase):
    def setUp(self):
        self.reporter = User.objects.create_user(
            username='complainant_user', email='complainant@test.com',
            password='Password123!', role='individual'
        )
        self.respondent = User.objects.create_user(
            username='respondent_user', email='respondent@test.com',
            password='Password123!', role='individual'
        )
        self.moderator = User.objects.create_user(
            username='mod_user', email='moderator@test.com',
            password='Password123!', role='moderator'
        )
        self.subject = SubjectEntity.objects.create(
            name='Test Subject Person',
            type='person'
        )
        self.report = FraudReport.objects.create(
            reporter=self.reporter,
            target_subject=self.subject,
            title='Alleged Dispute Incident',
            allegation='Complainant full chronological narrative for testing.',
            state='disputed',
            reference_number='VNG-20261024-TEST'
        )

    def test_urls_reverse_cleanly(self, *mocks):
        ref = self.report.reference_number
        self.assertEqual(reverse('reports:create_rebuttal', kwargs={'reference_number': ref}), f'/reports/{ref}/rebuttal/')
        self.assertEqual(reverse('reports:issue_info_request', kwargs={'reference_number': ref}), f'/reports/{ref}/info-request/')
        self.assertEqual(reverse('reports:fulfill_info_request', kwargs={'reference_number': ref, 'request_id': 1}), f'/reports/{ref}/info-request/1/fulfill/')

    def test_due_process_forms(self, *mocks):
        from reports.forms import ComplainantRebuttalForm, ModeratorInfoRequestForm, InfoRequestFulfillForm

        # Rebuttal form
        reb_form = ComplainantRebuttalForm(data={'rebuttal_statement': 'This is a valid factual rebuttal that exceeds 20 characters.'})
        self.assertTrue(reb_form.is_valid(), reb_form.errors)

        # Moderator info request form
        info_form = ModeratorInfoRequestForm(data={
            'target_role': 'complainant',
            'title': 'Request for Bank Statement',
            'message': 'Please upload your stamped account statement.'
        })
        self.assertTrue(info_form.is_valid(), info_form.errors)

        # Fulfillment form
        ful_form = InfoRequestFulfillForm(data={
            'response_statement': 'Here is the requested explanation of the transaction.'
        })
        self.assertTrue(ful_form.is_valid(), ful_form.errors)

    def test_rebuttal_and_info_request_lifecycle(self, *mocks):
        from reports.models import Dispute
        from reports.services import (
            submit_complainant_rebuttal,
            issue_moderator_info_request,
            fulfill_moderator_info_request
        )

        # Before dispute: can_submit_rebuttal is False
        self.assertFalse(self.report.can_submit_rebuttal)

        # Accused party files dispute
        dispute = Dispute.objects.create(
            report=self.report,
            disputant=self.respondent,
            reason='Defense statement refuting the claim completely.',
            status='opened'
        )

        # Now can_submit_rebuttal is True
        self.assertTrue(self.report.can_submit_rebuttal)
        self.assertIsNone(self.report.complainant_rebuttal)

        # Complainant files 1-time formal rebuttal
        log = submit_complainant_rebuttal(
            report=self.report,
            reporter=self.reporter,
            rebuttal_statement='Final rebuttal explaining bank transaction details.',
            evidence_file=None,
            ip_address='127.0.0.1'
        )
        self.assertIsNotNone(self.report.complainant_rebuttal)
        self.assertEqual(self.report.complainant_rebuttal['statement'], 'Final rebuttal explaining bank transaction details.')
        # Pleadings closed: can_submit_rebuttal becomes False
        self.assertFalse(self.report.can_submit_rebuttal)

        # Moderator issues information request to respondent
        req_log = issue_moderator_info_request(
            report=self.report,
            moderator=self.moderator,
            target_role='respondent',
            message='Provide signed delivery voucher.',
            request_title='Delivery Voucher Clarification',
            ip_address='127.0.0.1'
        )
        pending = self.report.pending_info_request_for_user(self.respondent)
        self.assertIsNotNone(pending)
        self.assertEqual(pending.id, req_log.id)

        # Respondent fulfills information request
        fulfill_moderator_info_request(
            report=self.report,
            user=self.respondent,
            request_id=req_log.id,
            response_statement='Attached delivery voucher signed by customer.',
            evidence_file=None,
            ip_address='127.0.0.1'
        )

        # Verify request is marked fulfilled
        self.assertIsNone(self.report.pending_info_request_for_user(self.respondent))


