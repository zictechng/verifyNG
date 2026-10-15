
from identities.models import Identifier
from verification.models import VerificationCertificate

def lookup_public_record(identifier_hash: str) -> dict | None:
    """
    Queries an identifier by its peppered HMAC-SHA256 digest.
    
    Database Performance:
    - select_related('subject', 'subject__business_profile') uses an indexed SQL JOIN
      to fetch Identifier, SubjectEntity, and BusinessProfile in a single primary query.
    - prefetch_related('subject__reports', 'subject__verification_requests__result')
      executes 2 targeted secondary queries to prefetch related sets into memory,
      completely preventing N+1 queries during evaluation.
    
    Status Separation:
    - Verifications: Evaluated strictly from BusinessProfile.is_verified_business or
      completed VerificationRequest with outcome='verified'.
    - Allegations: Counted strictly from FraudReport where state='published'.
      Non-public moderation states (submitted, under_review, rejected, restricted, archived)
      are strictly excluded. Disputed reports (state='disputed') are tracked separately.
    - Privacy: Raw identifiers, reporter identities, and moderation notes are strictly omitted.
    """
    try:
        identifier = (
                        Identifier.objects.select_related('subject', 'subject__business_profile', 'subject__trust_score')
            .prefetch_related(
                'subject__reports',
                'subject__verification_requests__result',
            )
            .get(value_hash=identifier_hash)
        )
    except Identifier.DoesNotExist:
        return None

    subject = identifier.subject
    entity_type = subject.type
    subject_name = subject.name

    # Determine business verification and official naming
    official_business_name = None
    is_business_verified = False
    if entity_type == 'business' and hasattr(subject, 'business_profile'):
        bp = subject.business_profile
        official_business_name = bp.official_name or subject_name
        is_business_verified = bp.is_verified_business

    # Evaluate official completed verification requests
    has_verified_request = any(
        vr.status == 'completed'
        and hasattr(vr, 'result')
        and vr.result.outcome == 'verified'
        for vr in subject.verification_requests.all()
    )

    identity_verified = is_business_verified or has_verified_request
    if identity_verified:
        verification_label = "Officially Verified"
    else:
        verification_label = "Unverified (No Official Verification on File)"

    # Moderation filtering: Only 'published' and 'disputed'
    published_reports = [r for r in subject.reports.all() if r.state == 'published']
    disputed_reports = [r for r in subject.reports.all() if r.state == 'disputed']

    published_count = len(published_reports)
    disputed_count = len(disputed_reports)
    has_active_flags = published_count > 0

    allegation_notice = (
        "Fraud reports represent unverified community allegations published for public awareness. "
        "They do not constitute formal judicial findings, court convictions, or regulatory adjudications."
    )
    active_certs = (
        VerificationCertificate.objects
        .filter(subject=subject, status='active', is_active=True)
        .order_by('-issued_at')
    )
    certificates = [
        {
            'certificate_id':  cert.certificate_id,
            'check_level':     cert.check_level,
            'check_level_display': cert.get_check_level_display(),
            'issued_at':       cert.issued_at.strftime('%Y-%m-%d') if cert.issued_at else None,
            'expires_at':      cert.expires_at.strftime('%Y-%m-%d') if cert.expires_at else None,
            'is_valid':        cert.is_valid,
            'status':          cert.status,
        }
        for cert in active_certs
    ]
    # Fetch pre-computed trust score (None if not yet calculated)
    ts = getattr(subject, 'trust_score', None)
    return {
        "subject_name": subject_name,
        "entity_type": entity_type,
        "active_reports_count": published_count,
        "identity_verified": identity_verified,
        "verification_label": verification_label,
        "has_active_flags": has_active_flags,
        "published_reports_count": published_count,
        "disputed_reports_count": disputed_count,
        "official_business_name": official_business_name,
        "allegation_notice": allegation_notice,
        # Trust Score (None if not yet calculated)
        'trust_score':       getattr(ts, 'score', None),
        'trust_label':       getattr(ts, 'label', 'Unknown'),
        'trust_label_colour': getattr(ts, 'label_colour', 'secondary'),
        'identity_verified': getattr(ts, 'is_identity_verified', False),
        "certificates":            certificates,
    }

    