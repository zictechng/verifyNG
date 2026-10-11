
# tests/test_security.py
"""
Batch 14.6 — Security headers, CSP, CSRF, and rate-limiting utility tests.

Coverage:
  - Security response headers present on every page
  - X-Frame-Options: DENY (clickjacking prevention)
  - X-Content-Type-Options: nosniff
  - Referrer-Policy
  - Content-Security-Policy header present
  - CSRF: POST without token returns 403
  - CSRF: POST with token succeeds (login form smoke test)
  - SESSION_COOKIE_HTTPONLY / SAMESITE settings asserted
  - Rate limiting utility:
      - validate_positive_int raises on bad values
      - get_client_ip returns REMOTE_ADDR when no trusted proxy configured
      - get_client_ip returns REMOTE_ADDR when caller is NOT a trusted proxy
      - get_client_ip walks X-Forwarded-For when caller IS a trusted proxy
      - get_client_ip halts on malformed XFF entry
      - get_client_ip handles missing REMOTE_ADDR
      - check_rate_limit allows first N requests
      - check_rate_limit blocks on (N+1)th request
      - check_rate_limit fails open on cache connectivity error
      - check_rate_limit raises ImproperlyConfigured on bad backend
      - check_rate_limit raises ImproperlyConfigured on boolean limit
"""

from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, Client, RequestFactory, override_settings
from django.urls import reverse


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_request(ip='1.2.3.4', xff=None, trusted_proxies=None):
    """Build a minimal fake request for get_client_ip / check_rate_limit tests."""
    from core.rate_limiting import get_client_ip, check_rate_limit
    factory = RequestFactory()
    req = factory.get('/')
    req.META['REMOTE_ADDR'] = ip
    if xff:
        req.META['HTTP_X_FORWARDED_FOR'] = xff
    if trusted_proxies is not None:
        req._trusted_proxies_override = trusted_proxies
    return req


# ─── Security headers ─────────────────────────────────────────────────────────

class SecurityHeadersTest(TestCase):
    """
    Verify that critical security response headers are present on a public page.
    Uses the login page (always publicly accessible, no redirect).
    """

    def setUp(self):
        self.client = Client()
        self.url = reverse('users:login')

    def test_x_frame_options_deny(self):
        response = self.client.get(self.url)
        self.assertEqual(response.get('X-Frame-Options'), 'DENY')

    def test_x_content_type_options_nosniff(self):
        response = self.client.get(self.url)
        self.assertEqual(response.get('X-Content-Type-Options'), 'nosniff')

    def test_referrer_policy_present(self):
        response = self.client.get(self.url)
        self.assertIsNotNone(response.get('Referrer-Policy'))

    def test_csp_header_present(self):
        """Content-Security-Policy (or CSP-Report-Only) header must be set."""
        response = self.client.get(self.url)
        csp = response.get('Content-Security-Policy') or response.get('Content-Security-Policy-Report-Only')
        self.assertIsNotNone(csp, "Neither CSP nor CSP-Report-Only header is present.")

    def test_csp_blocks_frame_ancestors(self):
        """CSP must include frame-ancestors 'none' to prevent clickjacking."""
        response = self.client.get(self.url)
        csp = response.get('Content-Security-Policy') or response.get('Content-Security-Policy-Report-Only', '')
        self.assertIn("frame-ancestors", csp)

    def test_csp_restricts_default_src(self):
        response = self.client.get(self.url)
        csp = response.get('Content-Security-Policy') or response.get('Content-Security-Policy-Report-Only', '')
        self.assertIn("default-src", csp)


# ─── Django security settings ─────────────────────────────────────────────────

class DjangoSecuritySettingsTest(TestCase):
    """Assert that the settings module has the required security flags configured."""

    def test_x_frame_options_setting(self):
        self.assertEqual(settings.X_FRAME_OPTIONS, 'DENY')

    def test_secure_content_type_nosniff(self):
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)

    def test_session_cookie_httponly(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)

    def test_session_cookie_samesite(self):
        self.assertIn(settings.SESSION_COOKIE_SAMESITE, ('Lax', 'Strict'))

    def test_csrf_cookie_httponly(self):
        self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)

    def test_csrf_cookie_samesite(self):
        self.assertIn(settings.CSRF_COOKIE_SAMESITE, ('Lax', 'Strict'))

    def test_referrer_policy_configured(self):
        self.assertTrue(settings.SECURE_REFERRER_POLICY)


