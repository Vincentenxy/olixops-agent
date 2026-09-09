"""One shared Redis connection pool with application-scoped keys and explicit TTLs."""

from redis.asyncio import Redis
from redis.exceptions import RedisError


class Cache:
    def __init__(self, url: str | None) -> None:
        self.client = (
            Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                max_connections=20,
            )
            if url
            else None
        )

    @property
    def enabled(self) -> bool:
        return self.client is not None

    async def check(self) -> bool:
        if self.client is None:
            return False
        try:
            return bool(await self.client.ping())
        except RedisError, OSError, TimeoutError:
            return False

    @staticmethod
    def _key(key: str) -> str:
        if not key or len(key) > 256:
            raise ValueError("Cache keys must contain 1 to 256 characters")
        return f"olixops:{key}"

    async def get(self, key: str) -> str | None:
        if self.client is None:
            return None
        value = await self.client.get(self._key(key))
        return value if isinstance(value, str) else None

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        if ttl_seconds < 1:
            raise ValueError("Cache writes require a positive TTL")
        if self.client is not None:
            await self.client.set(self._key(key), value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        if self.client is not None:
            await self.client.delete(self._key(key))

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
