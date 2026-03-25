"""Integration tests for the AI pipeline: screener -> analyst -> execution flow.

These tests verify the end-to-end data flow from market screening through
deep analysis, using mocked AI responses to avoid real API calls.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.core.ai.client import AIClient, AIResponse
from packages.core.ai.cost_tracker import CostTracker
from packages.core.ai.screener import Screener
from packages.core.ai.analyst import Analyst
from packages.core.config import SystemConfig, AIConfig
from packages.core.models import (
    Market,
    MarketSnapshot,
    Opportunity,
    TraderConfig,
    NetExpectedValue,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def system_config() -> SystemConfig:
    cfg = SystemConfig()
    cfg.ai = AIConfig(daily_cost_limit_usd=50.0)
    return cfg


@pytest.fixture
def mock_ai() -> MagicMock:
    client = MagicMock(spec=AIClient)
    client.call_sonnet = AsyncMock()
    client.call_opus = AsyncMock()
    return client


@pytest.fixture
def mock_cost_tracker() -> MagicMock:
    tracker = MagicMock(spec=CostTracker)
    tracker.record_call = AsyncMock()
    tracker.is_budget_exhausted = AsyncMock(return_value=False)
    tracker.remaining_budget = AsyncMock(return_value=40.0)
    return tracker


# ---------------------------------------------------------------------------
# Screener -> Analyst pipeline
# ---------------------------------------------------------------------------


class TestScreenerToAnalystFlow:
    """Verify data flows correctly from screener output into analyst input."""

    @pytest.mark.asyncio
    async def test_screener_produces_opportunities_for_analyst(
        self, mock_ai: MagicMock, mock_cost_tracker: MagicMock
    ) -> None:
        """Screener output should be parseable as Opportunity objects that
        the Analyst can consume."""
        screener_response = AIResponse(
            content=json.dumps({
                "opportunities": [
                    {
                        "symbol": "BTC/USDT",
                        "confidence": 0.75,
                        "current_price": 65000.0,
                        "estimated_edge": 0.04,
                        "title": "BTC momentum breakout",
                        "description": "Strong volume above resistance",
                    }
                ]
            }),
            input_tokens=800,
            output_tokens=300,
            cost_usd=0.006,
            latency_ms=400,
            model="claude-sonnet-4-20250514",
        )
        mock_ai.call_sonnet = AsyncMock(return_value=screener_response)

        # The screener needs a prompt file; patch _load_prompt to avoid file I/O
        with patch("packages.core.ai.screener._load_prompt", return_value="{market_data}{num_markets}{market_type}{max_positions}{available_balance}{risk_tolerance}{enabled_strategies}"):
            screener = Screener(mock_ai, mock_cost_tracker, trader_id="t1")
            snapshots = [
                MarketSnapshot(market=Market.CRYPTO, symbol="BTC/USDT", price=65000.0),
            ]
            result = await screener.scan(snapshots, TraderConfig(initial_balance=10_000.0), Market.CRYPTO)

        assert len(result.opportunities) == 1
        opp = result.opportunities[0]
        assert opp.symbol == "BTC/USDT"
        assert opp.confidence == 0.75

    @pytest.mark.asyncio
    async def test_analyst_gate_respects_budget(
        self, mock_ai: MagicMock, mock_cost_tracker: MagicMock
    ) -> None:
        """Analyst should refuse to call Opus when budget is insufficient."""
        mock_cost_tracker.remaining_budget = AsyncMock(return_value=0.01)

        analyst = Analyst(mock_ai, mock_cost_tracker, trader_id="t1")
        opp = Opportunity(
            market=Market.CRYPTO,
            symbol="ETH/USDT",
            confidence=0.80,
            current_price=3200.0,
        )
        should_call = await analyst.should_call_opus(
            opp, TraderConfig(initial_balance=10_000.0)
        )
        assert should_call is False

    @pytest.mark.asyncio
    async def test_analyst_produces_trade_plan(
        self, mock_ai: MagicMock, mock_cost_tracker: MagicMock
    ) -> None:
        """Analyst should produce a TradePlan from a valid Opus response."""
        analyst_response = AIResponse(
            content=json.dumps({
                "decision": "approve",
                "symbol": "ETH/USDT",
                "direction": "buy",
                "confidence": 0.80,
                "entry_price": 3200.0,
                "stop_loss_price": 3000.0,
                "take_profit_price": 3600.0,
                "position_size_usd": 500.0,
                "leverage": 1.0,
                "reasoning": "Strong breakout with volume",
                "key_risks": ["Macro downturn"],
                "catalysts": ["ETF approval"],
            }),
            input_tokens=2000,
            output_tokens=800,
            cost_usd=0.105,
            latency_ms=2500,
            model="claude-opus-4-20250514",
        )
        mock_ai.call_opus = AsyncMock(return_value=analyst_response)

        with patch("packages.core.ai.analyst._load_prompt", return_value="{symbol}{market_type}{current_price}{estimated_edge}{screener_confidence}{title}{description}{volume_24h}{liquidity}{volatility}{category}{tags}{portfolio_state}{recent_trades}{market_conditions}{risk_limits}{available_balance}{max_position_pct}"):
            analyst = Analyst(mock_ai, mock_cost_tracker, trader_id="t1")
            opp = Opportunity(
                market=Market.CRYPTO,
                symbol="ETH/USDT",
                confidence=0.75,
                current_price=3200.0,
            )
            plan = await analyst.analyze(opp, {"portfolio_state": {}}, Market.CRYPTO)

        assert plan is not None
        assert plan.symbol == "ETH/USDT"
        assert plan.direction.value == "buy"
        assert plan.entry_price == 3200.0
        assert plan.position_size_usd == 500.0

    @pytest.mark.asyncio
    async def test_analyst_rejects_low_conviction(
        self, mock_ai: MagicMock, mock_cost_tracker: MagicMock
    ) -> None:
        """Analyst returns None when Opus rejects the opportunity."""
        reject_response = AIResponse(
            content=json.dumps({
                "decision": "reject",
                "reasoning": "Insufficient volume and declining momentum",
            }),
            input_tokens=2000,
            output_tokens=200,
            cost_usd=0.09,
            latency_ms=1800,
            model="claude-opus-4-20250514",
        )
        mock_ai.call_opus = AsyncMock(return_value=reject_response)

        with patch("packages.core.ai.analyst._load_prompt", return_value="{symbol}{market_type}{current_price}{estimated_edge}{screener_confidence}{title}{description}{volume_24h}{liquidity}{volatility}{category}{tags}{portfolio_state}{recent_trades}{market_conditions}{risk_limits}{available_balance}{max_position_pct}"):
            analyst = Analyst(mock_ai, mock_cost_tracker, trader_id="t1")
            opp = Opportunity(
                market=Market.CRYPTO,
                symbol="LOW/USDT",
                confidence=0.55,
                current_price=1.0,
            )
            plan = await analyst.analyze(opp, {}, Market.CRYPTO)

        assert plan is None