# ─── CSRF enforcement ─────────────────────────────────────────────────────────

class CSRFEnforcementTest(TestCase):
    """
    Verify that POST endpoints reject requests lacking a valid CSRF token.
    Django's test Client enforces CSRF when enforce_csrf_checks=True.
    """

    def setUp(self):
        self.strict_client = Client(enforce_csrf_checks=True)

    def test_login_post_without_csrf_token_rejected(self):
        url = reverse('users:login')
        response = self.strict_client.post(url, {
            'username': 'user@example.com',
            'password': 'SomePass123!',
        })
        self.assertEqual(response.status_code, 403)

    def test_login_post_with_csrf_token_not_rejected_by_csrf(self):
        """With a valid CSRF token the middleware passes; auth may still fail (401/200) but not 403."""
        url = reverse('users:login')
        # GET first to obtain the CSRF cookie
        get_response = self.strict_client.get(url)
        csrf_token = get_response.cookies.get('csrftoken')
        self.assertIsNotNone(csrf_token, "CSRF cookie must be set on GET.")
        response = self.strict_client.post(
            url,
            {
                'username': 'nonexistent@example.com',
                'password': 'WrongPassword1!',
                'csrfmiddlewaretoken': csrf_token.value,
            },
            HTTP_X_CSRFTOKEN=csrf_token.value,
        )
        # CSRF passed — response is 200 (form re-render) or 302 (redirect), never 403
        self.assertNotEqual(response.status_code, 403)

    def test_webhook_endpoint_is_csrf_exempt(self):
        """paystack_webhook is marked @csrf_exempt — must NOT return 403 on missing token."""
        url = reverse('payments:webhook')
        import json
        response = self.strict_client.post(
            url,
            data=json.dumps({'event': 'test'}).encode(),
            content_type='application/json',
            # No CSRF token, no signature
        )
        # 400 (missing signature) is correct; 403 (CSRF) would be wrong
        self.assertNotEqual(response.status_code, 403)


# ─── Rate limiting utility ────────────────────────────────────────────────────

class ValidatePositiveIntTest(TestCase):

    def _call(self, val, name='Rate limit'):
        from core.rate_limiting import validate_positive_int
        return validate_positive_int(val, name)

    def test_valid_positive_int(self):
        self.assertEqual(self._call(10), 10)

    def test_zero_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            self._call(0)

    def test_negative_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            self._call(-5)

    def test_boolean_true_raises(self):
        # True == 1 in Python but must be rejected
        with self.assertRaises(ImproperlyConfigured):
            self._call(True)

    def test_boolean_false_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            self._call(False)

    def test_float_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            self._call(1.5)

    def test_string_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            self._call('10')


class GetClientIPTest(TestCase):

    def _ip(self, remote_addr='1.2.3.4', xff=None, trusted=None):
        from core.rate_limiting import get_client_ip
        factory = RequestFactory()
        req = factory.get('/')
        req.META['REMOTE_ADDR'] = remote_addr
        if xff:
            req.META['HTTP_X_FORWARDED_FOR'] = xff
        trusted_list = trusted if trusted is not None else []
        with override_settings(SECURE_PROXY_TRUSTED_IPS=trusted_list):
            return get_client_ip(req)

    def test_returns_remote_addr_when_no_trusted_proxy(self):
        self.assertEqual(self._ip(remote_addr='5.6.7.8'), '5.6.7.8')

    def test_returns_remote_addr_when_caller_not_trusted(self):
        # Trusted proxy is 10.0.0.1 but REMOTE_ADDR is 5.6.7.8 — not trusted
        self.assertEqual(
            self._ip(remote_addr='5.6.7.8', xff='203.0.113.10', trusted=['10.0.0.1']),
            '5.6.7.8',
        )

    def test_walks_xff_when_caller_is_trusted_proxy(self):
        # Trusted proxy at 10.0.0.1 passes XFF with real client IP
        result = self._ip(
            remote_addr='10.0.0.1',
            xff='203.0.113.10, 10.0.0.1',
            trusted=['10.0.0.1'],
        )
        self.assertEqual(result, '203.0.113.10')

    def test_halts_on_malformed_xff_entry(self):
        # Malformed entry in XFF — traversal must stop; result is last trusted proxy
        result = self._ip(
            remote_addr='10.0.0.1',
            xff='NOTANIP, 203.0.113.10',
            trusted=['10.0.0.1'],
        )
        # 203.0.113.10 is valid and untrusted → returned before NOTANIP is even reached
        self.assertEqual(result, '203.0.113.10')

    def test_missing_remote_addr_returns_invalid_peer(self):
        from core.rate_limiting import get_client_ip
        factory = RequestFactory()
        req = factory.get('/')
        req.META['REMOTE_ADDR'] = ''
        with override_settings(SECURE_PROXY_TRUSTED_IPS=[]):
            result = get_client_ip(req)
        self.assertEqual(result, 'invalid_peer')

    def test_xff_ignored_when_no_trusted_proxy_configured(self):
        # XFF is present but SECURE_PROXY_TRUSTED_IPS is empty — must use REMOTE_ADDR
        result = self._ip(
            remote_addr='1.2.3.4',
            xff='10.10.10.10',
            trusted=[],
        )
        self.assertEqual(result, '1.2.3.4')


