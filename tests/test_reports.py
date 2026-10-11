
# tests/test_reports.py
"""
Batch 14.3 — Fraud report submission gate and state transition tests.

Coverage:
  - FraudReport model: creation, state choices, reference number, str repr
  - create_fraud_report() service: atomic creation, audit log, identifier hashing,
    subject deduplication, state starts as 'submitted'
  - transition_report_state() service: valid transitions, audit log, same-state no-op,
    invalid state rejection
  - file_dispute_for_report() service: dispute creation, report state → 'disputed',
    non-published report rejection
  - resolve_dispute() service: accepted → 'restricted', rejected → 'published'
  - AuditLog: immutability check (no update path), audit entries created per transition
  - Security: allegation stored as-is (never auto-published), moderation_notes
    not exposed via lookup_public_record()
"""

from unittest.mock import patch, MagicMock

from django.test import TestCase

from users.models import User
from identities.models import SubjectEntity, Identifier
from identities.utils import hash_identifier_value
from reports.models import FraudReport, AuditLog, Dispute
from reports.services import (
    create_fraud_report,
    transition_report_state,
    file_dispute_for_report,
    resolve_dispute,
    generate_report_reference_number,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_verified_user(username='reporter', email='reporter@example.com'):
    user = User.objects.create_user(username=username, email=email, password='StrongPass123!')
    user.identity_verified = True
    user.save(update_fields=['identity_verified'])
    return user


def make_moderator(username='moderator'):
    user = User.objects.create_user(username=username, email='mod@example.com', password='StrongPass123!')
    user.role = 'moderator'
    user.save(update_fields=['role'])
    return user


def make_report(reporter, state='submitted', title='Test Fraud', allegation='Scam allegation.'):
    """Creates a FraudReport directly via the model (bypasses service storage layer)."""
    subject = SubjectEntity.objects.create(name='Suspect Person', type='person')
    ref = generate_report_reference_number()
    report = FraudReport(
        reference_number=ref,
        reporter=reporter,
        target_subject=subject,
        title=title,
        allegation=allegation,
        state=state,
    )
    report._audit_logged = True   # suppress signal fallback — not created via service layer
    report.save()
    return report

# Patch both the storage service AND Celery task to keep tests fast and isolated
MOCK_STORAGE = patch(
    'reports.services.get_storage_service',
    return_value=MagicMock(upload_evidence=MagicMock(return_value=None)),
)
MOCK_CELERY = patch('reports.services.send_email_notification_task')


# ─── Reference number generator ───────────────────────────────────────────────

class ReferenceNumberTest(TestCase):

    def test_reference_starts_with_vng(self):
        ref = generate_report_reference_number()
        self.assertTrue(ref.startswith('VNG-'))

    def test_reference_is_unique(self):
        refs = {generate_report_reference_number() for _ in range(20)}
        self.assertEqual(len(refs), 20)

    def test_reference_format(self):
        """Expected format: VNG-YYYYMMDD-XXXX"""
        ref = generate_report_reference_number()
        parts = ref.split('-')
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0], 'VNG')
        self.assertTrue(parts[1].isdigit() and len(parts[1]) == 8)
        self.assertEqual(len(parts[2]), 4)


# ─── FraudReport model ────────────────────────────────────────────────────────

class FraudReportModelTest(TestCase):

    def setUp(self):
        self.user = make_verified_user()
        self.report = make_report(self.user)

    def test_default_state_is_submitted(self):
        self.assertEqual(self.report.state, 'submitted')

    def test_reference_number_unique(self):
        from django.db import IntegrityError
        subject = SubjectEntity.objects.create(name='Another', type='person')
        with self.assertRaises(IntegrityError):
            FraudReport.objects.create(
                reference_number=self.report.reference_number,
                reporter=self.user,
                target_subject=subject,
                title='Dup',
                allegation='Duplicate ref.',
            )

    def test_str_contains_reference_number(self):
        self.assertIn(self.report.reference_number, str(self.report))

    def test_allegation_stored_verbatim(self):
        self.assertEqual(self.report.allegation, 'Scam allegation.')

    def test_all_valid_states_accepted(self):
        valid_states = ['submitted', 'under_review', 'published', 'disputed',
                        'resolved', 'rejected', 'restricted', 'archived']
        for state in valid_states:
            self.report.state = state
            self.report.save(update_fields=['state'])
            self.report.refresh_from_db()
            self.assertEqual(self.report.state, state)


