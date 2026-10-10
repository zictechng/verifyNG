
# identities/trust_score.py
"""
Trust Score calculation engine for VerifyNG.

Formula (0–1000 total):
  Identity Verification  30%  → max 300 pts
  Conduct / Behaviour    30%  → max 300 pts
  Reports Against        25%  → max 250 pts
  Longevity on Platform  15%  → max 150 pts

Design rules:
  - This module is pure calculation logic only.
  - It has NO side effects — it does not save, signal, or email.
  - Call recalculate_trust_score() to compute AND persist.
  - All callers (signals, management commands, tests) use this module.
  - Never call this inline on a web request; always triggered post-commit.
"""

import logging
from django.utils import timezone
from django.db import transaction

logger = logging.getLogger(__name__)


# ─── Component calculators ────────────────────────────────────────────────────

def _calculate_identity_score(subject) -> int:
    """
    Identity Verification component — max 300 pts.

    Points awarded:
      200 pts  — subject has at least one completed VerificationResult (verified/inconclusive)
       50 pts  — subject has a verified BusinessProfile (is_verified_business=True)
       50 pts  — subject has ≥ 2 distinct identifier types registered (phone, nin, email, etc.)

    Returns an integer 0–300.
    """
    score = 0

    # 200 pts: at least one completed verification with a positive outcome
    has_verified_result = subject.verification_requests.filter(
        status='completed',
        result__outcome__in=['verified', 'inconclusive']
    ).exists()
    if has_verified_result:
        score += 200

    # 50 pts: verified business profile
    if hasattr(subject, 'business_profile') and subject.business_profile.is_verified_business:
        score += 50

    # 50 pts: ≥ 2 distinct identifier types (shows more complete identity)
    distinct_id_types = subject.identifiers.values('type').distinct().count()
    if distinct_id_types >= 2:
        score += 50

    return min(score, 300)


def _calculate_conduct_score(subject) -> int:
    """
    Conduct / Behaviour component — max 300 pts.

    Start at 300 (clean slate). Deduct for negative signals:
      -100 pts  per published report (capped at 3 reports = -300 max)
      -50  pts  per restricted report (dispute accepted — serious)
      +50  pts  per successfully rejected dispute (allegation contested and won)

    Returns an integer 0–300.
    """
    score = 300

    published_count   = subject.reports.filter(state='published').count()
    restricted_count  = subject.reports.filter(state='restricted').count()

    # Disputes filed against this subject's reports that were REJECTED
    # (i.e. the original report was upheld — the dispute was not accepted)
    # This counts as a negative: the subject tried to suppress a valid report
    disputes_lost = subject.reports.filter(
        disputes__status='rejected'
    ).distinct().count()

    # Disputes the subject filed that were ACCEPTED
    # (the subject successfully contested a false report)
    disputes_won = subject.reports.filter(
        disputes__status='accepted'
    ).distinct().count()

    score -= min(published_count, 3) * 100
    score -= restricted_count * 50
    score -= disputes_lost * 25
    score += disputes_won * 50

    return max(0, min(score, 300))


def _calculate_reports_score(subject) -> int:
    """
    Reports Against component — max 250 pts.

    Starts at 250 (no reports = clean). Deducts per verified report.
    A 'restricted' report (dispute accepted) carries less weight
    than a fully published one.

      published   → -80 pts each (capped: 3 = -240)
      restricted  → -40 pts each (capped: 3 = -120)

    Returns an integer 0–250.
    """
    published_count  = subject.reports.filter(state='published').count()
    restricted_count = subject.reports.filter(state='restricted').count()

    deduction = (min(published_count, 3) * 80) + (min(restricted_count, 3) * 40)
    return max(0, 250 - deduction)


def _calculate_longevity_score(subject) -> int:
    """
    Longevity on Platform component — max 150 pts.

    Points for time since first SubjectEntity record was created:
      0–29 days    →  0 pts
      30–89 days   → 30 pts
      90–179 days  → 60 pts
      180–364 days → 100 pts
      365+ days    → 150 pts

    Returns an integer 0–150.
    """
    age_days = (timezone.now() - subject.created_at).days

    if age_days >= 365:
        return 150
    elif age_days >= 180:
        return 100
    elif age_days >= 90:
        return 60
    elif age_days >= 30:
        return 30
    return 0


# ─── Main public function ─────────────────────────────────────────────────────

def recalculate_trust_score(subject_id: int) -> 'TrustScore':
    """
    Computes and persists the TrustScore for a SubjectEntity.

    Args:
        subject_id: pk of the SubjectEntity to score.

    Returns:
        The saved TrustScore instance.

    Raises:
        SubjectEntity.DoesNotExist if subject_id is invalid.

    Usage:
        # From a signal (always call via transaction.on_commit):
        transaction.on_commit(lambda: recalculate_trust_score(subject.id))

        # From a management command or test:
        score = recalculate_trust_score(subject.id)
    """
    from identities.models import SubjectEntity, TrustScore

    subject = SubjectEntity.objects.select_related(
        'business_profile',
        'trust_score',
    ).prefetch_related(
        'identifiers',
        'reports',
        'reports__disputes',
        'verification_requests',
        'verification_requests__result',
    ).get(pk=subject_id)

    identity_score  = _calculate_identity_score(subject)
    conduct_score   = _calculate_conduct_score(subject)
    reports_score   = _calculate_reports_score(subject)
    longevity_score = _calculate_longevity_score(subject)

    composite = identity_score + conduct_score + reports_score + longevity_score

    # Gather metadata counts for the stored record
    published_count  = subject.reports.filter(state='published').count()
    disputed_count   = subject.reports.filter(state='disputed').count()
    restricted_count = subject.reports.filter(state='restricted').count()
    completed_verifs = subject.verification_requests.filter(status='completed').count()
    is_verified      = subject.verification_requests.filter(
        status='completed', result__outcome='verified'
    ).exists()

    trust_score, _ = TrustScore.objects.update_or_create(
        subject=subject,
        defaults={
            'score':                    composite,
            'identity_score':           identity_score,
            'conduct_score':            conduct_score,
            'reports_score':            reports_score,
            'longevity_score':          longevity_score,
            'published_reports_count':  published_count,
            'disputed_reports_count':   disputed_count,
            'restricted_reports_count': restricted_count,
            'is_identity_verified':     is_verified,
            'completed_verifications':  completed_verifs,
        }
    )

    logger.info(
        "TrustScore recalculated: subject_id=%s score=%s (I:%s C:%s R:%s L:%s)",
        subject_id, composite,
        identity_score, conduct_score, reports_score, longevity_score
    )

    return trust_score
