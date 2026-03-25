"""Redis-backed market data cache with TTL-based expiration."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from packages.core.models import Market, NormalizedSignal

logger = logging.getLogger(__name__)

# Default TTL in seconds for cached market data.
_DEFAULT_TTL: int = 300  # 5 minutes


class MarketDataCache:
    """Thin async wrapper around Redis for real-time market data caching.

    All values are serialised to JSON.  Keys follow the convention::

        marketdata:{namespace}:{key}

    so that the cache can be shared with other Redis users without
    collisions.

    Parameters
    ----------
    redis_url:
        Redis connection string (e.g. ``redis://localhost:6379/0``).
    namespace:
        Key prefix added after ``marketdata:``.  Useful for separating
        environments (``prod``, ``paper``, ``test``).
    default_ttl:
        Default time-to-live in seconds for cached entries.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        *,
        namespace: str = "default",
        default_ttl: int = _DEFAULT_TTL,
    ) -> None:
        self._redis_url = redis_url
        self._namespace = namespace
        self._default_ttl = default_ttl
        self._redis: Any = None  # redis.asyncio.Redis instance (lazy)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Establish the connection pool to Redis."""
        if self._redis is not None:
            return

        try:
            import redis.asyncio as aioredis
        except ImportError as exc:
            raise ImportError(
                "The 'redis' package with async support is required. "
                "Install it with: pip install redis[hiredis]"
            ) from exc

        self._redis = aioredis.from_url(
            self._redis_url,
            decode_responses=True,
        )
        logger.info("MarketDataCache connected to %s (ns=%s)", self._redis_url, self._namespace)

    async def disconnect(self) -> None:
        """Close the Redis connection pool."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
            logger.info("MarketDataCache disconnected")

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    async def set(
        self,
        key: str,
        data: Any,
        ttl: Optional[int] = None,
    ) -> None:
        """Store *data* under *key* with an optional TTL override.

        Parameters
        ----------
        key:
            Cache key (the namespace prefix is added automatically).
        data:
            Any JSON-serialisable value, or a Pydantic ``BaseModel`` instance.
        ttl:
            Time-to-live in seconds.  Falls back to the default TTL
            configured at construction time.
        """
        redis = self._get_redis()
        full_key = self._full_key(key)
        payload = self._serialize(data)
        effective_ttl = ttl if ttl is not None else self._default_ttl

        await redis.set(full_key, payload, ex=effective_ttl)
        logger.debug("CACHE SET %s  ttl=%ds", full_key, effective_ttl)

    async def get(self, key: str) -> Optional[Any]:
        """Retrieve the value stored under *key*.

        Returns ``None`` if the key does not exist or has expired.
        """
        redis = self._get_redis()
        full_key = self._full_key(key)
        raw = await redis.get(full_key)
        if raw is None:
            logger.debug("CACHE MISS %s", full_key)
            return None
        logger.debug("CACHE HIT  %s", full_key)
        return self._deserialize(raw)

    async def get_latest_signals(
        self,
        market: Market,
        asset: str,
    ) -> list[NormalizedSignal]:
        """Return cached ``NormalizedSignal`` objects for *market* / *asset*.

        The signals are stored as a JSON list under the key
        ``signals:{market}:{asset}``.
        """
        key = f"signals:{market.value}:{asset}"
        data = await self.get(key)
        if data is None:
            return []

        signals: list[NormalizedSignal] = []
        items = data if isinstance(data, list) else [data]
        for item in items:
            try:
                if isinstance(item, dict):
                    signals.append(NormalizedSignal.model_validate(item))
                elif isinstance(item, str):
                    signals.append(NormalizedSignal.model_validate_json(item))
            except Exception:  # noqa: BLE001
                logger.warning("Skipping un-parseable cached signal for %s:%s", market.value, asset)
        return signals

    async def set_latest_signals(
        self,
        market: Market,
        asset: str,
        signals: list[NormalizedSignal],
        ttl: Optional[int] = None,
    ) -> None:
        """Cache a list of ``NormalizedSignal`` for *market* / *asset*.

        Convenience wrapper that serialises via Pydantic and stores under a
        well-known key pattern.
        """
        key = f"signals:{market.value}:{asset}"
        payload = [s.model_dump(mode="json") for s in signals]
        await self.set(key, payload, ttl=ttl)

    async def invalidate(self, key: str) -> bool:
        """Delete *key* from the cache.

        Returns ``True`` if the key existed and was removed.
        """
        redis = self._get_redis()
        full_key = self._full_key(key)
        removed = await redis.delete(full_key)
        logger.debug("CACHE DEL  %s  removed=%d", full_key, removed)
        return removed > 0

    # ------------------------------------------------------------------
    # Bulk helpers
    # ------------------------------------------------------------------

    async def invalidate_pattern(self, pattern: str) -> int:
        """Delete all keys matching a glob *pattern* (within the namespace).

        Returns the number of keys deleted.

        .. warning:: Uses ``SCAN`` under the hood so it is safe for
           production but may take a few round-trips on large key spaces.
        """
        redis = self._get_redis()
        full_pattern = self._full_key(pattern)
        deleted = 0
        async for key in redis.scan_iter(match=full_pattern):
            await redis.delete(key)
            deleted += 1
        if deleted:
            logger.info("CACHE DEL pattern=%s  removed=%d", full_pattern, deleted)
        return deleted

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_redis(self) -> Any:
        if self._redis is None:
            raise RuntimeError(
                "MarketDataCache is not connected. Call `await cache.connect()` first."
            )
        return self._redis

    def _full_key(self, key: str) -> str:
        return f"marketdata:{self._namespace}:{key}"

    @staticmethod
    def _serialize(data: Any) -> str:
        """Convert *data* to a JSON string."""
        # Pydantic models
        if hasattr(data, "model_dump"):
            return json.dumps(data.model_dump(mode="json"), default=str)
        # Datetime-safe fallback
        return json.dumps(data, default=str)

    @staticmethod
    def _deserialize(raw: str) -> Any:
        """Parse a JSON string back to a Python object."""
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
