"""
core/email_utils.py
-------------------
Central email rendering utility for VerifyNG.

Every outbound email goes through render_email() so that:
  - site_name, support_email, base_url, social links are always pulled from
    SiteConfiguration — editable in admin, zero hardcoding.
  - All emails use the shared templates/emails/ layout system.
  - Callers only provide what is specific to their individual email.

Usage
-----
    from core.email_utils import render_email
    from notifications.tasks import send_broadcast_email_task

    html, text = render_email('password_changed', {
        'user_name': 'Emeka',
        'changed_at': '11 Oct 2026, 09:14 AM',
    })
    send_broadcast_email_task.delay(
        to_email='emeka@example.com',
        subject='Your password has been changed',
        html_body=html,
        text_body=text,
    )

Adding a new email type
-----------------------
1. Add an entry to EMAIL_TEMPLATES below.
2. Create templates/emails/<your_key>.html extending emails/base_email.html.
Done — the new type is immediately available everywhere.
"""

import logging

from django.template.loader import render_to_string
from django.utils.html import strip_tags

from core.models import SiteConfiguration

logger = logging.getLogger(__name__)

# Maps logical email type → template path under templates/
EMAIL_TEMPLATES: dict[str, str] = {
    'welcome':               'emails/welcome.html',
    'otp_verification':      'emails/otp_email.html',
    'password_reset':        'emails/password_reset.html',
    'password_changed':      'emails/password_changed.html',
    'report_submitted':      'emails/report_submitted.html',
    'report_status_update':  'emails/report_status_update.html',
    'dispute_opened':        'emails/dispute_opened.html',
    'dispute_resolved':      'emails/dispute_resolved.html',
    'verification_received': 'emails/verification_received.html',
    'verification_complete': 'emails/verification_complete.html',
    'verification_declined': 'emails/verification_declined.html',
    'account_suspended':     'emails/account_suspended.html',
    'generic_notification':  'emails/generic_notification.html',
    'support_inquiry':       'emails/support_inquiry.html',
    'misconduct_receipt':    'emails/misconduct_report_receipt.html',
    'misconduct_notice':     'emails/staff_misconduct_notice.html',
}


def render_email(email_type: str, context: dict) -> tuple[str, str]:
    """
    Render an email template and return (html_body, text_body).

    SiteConfiguration fields are injected automatically so every template
    has access to {{ site_name }}, {{ support_email }}, {{ site_url }},
    {{ twitter_url }}, {{ youtube_url }}, etc. Caller-supplied context
    values take precedence.

    Args:
        email_type: Key from EMAIL_TEMPLATES.
        context:    Variables specific to this individual email.

    Returns:
        (html_body, text_body) — text_body is derived by stripping HTML.

    Raises:
        ValueError: If email_type is not in EMAIL_TEMPLATES.
    """
    if email_type not in EMAIL_TEMPLATES:
        valid = ', '.join(sorted(EMAIL_TEMPLATES))
        raise ValueError(
            f"Unknown email type '{email_type}'. Valid types: {valid}"
        )

    try:
        config = SiteConfiguration.get_solo()
    except Exception as exc:
        logger.warning("SiteConfiguration lookup failed in render_email: %s", exc)
        config = None

    site_url = (getattr(config, 'base_url', '') or 'https://verifyng.com').rstrip('/')

    # Build absolute logo URL for email clients (emails must use absolute URLs)
    logo_url = ''
    if config and config.logo:
        logo_name = config.logo.name
        if logo_name.startswith('http'):
            logo_url = logo_name
        else:
            logo_url = f"{site_url}/media/{logo_name}"

    site_context: dict = {
        'site_name':       getattr(config, 'site_name', '') or 'VerifyNG',
        'site_tagline':    getattr(config, 'site_tagline', '') or 'Public Trust & Verification Platform',
        'site_url':        site_url,
        'logo_url':        logo_url,
        'support_email':   getattr(config, 'support_email', '') or 'support@verifyng.com',
        'company_address': getattr(config, 'company_address', '') or '',
        'company_reg':     getattr(config, 'company_reg_number', '') or '',
        'twitter_url':     getattr(config, 'twitter_url', '') or '',
        'facebook_url':    getattr(config, 'facebook_url', '') or '',
        'instagram_url':   getattr(config, 'instagram_url', '') or '',
        'linkedin_url':    getattr(config, 'linkedin_url', '') or '',
        'youtube_url':     getattr(config, 'youtube_url', '') or '',
        'whatsapp_number': getattr(config, 'whatsapp_number', '') or '',
    }

    full_context = {**site_context, **context}

    template_path = EMAIL_TEMPLATES[email_type]
    html_body = render_to_string(template_path, full_context)
    text_body = strip_tags(html_body).strip()

    logger.debug(
        "render_email: type=%s template=%s context_keys=%s",
        email_type,
        template_path,
        list(context.keys()),
    )

    return html_body, text_body
