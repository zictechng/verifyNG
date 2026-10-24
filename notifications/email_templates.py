
# notifications/email_templates.py
"""
Subject lines and plain-text/HTML body builders for each notification event type.
All builders return (subject: str, html_body: str, text_body: str).
No sensitive data (evidence files, moderation notes, NIN/BVN) is included.
"""

from typing import Tuple
from django.utils import timezone
from core.models import SiteConfiguration
from core.email_utils import render_email


_BASE_SITE_NAME = "VerifyNG"
_BASE_SITE_URL = "https://verifyng.com"  # overridden by settings in production
_DISCLAIMER = (
    "This is an automated notification from the VerifyNG platform. "
    "Do not reply to this email."
)


def _html_wrapper(title: str, body_html: str) -> str:
    """Wraps content in a minimal, inline-styled HTML email shell."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#F6F8FC;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F6F8FC;padding:32px 0;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="background:#FFFFFF;border-radius:12px;border:1px solid #E3E9F2;overflow:hidden;max-width:600px;width:100%;">
      <!-- Header -->
      <tr>
        <td style="background:#2457D6;padding:24px 32px;">
          <span style="color:#FFFFFF;font-size:22px;font-weight:800;letter-spacing:-0.02em;">
            VerifyNG
          </span>
          <span style="color:rgba(255,255,255,0.7);font-size:12px;font-weight:500;margin-left:8px;text-transform:uppercase;letter-spacing:0.05em;">
            Public Trust Platform
          </span>
        </td>
      </tr>
      <!-- Body -->
      <tr>
        <td style="padding:32px;">
          {body_html}
        </td>
      </tr>
      <!-- Footer -->
      <tr>
        <td style="padding:16px 32px 24px;border-top:1px solid #E3E9F2;background:#F8FAFC;">
          <p style="margin:0;font-size:11px;color:#94A3B8;line-height:1.6;">{_DISCLAIMER}</p>
          <p style="margin:8px 0 0;font-size:11px;color:#94A3B8;">
            &copy; 2024 VerifyNG. Nigeria&rsquo;s Public Trust &amp; Safety Platform.
          </p>
        </td>
      </tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


def _cta_button(url: str, label: str) -> str:
    return (
        f'<a href="{url}" style="display:inline-block;background:#2457D6;color:#FFFFFF;'
        f'text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600;'
        f'font-size:14px;margin-top:20px;">{label}</a>'
    )


def _heading(text: str) -> str:
    return f'<h2 style="color:#17233B;font-size:20px;font-weight:700;margin:0 0 16px;">{text}</h2>'


def _para(text: str) -> str:
    return f'<p style="color:#334155;font-size:15px;line-height:1.7;margin:0 0 12px;">{text}</p>'


def _ref_pill(ref: str) -> str:
    return (
        f'<span style="display:inline-block;background:#EAF1FF;color:#2457D6;'
        f'font-family:monospace;font-size:13px;font-weight:600;padding:4px 10px;'
        f'border-radius:6px;margin-bottom:16px;">{ref}</span>'
    )


# ---------------------------------------------------------------------------
# Event template builders
# ---------------------------------------------------------------------------

def build_report_submitted(reference_number: str, username: str) -> Tuple[str, str, str]:
    subject = f"Report Received — {reference_number} | VerifyNG"
    body_html = (
        _heading("Your Fraud Report Has Been Received")
        + _para(f"Hi {username},")
        + _para(
            "Thank you for submitting a fraud report to VerifyNG. "
            "We have received your allegation and it is now queued for review by our moderation team."
        )
        + _ref_pill(reference_number)
        + _para(
            "Our team will review your submission and update you as it progresses through "
            "the verification process. This typically takes 1–3 business days."
        )
        + _cta_button(f"{_BASE_SITE_URL}/dashboard/", "View My Reports")
    )
    text_body = (
        f"Hi {username},\n\n"
        f"Your fraud report ({reference_number}) has been received and is queued for review.\n\n"
        f"View your reports at: {_BASE_SITE_URL}/dashboard/\n\n"
        f"{_DISCLAIMER}"
    )
    return subject, _html_wrapper(subject, body_html), text_body


def build_report_published(reference_number: str, username: str) -> Tuple[str, str, str]:
    subject = f"Report Published — {reference_number} | VerifyNG"
    body_html = (
        _heading("Your Fraud Report Has Been Published")
        + _para(f"Hi {username},")
        + _para(
            "Your fraud report has been reviewed and published on the VerifyNG platform. "
            "It is now visible to users performing trust checks."
        )
        + _ref_pill(reference_number)
        + _para("Thank you for helping protect the Nigerian public from fraud.")
        + _cta_button(f"{_BASE_SITE_URL}/dashboard/", "View Report")
    )
    text_body = (
        f"Hi {username},\n\n"
        f"Your fraud report ({reference_number}) has been verified and published.\n\n"
        f"View your reports at: {_BASE_SITE_URL}/dashboard/\n\n"
        f"{_DISCLAIMER}"
    )
    return subject, _html_wrapper(subject, body_html), text_body


def build_report_rejected(reference_number: str, username: str) -> Tuple[str, str, str]:
    subject = f"Report Update — {reference_number} | VerifyNG"
    body_html = (
        _heading("Update on Your Fraud Report")
        + _para(f"Hi {username},")
        + _para(
            "After careful review, our moderation team was unable to publish your fraud report "
            "at this time. This may be due to insufficient evidence, a policy consideration, "
            "or a duplicate submission."
        )
        + _ref_pill(reference_number)
        + _para(
            "If you have additional evidence or believe this decision was made in error, "
            "you may contact our support team for clarification."
        )
        + _cta_button(f"{_BASE_SITE_URL}/dashboard/", "View My Reports")
    )
    text_body = (
        f"Hi {username},\n\n"
        f"Your fraud report ({reference_number}) could not be published at this time.\n\n"
        f"View your reports at: {_BASE_SITE_URL}/dashboard/\n\n"
        f"{_DISCLAIMER}"
    )
    return subject, _html_wrapper(subject, body_html), text_body


def build_dispute_opened(reference_number: str, username: str) -> Tuple[str, str, str]:
    subject = f"Dispute Filed on Report {reference_number} | VerifyNG"
    body_html = (
        _heading("A Dispute Has Been Filed on Your Report")
        + _para(f"Hi {username},")
        + _para(
            "A dispute has been filed regarding a fraud report you submitted. "
            "Our team will review the dispute and supporting evidence from both parties."
        )
        + _ref_pill(reference_number)
        + _para(
            "No action is required from you at this stage. You will be notified "
            "once the dispute review is complete."
        )
        + _cta_button(f"{_BASE_SITE_URL}/dashboard/", "View My Reports")
    )
    text_body = (
        f"Hi {username},\n\n"
        f"A dispute has been filed on your report ({reference_number}). "
        f"Our team is reviewing it.\n\n"
        f"View your reports at: {_BASE_SITE_URL}/dashboard/\n\n"
        f"{_DISCLAIMER}"
    )
    return subject, _html_wrapper(subject, body_html), text_body


def build_dispute_resolved(
    reference_number: str,
    username: str,
    outcome: str,  # 'accepted' or 'rejected'
) -> Tuple[str, str, str]:
    outcome_label = "accepted" if outcome == "accepted" else "rejected"
    subject = f"Dispute Resolved — {reference_number} | VerifyNG"
    body_html = (
        _heading("Your Dispute Has Been Resolved")
        + _para(f"Hi {username},")
        + _para(
            f"The dispute filed on report {reference_number} has been reviewed and resolved. "
            f"The dispute was <strong>{outcome_label}</strong> by our moderation team."
        )
        + _ref_pill(reference_number)
        + _para("You can view the full details of this report and its status on your dashboard.")
        + _cta_button(f"{_BASE_SITE_URL}/dashboard/", "View Report")
    )
    text_body = (
        f"Hi {username},\n\n"
        f"The dispute on report ({reference_number}) has been resolved ({outcome_label}).\n\n"
        f"View your reports at: {_BASE_SITE_URL}/dashboard/\n\n"
        f"{_DISCLAIMER}"
    )
    return subject, _html_wrapper(subject, body_html), text_body


def build_verification_completed(reference_number: str, username: str) -> Tuple[str, str, str]:
    try:
        config = SiteConfiguration.get_solo()
        site_name = config.site_name
        site_url = config.base_url.rstrip('/')
        subject = f"Verification Completed [{reference_number}] — {site_name}"
        html_body, text_body = render_email('verification_complete', {
            'user_name': username,
            'reference_number': reference_number,
            'subject_name': 'Target Subject',
            'scope_display': 'Verification',
            'outcome_display': 'Verified Genuine',
            'outcome': 'verified',
            'summary': 'Verification request processed and completed.',
            'completed_at': timezone.now().strftime('%d %B %Y, %I:%M %p'),
            'report_url': f"{site_url}/verification/{reference_number}/report/",
            'detail_url': f"{site_url}/verification/{reference_number}/",
        })
        return subject, html_body, text_body
    except Exception:
        config = SiteConfiguration.get_solo()
        site_name = config.site_name if config else _BASE_SITE_NAME
        site_url = config.base_url.rstrip('/') if config else _BASE_SITE_URL
        subject = f"Verification Complete — {reference_number} | {site_name}"
        body_html = (
            _heading("Your Verification Request Is Complete")
            + _para(f"Hi {username},")
            + _para(
                f"Great news — your verification request has been processed and completed. "
                f"You can now view the full result and download your {site_name} Verification Report."
            )
            + _ref_pill(reference_number)
            + _cta_button(f"{site_url}/verification/{reference_number}/", "View Verification Result")
        )
        text_body = (
            f"Hi {username},\n\n"
            f"Your verification request ({reference_number}) is complete.\n\n"
            f"View your results at: {site_url}/verification/{reference_number}/\n\n"
            f"{_DISCLAIMER}"
        )
        return subject, _html_wrapper(subject, body_html), text_body


def build_verification_rejected(reference_number: str, username: str) -> Tuple[str, str, str]:
    try:
        config = SiteConfiguration.get_solo()
        site_name = config.site_name
        site_url = config.base_url.rstrip('/')
        subject = f"Update on Verification Request [{reference_number}] — {site_name}"
        html_body, text_body = render_email('verification_declined', {
            'user_name': username,
            'reference_number': reference_number,
            'subject_name': 'Target Subject',
            'scope_display': 'Verification',
            'reason': 'Supporting documentation could not be substantiated against primary records.',
            'declined_at': timezone.now().strftime('%d %B %Y, %I:%M %p'),
            'detail_url': f"{site_url}/verification/{reference_number}/",
        })
        return subject, html_body, text_body
    except Exception:
        config = SiteConfiguration.get_solo()
        site_name = config.site_name if config else _BASE_SITE_NAME
        site_url = config.base_url.rstrip('/') if config else _BASE_SITE_URL
        subject = f"Verification Update — {reference_number} | {site_name}"
        body_html = (
            _heading("Update on Your Verification Request")
            + _para(f"Hi {username},")
            + _para(
                f"Our verification team has reviewed your request and was unable to complete "
                f"the verification at this time."
            )
            + _ref_pill(reference_number)
            + _cta_button(f"{site_url}/verification/{reference_number}/", "View My Request")
        )
        text_body = (
            f"Hi {username},\n\n"
            f"Your verification request ({reference_number}) could not be completed.\n\n"
            f"View your request at: {site_url}/verification/{reference_number}/\n\n"
            f"{_DISCLAIMER}"
        )
        return subject, _html_wrapper(subject, body_html), text_body


def build_broadcast(subject_line: str, message_body: str, username: str) -> Tuple[str, str, str]:
    subject = f"{subject_line} | VerifyNG"
    body_html = (
        _heading("Message from the VerifyNG Team")
        + _para(f"Hi {username},")
        + f'<div style="color:#334155;font-size:15px;line-height:1.7;">{message_body}</div>'
        + '<p style="margin-top:20px;"></p>'
        + _cta_button(f"{_BASE_SITE_URL}/dashboard/", "Visit Dashboard")
    )
    text_body = (
        f"Hi {username},\n\n"
        f"{message_body}\n\n"
        f"Visit your dashboard: {_BASE_SITE_URL}/dashboard/\n\n"
        f"{_DISCLAIMER}"
    )
    return subject, _html_wrapper(subject, body_html), text_body
