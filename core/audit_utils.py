
# core/audit_utils.py
"""
Single entry point for writing to the platform-wide AuditLog.
Import and call this from any view, service, or task.
"""
from __future__ import annotations

import logging
from django.utils import timezone
from reports.models import AuditLog
from core.rate_limiting import get_client_ip
from users.signals import resolve_ip_location, get_sanitized_client_ip

logger = logging.getLogger(__name__)


def _parse_user_agent(ua_string: str) -> dict:
    """
    Basic user-agent parsing without an external library.
    Returns device_type, browser, os.
    """
    ua = ua_string.lower()

    # Device
    if 'mobile' in ua or 'android' in ua:
        device_type = 'Mobile'
    elif 'tablet' in ua or 'ipad' in ua:
        device_type = 'Tablet'
    else:
        device_type = 'Desktop'

    # Browser
    if 'edg/' in ua or 'edge/' in ua:
        browser = 'Edge'
    elif 'opr/' in ua or 'opera' in ua:
        browser = 'Opera'
    elif 'chrome/' in ua and 'safari/' in ua:
        browser = 'Chrome'
    elif 'firefox/' in ua:
        browser = 'Firefox'
    elif 'safari/' in ua and 'chrome/' not in ua:
        browser = 'Safari'
    else:
        browser = 'Unknown'

    # OS
    if 'windows' in ua:
        os_name = 'Windows'
    elif 'mac os' in ua or 'macos' in ua:
        os_name = 'macOS'
    elif 'android' in ua:
        os_name = 'Android'
    elif 'iphone' in ua or 'ipad' in ua or 'ios' in ua:
        os_name = 'iOS'
    elif 'linux' in ua:
        os_name = 'Linux'
    else:
        os_name = 'Unknown'

    return {'device_type': device_type, 'browser': browser, 'os': os_name}


def log_admin_action(
    *,
    action: str,
    action_type: str = 'ADMIN',
    performed_by=None,
    target_user=None,
    report=None,
    request=None,
    details: dict | None = None,
    description: str = '',
    **extra,
) -> None:
    """
    Write a single immutable row to AuditLog.

    Usage:
        from core.audit_utils import log_admin_action
        log_admin_action(
            action='USER_SUSPENDED',
            action_type='USER_MGMT',
            performed_by=request.user,
            target_user=user,
            request=request,
            details={'reason': 'Terms violation'},
        )
    """
    try:
        ip_address = None
        url_path = ''
        http_method = ''
        user_agent = ''
        device_type = 'Desktop'
        browser = 'Unknown'
        os_name = 'Unknown'
        location_country = ''
        location_city = ''

        if request is not None:
            ip_address = get_sanitized_client_ip(request)
            url_path = request.path[:500]
            http_method = request.method
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:1000]
            parsed = _parse_user_agent(user_agent)
            device_type = parsed.get('device_type', 'Desktop')
            browser = parsed.get('browser', 'Unknown')
            os_name = parsed.get('os', 'Unknown')
            location_city, location_country = resolve_ip_location(ip_address)

        merged_details = dict(details or {})
        if description and 'description' not in merged_details:
            merged_details['description'] = description
        for k, v in extra.items():
            if k not in merged_details and k not in ('admin_user', 'ip_address'):
                merged_details[k] = str(v)

        actor = performed_by or extra.get('admin_user')

        AuditLog.objects.create(
            action=action,
            action_type=action_type,
            performed_by=actor,
            target_user=target_user,
            report=report,
            ip_address=ip_address or extra.get('ip_address'),
            url_path=url_path,
            http_method=http_method,
            user_agent=user_agent,
            device_type=device_type,
            browser=browser,
            os=os_name,
            location_country=location_country,
            location_city=location_city,
            details=merged_details,
        )
    except Exception:
        # Audit logging must never crash the main request
        logger.exception("Failed to write AuditLog entry for action=%s", action)

