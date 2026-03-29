"""Unit tests for CostTracker: recording calls, budget queries."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.core.ai.client import AIResponse
from packages.core.ai.cost_tracker import CostTracker, _daily_key
from packages.core.config import AIConfig, SystemConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(daily_limit: float = 50.0) -> SystemConfig:
    """Build a SystemConfig with a specific daily cost limit."""
    cfg = SystemConfig()
    # Override the AI daily cost limit
    cfg.ai = AIConfig(daily_cost_limit_usd=daily_limit)
    return cfg


def _make_response(cost: float = 0.005, model: str = "claude-sonnet-4-20250514") -> AIResponse:
    return AIResponse(
        content='{"result": "ok"}',
        input_tokens=500,
        output_tokens=200,
        cost_usd=cost,
        latency_ms=300,
        model=model,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRecordCall:
    """Verify that record_call persists data to Redis and returns an InferenceCost."""

    @pytest.mark.asyncio
    async def test_record_call(self, mock_redis: AsyncMock, test_db_session: AsyncMock) -> None:
        """Recording a call should pipeline-write to Redis and return an InferenceCost."""
        tracker = CostTracker(
            config=_make_config(daily_limit=50.0),
            redis=mock_redis,
            db_session=test_db_session,
        )
        response = _make_response(cost=0.0045)

        result = await tracker.record_call(
            trader_id="t1",
            response=response,
            purpose="screener_crypto",
        )

        assert result.cost_usd == 0.0045
        assert result.model == "claude-sonnet-4-20250514"
        assert result.purpose == "screener_crypto"

        # Redis pipeline should have been used
        mock_redis.pipeline.assert_called_once()
        pipe = mock_redis.pipeline.return_value
        pipe.execute.assert_awaited_once()

        # DB session should have had the record added
        test_db_session.add.assert_called_once()
        test_db_session.flush.assert_awaited_once()


class TestDailyTotal:
    """Verify get_daily_cost reads from Redis."""

    @pytest.mark.asyncio
    async def test_daily_total(self, mock_redis: AsyncMock) -> None:
        """get_daily_cost returns the float stored in Redis."""
        mock_redis.hget = AsyncMock(return_value=b"3.50")

        tracker = CostTracker(
            config=_make_config(daily_limit=50.0),
            redis=mock_redis,
        )
        total = await tracker.get_daily_cost("t1")

        assert total == 3.50
        mock_redis.hget.assert_awaited_once()


class TestBudgetExhausted:
    """Verify budget exhaustion detection."""

    @pytest.mark.asyncio
    async def test_budget_exhausted(self, mock_redis: AsyncMock) -> None:
        """When daily spend equals or exceeds the limit, budget is exhausted."""
        # Daily limit is 10.0, daily cost is 10.50 => exhausted
        mock_redis.hget = AsyncMock(return_value=b"10.50")

        tracker = CostTracker(
            config=_make_config(daily_limit=10.0),
            redis=mock_redis,
        )
        assert await tracker.is_budget_exhausted("t1") is True


class TestRemainingBudget:
    """Verify remaining_budget calculation."""

    @pytest.mark.asyncio
    async def test_remaining_budget(self, mock_redis: AsyncMock) -> None:
        """remaining_budget = daily_limit - daily_cost, clamped to >= 0."""
        mock_redis.hget = AsyncMock(return_value=b"7.25")

        tracker = CostTracker(
            config=_make_config(daily_limit=50.0),
            redis=mock_redis,
        )
        remaining = await tracker.remaining_budget("t1")

        assert remaining == pytest.approx(42.75)

    @pytest.mark.asyncio
    async def test_remaining_budget_never_negative(self, mock_redis: AsyncMock) -> None:
        """remaining_budget is clamped to zero when over-spent."""
        mock_redis.hget = AsyncMock(return_value=b"60.0")

        tracker = CostTracker(
            config=_make_config(daily_limit=50.0),
            redis=mock_redis,
        )
        remaining = await tracker.remaining_budget("t1")

        assert remaining == 0.0
