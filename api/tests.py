import json
from django.test import TestCase, override_settings
from django.core.cache import caches
from identities.models import SubjectEntity, Identifier
from reports.models import FraudReport


@override_settings(CACHES={
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'api-locmem-test',
        'KEY_PREFIX': 'verifyng_api_test',
    }
})
class RateLimitingEndpointRegressionTestCase(TestCase):
    def setUp(self):
        caches['default'].clear()
        self.subject = SubjectEntity.objects.create(type='person', name='Lookup Target')
        self.identifier = Identifier.objects.create(
            subject=self.subject,
            type='phone',
            value_hash='hash_abc123'
        )

    def test_api_check_success_and_rate_limit_429(self):
        url = '/api/v1/check/hash_abc123'

        # Requests under limit return 200 with CheckResponse schema
        with override_settings(PUBLIC_CHECK_RATE_LIMIT=3, PUBLIC_CHECK_RATE_LIMIT_WINDOW=60):
            for _ in range(3):
                res = self.client.get(url, REMOTE_ADDR='198.51.100.5')
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertEqual(data['subject_name'], 'Lookup Target')
                self.assertEqual(data['entity_type'], 'person')

            # 4th request exceeds limit: returns HTTP 429
            res4 = self.client.get(url, REMOTE_ADDR='198.51.100.5')
            self.assertEqual(res4.status_code, 429)
            self.assertEqual(res4['Content-Type'], 'application/json')
            self.assertIn('Retry-After', res4.headers)
            self.assertGreater(int(res4.headers['Retry-After']), 0)
            self.assertEqual(res4.json(), {"detail": "Rate limit exceeded. Please wait before retrying."})

    def test_web_check_view_rate_limit_429(self):
        url = '/check/'
        with override_settings(PUBLIC_CHECK_RATE_LIMIT=2, PUBLIC_CHECK_RATE_LIMIT_WINDOW=60):
            res1 = self.client.get(url, REMOTE_ADDR='198.51.100.6')
            self.assertEqual(res1.status_code, 200)

            res2 = self.client.get(url, REMOTE_ADDR='198.51.100.6')
            self.assertEqual(res2.status_code, 200)

            res3 = self.client.get(url, REMOTE_ADDR='198.51.100.6')
            self.assertEqual(res3.status_code, 429)
            self.assertIn('Retry-After', res3.headers)
            self.assertGreater(int(res3.headers['Retry-After']), 0)

    @override_settings(IDENTIFIER_HASH_PEPPER="test-api-pepper")
    def test_post_check_lookup_raw_phone_success(self):
        from identities.utils import hash_identifier_value
        phone_hash = hash_identifier_value('phone', '08099887766')
        Identifier.objects.create(
            subject=self.subject,
            type='phone',
            value_hash=phone_hash
        )

        res = self.client.post(
            '/api/v1/check/lookup',
            data=json.dumps({
                'identifier_type': 'phone',
                'identifier_value': '08099887766'
            }),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['subject_name'], 'Lookup Target')
        self.assertEqual(data['entity_type'], 'person')
        self.assertFalse(data['is_verified'])
        self.assertFalse(data['has_active_flags'])
        self.assertIn('allegation_notice', data)
        # Ensure zero raw identifier or PII is returned
        self.assertNotIn('08099887766', str(data))

    def test_post_check_lookup_invalid_format_returns_400(self):
        res = self.client.post(
            '/api/v1/check/lookup',
            data=json.dumps({
                'identifier_type': 'phone',
                'identifier_value': 'invalid-phone-string'
            }),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn('detail', res.json())

    def test_check_missing_record_returns_404(self):
        res = self.client.get('/api/v1/check/non_existent_hash_999')
        self.assertEqual(res.status_code, 404)

