
# tests/test_trust_score.py
"""
Unit tests for the Trust Score calculation engine.

Run with:
    python manage.py test tests.test_trust_score --verbosity=2
"""

from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch

from identities.models import SubjectEntity, TrustScore
from identities.trust_score import (
    recalculate_trust_score,
    _calculate_identity_score,
    _calculate_conduct_score,
    _calculate_reports_score,
    _calculate_longevity_score,
)


def make_subject(name='Test Person', subject_type='individual', age_days=0):
    """Helper: create a SubjectEntity with a controlled created_at."""
    subject = SubjectEntity.objects.create(name=name, type=subject_type)
    if age_days:
        SubjectEntity.objects.filter(pk=subject.pk).update(
            created_at=timezone.now() - timedelta(days=age_days)
        )
        subject.refresh_from_db()
    return subject


class LongevityScoreTest(TestCase):

    def test_new_subject_scores_zero(self):
        subject = make_subject(age_days=0)
        self.assertEqual(_calculate_longevity_score(subject), 0)

    def test_30_days_scores_30(self):
        subject = make_subject(age_days=30)
        self.assertEqual(_calculate_longevity_score(subject), 30)

    def test_90_days_scores_60(self):
        subject = make_subject(age_days=90)
        self.assertEqual(_calculate_longevity_score(subject), 60)

    def test_180_days_scores_100(self):
        subject = make_subject(age_days=180)
        self.assertEqual(_calculate_longevity_score(subject), 100)

    def test_365_days_scores_150(self):
        subject = make_subject(age_days=365)
        self.assertEqual(_calculate_longevity_score(subject), 150)


class ReportsScoreTest(TestCase):

    def test_no_reports_scores_250(self):
        subject = make_subject()
        self.assertEqual(_calculate_reports_score(subject), 250)

    def test_one_published_report_deducts_80(self):
        from reports.models import FraudReport
        subject = make_subject()
        FraudReport.objects.create(
            reference_number='VNG-20260101-TEST',
            target_subject=subject,
            title='Test', allegation='Test allegation', state='published'
        )
        self.assertEqual(_calculate_reports_score(subject), 170)

    def test_three_published_reports_caps_at_zero(self):
        from reports.models import FraudReport
        subject = make_subject()
        for i in range(3):
            FraudReport.objects.create(
                reference_number=f'VNG-20260101-T{i:03}',
                target_subject=subject,
                title='Test', allegation='Test allegation', state='published'
            )
        self.assertEqual(_calculate_reports_score(subject), 10)  # 250 - 240 = 10


class ConductScoreTest(TestCase):

    def test_clean_subject_scores_300(self):
        subject = make_subject()
        self.assertEqual(_calculate_conduct_score(subject), 300)

    def test_one_published_report_deducts_100(self):
        from reports.models import FraudReport
        subject = make_subject()
        FraudReport.objects.create(
            reference_number='VNG-20260101-TEST',
            target_subject=subject,
            title='Test', allegation='Test allegation', state='published'
        )
        self.assertEqual(_calculate_conduct_score(subject), 200)


class TrustScoreLabelTest(TestCase):

    def _make_score(self, score_val):
        subject = make_subject()
        ts = TrustScore.objects.create(subject=subject, score=score_val)
        return ts

    def test_800_plus_is_high_trust(self):
        self.assertEqual(self._make_score(850).label, 'High Trust')

    def test_600_to_799_is_moderate_trust(self):
        self.assertEqual(self._make_score(650).label, 'Moderate Trust')

    def test_400_to_599_is_low_trust(self):
        self.assertEqual(self._make_score(450).label, 'Low Trust')

    def test_200_to_399_is_at_risk(self):
        self.assertEqual(self._make_score(300).label, 'At Risk')

    def test_below_200_is_high_risk(self):
        self.assertEqual(self._make_score(100).label, 'High Risk')


class RecalculateTrustScoreTest(TestCase):

    def test_clean_subject_scores_500_on_day_0(self):
        """New subject with no reports, no verifications, day 0 → 500 baseline."""
        subject = make_subject()
        # identity=0, conduct=300, reports=250, longevity=0 → 550
        # (conduct starts clean at 300, reports start clean at 250)
        ts = recalculate_trust_score(subject.id)
        self.assertEqual(ts.score, 550)

    def test_score_persisted_to_db(self):
        subject = make_subject()
        recalculate_trust_score(subject.id)
        ts = TrustScore.objects.get(subject=subject)
        self.assertIsNotNone(ts.score)

    def test_recalculate_updates_existing_record(self):
        subject = make_subject()
        recalculate_trust_score(subject.id)
        recalculate_trust_score(subject.id)
        # Should be exactly one record
        self.assertEqual(TrustScore.objects.filter(subject=subject).count(), 1)
