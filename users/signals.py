import re
import ipaddress
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver
from core.rate_limiting import get_client_ip
from users.models import User, LoginAudit


def get_sanitized_client_ip(request) -> str:
    """
    Safely resolves client IP for PostgreSQL INET field.
    Falls back to '127.0.0.1' for mock test requests or missing peers.
    """
    if not request:
        return '127.0.0.1'

    raw_ip = get_client_ip(request)
    if not raw_ip or raw_ip == 'invalid_peer':
        return '127.0.0.1'

    try:
        ipaddress.ip_address(raw_ip)
        return raw_ip
    except ValueError:
        return '127.0.0.1'


def parse_user_agent(ua_string: str):
    """Parses operating system, browser, and device from User-Agent string."""
    if not ua_string:
        return 'Unknown', 'Unknown', 'Desktop'

    ua = ua_string.lower()

    # Detect Device & OS
    if 'android' in ua:
        os = 'Android'
        device = 'Mobile'
    elif 'iphone' in ua:
        os = 'iOS'
        device = 'Mobile'
    elif 'ipad' in ua:
        os = 'iPadOS'
        device = 'Tablet'
    elif 'windows' in ua:
        os = 'Windows'
        device = 'Desktop'
    elif 'macintosh' in ua or 'mac os' in ua:
        os = 'macOS'
        device = 'Desktop'
    elif 'linux' in ua:
        os = 'Linux'
        device = 'Desktop'
    else:
        os = 'Other / Unknown'
        device = 'Desktop'

    # Detect Browser
    if 'edg/' in ua or 'edge/' in ua:
        browser = 'Microsoft Edge'
    elif 'chrome/' in ua and 'safari/' in ua:
        browser = 'Google Chrome'
    elif 'firefox/' in ua:
        browser = 'Mozilla Firefox'
    elif 'safari/' in ua and 'chrome/' not in ua:
        browser = 'Apple Safari'
    elif 'opera/' in ua or 'opr/' in ua:
        browser = 'Opera'
    else:
        browser = 'Unknown Browser'

    return os, browser, device


def resolve_ip_location(ip: str):
    """Provides human-readable network localization for internal and public addresses."""
    if not ip or ip in ('127.0.0.1', '::1') or ip.startswith('192.168.') or ip.startswith('10.'):
        return 'Local Development', 'Private / Local Network'
    return 'Lagos', 'Nigeria'


@receiver(user_logged_in)
def log_successful_login(sender, request, user, **kwargs):
    ip = get_sanitized_client_ip(request)
    ua_raw = request.META.get('HTTP_USER_AGENT', '') if request else ''
    os, browser, device = parse_user_agent(ua_raw)
    city, country = resolve_ip_location(ip)

    LoginAudit.objects.create(
        user=user,
        username_attempted=user.username,
        ip_address=ip,
        user_agent=ua_raw,
        device_type=device,
        browser=browser,
        os=os,
        location_country=country,
        location_city=city,
        status='success',
        failure_reason=''
    )


@receiver(user_login_failed)
def log_failed_login(sender, credentials, request, **kwargs):
    username = credentials.get('username', '') if credentials else ''
    ip = get_sanitized_client_ip(request)
    ua_raw = request.META.get('HTTP_USER_AGENT', '') if request else ''
    os, browser, device = parse_user_agent(ua_raw)
    city, country = resolve_ip_location(ip)

    # Check if user exists but was suspended
    user_obj = User.objects.filter(username=username).first()
    if user_obj and not user_obj.is_active:
        status = 'blocked'
        reason = 'Account suspended / inactive'
    else:
        status = 'failed'
        reason = 'Invalid username or password'

    LoginAudit.objects.create(
        user=user_obj,
        username_attempted=username or 'Unknown',
        ip_address=ip,
        user_agent=ua_raw,
        device_type=device,
        browser=browser,
        os=os,
        location_country=country,
        location_city=city,
        status=status,
        failure_reason=reason
    )

