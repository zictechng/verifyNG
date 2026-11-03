# notifications/email_templates.py
"""
Subject lines and plain-text/HTML body builders for each notification event type.
All builders return (subject: str, html_body: str, text_body: str).
All notifications use the central core.email_utils.render_email() system
extending templates/emails/base_email.html for professional, mobile-friendly design.
"""

from typing import Tuple, Optional
from django.utils import timezone
from core.models import SiteConfiguration
from core.email_utils import render_email, get_dynamic_base_url

_BASE_SITE_NAME = "VerifyNG"


def _get_site_meta() -> Tuple[str, str]:
    try:
        config = SiteConfiguration.get_solo()
        name = getattr(config, 'site_name', '') or _BASE_SITE_NAME
        url = get_dynamic_base_url()
        return name, url
    except Exception:
        from django.conf import settings
        return _BASE_SITE_NAME, getattr(settings, 'SITE_BASE_URL', 'http://localhost:8000').rstrip('/')


def _get_disclaimer() -> str:
    name, _ = _get_site_meta()
    return f"This is an automated notification from the {name} platform. Do not reply directly to this email."

_DISCLAIMER = (
    "This is an automated notification from the platform. "
    "Do not reply directly to this email."
)


def _html_fallback(title: str, body_html: str) -> str:
    """Minimal fallback HTML if template engine is unavailable."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{title}</title></head>
<body style="font-family:sans-serif;padding:24px;background:#f5f5f7;color:#1d1d1f;">
  <div style="max-width:600px;margin:0 auto;background:#ffffff;padding:24px;border-radius:12px;">
    {body_html}
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Report Lifecycle Builders
# ---------------------------------------------------------------------------

def build_report_submitted(
    reference_number: str,
    username: str,
    report=None
) -> Tuple[str, str, str]:
    """Dispatched to the reporter upon successful fraud report registration."""
    site_name, site_url = _get_site_meta()
    target_name = ''
    report_title = ''
    submitted_at = timezone.now().strftime('%d %B %Y, %I:%M %p')

    if report:
        target_name = getattr(report.target_subject, 'name', '') if getattr(report, 'target_subject', None) else ''
        report_title = getattr(report, 'title', '')
        if getattr(report, 'created_at', None):
            submitted_at = report.created_at.strftime('%d %B %Y, %I:%M %p')
    else:
        try:
            from reports.models import FraudReport
            rep = FraudReport.objects.filter(reference_number=reference_number).select_related('target_subject').first()
            if rep:
                target_name = rep.target_subject.name if rep.target_subject else ''
                report_title = rep.title
                submitted_at = rep.created_at.strftime('%d %B %Y, %I:%M %p')
        except Exception:
            pass

    subject = f"Fraud Report Received [{reference_number}] — {site_name}"
    try:
        html_body, text_body = render_email('report_submitted', {
            'user_name': username,
            'reference_number': reference_number,
            'target_name': target_name,
            'report_title': report_title,
            'submitted_at': submitted_at,
            'report_url': f"{site_url}/reports/{reference_number}/?src=my_reports",
            'detail_url': f"{site_url}/reports/{reference_number}/?src=my_reports",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Report Received</h2><p>Hi {username}, your report {reference_number} has been received.</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, your report {reference_number} has been received."


def build_report_published(
    reference_number: str,
    username: str,
    report=None
) -> Tuple[str, str, str]:
    """Dispatched when a report is verified and published live."""
    site_name, site_url = _get_site_meta()
    target_name = ''
    report_title = ''
    updated_at = timezone.now().strftime('%d %B %Y, %I:%M %p')
    moderation_notes = ''

    if report:
        target_name = getattr(report.target_subject, 'name', '') if getattr(report, 'target_subject', None) else ''
        report_title = getattr(report, 'title', '')
        moderation_notes = getattr(report, 'moderation_notes', '')
    else:
        try:
            from reports.models import FraudReport
            rep = FraudReport.objects.filter(reference_number=reference_number).select_related('target_subject').first()
            if rep:
                target_name = rep.target_subject.name if rep.target_subject else ''
                report_title = rep.title
                moderation_notes = rep.moderation_notes or ''
        except Exception:
            pass

    subject = f"Report Approved & Published [{reference_number}] — {site_name}"
    try:
        html_body, text_body = render_email('report_status_update', {
            'user_name': username,
            'reference_number': reference_number,
            'status_key': 'published',
            'status_display': 'Approved & Published',
            'status_heading': 'Your Fraud Report Has Been Approved & Published',
            'status_message': 'Your fraud report has been reviewed and verified by our compliance moderation desk. It is now published in the public trust index to protect citizens and organizations from potential fraud.',
            'target_name': target_name,
            'report_title': report_title,
            'updated_at': updated_at,
            'moderation_notes': moderation_notes,
            'report_url': f"{site_url}/reports/{reference_number}/",
            'detail_url': f"{site_url}/reports/{reference_number}/",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Report Published</h2><p>Hi {username}, report {reference_number} has been published.</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, report {reference_number} has been published."


def build_report_rejected(
    reference_number: str,
    username: str,
    report=None,
    moderation_notes=None
) -> Tuple[str, str, str]:
    """Dispatched when a report is declined / rejected by compliance."""
    site_name, site_url = _get_site_meta()
    target_name = ''
    report_title = ''
    updated_at = timezone.now().strftime('%d %B %Y, %I:%M %p')
    notes = moderation_notes or ''

    if report:
        target_name = getattr(report.target_subject, 'name', '') if getattr(report, 'target_subject', None) else ''
        report_title = getattr(report, 'title', '')
        if not notes:
            notes = getattr(report, 'moderation_notes', '')
    else:
        try:
            from reports.models import FraudReport
            rep = FraudReport.objects.filter(reference_number=reference_number).select_related('target_subject').first()
            if rep:
                target_name = rep.target_subject.name if rep.target_subject else ''
                report_title = rep.title
                if not notes:
                    notes = rep.moderation_notes or ''
        except Exception:
            pass

    subject = f"Report Decision Update [{reference_number}] — {site_name}"
    try:
        html_body, text_body = render_email('report_status_update', {
            'user_name': username,
            'reference_number': reference_number,
            'status_key': 'rejected',
            'status_display': 'Declined',
            'status_heading': 'Update on Your Fraud Report',
            'status_message': 'After careful review against our verification guidelines, our moderation team was unable to publish your fraud report at this time. This may be due to inconclusive proof, insufficient primary documentation, or policy considerations.',
            'target_name': target_name,
            'report_title': report_title,
            'updated_at': updated_at,
            'moderation_notes': notes,
            'report_url': f"{site_url}/reports/{reference_number}/",
            'detail_url': f"{site_url}/reports/{reference_number}/",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Report Update</h2><p>Hi {username}, report {reference_number} was declined.</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, report {reference_number} was declined."


def build_report_status_update(
    reference_number: str,
    username: str,
    new_state: str,
    report=None,
    moderation_notes=None,
) -> Tuple[str, str, str]:
    """Unified handler for all state changes (published, rejected, archived, under_review, resolved, restricted)."""
    if new_state == 'published':
        return build_report_published(reference_number, username, report=report)
    elif new_state == 'rejected':
        return build_report_rejected(reference_number, username, report=report, moderation_notes=moderation_notes)

    site_name, site_url = _get_site_meta()
    target_name = ''
    report_title = ''
    updated_at = timezone.now().strftime('%d %B %Y, %I:%M %p')
    notes = moderation_notes or ''

    if report:
        target_name = getattr(report.target_subject, 'name', '') if getattr(report, 'target_subject', None) else ''
        report_title = getattr(report, 'title', '')
        if not notes:
            notes = getattr(report, 'moderation_notes', '')
    else:
        try:
            from reports.models import FraudReport
            rep = FraudReport.objects.filter(reference_number=reference_number).select_related('target_subject').first()
            if rep:
                target_name = rep.target_subject.name if rep.target_subject else ''
                report_title = rep.title
                if not notes:
                    notes = rep.moderation_notes or ''
        except Exception:
            pass

    state_configs = {
        'under_review': {
            'subject': f"Report Under Active Review [{reference_number}] — {site_name}",
            'heading': "Your Fraud Report is Under Active Review",
            'display': "Under Formal Review",
            'message': "Your report has been assigned to a compliance officer. We are currently verifying all submitted records and cross-referencing suspect identifiers.",
        },
        'archived': {
            'subject': f"Report Closed & Archived [{reference_number}] — {site_name}",
            'heading': "Fraud Report Closed & Archived",
            'display': "Archived / Cancelled",
            'message': "This report case has been formally closed and archived by compliance administration.",
        },
        'resolved': {
            'subject': f"Report Marked Resolved [{reference_number}] — {site_name}",
            'heading': "Fraud Report Case Resolved",
            'display': "Resolved",
            'message': "The allegations and matters concerning this report have been marked as resolved following compliance mediation.",
        },
        'restricted': {
            'subject': f"Report Access Restricted [{reference_number}] — {site_name}",
            'heading': "Report Access Restricted",
            'display': "Restricted",
            'message': "Public access to this report has been restricted pending further review.",
        },
    }

    cfg = state_configs.get(new_state, {
        'subject': f"Report Status Update [{reference_number}] — {site_name}",
        'heading': "Status Update on Your Report",
        'display': new_state.replace('_', ' ').title(),
        'message': f"Your fraud report status has been updated to {new_state.replace('_', ' ')}.",
    })

    try:
        html_body, text_body = render_email('report_status_update', {
            'user_name': username,
            'reference_number': reference_number,
            'status_key': new_state,
            'status_display': cfg['display'],
            'status_heading': cfg['heading'],
            'status_message': cfg['message'],
            'target_name': target_name,
            'report_title': report_title,
            'updated_at': updated_at,
            'moderation_notes': notes,
            'report_url': f"{site_url}/reports/{reference_number}/",
            'detail_url': f"{site_url}/reports/{reference_number}/",
        })
        return cfg['subject'], html_body, text_body
    except Exception:
        fallback_html = f"<h2>{cfg['heading']}</h2><p>Hi {username}, report {reference_number} is now {cfg['display']}.</p>"
        return cfg['subject'], _html_fallback(cfg['subject'], fallback_html), f"Hi {username}, report {reference_number} is now {cfg['display']}."


# ---------------------------------------------------------------------------
# Dispute Lifecycle Builders
# ---------------------------------------------------------------------------

def build_dispute_opened(
    reference_number: str,
    username: str,
    report=None
) -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    target_name = ''
    report_title = ''
    filed_at = timezone.now().strftime('%d %B %Y, %I:%M %p')

    if report:
        target_name = getattr(report.target_subject, 'name', '') if getattr(report, 'target_subject', None) else ''
        report_title = getattr(report, 'title', '')
    else:
        try:
            from reports.models import FraudReport
            rep = FraudReport.objects.filter(reference_number=reference_number).select_related('target_subject').first()
            if rep:
                target_name = rep.target_subject.name if rep.target_subject else ''
                report_title = rep.title
        except Exception:
            pass

    subject = f"Notice: Dispute Filed on Report [{reference_number}] — {site_name}"
    try:
        html_body, text_body = render_email('dispute_opened', {
            'user_name': username,
            'reference_number': reference_number,
            'target_name': target_name,
            'report_title': report_title,
            'filed_at': filed_at,
            'report_url': f"{site_url}/reports/{reference_number}/",
            'detail_url': f"{site_url}/reports/{reference_number}/",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Dispute Filed</h2><p>Hi {username}, a dispute was filed on report {reference_number}.</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, a dispute was filed on report {reference_number}."


def build_dispute_resolved(
    reference_number: str,
    username: str,
    outcome: str,
    report=None,
    notes=None
) -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    outcome_label = "Accepted / Upheld" if outcome == "accepted" else "Rejected / Overruled"
    resolved_at = timezone.now().strftime('%d %B %Y, %I:%M %p')
    subject = f"Dispute Adjudication Verdict [{reference_number}] — {site_name}"

    try:
        html_body, text_body = render_email('dispute_resolved', {
            'user_name': username,
            'reference_number': reference_number,
            'outcome': outcome,
            'outcome_display': outcome_label,
            'resolution_notes': notes or '',
            'resolved_at': resolved_at,
            'report_url': f"{site_url}/reports/{reference_number}/",
            'detail_url': f"{site_url}/reports/{reference_number}/",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Dispute Resolved</h2><p>Hi {username}, dispute on report {reference_number} resolved: {outcome_label}.</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, dispute on report {reference_number} resolved: {outcome_label}."


# ---------------------------------------------------------------------------
# Verification Lifecycle Builders
# ---------------------------------------------------------------------------

def build_verification_completed(reference_number: str, username: str, verification=None) -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject_name = 'Target Subject'
    scope_display = 'Verification'
    outcome = 'verified'
    outcome_display = 'Verified Genuine'
    summary = 'Official verification confirmed and approved.'
    completed_at = timezone.now().strftime('%d %B %Y, %I:%M %p')

    if verification:
        subject_name = getattr(verification.target_subject, 'name', 'Target Subject') if getattr(verification, 'target_subject', None) else 'Target Subject'
        scope_display = dict(getattr(verification, 'VERIFICATION_TYPES', [])).get(getattr(verification, 'verification_type', ''), 'Verification')
        result = getattr(verification, 'result', None)
        if result:
            outcome = getattr(result, 'outcome', 'verified')
            outcome_display = dict(getattr(result, 'OUTCOME_CHOICES', [])).get(outcome, 'Verified Genuine')
            summary = getattr(result, 'summary', '') or summary
            if getattr(result, 'verified_at', None):
                completed_at = result.verified_at.strftime('%d %B %Y, %I:%M %p')

    subject = f"Verification Completed [{reference_number}]: {outcome_display} — {site_name}"
    try:
        html_body, text_body = render_email('verification_complete', {
            'user_name': username,
            'reference_number': reference_number,
            'subject_name': subject_name,
            'scope_display': scope_display,
            'outcome_display': outcome_display,
            'outcome': outcome,
            'summary': summary,
            'completed_at': completed_at,
            'report_url': f"{site_url}/verification/{reference_number}/report/",
            'detail_url': f"{site_url}/verification/{reference_number}/",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Verification Completed</h2><p>Hi {username}, verification {reference_number} is complete.</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, verification {reference_number} is complete."


def build_verification_rejected(reference_number: str, username: str, verification=None, reason=None) -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject_name = 'Target Subject'
    scope_display = 'Verification'
    reason_text = reason or 'Supporting documentation could not be substantiated against primary records.'
    declined_at = timezone.now().strftime('%d %B %Y, %I:%M %p')

    if verification:
        subject_name = getattr(verification.target_subject, 'name', 'Target Subject') if getattr(verification, 'target_subject', None) else 'Target Subject'
        scope_display = dict(getattr(verification, 'VERIFICATION_TYPES', [])).get(getattr(verification, 'verification_type', ''), 'Verification')
        if not reason and getattr(verification, 'notes', None):
            reason_text = verification.notes

    subject = f"Update on Verification Request [{reference_number}] — {site_name}"
    try:
        html_body, text_body = render_email('verification_declined', {
            'user_name': username,
            'reference_number': reference_number,
            'subject_name': subject_name,
            'scope_display': scope_display,
            'reason': reason_text,
            'declined_at': declined_at,
            'detail_url': f"{site_url}/verification/{reference_number}/",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Verification Declined</h2><p>Hi {username}, verification {reference_number} could not be completed.</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, verification {reference_number} could not be completed."


def build_broadcast(subject_line: str, message_body: str, username: str) -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject = f"{subject_line} — {site_name}"
    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': subject_line,
            'body_html': f'<p>{message_body}</p>',
            'cta_url': f"{site_url}/dashboard/",
            'cta_label': "Visit Dashboard →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>{subject_line}</h2><p>Hi {username},</p><p>{message_body}</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username},\n\n{message_body}"


# ---------------------------------------------------------------------------
# Account Identity & Corporate CAC Compliance Builders
# ---------------------------------------------------------------------------

def build_identity_verified(username: str, id_type: str = "Government ID") -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject = f"Identity Verification Approved — {site_name}"
    body_html = f"""
    <p>Congratulations! Your {id_type} document has been authenticated and approved by our compliance officers.</p>
    <p>Your account now holds an official <strong>Verified Identity Badge</strong>. You can now publish verified fraud reports, submit dispute resolutions, and request candidate checks across {site_name}.</p>
    """
    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Identity Verification Approved",
            'body_html': body_html,
            'cta_url': f"{site_url}/users/profile/",
            'cta_label': "View Your Verified Profile →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Identity Verification Approved</h2><p>Hi {username}, your {id_type} has been verified.</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, your {id_type} has been verified."


def build_identity_rejected(username: str, id_type: str = "Government ID", reason: str = "") -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject = f"Action Required: Identity Verification Update — {site_name}"
    reason_clean = reason or "Document could not be authenticated against primary identity registries."
    body_html = f"""
    <p>We reviewed your submitted {id_type} document, but our compliance team was unable to verify it at this time.</p>
    <div style="background:#fef2f2;border-left:4px solid #ef4444;padding:12px 16px;border-radius:6px;margin:16px 0;">
        <strong style="color:#991b1b;">Reason:</strong>
        <p style="color:#7f1d1d;margin:4px 0 0;">{reason_clean}</p>
    </div>
    <p>Please log in to your profile, review your submitted information, and provide a clear, valid government-issued document.</p>
    """
    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Identity Verification Declined",
            'body_html': body_html,
            'cta_url': f"{site_url}/users/profile/",
            'cta_label': "Update Document in Profile →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Identity Verification Declined</h2><p>Hi {username}, your {id_type} was declined. Reason: {reason_clean}</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, your {id_type} was declined. Reason: {reason_clean}"


def build_identity_revoked(username: str) -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject = f"Notice: Identity Verification Badge Revoked — {site_name}"
    body_html = f"""
    <p>This is to inform you that your verified identity badge on {site_name} has been revoked by platform compliance.</p>
    <p>Your status has reverted to unverified. Platform operations that require verified identity will remain locked until valid documents are submitted and re-approved.</p>
    """
    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Identity Verification Revoked",
            'body_html': body_html,
            'cta_url': f"{site_url}/users/profile/",
            'cta_label': "Review Profile →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Identity Verification Revoked</h2><p>Hi {username}, your verified badge has been revoked.</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, your verified badge has been revoked."


def build_employer_verified(company_name: str, username: str) -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject = f"Corporate CAC Verification Approved — {site_name}"
    body_html = f"""
    <p>Congratulations! Corporate incorporation records for <strong>{company_name}</strong> have been verified by compliance.</p>
    <p>Your organization now holds an active <strong>Verified Employer Badge</strong>. Full candidate clearance certificates (TrustPass), staff checks, and bulk screening capabilities have been unlocked for your team.</p>
    """
    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Company Verification Approved",
            'body_html': body_html,
            'cta_url': f"{site_url}/employer/",
            'cta_label': "Go to Employer Portal →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Company Verification Approved</h2><p>Hi {username}, {company_name} has been verified.</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, {company_name} has been verified."


def build_employer_rejected(company_name: str, username: str, reason: str = "") -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject = f"Action Required: CAC Verification Declined for {company_name} — {site_name}"
    reason_clean = reason or "CAC incorporation certificate or registration details could not be validated against registry records."
    body_html = f"""
    <p>We reviewed the corporate registration documents for <strong>{company_name}</strong>, but our compliance team was unable to approve them at this time.</p>
    <div style="background:#fef2f2;border-left:4px solid #ef4444;padding:12px 16px;border-radius:6px;margin:16px 0;">
        <strong style="color:#991b1b;">Reason for Decline:</strong>
        <p style="color:#7f1d1d;margin:4px 0 0;">{reason_clean}</p>
    </div>
    <p>Under NDPR and workforce vetting regulations, candidate clearance dossiers remain locked until a valid CAC certificate is confirmed. Any check purchases remain safely credited to your wallet balance.</p>
    <p>Please update your registration documents in your employer settings to request a re-review.</p>
    """
    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "CAC Verification Declined",
            'body_html': body_html,
            'cta_url': f"{site_url}/employer/profile/?tab=verification",
            'cta_label': "Update CAC Document →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>CAC Verification Declined</h2><p>Hi {username}, CAC for {company_name} was declined. Reason: {reason_clean}</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, CAC for {company_name} was declined. Reason: {reason_clean}"


def build_employer_unverified(company_name: str, username: str) -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject = f"Notice: Verified Employer Status Removed — {site_name}"
    body_html = f"""
    <p>This is to inform you that the verified organization status for <strong>{company_name}</strong> on {site_name} has been removed by platform compliance.</p>
    <p>Candidate clearance certificates and candidate vetting operations are now locked. Please re-submit your verification documents or contact compliance if you have any questions.</p>
    """
    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Employer Verification Status Removed",
            'body_html': body_html,
            'cta_url': f"{site_url}/employer/profile/",
            'cta_label': "View Employer Profile →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Employer Status Removed</h2><p>Hi {username}, verified status for {company_name} was removed.</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, verified status for {company_name} was removed."


# ---------------------------------------------------------------------------
# Evidence Dossier & Police Petition Payment Notifications
# ---------------------------------------------------------------------------

def build_dossier_payment_approved(dossier, username: str, admin_notes: str = "") -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    report_ref = dossier.report.reference_number if getattr(dossier, 'report', None) else ""
    amount_str = f"₦{dossier.amount_paid:,.2f}" if getattr(dossier, 'amount_paid', None) else "₦1,000.00"
    tracking_id = getattr(dossier, 'tracking_id', '')

    subject = f"Payment Confirmed: Legal Petition & Evidence Dossier Unlocked [{tracking_id}] — {site_name}"
    
    download_url = f"{site_url}/reports/{report_ref}/dossier/download/" if report_ref else f"{site_url}/reports/"

    body_html = f"""
    <p>Good news! Your direct bank transfer payment for the <strong>Official Police Petition &amp; Section 84 Evidence Dossier</strong> has been verified and confirmed by our administration.</p>
    
    <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-left:4px solid #16a34a;padding:14px 18px;border-radius:8px;margin:18px 0;font-size:14px;color:#166534;">
        <div style="margin-bottom:6px;"><strong>Tracking ID:</strong> <span style="font-family:monospace;font-weight:700;">{tracking_id}</span></div>
        <div style="margin-bottom:6px;"><strong>Case Report:</strong> {report_ref}</div>
        <div style="margin-bottom:6px;"><strong>Amount Verified:</strong> {amount_str}</div>
        <div><strong>Status:</strong> <span style="background:#dcfce7;color:#15803d;padding:2px 8px;border-radius:4px;font-weight:700;">Verified &amp; Active</span></div>
    </div>

    <p>Your court-ready petition package and certified Section 84 Evidence Act certificate are now completely unlocked and ready for printing or instant PDF download.</p>
    
    <p style="font-size:13px;color:#64748b;">You can present this official certified document directly to the Nigeria Police Force (NPF), EFCC, court, or your legal counsel. Each copy includes a tamper-evident cryptographic QR verification seal.</p>
    """

    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Petition & Evidence Dossier Unlocked",
            'body_html': body_html,
            'cta_url': download_url,
            'cta_label': "Download & Print Legal Petition (PDF) →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Payment Approved</h2><p>Hi {username}, your petition payment for {tracking_id} has been approved. You can now download your petition at: {download_url}</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, your petition payment for {tracking_id} has been approved. Download: {download_url}"


def build_dossier_payment_rejected(dossier, username: str, reason: str = "") -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    report_ref = dossier.report.reference_number if getattr(dossier, 'report', None) else ""
    amount_str = f"₦{dossier.amount_paid:,.2f}" if getattr(dossier, 'amount_paid', None) else "₦1,000.00"
    tracking_id = getattr(dossier, 'tracking_id', '')
    reason_clean = reason or "Transaction could not be verified on corporate bank statement or transferred amount was incomplete."

    subject = f"Notice: Petition Payment Verification Failed [{tracking_id}] — {site_name}"
    report_url = f"{site_url}/reports/{report_ref}/#petition-section" if report_ref else f"{site_url}/reports/"

    body_html = f"""
    <p>We reviewed your submitted direct transfer payment for Evidence Dossier <strong>{tracking_id}</strong> (Case Report: {report_ref}), but our finance team was unable to verify the transaction.</p>
    
    <div style="background:#fef2f2;border:1px solid #fecaca;border-left:4px solid #ef4444;padding:14px 18px;border-radius:8px;margin:18px 0;font-size:14px;color:#991b1b;">
        <div style="font-weight:700;margin-bottom:4px;">Reason for Rejection:</div>
        <div style="color:#7f1d1d;line-height:1.5;">{reason_clean}</div>
    </div>

    <p><strong>What to do next:</strong></p>
    <ul style="color:#334155;line-height:1.6;font-size:14px;">
        <li>Check your bank debit receipt to confirm the funds left your account.</li>
        <li>Ensure the transfer reference matches your tracking ID or registered name.</li>
        <li>You can re-upload your payment proof or choose instant online payment via card / bank transfer on the report page.</li>
    </ul>
    """

    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Payment Verification Declined",
            'body_html': body_html,
            'cta_url': report_url,
            'cta_label': "View Case Report & Re-submit →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Payment Declined</h2><p>Hi {username}, your payment for {tracking_id} could not be verified. Reason: {reason_clean}</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, your payment for {tracking_id} could not be verified. Reason: {reason_clean}"


def build_subscription_payment_approved(subscription, username: str, admin_notes: str = "") -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    plan_name = subscription.plan.name if subscription.plan else "Subscription Plan"
    amount_str = f"₦{subscription.plan.price_naira:,.2f}" if subscription.plan else "₦0.00"
    period_end = subscription.current_period_end.strftime('%d %B %Y') if subscription.current_period_end else "30 Days Active"
    checks_str = "Unlimited" if getattr(subscription.plan, 'has_unlimited_checks', False) else f"{subscription.plan.check_limit} Checks"

    subject = f"Subscription Activated: {plan_name} — {site_name}"
    dashboard_url = f"{site_url}/employer/" if getattr(subscription.user, 'is_employer', False) else f"{site_url}/dashboard/"

    body_html = f"""
    <p>Congratulations! Your direct bank transfer payment for the <strong>{plan_name}</strong> subscription has been verified and confirmed by our finance administration.</p>
    
    <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-left:4px solid #16a34a;padding:14px 18px;border-radius:8px;margin:18px 0;font-size:14px;color:#166534;">
        <div style="margin-bottom:6px;"><strong>Plan Activated:</strong> <span style="font-weight:700;">{plan_name}</span></div>
        <div style="margin-bottom:6px;"><strong>Amount Verified:</strong> {amount_str}</div>
        <div style="margin-bottom:6px;"><strong>Included Quota:</strong> {checks_str}</div>
        <div style="margin-bottom:6px;"><strong>Valid Until:</strong> {period_end}</div>
        <div><strong>Status:</strong> <span style="background:#dcfce7;color:#15803d;padding:2px 8px;border-radius:4px;font-weight:700;">Active &amp; Operational</span></div>
    </div>

    <p>Your subscription benefits, verification check allowances, and continuous monitoring tools are now fully active across your account.</p>
    """

    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': f"Your {plan_name} is Now Active!",
            'body_html': body_html,
            'cta_url': dashboard_url,
            'cta_label': "Go to Dashboard & Start Verifying →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Subscription Activated</h2><p>Hi {username}, your {plan_name} has been activated. Access your account at: {dashboard_url}</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, your {plan_name} has been activated. Access: {dashboard_url}"


def build_subscription_payment_rejected(subscription, username: str, reason: str = "") -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    plan_name = subscription.plan.name if subscription.plan else "Subscription Plan"
    reason_clean = reason or "Transaction could not be verified on corporate bank statement or transferred amount was incomplete."

    subject = f"Notice: Subscription Payment Verification Failed ({plan_name}) — {site_name}"
    plans_url = f"{site_url}/payments/"

    body_html = f"""
    <p>We reviewed your submitted direct bank transfer payment for the <strong>{plan_name}</strong> subscription, but our finance administration was unable to verify the transaction credit.</p>
    
    <div style="background:#fef2f2;border:1px solid #fecaca;border-left:4px solid #ef4444;padding:14px 18px;border-radius:8px;margin:18px 0;font-size:14px;color:#991b1b;">
        <div style="font-weight:700;margin-bottom:4px;">Reason for Rejection:</div>
        <div style="color:#7f1d1d;line-height:1.5;">{reason_clean}</div>
    </div>

    <p><strong>What to do next:</strong></p>
    <ul style="color:#334155;line-height:1.6;font-size:14px;">
        <li>Confirm with your bank that the funds successfully left your account.</li>
        <li>Ensure the payment reference or depositor name matches your registered account details.</li>
        <li>You can re-submit your transfer receipt or activate your plan instantly using online payment via card / USSD.</li>
    </ul>
    """

    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Subscription Payment Declined",
            'body_html': body_html,
            'cta_url': plans_url,
            'cta_label': "Review Plans & Re-submit Proof →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Payment Declined</h2><p>Hi {username}, your payment for {plan_name} could not be verified. Reason: {reason_clean}</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, your payment for {plan_name} could not be verified. Reason: {reason_clean}"




def build_merchant_badge_approved(store_name: str, username: str, store_slug: str) -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject = f"Verified Merchant Seal Approved: {store_name} — {site_name}"
    store_url = f"{site_url}/trust-seal/v/{store_slug}/"
    body_html = f"""
    <p>Congratulations <strong>{username}</strong>! Your application for the <strong>Verified Merchant Trust Seal</strong> for <strong>{store_name}</strong> has been officially approved by platform compliance.</p>
    <div style="background:#f0fdf4;border-left:4px solid #16a34a;padding:14px 18px;border-radius:6px;margin:18px 0;">
        <h4 style="margin:0 0 6px;color:#15803d;font-size:15px;">Official Verification Link Active</h4>
        <p style="margin:0 0 8px;font-size:13px;color:#166534;">Your customers can now verify your genuine business, safe track record, and settlement bank account.</p>
        <a href="{store_url}" style="font-weight:bold;color:#15803d;word-break:break-all;">{store_url}</a>
    </div>
    <h4 style="color:#0f172a;margin:18px 0 8px;font-size:14px;">Next Steps to Maximize Your Buyer Trust:</h4>
    <ul style="color:#334155;line-height:1.6;font-size:13px;padding-left:20px;">
        <li><strong>Add to your Instagram, TikTok, and WhatsApp bio:</strong> Place your verified link in your bio so potential buyers know you are authenticated.</li>
        <li><strong>Embed the Trust Seal on your store / website:</strong> Log in to your dashboard to copy the one-line embed badge code.</li>
        <li><strong>Share on invoices and payment receipts:</strong> Protect your customers from clone accounts and impersonators.</li>
    </ul>
    """
    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Merchant Trust Badge Approved",
            'body_html': body_html,
            'cta_url': store_url,
            'cta_label': "View Your Public Trust Page →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Merchant Badge Approved</h2><p>Hi {username}, your seal for {store_name} is approved. Public URL: {store_url}</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, your seal for {store_name} is approved: {store_url}"


def build_merchant_badge_rejected(store_name: str, username: str, reason: str = "") -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject = f"Update on Your Verified Merchant Application: {store_name} — {site_name}"
    reason_clean = reason or "Verification information or settlement bank details could not be authenticated against our compliance records."
    body_html = f"""
    <p>Thank you for applying for the <strong>Verified Merchant Trust Seal</strong> for <strong>{store_name}</strong>.</p>
    <p>After reviewing your submission, our compliance team was unable to approve your application at this time.</p>
    <div style="background:#fef2f2;border-left:4px solid #ef4444;padding:12px 16px;border-radius:6px;margin:16px 0;">
        <strong style="color:#991b1b;">Reason for Decision:</strong>
        <p style="color:#7f1d1d;margin:4px 0 0;font-size:13px;">{reason_clean}</p>
    </div>
    <p>You can correct any missing or unclear details and re-apply directly from your merchant verification dashboard.</p>
    """
    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Merchant Application Update",
            'body_html': body_html,
            'cta_url': f"{site_url}/trust-badge/apply/",
            'cta_label': "Update Application →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Merchant Application Update</h2><p>Hi {username}, your seal application for {store_name} was not approved. Reason: {reason_clean}</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, your seal application for {store_name} was not approved: {reason_clean}"


def build_merchant_badge_revoked(store_name: str, username: str, reason: str = "") -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject = f"Notice: Verified Merchant Seal Suspended for {store_name} — {site_name}"
    reason_clean = reason or "Your verified merchant status has been suspended pending compliance review or dispute resolution."
    body_html = f"""
    <p>Hi <strong>{username}</strong>,</p>
    <p>This is an official notice regarding your Verified Merchant Trust Seal for <strong>{store_name}</strong> on {site_name}.</p>
    <p>Following a recent compliance inspection, your public Verified Merchant Seal has been <strong>temporarily suspended</strong>.</p>
    <div style="background:#fef2f2;border-left:4px solid #ef4444;padding:14px 18px;border-radius:6px;margin:18px 0;">
        <h4 style="margin:0 0 6px;color:#991b1b;font-size:15px;">Suspension Notice &amp; Grounds</h4>
        <p style="margin:0;font-size:13px;color:#7f1d1d;line-height:1.5;">{reason_clean}</p>
    </div>
    <p>While suspended, the green verification badge will not be displayed on your store link. If you believe this action was made in error or have resolved any open complaints, please contact our Compliance and Trust Desk.</p>
    """
    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Verified Merchant Seal Suspended",
            'body_html': body_html,
            'cta_url': f"{site_url}/contact/",
            'cta_label': "Contact Compliance Desk →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Seal Suspended</h2><p>Hi {username}, your seal for {store_name} has been suspended: {reason_clean}</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, your seal for {store_name} has been suspended: {reason_clean}"


def build_merchant_bank_approved(store_name: str, username: str, new_bank: str, new_account: str, account_name: str) -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject = f"Settlement Bank Update Approved: {store_name} — {site_name}"
    body_html = f"""
    <p>Hi <strong>{username}</strong>,</p>
    <p>Your request to update the verified settlement bank account for <strong>{store_name}</strong> has been <strong>approved</strong> by our compliance officers.</p>
    <div style="background:#f0fdf4;border-left:4px solid #16a34a;padding:14px 18px;border-radius:6px;margin:18px 0;">
        <h4 style="margin:0 0 6px;color:#15803d;font-size:15px;">New Verified Payout Bank</h4>
        <p style="margin:0 0 4px;font-size:13px;color:#166534;">Bank: <strong>{new_bank}</strong></p>
        <p style="margin:0 0 4px;font-size:13px;color:#166534;">Account Number: <strong>{new_account}</strong></p>
        <p style="margin:0;font-size:13px;color:#166534;">Account Name: <strong>{account_name}</strong></p>
    </div>
    <p>Your live public trust badge has been automatically updated with your new verified banking credentials.</p>
    """
    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Settlement Bank Approved",
            'body_html': body_html,
            'cta_url': f"{site_url}/trust-seal/apply/",
            'cta_label': "View Merchant Desk →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Bank Update Approved</h2><p>Hi {username}, payout bank for {store_name} updated to {new_bank} ({new_account}).</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, payout bank for {store_name} updated to {new_bank} ({new_account})."


def build_merchant_bank_rejected(store_name: str, username: str, requested_bank: str, reason: str = "") -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject = f"Settlement Bank Update Request Declined: {store_name} — {site_name}"
    reason_clean = reason or "Bank account name does not match verified legal identity or CAC registry records."
    body_html = f"""
    <p>Hi <strong>{username}</strong>,</p>
    <p>We reviewed your request to update the payout bank account for <strong>{store_name}</strong> to <strong>{requested_bank}</strong>.</p>
    <div style="background:#fef2f2;border-left:4px solid #ef4444;padding:14px 18px;border-radius:6px;margin:18px 0;">
        <h4 style="margin:0 0 6px;color:#991b1b;font-size:15px;">Compliance Review Finding</h4>
        <p style="margin:0;font-size:13px;color:#7f1d1d;line-height:1.5;">{reason_clean}</p>
    </div>
    <p>To protect your store and prevent unauthorized banking changes, your previous verified settlement bank account remains active on your public trust badge.</p>
    """
    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Bank Update Request Declined",
            'body_html': body_html,
            'cta_url': f"{site_url}/trust-seal/apply/",
            'cta_label': "Review Merchant Desk →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Bank Update Declined</h2><p>Hi {username}, payout bank update for {store_name} was declined: {reason_clean}</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, payout bank update for {store_name} was declined: {reason_clean}"


def build_merchant_trial_expiring(store_name: str, username: str, days_left: int, amount_naira: float) -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    days_text = "Tomorrow" if days_left <= 1 else f"in {days_left} Days"
    subject = f"Your Verified Merchant Free Trial Ends {days_text} — {site_name}"
    checkout_url = f"{site_url}/payments/review/service/merchant_badge/"
    body_html = f"""
    <p>Hi <strong>{username}</strong>,</p>
    <p>This is a quick courtesy notification that your complimentary free trial for your <strong>Verified Merchant Trust Seal ({store_name})</strong> is expiring <strong>{days_text}</strong>.</p>
    <div style="background:#f8fafc;border:1px solid #cbd5e1;padding:16px 20px;border-radius:8px;margin:18px 0;">
        <div style="font-size:13px;color:#64748b;text-transform:uppercase;font-weight:bold;margin-bottom:4px;">Active Seal</div>
        <div style="font-size:16px;font-weight:bold;color:#0f172a;margin-bottom:8px;">{store_name}</div>
        <div style="font-size:14px;color:#334155;">Monthly Renewal: <strong>₦{amount_naira:,.0f}</strong></div>
    </div>
    <p>Keep your public verification badge active without disruption to ensure your buyers continue checking out with complete peace of mind.</p>
    """
    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Keep Your Trust Seal Active",
            'body_html': body_html,
            'cta_url': checkout_url,
            'cta_label': f"Renew Seal — ₦{amount_naira:,.0f}/mo →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Trial Ending Soon</h2><p>Hi {username}, trial for {store_name} ends {days_text}. Renew: {checkout_url}</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, trial for {store_name} ends {days_text}. Renew: {checkout_url}"


def build_merchant_dispute_opened(
    store_name: str,
    username: str,
    reference_number: str,
    report_title: str = "",
    amount_lost: str = "",
    reporter_allegation: str = "",
) -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject = f"Action Required: Customer Dispute Lodged Against {store_name} [{reference_number}] — {site_name}"
    dispute_url = f"{site_url}/reports/{reference_number}/"
    filed_at = timezone.now().strftime('%d %B %Y, %I:%M %p')

    allegation_snippet = (
        f'<div style="background:#fef2f2;border-left:4px solid #ef4444;padding:12px 16px;border-radius:6px;margin:16px 0;">'
        f'<strong style="color:#991b1b;font-size:13px;">Customer Complaint Summary:</strong>'
        f'<p style="color:#7f1d1d;margin:6px 0 0;font-size:13px;line-height:1.5;">{reporter_allegation or report_title or "Unfulfilled transaction or customer payment dispute."}</p>'
        f'</div>'
    )

    amount_html = f"<p style='margin:0 0 4px;font-size:13px;color:#78350f;'><strong>Disputed Amount:</strong> {amount_lost}</p>" if amount_lost else ""

    body_html = f"""
    <p>Hi <strong>{username}</strong>,</p>
    <p>This is an official compliance notice from <strong>{site_name}</strong>.</p>
    <p>A customer has filed a formal commercial transaction dispute regarding your verified store <strong>{store_name}</strong>.</p>
    
    <div style="background:#fffbeb;border:1px solid #fde68a;border-left:4px solid #f59e0b;padding:14px 18px;border-radius:6px;margin:16px 0;">
        <h4 style="margin:0 0 8px;color:#92400e;font-size:15px;">Dispute Details &amp; Reference</h4>
        <p style="margin:0 0 4px;font-size:13px;color:#78350f;"><strong>Case Reference:</strong> #{reference_number}</p>
        <p style="margin:0 0 4px;font-size:13px;color:#78350f;"><strong>Dispute Date:</strong> {filed_at}</p>
        <p style="margin:0 0 4px;font-size:13px;color:#78350f;"><strong>Claim Subject:</strong> {report_title or "Order Fulfillment Issue"}</p>
        {amount_html}
    </div>

    {allegation_snippet}

    <h4 style="color:#0f172a;margin:18px 0 8px;font-size:14px;">Impact on Your Verified Merchant Seal:</h4>
    <p style="color:#334155;font-size:13px;line-height:1.6;">
        In accordance with our platform rules, your public Verified Merchant Seal has been placed on <strong>Dispute Investigation (🟡 Under Dispute)</strong>.
    </p>
    <h4 style="color:#0f172a;margin:16px 0 8px;font-size:14px;">Next Steps (48-Hour Resolution Window):</h4>
    <ul style="color:#334155;line-height:1.6;font-size:13px;padding-left:20px;">
        <li><strong>Fulfill or Refund:</strong> Contact the customer or issue a refund if the transaction was unfulfilled.</li>
        <li><strong>Submit Proof:</strong> Log in to submit evidence of delivery or refund transfer receipt.</li>
        <li><strong>Seal Restoration:</strong> Once the customer confirms settlement or compliance reviews your proof, your seal will be instantly restored to <strong>Active (🟢)</strong>.</li>
    </ul>
    """
    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Customer Dispute Filed",
            'body_html': body_html,
            'cta_url': dispute_url,
            'cta_label': "View Dispute & Submit Response →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Customer Dispute Filed</h2><p>Hi {username}, a customer filed dispute #{reference_number} on {store_name}. Please resolve: {dispute_url}</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, a customer filed dispute #{reference_number} on {store_name}: {dispute_url}"


def build_merchant_dispute_resolved(
    store_name: str,
    username: str,
    reference_number: str,
) -> Tuple[str, str, str]:
    site_name, site_url = _get_site_meta()
    subject = f"Resolved: Dispute #{reference_number} Closed — Verified Seal Restored | {site_name}"
    resolved_at = timezone.now().strftime('%d %B %Y, %I:%M %p')

    body_html = f"""
    <p>Hi <strong>{username}</strong>,</p>
    <p>Good news! Customer transaction dispute <strong>#{reference_number}</strong> regarding <strong>{store_name}</strong> has been officially confirmed as <strong>Resolved</strong>.</p>
    
    <div style="background:#f0fdf4;border-left:4px solid #16a34a;padding:14px 18px;border-radius:6px;margin:18px 0;">
        <h4 style="margin:0 0 6px;color:#15803d;font-size:15px;">Seal Restored to Active 🟢</h4>
        <p style="margin:0;font-size:13px;color:#166534;line-height:1.5;">
            Your public Verified Merchant Seal has been cleared of the dispute warning and restored to good standing on {resolved_at}.
        </p>
    </div>
    <p>Thank you for resolving this matter professionally and maintaining consumer trust in Nigerian digital commerce.</p>
    """
    try:
        html_body, text_body = render_email('generic_notification', {
            'user_name': username,
            'heading': "Dispute Resolved & Seal Restored",
            'body_html': body_html,
            'cta_url': f"{site_url}/dashboard/",
            'cta_label': "Go to Merchant Dashboard →",
        })
        return subject, html_body, text_body
    except Exception:
        fallback_html = f"<h2>Dispute Resolved</h2><p>Hi {username}, dispute #{reference_number} is resolved and your seal is active.</p>"
        return subject, _html_fallback(subject, fallback_html), f"Hi {username}, dispute #{reference_number} is resolved: {store_name}"