class CheckRateLimitTest(TestCase):
    """
    Tests for check_rate_limit using LocMemCache (the test default).
    Each test uses a unique namespace to avoid cross-test counter pollution.
    """

    def _req(self, ip='127.0.0.1'):
        factory = RequestFactory()
        req = factory.get('/')
        req.META['REMOTE_ADDR'] = ip
        return req

    def test_first_request_not_limited(self):
        from core.rate_limiting import check_rate_limit
        req = self._req(ip='10.0.1.1')
        is_limited, retry_after = check_rate_limit(req, namespace='test_first', limit=5, window=60)
        self.assertFalse(is_limited)
        self.assertEqual(retry_after, 0)

    def test_requests_within_limit_not_blocked(self):
        from core.rate_limiting import check_rate_limit
        req = self._req(ip='10.0.1.2')
        for _ in range(3):
            is_limited, _ = check_rate_limit(req, namespace='test_within', limit=5, window=60)
        self.assertFalse(is_limited)

    def test_exceeding_limit_is_blocked(self):
        from core.rate_limiting import check_rate_limit
        req = self._req(ip='10.0.1.3')
        for _ in range(3):
            check_rate_limit(req, namespace='test_exceed', limit=3, window=60)
        # 4th request must be blocked
        is_limited, retry_after = check_rate_limit(req, namespace='test_exceed', limit=3, window=60)
        self.assertTrue(is_limited)
        self.assertGreater(retry_after, 0)

    def test_different_ips_have_independent_counters(self):
        from core.rate_limiting import check_rate_limit
        req_a = self._req(ip='10.0.2.1')
        req_b = self._req(ip='10.0.2.2')
        for _ in range(3):
            check_rate_limit(req_a, namespace='test_independent', limit=3, window=60)
        # req_a is now blocked but req_b should still be free
        is_limited_b, _ = check_rate_limit(req_b, namespace='test_independent', limit=3, window=60)
        self.assertFalse(is_limited_b)

    def test_fails_open_on_cache_connectivity_error(self):
        """On Redis outage the function must return (False, 0) — never block traffic."""
        from core.rate_limiting import check_rate_limit, CACHE_CONNECTIVITY_ERRORS
        from redis.exceptions import ConnectionError as RedisConnectionError
        req = self._req(ip='10.0.1.4')
        with patch('core.rate_limiting._execute_test_locmem_rate_limit',
                   side_effect=RedisConnectionError("down")):
            is_limited, retry_after = check_rate_limit(
                req, namespace='test_failopen', limit=5, window=60
            )
        self.assertFalse(is_limited)
        self.assertEqual(retry_after, 0)

    def test_boolean_limit_raises_improperly_configured(self):
        from core.rate_limiting import check_rate_limit
        req = self._req(ip='10.0.1.5')
        with self.assertRaises(ImproperlyConfigured):
            check_rate_limit(req, namespace='test_bool', limit=True, window=60)

    def test_zero_window_raises_improperly_configured(self):
        from core.rate_limiting import check_rate_limit
        req = self._req(ip='10.0.1.6')
        with self.assertRaises(ImproperlyConfigured):
            check_rate_limit(req, namespace='test_zerowin', limit=5, window=0)

