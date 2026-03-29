"""Token usage and cost accounting backed by Redis + Postgres.

Tracks per-trader, per-day inference costs in real time using Redis
for fast reads and writes, and persists summarised records to Postgres
at the end of each day (or on demand).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.ai.client import AIResponse
from packages.core.config import SystemConfig
from packages.core.models import DailyCostSummary, InferenceCost

logger = structlog.get_logger(__name__)

# Redis key helpers --------------------------------------------------------

_PREFIX = "trader:cost"


def _daily_key(trader_id: str, day: str) -> str:
    return f"{_PREFIX}:{trader_id}:{day}"


def _model_key(trader_id: str, day: str, model: str) -> str:
    return f"{_PREFIX}:{trader_id}:{day}:model:{model}"


class CostTracker:
    """Real-time inference cost tracker.

    Uses Redis sorted-sets / hashes for fast per-trader per-day aggregation
    and writes durable records to Postgres via SQLAlchemy async sessions.

    Usage::

        tracker = CostTracker(config, redis, session)
        await tracker.record_call(trader_id="t1", response=resp, purpose="screener")
        remaining = await tracker.remaining_budget("t1")
    """

    def __init__(
        self,
        config: SystemConfig,
        redis: aioredis.Redis,
        db_session: AsyncSession | None = None,
    ) -> None:
        self._config = config
        self._redis = redis
        self._db = db_session
        self._daily_limit = config.ai.daily_cost_limit_usd

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def record_call(
        self,
        *,
        trader_id: str,
        response: AIResponse,
        purpose: str,
        trade_id: str | None = None,
        signal_id: str | None = None,
    ) -> InferenceCost:
        """Record a single inference call to Redis and (optionally) Postgres.

        Returns the :class:`InferenceCost` model for downstream use.
        """
        today = date.today().isoformat()
        cost = response.cost_usd

        # ---- Redis real-time counters ------------------------------------
        pipe = self._redis.pipeline(transaction=False)
        daily_k = _daily_key(trader_id, today)
        model_k = _model_key(trader_id, today, response.model)

        pipe.hincrbyfloat(daily_k, "total_cost", cost)
        pipe.hincrby(daily_k, "call_count", 1)
        pipe.hincrby(daily_k, "input_tokens", response.input_tokens)
        pipe.hincrby(daily_k, "output_tokens", response.output_tokens)
        pipe.hincrbyfloat(model_k, "cost", cost)
        pipe.hincrby(model_k, "calls", 1)
        # Expire keys after 48h so stale days are auto-cleaned
        pipe.expire(daily_k, 172_800)
        pipe.expire(model_k, 172_800)
        await pipe.execute()

        # ---- Postgres persistence ----------------------------------------
        record = InferenceCost(
            model=response.model,
            provider="anthropic",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=cost,
            latency_ms=response.latency_ms,
            purpose=purpose,
            trade_id=trade_id,
            signal_id=signal_id,
        )

        if self._db is not None:
            try:
                self._db.add(record)  # type: ignore[arg-type]
                await self._db.flush()
            except Exception:
                logger.warning("cost_tracker_db_write_failed", exc_info=True)

        logger.info(
            "cost_recorded",
            trader_id=trader_id,
            purpose=purpose,
            cost_usd=cost,
            model=response.model,
        )
        return record

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_daily_cost(self, trader_id: str, day: str | None = None) -> float:
        """Return total inference cost for *trader_id* on *day* (default today)."""
        day = day or date.today().isoformat()
        val = await self._redis.hget(_daily_key(trader_id, day), "total_cost")
        return float(val) if val else 0.0

    async def get_trader_cost(self, trader_id: str) -> float:
        """Return lifetime inference cost for *trader_id* by scanning Redis.

        For full lifetime totals prefer a Postgres query; this method covers
        the last 48 h window available in Redis.
        """
        pattern = f"{_PREFIX}:{trader_id}:*"
        total = 0.0
        async for key in self._redis.scan_iter(match=pattern, count=100):
            key_str = key.decode() if isinstance(key, bytes) else key
            # Only look at daily aggregate keys (not model sub-keys)
            parts = key_str.split(":")
            if len(parts) == 4:  # trader:cost:<id>:<date>
                val = await self._redis.hget(key, "total_cost")
                if val:
                    total += float(val)
        return total

    async def remaining_budget(self, trader_id: str) -> float:
        """Return how much of today's budget remains for *trader_id*."""
        spent = await self.get_daily_cost(trader_id)
        return max(0.0, self._daily_limit - spent)

    async def is_budget_exhausted(self, trader_id: str) -> bool:
        """Check whether today's inference budget is fully consumed."""
        remaining = await self.remaining_budget(trader_id)
        return remaining <= 0.0

    # ------------------------------------------------------------------
    # Summaries / Persistence
    # ------------------------------------------------------------------

    async def get_daily_summary(self, trader_id: str, day: str | None = None) -> DailyCostSummary:
        """Build a :class:`DailyCostSummary` from Redis counters."""
        day = day or date.today().isoformat()
        daily_k = _daily_key(trader_id, day)
        data = await self._redis.hgetall(daily_k)

        def _f(k: str) -> float:
            v = data.get(k.encode() if isinstance(next(iter(data), b""), bytes) else k, 0)
            return float(v)

        def _i(k: str) -> int:
            v = data.get(k.encode() if isinstance(next(iter(data), b""), bytes) else k, 0)
            return int(v)

        return DailyCostSummary(
            date=day,
            total_inference_cost=_f("total_cost"),
            inference_call_count=_i("call_count"),
            total_input_tokens=_i("input_tokens"),
            total_output_tokens=_i("output_tokens"),
            budget_remaining=max(0.0, self._daily_limit - _f("total_cost")),
            budget_utilization_pct=min(1.0, _f("total_cost") / self._daily_limit)
            if self._daily_limit > 0
            else 0.0,
        )

    async def persist_daily_summary(self, trader_id: str, day: str | None = None) -> None:
        """Write the daily summary to Postgres (idempotent upsert)."""
        if self._db is None:
            logger.warning("persist_skipped_no_db_session")
            return
        summary = await self.get_daily_summary(trader_id, day)
        await self._db.execute(
            text(
                """
                INSERT INTO daily_cost_summaries (date, total_inference_cost, inference_call_count,
                    total_input_tokens, total_output_tokens, budget_remaining, budget_utilization_pct)
                VALUES (:date, :cost, :calls, :in_tok, :out_tok, :remaining, :util)
                ON CONFLICT (date) DO UPDATE SET
                    total_inference_cost = EXCLUDED.total_inference_cost,
                    inference_call_count = EXCLUDED.inference_call_count,
                    total_input_tokens   = EXCLUDED.total_input_tokens,
                    total_output_tokens  = EXCLUDED.total_output_tokens,
                    budget_remaining     = EXCLUDED.budget_remaining,
                    budget_utilization_pct = EXCLUDED.budget_utilization_pct
                """
            ),
            {
                "date": summary.date,
                "cost": summary.total_inference_cost,
                "calls": summary.inference_call_count,
                "in_tok": summary.total_input_tokens,
                "out_tok": summary.total_output_tokens,
                "remaining": summary.budget_remaining,
                "util": summary.budget_utilization_pct,
            },
        )
        await self._db.flush()
        logger.info("daily_summary_persisted", trader_id=trader_id, day=summary.date)
