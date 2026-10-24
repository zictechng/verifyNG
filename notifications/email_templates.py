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
from core.email_utils import render_email

_BASE_SITE_NAME = "VerifyNG"
_BASE_SITE_URL = "https://verifyng.com"
_DISCLAIMER = (
    "This is an automated notification from the VerifyNG platform. "
    "Do not reply directly to this email."
)


def _get_site_meta() -> Tuple[str, str]:
    try:
        config = SiteConfiguration.get_solo()
        name = config.site_name or _BASE_SITE_NAME
        url = (config.base_url or _BASE_SITE_URL).rstrip('/')
        return name, url
    except Exception:
        return _BASE_SITE_NAME, _BASE_SITE_URL


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