# ─── create_fraud_report() service ────────────────────────────────────────────

class CreateFraudReportTest(TestCase):

    def setUp(self):
        self.reporter = make_verified_user()

    @MOCK_CELERY
    @MOCK_STORAGE
    def test_report_created_with_submitted_state(self, *mocks):
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name='John Scammer',
            subject_type='person',
            title='Rental Scam',
            allegation='Collected money and disappeared.',
        )
        self.assertEqual(report.state, 'submitted')

    @MOCK_CELERY
    @MOCK_STORAGE
    def test_report_reference_number_generated(self, *mocks):
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name='Jane Fraud',
            subject_type='person',
            title='Online Scam',
            allegation='Fake goods sold.',
        )
        self.assertTrue(report.reference_number.startswith('VNG-'))

    @MOCK_CELERY
    @MOCK_STORAGE
    def test_audit_log_created_on_submission(self, *mocks):
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name='Fake Company Ltd',
            subject_type='business',
            title='Business Fraud',
            allegation='Stole funds.',
        )
        log = AuditLog.objects.filter(report=report, action='REPORT_SUBMITTED').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.performed_by, self.reporter)

    @MOCK_CELERY
    @MOCK_STORAGE
    def test_suspect_phone_hashed_and_stored(self, *mocks):
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name='Phone Suspect',
            subject_type='person',
            title='Phone Scam',
            allegation='Fraudulent transfer.',
            suspect_phone='08099887766',
        )
        expected_hash = hash_identifier_value('phone', '08099887766')
        exists = Identifier.objects.filter(value_hash=expected_hash).exists()
        self.assertTrue(exists)

    @MOCK_CELERY
    @MOCK_STORAGE
    def test_suspect_phone_plain_not_stored(self, *mocks):
        raw_phone = '08099887766'
        create_fraud_report(
            reporter=self.reporter,
            subject_name='Phone Suspect 2',
            subject_type='person',
            title='Phone Scam 2',
            allegation='Fraudulent transfer.',
            suspect_phone=raw_phone,
        )
        # Plain phone must not appear in any Identifier value_hash column
        plain_in_db = Identifier.objects.filter(value_hash=raw_phone).exists()
        self.assertFalse(plain_in_db)

    @MOCK_CELERY
    @MOCK_STORAGE
    def test_subject_deduplication_reuses_existing_entity(self, *mocks):
        """Two reports with the same phone should share one SubjectEntity."""
        create_fraud_report(
            reporter=self.reporter,
            subject_name='Known Scammer',
            subject_type='person',
            title='First Report',
            allegation='First allegation.',
            suspect_phone='08055544433',
        )
        initial_subject_count = SubjectEntity.objects.count()

        # Second reporter with same phone
        reporter2 = make_verified_user(username='reporter2', email='r2@example.com')
        create_fraud_report(
            reporter=reporter2,
            subject_name='Known Scammer Again',
            subject_type='person',
            title='Second Report',
            allegation='Second allegation.',
            suspect_phone='08055544433',
        )
        # No new SubjectEntity should be created
        self.assertEqual(SubjectEntity.objects.count(), initial_subject_count)

    @MOCK_CELERY
    @MOCK_STORAGE
    def test_report_never_auto_published(self, *mocks):
        """Allegation must start as 'submitted', never 'published'."""
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name='Auto Pub Test',
            subject_type='person',
            title='Test',
            allegation='Should not auto-publish.',
        )
        self.assertNotEqual(report.state, 'published')


# ─── transition_report_state() service ───────────────────────────────────────

