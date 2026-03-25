"""Unit tests for NEV (Net Expected Value) calculation in RiskManager."""

from __future__ import annotations

import pytest

from packages.core.models.cost import InferenceCost, TradeCost, TradeCostBreakdown
from packages.core.models.signal import NormalizedSignal
from packages.core.models.trade import Direction, Market
from packages.core.risk.manager import RiskManager, TradePlan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(confidence: float = 0.70) -> NormalizedSignal:
    return NormalizedSignal(
        market=Market.CRYPTO,
        symbol="ETH/USDT",
        direction=Direction.BUY,
        normalized_confidence=confidence,
    )


def _make_plan(
    *,
    size_usd: float = 1_000.0,
    stop_loss_pct: float = 0.10,
    take_profit_pct: float = 0.20,
    confidence: float = 0.70,
) -> TradePlan:
    return TradePlan(
        signal=_make_signal(confidence),
        proposed_size_usd=size_usd,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )


def _make_costs(
    execution_cost: float = 0.0,
    inference_cost: float = 0.0,
) -> TradeCostBreakdown:
    return TradeCostBreakdown(
        trade_cost=TradeCost(market=Market.CRYPTO, total_cost=execution_cost),
        total_inference_cost=inference_cost,
        total_execution_cost=execution_cost,
        total_cost=execution_cost + inference_cost,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProfitableTrade:
    """Verify NEV is positive for a high-confidence trade with low costs."""

    def test_profitable_trade_positive_nev(self) -> None:
        """70% confidence, 20% take-profit, 10% stop-loss, $1000 size, $1 cost.

        NEV = (0.70 * 200) - (0.30 * 100) - 1.0
            = 140 - 30 - 1 = 109.0
        """
        rm = RiskManager()
        plan = _make_plan(size_usd=1_000.0, confidence=0.70)
        costs = _make_costs(execution_cost=0.50, inference_cost=0.50)

        nev = rm.calculate_nev(plan, costs)

        assert nev > 0
        assert nev == pytest.approx(109.0, abs=0.01)


class TestHighCost:
    """Verify NEV turns negative when costs overwhelm the edge."""

    def test_high_cost_negative_nev(self) -> None:
        """Same trade as above but $200 in costs should produce negative NEV.

        NEV = (0.70 * 200) - (0.30 * 100) - 200
            = 140 - 30 - 200 = -90.0
        """
        rm = RiskManager()
        plan = _make_plan(size_usd=1_000.0, confidence=0.70)
        costs = _make_costs(execution_cost=100.0, inference_cost=100.0)

        nev = rm.calculate_nev(plan, costs)

        assert nev < 0
        assert nev == pytest.approx(-90.0, abs=0.01)


class TestLowWinProbability:
    """Verify NEV is negative when win probability is low."""

    def test_low_win_probability_negative_nev(self) -> None:
        """30% confidence makes the gross EV negative even before costs.

        NEV = (0.30 * 200) - (0.70 * 100) - 1.0
            = 60 - 70 - 1 = -11.0
        """
        rm = RiskManager()
        plan = _make_plan(size_usd=1_000.0, confidence=0.30)
        costs = _make_costs(execution_cost=0.50, inference_cost=0.50)

        nev = rm.calculate_nev(plan, costs)

        assert nev < 0
        assert nev == pytest.approx(-11.0, abs=0.01)


class TestInferenceCostImpact:
    """Verify that inference cost alone can flip NEV from positive to negative."""

    def test_inference_cost_impact(self) -> None:
        """A marginally profitable trade becomes negative with high inference cost.

        With 55% confidence, $100 size, 20% TP, 10% SL:
        Gross EV = (0.55 * 20) - (0.45 * 10) = 11.0 - 4.5 = 6.5

        With $0 cost: NEV = 6.5 (positive)
        With $10 inference cost: NEV = 6.5 - 10.0 = -3.5 (negative)
        """
        rm = RiskManager()
        plan = _make_plan(size_usd=100.0, confidence=0.55)

        # Without significant cost
        low_costs = _make_costs(inference_cost=0.0)
        nev_low = rm.calculate_nev(plan, low_costs)
        assert nev_low > 0
        assert nev_low == pytest.approx(6.5, abs=0.01)

        # With high inference cost
        high_costs = _make_costs(inference_cost=10.0)
        nev_high = rm.calculate_nev(plan, high_costs)
        assert nev_high < 0
        assert nev_high == pytest.approx(-3.5, abs=0.01)
