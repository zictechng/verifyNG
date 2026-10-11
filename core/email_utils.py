"""
core/email_utils.py
-------------------
Reusable email rendering utility for VerifyNG.

Every outbound email must go through render_email() so that:
  - site_name, support_email, social links, base_url always come from
    SiteConfiguration (admin-editable, no hardcoding).
  - Emails are rendered from Django templates (templates/emails/).
  - The caller only supplies what is specific to this individual email.

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
        subject=f'Your password has been changed',
        html_body=html,
        text_body=text,
    )

Email type registry
-------------------
Each key maps to a template at templates/emails/<key>.html.
Add a new entry here and create the matching template to add a new email type.
"""

import logging
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from core.models import SiteConfiguration

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry — maps logical email type → template path
# ---------------------------------------------------------------------------
EMAIL_TEMPLATES: dict[str, str] = {
    'welcome':               'emails/welcome.html',
    'otp_verification':      'emails/otp_email.html',
    'password_reset':        'emails/password_reset.html',
    'password_changed':      'emails/password_changed.html',
    'report_submitted':      'emails/report_submitted.html',
    'report_status_update':  'emails/report_status_update.html',
    'verification_complete': 'emails/verification_complete.html',
    'account_suspended':     'emails/account_suspended.html',
    'generic_notification':  'emails/generic_notification.html',
}


def render_email(email_type: str, context: dict) -> tuple[str, str]:
    """
    Renders an email template and returns (html_body, text_body).

    Automatically merges SiteConfiguration fields into the template context
    so every template can use {{ site_name }}, {{ support_email }},
    {{ base_url }}, {{ twitter_url }}, etc. without the caller providing them.

    Caller-supplied context values override the defaults (e.g. you can pass
    a custom site_name for a white-label build).

    Args:
        email_type:  Key from EMAIL_TEMPLATES registry.
        context:     Template variables specific to this particular email.

    Returns:
        Tuple of (html_body: str, text_body: str).
        text_body is derived by stripping HTML tags from html_body.

    Raises:
        ValueError: If email_type is not registered in EMAIL_TEMPLATES.
    """
    if email_type not in EMAIL_TEMPLATES:
        valid = ', '.join(sorted(EMAIL_TEMPLATES))
        raise ValueError(
            f"Unknown email type '{email_type}'. Valid types: {valid}"
        )

    config = SiteConfiguration.get_solo()

    # Site-wide defaults injected into every email template
    site_context: dict = {
        'site_name':         config.site_name,
        'site_tagline':      config.site_tagline,
        'site_url':          config.base_url,
        'support_email':     config.support_email,
        'company_address':   config.company_address,
        'company_reg':       config.company_reg_number,
        'twitter_url':       config.twitter_url,
        'facebook_url':      config.facebook_url,
        'instagram_url':     config.instagram_url,
        'linkedin_url':      config.linkedin_url,
        'youtube_url':      config.youtube_url,
        'whatsapp_number':   config.whatsapp_number,
    }

    # Caller context takes precedence over site defaults
    full_context = {**site_context, **context}

    template_path = EMAIL_TEMPLATES[email_type]
    html_body = render_to_string(template_path, full_context)
    text_body = strip_tags(html_body).strip()

    logger.debug(
        "render_email: type=%s template=%s recipients context keys=%s",
        email_type,
        template_path,
        list(context.keys()),
    )

    return html_body, text_body

