import time
from django.test import TestCase
from django.core.cache import caches
from django.core.cache.backends.redis import RedisCache
from core.rate_limiting import _execute_redis_rate_limit, _get_raw_redis_client


class LiveRedisLuaIntegrationTestCase(TestCase):
    """
    Dedicated integration test that executes directly against the configured Redis backend.
    Tests atomic Lua counter, bucket-end PEXPIREAT, missing-TTL repair, and clamping.
    """

    def test_live_redis_lua_execution_and_expiry_guarantees(self):
        backend = caches['default']
        if not isinstance(backend, RedisCache):
            self.skipTest("Default cache backend is not RedisCache. Skipping live Redis test.")

        raw_client = _get_raw_redis_client(backend)
        test_key = backend.make_key('live_redis_test_key')

        now = time.time()
        window = 60
        bucket_end_ms = int((now + window) * 1000)
        now_ms = int(now * 1000)

        try:
            raw_client.delete(test_key)

            # 1. Normal initialization (INCR returns 1, PEXPIREAT set)
            c1 = _execute_redis_rate_limit(backend, 'live_redis_test_key', bucket_end_ms, now_ms)
            self.assertEqual(c1, 1)
            pttl1 = raw_client.pttl(test_key)
            self.assertGreater(pttl1, 0)
            self.assertLessEqual(pttl1, (window * 1000) + 50)

            # 2. Consecutive increments preserve bucket expiry
            c2 = _execute_redis_rate_limit(backend, 'live_redis_test_key', bucket_end_ms, now_ms)
            self.assertEqual(c2, 2)

            # 3. Missing-TTL repair: PERSIST key (TTL = -1) -> Lua restores PEXPIREAT
            raw_client.persist(test_key)
            self.assertEqual(raw_client.pttl(test_key), -1)
            c3 = _execute_redis_rate_limit(backend, 'live_redis_test_key', bucket_end_ms, now_ms)
            self.assertEqual(c3, 3)
            pttl3 = raw_client.pttl(test_key)
            self.assertGreater(pttl3, 0)
            self.assertLessEqual(pttl3, (window * 1000) + 50)

            # 4. Shorten later expiry: Artificially set PEXPIRE to 300 seconds -> Lua clamps to bucket_end
            raw_client.pexpire(test_key, 300000)
            self.assertGreater(raw_client.pttl(test_key), 200000)
            c4 = _execute_redis_rate_limit(backend, 'live_redis_test_key', bucket_end_ms, now_ms)
            self.assertEqual(c4, 4)
            pttl4 = raw_client.pttl(test_key)
            self.assertLessEqual(pttl4, (window * 1000) + 50)

            # 5. Boundary past: bucket_end_ms in the past returns -1
            c_past = _execute_redis_rate_limit(backend, 'live_redis_test_key', int((now - 10) * 1000), now_ms)
            self.assertEqual(c_past, -1)

        finally:
            raw_client.delete(test_key)

