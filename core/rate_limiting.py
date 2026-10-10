import time
import math
import threading
import logging
import ipaddress
from socket import timeout as SocketTimeout
from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends.redis import RedisCache
from django.core.cache.backends.locmem import LocMemCache
from django.core.exceptions import ImproperlyConfigured
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
    BusyLoadingError,
)

logger = logging.getLogger(__name__)

# Explicitly identified connectivity-related failures
CACHE_CONNECTIVITY_ERRORS = (
    RedisConnectionError,
    RedisTimeoutError,
    BusyLoadingError,
    SocketTimeout,
    ConnectionRefusedError,
    ConnectionResetError,
)

# Thread-safe log throttling state
_log_lock = threading.Lock()
_last_redis_warning_time = 0.0
REDIS_LOG_BACKOFF_SECONDS = 60.0

LUA_RATE_LIMIT_SCRIPT = """
local bucket_end = tonumber(ARGV[1])
local now_ms = tonumber(ARGV[2])

if bucket_end <= now_ms then
    return -1
end

local current = redis.call('INCR', KEYS[1])
local pttl = redis.call('PTTL', KEYS[1])

if current == 1 or pttl == -1 or pttl > (bucket_end - now_ms) then
    redis.call('PEXPIREAT', KEYS[1], bucket_end)
end

return current
"""


def validate_positive_int(val, name: str) -> int:
    """Validates that a value is strictly a positive integer and not a boolean."""
    if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
        raise ImproperlyConfigured(f"{name} must be a positive integer, not a boolean or non-integer.")
    return val


def _get_raw_redis_client(backend):
    """
    Retrieve the raw redis.Redis client instance from Django's cache backend.
    Django 5.x native RedisCache holds the client on backend._cache.
    """
    if hasattr(backend, '_cache') and hasattr(backend._cache, 'get_client'):
        return backend._cache.get_client()
    if hasattr(backend, 'client') and hasattr(backend.client, 'get_client'):
        return backend.client.get_client()
    if hasattr(backend, '_client'):
        return backend._client
    raise AttributeError(f"Unable to access raw Redis client from cache backend '{type(backend).__name__}'.")


def get_client_ip(request) -> str:
    """
    Safely resolves the client IP address.
    - If SECURE_PROXY_TRUSTED_IPS is empty, strictly uses REMOTE_ADDR.
    - If REMOTE_ADDR matches a configured trusted proxy, walks X-Forwarded-For right-to-left.
    - Halts on malformed entries and returns the last validated proxy IP.
    """
    raw_remote = request.META.get('REMOTE_ADDR', '')

    def parse_ip(ip_str):
        if not ip_str:
            return None
        try:
            return ipaddress.ip_address(ip_str.strip())
        except ValueError:
            return None

    remote_ip = parse_ip(raw_remote)
    if not remote_ip:
        return 'invalid_peer'

    trusted_configs = getattr(settings, 'SECURE_PROXY_TRUSTED_IPS', [])
    trusted_set = set()
    for entry in trusted_configs:
        parsed = parse_ip(entry)
        if parsed:
            trusted_set.add(parsed)

    if not trusted_set or remote_ip not in trusted_set:
        return str(remote_ip)

    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if not x_forwarded_for:
        return str(remote_ip)

    forwarded_parts = [p.strip() for p in x_forwarded_for.split(',') if p.strip()]
    selected_ip = remote_ip

    for candidate in reversed(forwarded_parts):
        parsed_candidate = parse_ip(candidate)
        if not parsed_candidate:
            # Malformed entry encountered: halt traversal immediately
            break
        if parsed_candidate not in trusted_set:
            return str(parsed_candidate)
        selected_ip = parsed_candidate

    return str(selected_ip)


def _execute_redis_rate_limit(backend, raw_key: str, bucket_end_ms: int, now_ms: int = None) -> int:
    """Executes atomic Lua script on genuine Redis backend using prefixed key."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    prefixed_key = backend.make_key(raw_key)
    raw_client = _get_raw_redis_client(backend)
    count = raw_client.eval(LUA_RATE_LIMIT_SCRIPT, 1, prefixed_key, bucket_end_ms, now_ms)
    return int(count)


def _execute_test_locmem_rate_limit(backend, raw_key: str, time_left: int) -> int:
    """
    TEST-ONLY fallback for LocMemCache in unit test suites.
    Note: Does not provide cross-process concurrency guarantees.
    """
    added = backend.add(raw_key, 1, timeout=time_left)
    if added:
        return 1
    return backend.incr(raw_key)


def check_rate_limit(request, namespace: str, limit: int = None, window: int = None):
    """
    Fixed-window bucket rate limiter with atomic increments.
    Returns: (is_limited: bool, retry_after: int)
    Fails open with throttled logging on explicit Redis connectivity outages.
    """
    global _last_redis_warning_time

    if limit is None:
        limit = getattr(settings, 'PUBLIC_CHECK_RATE_LIMIT', 30)
    if window is None:
        window = getattr(settings, 'PUBLIC_CHECK_RATE_LIMIT_WINDOW', 60)

    limit = validate_positive_int(limit, 'Rate limit')
    window = validate_positive_int(window, 'Rate limit window')

    client_ip = get_client_ip(request)

    backend = caches['default']

    if not isinstance(backend, (RedisCache, LocMemCache)):
        raise ImproperlyConfigured(
            f"Unsupported cache backend for rate limiting: '{backend.__class__.__name__}'. "
            "Only RedisCache and LocMemCache are supported."
        )

    max_attempts = 2
    for attempt in range(max_attempts):
        now = time.time()
        bucket = int(now // window)
        time_left = max(1, int(math.ceil(((bucket + 1) * window) - now)))
        bucket_end_ms = int(((bucket + 1) * window) * 1000)
        now_ms = int(now * 1000)
        raw_key = f"rl:{namespace}:{client_ip}:{bucket}"

        try:
            if isinstance(backend, RedisCache):
                count = _execute_redis_rate_limit(backend, raw_key, bucket_end_ms, now_ms)
                if count == -1:
                    # Request crossed boundary between time calculation and Lua execution
                    if attempt < max_attempts - 1:
                        continue
                    count = 1
            else:
                count = _execute_test_locmem_rate_limit(backend, raw_key, time_left)

            if count > limit:
                return True, time_left
            return False, 0

        except CACHE_CONNECTIVITY_ERRORS as e:
            with _log_lock:
                current_time = time.time()
                if (current_time - _last_redis_warning_time) > REDIS_LOG_BACKOFF_SECONDS:
                    _last_redis_warning_time = current_time
                    logger.warning(
                        "Rate limiter cache unavailable (Error: %s). Temporarily bypassing rate limits for namespace '%s'.",
                        type(e).__name__, namespace
                    )
            # Fail open: permit request through during cache outage
            return False, 0

    return False, 0

