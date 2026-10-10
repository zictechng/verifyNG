
# identities/signals.py
"""
Signal receivers that trigger TrustScore recalculation.

Triggers (all use transaction.on_commit — score only updates after DB commit):
  1. FraudReport post_save  → when state changes to/from 'published' or 'restricted'
  2. VerificationResult post_save → when a verification is completed
  3. Dispute post_save      → when a dispute status changes to 'accepted' or 'rejected'

Design: signals never calculate inline — they schedule via on_commit so the
score is always computed against fully committed data.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction

import logging
logger = logging.getLogger(__name__)

# States that affect the trust score when a FraudReport enters or leaves them
SCORE_AFFECTING_REPORT_STATES = {'published', 'restricted', 'disputed', 'resolved'}

# Dispute resolutions that affect the score
SCORE_AFFECTING_DISPUTE_STATUSES = {'accepted', 'rejected'}


@receiver(post_save, sender='reports.FraudReport')
def on_fraud_report_saved(sender, instance, created, **kwargs):
    """
    Recalculate trust score when a FraudReport reaches a score-affecting state.
    Only fires if the report has a linked target_subject.
    """
    if not instance.target_subject_id:
        return

    current_state = instance.state
    previous_state = getattr(instance, '_previous_state', None)

    # Only recalculate if the state is one that affects the score,
    # or if we transitioned away from one (e.g. restricted → archived)
    relevant = (
        current_state in SCORE_AFFECTING_REPORT_STATES
        or previous_state in SCORE_AFFECTING_REPORT_STATES
    )
    if not relevant:
        return

    subject_id = instance.target_subject_id

    def _recalc():
        from identities.trust_score import recalculate_trust_score
        try:
            recalculate_trust_score(subject_id)
        except Exception as e:
            logger.exception(
                "TrustScore recalculation failed for subject_id=%s after FraudReport save: %s",
                subject_id, e
            )

    transaction.on_commit(_recalc)


@receiver(post_save, sender='verification.VerificationResult')
def on_verification_result_saved(sender, instance, created, **kwargs):
    """
    Recalculate trust score when a VerificationResult is created or updated.
    Follows the request → target_subject chain.
    """
    try:
        subject_id = instance.request.target_subject_id
    except Exception:
        return

    if not subject_id:
        return

    def _recalc():
        from identities.trust_score import recalculate_trust_score
        try:
            recalculate_trust_score(subject_id)
        except Exception as e:
            logger.exception(
                "TrustScore recalculation failed for subject_id=%s after VerificationResult save: %s",
                subject_id, e
            )

    transaction.on_commit(_recalc)


@receiver(post_save, sender='reports.Dispute')
def on_dispute_saved(sender, instance, created, **kwargs):
    """
    Recalculate trust score when a Dispute is resolved (accepted or rejected).
    """
    if instance.status not in SCORE_AFFECTING_DISPUTE_STATUSES:
        return

    try:
        subject_id = instance.report.target_subject_id
    except Exception:
        return

    if not subject_id:
        return

    def _recalc():
        from identities.trust_score import recalculate_trust_score
        try:
            recalculate_trust_score(subject_id)
        except Exception as e:
            logger.exception(
                "TrustScore recalculation failed for subject_id=%s after Dispute save: %s",
                subject_id, e
            )

    transaction.on_commit(_recalc)

