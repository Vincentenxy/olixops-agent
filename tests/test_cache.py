"""Redis cache contract, including actual expiry against an opt-in local service."""

import asyncio
import os
from uuid import uuid4

import pytest

from app.core.cache import Cache


def test_disabled_cache_has_explicit_status() -> None:
    async def exercise() -> None:
        cache = Cache(None)
        assert not cache.enabled
        assert not await cache.check()
        assert await cache.get("absent") is None
        with pytest.raises(ValueError):
            await cache.set("key", "value", ttl_seconds=0)
        await cache.close()

    asyncio.run(exercise())


@pytest.mark.skipif(
    not os.environ.get("OLIXOPS_TEST_REDIS_URL"), reason="Test Redis not configured"
)
def test_redis_round_trip_namespace_expiry_and_delete() -> None:
    async def exercise() -> None:
        cache = Cache(os.environ["OLIXOPS_TEST_REDIS_URL"])
        key = f"test:{uuid4().hex}"
        try:
            assert await cache.check()
            await cache.set(key, "sample", ttl_seconds=1)
            assert await cache.get(key) == "sample"
            await asyncio.sleep(1.1)
            assert await cache.get(key) is None
            await cache.set(key, "again", ttl_seconds=60)
            await cache.delete(key)
            assert await cache.get(key) is None
        finally:
            await cache.delete(key)
            await cache.close()

    asyncio.run(exercise())