class TransitionReportStateTest(TestCase):

    def setUp(self):
        self.reporter  = make_verified_user()
        self.moderator = make_moderator()
        self.report    = make_report(self.reporter)

    @MOCK_CELERY
    def test_submitted_to_under_review(self, mock_celery):
        transition_report_state(
            report=self.report, new_state='under_review',
            actor=self.moderator, ip_address='127.0.0.1'
        )
        self.report.refresh_from_db()
        self.assertEqual(self.report.state, 'under_review')

    @MOCK_CELERY
    def test_under_review_to_published(self, mock_celery):
        self.report.state = 'under_review'
        self.report.save(update_fields=['state'])
        transition_report_state(
            report=self.report, new_state='published',
            actor=self.moderator, ip_address='127.0.0.1'
        )
        self.report.refresh_from_db()
        self.assertEqual(self.report.state, 'published')

    @MOCK_CELERY
    def test_transition_creates_audit_log(self, mock_celery):
        transition_report_state(
            report=self.report, new_state='under_review',
            actor=self.moderator, ip_address='10.0.0.1'
        )
        log = AuditLog.objects.filter(
            report=self.report,
            action='STATE_TRANSITION_SUBMITTED_TO_UNDER_REVIEW'
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.performed_by, self.moderator)
        self.assertEqual(log.ip_address, '10.0.0.1')

    @MOCK_CELERY
    def test_same_state_transition_is_no_op(self, mock_celery):
        """Transitioning to the current state must not create a duplicate audit log."""
        initial_log_count = AuditLog.objects.filter(report=self.report).count()
        transition_report_state(
            report=self.report, new_state='submitted',
            actor=self.moderator
        )
        self.assertEqual(AuditLog.objects.filter(report=self.report).count(), initial_log_count)

    @MOCK_CELERY
    def test_invalid_state_raises_value_error(self, mock_celery):
        with self.assertRaises(ValueError):
            transition_report_state(
                report=self.report, new_state='nonexistent_state',
                actor=self.moderator
            )

    @MOCK_CELERY
    def test_moderation_notes_saved_on_transition(self, mock_celery):
        transition_report_state(
            report=self.report, new_state='rejected',
            actor=self.moderator,
            moderation_notes='Insufficient evidence provided.'
        )
        self.report.refresh_from_db()
        self.assertEqual(self.report.moderation_notes, 'Insufficient evidence provided.')

    @MOCK_CELERY
    def test_audit_log_records_previous_and_new_state(self, mock_celery):
        transition_report_state(
            report=self.report, new_state='under_review',
            actor=self.moderator
        )
        log = AuditLog.objects.filter(
            report=self.report,
            action='STATE_TRANSITION_SUBMITTED_TO_UNDER_REVIEW'
        ).first()
        self.assertEqual(log.details['previous_state'], 'submitted')
        self.assertEqual(log.details['new_state'], 'under_review')


# ─── file_dispute_for_report() service ───────────────────────────────────────

class FileDisputeTest(TestCase):

    def setUp(self):
        self.reporter  = make_verified_user()
        self.disputant = make_verified_user(username='disputant', email='disp@example.com')
        self.report    = make_report(self.reporter, state='published')

    @MOCK_CELERY
    def test_dispute_created_for_published_report(self, mock_celery):
        dispute = file_dispute_for_report(
            report=self.report,
            disputant=self.disputant,
            reason='This allegation is false.',
        )
        self.assertIsNotNone(dispute.pk)
        self.assertEqual(dispute.status, 'opened')

    @MOCK_CELERY
    def test_report_state_becomes_disputed(self, mock_celery):
        file_dispute_for_report(
            report=self.report,
            disputant=self.disputant,
            reason='I have counter-evidence.',
        )
        self.report.refresh_from_db()
        self.assertEqual(self.report.state, 'disputed')

    @MOCK_CELERY
    def test_dispute_against_non_published_report_rejected(self, mock_celery):
        submitted_report = make_report(self.reporter, state='submitted')
        with self.assertRaises(ValueError):
            file_dispute_for_report(
                report=submitted_report,
                disputant=self.disputant,
                reason='Should not work.',
            )

    @MOCK_CELERY
    def test_dispute_against_under_review_report_rejected(self, mock_celery):
        under_review = make_report(self.reporter, state='under_review')
        with self.assertRaises(ValueError):
            file_dispute_for_report(
                report=under_review,
                disputant=self.disputant,
                reason='Should not work.',
            )


# ─── resolve_dispute() service ────────────────────────────────────────────────

