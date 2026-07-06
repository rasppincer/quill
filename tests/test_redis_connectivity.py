"""Connectivity smoke-test for the Redis broker.

These tests are opt-in: they only run when QUILL_TEST_REDIS_LIVE=1 is set.
This keeps the regular test suite from hanging when REDIS_URL is present in
.env (loaded by python-dotenv at app startup) but no worker is running.

Run manually against your LAN Redis:

    QUILL_TEST_REDIS_LIVE=1 pytest tests/test_redis_connectivity.py -v
"""
import os
import pytest

_LIVE = os.environ.get("QUILL_TEST_REDIS_LIVE", "") == "1"
_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

_skip_unless_live = pytest.mark.skipif(
    not _LIVE,
    reason="Set QUILL_TEST_REDIS_LIVE=1 to run live Redis connectivity tests",
)


@_skip_unless_live
def test_redis_ping():
    """redis-py can connect and PING the configured Redis server."""
    import redis
    client = redis.from_url(_REDIS_URL, socket_connect_timeout=3)
    assert client.ping(), "Redis did not respond to PING"


@_skip_unless_live
def test_celery_broker_reachable():
    """Celery can reach the Redis broker (no workers required)."""
    import redis
    # Test the broker URL directly — this avoids the Celery inspect() call
    # which blocks until workers respond (they may not be running yet).
    client = redis.from_url(_REDIS_URL, socket_connect_timeout=3)
    assert client.ping(), f"Redis broker at {_REDIS_URL!r} did not respond to PING"
