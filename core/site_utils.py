"""
core/site_utils.py
------------------
Central dynamic site URL and domain resolution.
Ensures that all generated email buttons, QR codes, verification badges,
and dispute links dynamically resolve to:
  1. The active incoming request scheme + host (if request provided)
  2. In development (DEBUG=True) or when unconfigured: settings.SITE_BASE_URL (defaults to http://localhost:8000)
  3. Once deployed in production: the configured SiteConfiguration.base_url or environment settings.SITE_BASE_URL.

Prevents hardcoded or unresolvable placeholder domains (e.g. verifyng.com) from breaking email links.
"""

from typing import Optional


def get_dynamic_base_url(request=None) -> str:
    """
    Dynamically resolves the canonical base URL for outbound emails, dispute links,
    and system notifications without hardcoding unregistered placeholder domains.
    - If request is provided, dynamically resolves from the active request scheme and host.
    - In development (DEBUG=True), falls back to settings.SITE_BASE_URL (defaults to http://localhost:8000).
    - In production, checks SiteConfiguration.base_url (ignoring unconfigured placeholders).
    - Falls back to settings.SITE_BASE_URL.
    """
    if request is not None:
        try:
            return request.build_absolute_uri('/')[:-1].rstrip('/')
        except Exception:
            pass

    from django.conf import settings
    default_url = getattr(settings, 'SITE_BASE_URL', 'http://localhost:8000').rstrip('/')

    try:
        from core.models import SiteConfiguration
        config = SiteConfiguration.get_solo()
        url = (getattr(config, 'base_url', '') or '').rstrip('/')
        # Treat unconfigured placeholder domains as unset
        if not url or url in ('https://verifyng.com', 'http://verifyng.com', 'https://verifyng.ng', 'http://verifyng.ng'):
            return default_url
        if getattr(settings, 'DEBUG', False) and 'localhost' in default_url:
            return default_url
        return url
    except Exception:
        return default_url