class ResolveDisputeTest(TestCase):

    def setUp(self):
        self.reporter  = make_verified_user()
        self.disputant = make_verified_user(username='disputant2', email='d2@example.com')
        self.moderator = make_moderator()
        self.report    = make_report(self.reporter, state='published')

    def _file_dispute(self):
        with patch('reports.services.send_email_notification_task'):
            return file_dispute_for_report(
                report=self.report,
                disputant=self.disputant,
                reason='Disputing this.',
            )

    @MOCK_CELERY
    def test_accepted_dispute_restricts_report(self, mock_celery):
        dispute = self._file_dispute()
        resolve_dispute(
            dispute=dispute, outcome='accepted',
            actor=self.moderator, resolution_notes='Evidence supports disputant.',
        )
        self.report.refresh_from_db()
        self.assertEqual(self.report.state, 'restricted')

    @MOCK_CELERY
    def test_rejected_dispute_restores_published(self, mock_celery):
        dispute = self._file_dispute()
        resolve_dispute(
            dispute=dispute, outcome='rejected',
            actor=self.moderator, resolution_notes='No compelling counter-evidence.',
        )
        self.report.refresh_from_db()
        self.assertEqual(self.report.state, 'published')

    @MOCK_CELERY
    def test_dispute_status_updated_on_resolution(self, mock_celery):
        dispute = self._file_dispute()
        resolve_dispute(
            dispute=dispute, outcome='accepted',
            actor=self.moderator, resolution_notes='Accepted.',
        )
        dispute.refresh_from_db()
        self.assertEqual(dispute.status, 'accepted')

    @MOCK_CELERY
    def test_invalid_outcome_raises_value_error(self, mock_celery):
        dispute = self._file_dispute()
        with self.assertRaises(ValueError):
            resolve_dispute(
                dispute=dispute, outcome='maybe',
                actor=self.moderator, resolution_notes='Invalid.',
            )

    @MOCK_CELERY
    def test_resolution_notes_stored(self, mock_celery):
        dispute = self._file_dispute()
        resolve_dispute(
            dispute=dispute, outcome='rejected',
            actor=self.moderator,
            resolution_notes='Report retained after review.',
        )
        dispute.refresh_from_db()
        self.assertEqual(dispute.resolution_notes, 'Report retained after review.')


# ─── AuditLog immutability ────────────────────────────────────────────────────

class AuditLogImmutabilityTest(TestCase):
    """
    AuditLog entries must never be altered after creation.
    The model has no update() path — we assert the log count grows
    correctly and that entries are not silently replaced.
    """

    def setUp(self):
        self.reporter  = make_verified_user()
        self.moderator = make_moderator()

    @MOCK_CELERY
    def test_each_transition_creates_new_audit_entry(self, mock_celery):
        report = make_report(self.reporter)
        transition_report_state(report=report, new_state='under_review', actor=self.moderator)
        transition_report_state(report=report, new_state='published',    actor=self.moderator)
        logs = AuditLog.objects.filter(report=report)
        # 2 transitions → 2 distinct audit entries
        self.assertEqual(logs.count(), 2)

    @MOCK_CELERY
    def test_audit_log_performed_by_recorded(self, mock_celery):
        report = make_report(self.reporter)
        transition_report_state(report=report, new_state='under_review', actor=self.moderator)
        log = AuditLog.objects.filter(report=report).first()
        self.assertEqual(log.performed_by, self.moderator)


# ─── Security: moderation data not exposed ────────────────────────────────────

class ModerationDataNotExposedTest(TestCase):
    """
    Internal moderation_notes must not leak into the public lookup response.
    """

    def setUp(self):
        self.reporter  = make_verified_user()
        self.moderator = make_moderator()

    @MOCK_CELERY
    def test_moderation_notes_not_in_public_record(self, mock_celery):
        from identities.services import lookup_public_record

        # Create subject + identifier so lookup can find the record
        subject = SubjectEntity.objects.create(name='Shady Person', type='person')
        raw_phone = '08011122233'
        value_hash = hash_identifier_value('phone', raw_phone)
        Identifier.objects.create(subject=subject, type='phone', value_hash=value_hash)

        ref = generate_report_reference_number()
        report = FraudReport.objects.create(
            reference_number=ref,
            reporter=self.reporter,
            target_subject=subject,
            title='Test',
            allegation='Allegation text.',
            state='submitted',
        )
        transition_report_state(
            report=report, new_state='published',
            actor=self.moderator,
            moderation_notes='INTERNAL: reporter credible, evidence strong.'
        )

        result = lookup_public_record(value_hash)
        self.assertIsNotNone(result)

        # moderation_notes must not appear anywhere in public result
        result_str = str(result)
        self.assertNotIn('INTERNAL', result_str)
        self.assertNotIn('reporter credible', result_str)
    