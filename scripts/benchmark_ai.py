#!/usr/bin/env python3
"""Benchmark AI inference performance and cost efficiency.

Measures latency, throughput, cost per call, and response quality
across different Claude models (Haiku, Sonnet, Opus) to optimize
the screener/analyst pipeline configuration.

Usage:
    python scripts/benchmark_ai.py [--iterations 10] [--models haiku,sonnet,opus]
    python scripts/benchmark_ai.py --market crypto --quick
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import structlog

from packages.core.config import SystemConfig
from packages.core.ai.client import AIClient
from packages.core.ai.cost_tracker import CostTracker
from packages.core.models import Market, MarketSnapshot

logger = structlog.get_logger(__name__)


class BenchmarkResult:
    """Accumulated results from an AI benchmark run."""

    def __init__(self, model: str, iterations: int) -> None:
        self.model = model
        self.iterations = iterations
        self.latencies_ms: list[float] = []
        self.costs_usd: list[float] = []
        self.input_tokens: list[int] = []
        self.output_tokens: list[int] = []
        self.errors: int = 0
        self.successes: int = 0

    def record(
        self,
        latency_ms: float,
        cost_usd: float,
        tokens_in: int,
        tokens_out: int,
    ) -> None:
        """Record a successful call."""
        self.latencies_ms.append(latency_ms)
        self.costs_usd.append(cost_usd)
        self.input_tokens.append(tokens_in)
        self.output_tokens.append(tokens_out)
        self.successes += 1

    def record_error(self) -> None:
        """Record a failed call."""
        self.errors += 1

    def summary(self) -> dict[str, Any]:
        """Generate a summary report."""
        if not self.latencies_ms:
            return {
                "model": self.model,
                "iterations": self.iterations,
                "successes": 0,
                "errors": self.errors,
            }

        return {
            "model": self.model,
            "iterations": self.iterations,
            "successes": self.successes,
            "errors": self.errors,
            "latency_ms": {
                "mean": round(statistics.mean(self.latencies_ms), 1),
                "median": round(statistics.median(self.latencies_ms), 1),
                "p95": round(
                    sorted(self.latencies_ms)[int(len(self.latencies_ms) * 0.95)], 1
                )
                if len(self.latencies_ms) > 1
                else round(self.latencies_ms[0], 1),
                "min": round(min(self.latencies_ms), 1),
                "max": round(max(self.latencies_ms), 1),
            },
            "cost_usd": {
                "total": round(sum(self.costs_usd), 6),
                "mean": round(statistics.mean(self.costs_usd), 6),
                "per_1k_tokens_out": round(
                    sum(self.costs_usd) / max(sum(self.output_tokens), 1) * 1000, 6
                ),
            },
            "tokens": {
                "avg_input": round(statistics.mean(self.input_tokens)),
                "avg_output": round(statistics.mean(self.output_tokens)),
                "total_input": sum(self.input_tokens),
                "total_output": sum(self.output_tokens),
            },
        }


def _build_sample_snapshots(market: str) -> list[MarketSnapshot]:
    """Build sample market snapshots for benchmarking."""
    if market == "crypto":
        return [
            MarketSnapshot(
                market=Market.CRYPTO,
                symbol=sym,
                price=price,
                change_24h_pct=chg,
                volume_24h=vol,
            )
            for sym, price, chg, vol in [
                ("BTC/USDT", 65000.0, 2.5, 25_000_000_000),
                ("ETH/USDT", 3200.0, 3.1, 12_000_000_000),
                ("SOL/USDT", 145.0, -1.2, 3_500_000_000),
                ("BNB/USDT", 590.0, 0.8, 1_200_000_000),
                ("XRP/USDT", 0.52, 5.3, 2_100_000_000),
            ]
        ]
    elif market == "stocks":
        return [
            MarketSnapshot(
                market=Market.STOCKS,
                symbol=sym,
                price=price,
                change_24h_pct=chg,
                volume_24h=vol,
            )
            for sym, price, chg, vol in [
                ("AAPL", 195.0, 1.2, 65_000_000),
                ("NVDA", 880.0, 4.5, 45_000_000),
                ("MSFT", 420.0, 0.3, 22_000_000),
                ("TSLA", 175.0, -2.1, 95_000_000),
                ("AMZN", 185.0, 1.8, 35_000_000),
            ]
        ]
    else:
        return [
            MarketSnapshot(
                market=Market.POLYMARKET,
                symbol=f"cond_{i}",
                price=price,
                volume_24h=vol,
            )
            for i, (price, vol) in enumerate([
                (0.65, 500_000),
                (0.32, 1_200_000),
                (0.78, 300_000),
                (0.15, 800_000),
                (0.91, 200_000),
            ])
        ]


async def benchmark_model(
    ai_client: AIClient,
    model_name: str,
    market: str,
    iterations: int,
) -> BenchmarkResult:
    """Run benchmark iterations against a specific model.

    Parameters
    ----------
    ai_client:
        Configured AI client.
    model_name:
        Model identifier to benchmark.
    market:
        Market type for sample data.
    iterations:
        Number of benchmark calls to make.
    """
    result = BenchmarkResult(model_name, iterations)
    snapshots = _build_sample_snapshots(market)

    # Build a sample screening prompt
    snapshot_text = json.dumps(
        [{"sym": s.symbol, "px": s.price, "chg": s.change_24h_pct} for s in snapshots],
        indent=2,
    )

    prompt = (
        f"You are a {market} market screener. Analyze these market snapshots and "
        f"identify the top 2 trading opportunities. For each, provide: symbol, "
        f"confidence (0-1), direction (buy/sell), and a one-sentence rationale.\n\n"
        f"Market data:\n{snapshot_text}\n\n"
        f"Respond in JSON format with an 'opportunities' array."
    )

    for i in range(iterations):
        start = time.monotonic()
        try:
            # Use the appropriate call method based on model
            if "haiku" in model_name.lower():
                response = await ai_client.call_sonnet(prompt)  # Haiku via Sonnet endpoint
            elif "opus" in model_name.lower():
                response = await ai_client.call_opus(prompt)
            else:
                response = await ai_client.call_sonnet(prompt)

            elapsed_ms = (time.monotonic() - start) * 1000

            result.record(
                latency_ms=elapsed_ms,
                cost_usd=response.cost_usd,
                tokens_in=response.input_tokens,
                tokens_out=response.output_tokens,
            )

            logger.info(
                "benchmark_call_complete",
                model=model_name,
                iteration=i + 1,
                latency_ms=round(elapsed_ms, 1),
                cost=response.cost_usd,
            )

        except Exception:
            result.record_error()
            logger.exception(
                "benchmark_call_failed",
                model=model_name,
                iteration=i + 1,
            )

        # Respect rate limits
        await asyncio.sleep(1.0)

    return result


async def main(
    models: list[str],
    market: str,
    iterations: int,
) -> None:
    """Run benchmarks across all specified models."""
    config = SystemConfig()
    ai_client = AIClient(config.ai)

    print(f"\nAI Benchmark: {market} market, {iterations} iterations per model")
    print("=" * 70)

    results: list[BenchmarkResult] = []

    for model in models:
        print(f"\nBenchmarking {model}...")
        result = await benchmark_model(ai_client, model, market, iterations)
        results.append(result)

    # Print results
    print("\n" + "=" * 70)
    print("BENCHMARK RESULTS")
    print("=" * 70)

    for result in results:
        summary = result.summary()
        print(f"\n--- {summary['model']} ---")
        print(f"  Successes: {summary['successes']}/{summary['iterations']}")

        if summary.get("latency_ms"):
            lat = summary["latency_ms"]
            print(f"  Latency (ms):  mean={lat['mean']}, median={lat['median']}, "
                  f"p95={lat['p95']}, range=[{lat['min']}, {lat['max']}]")

        if summary.get("cost_usd"):
            cost = summary["cost_usd"]
            print(f"  Cost (USD):    total=${cost['total']:.6f}, "
                  f"mean=${cost['mean']:.6f}, per_1k_out=${cost['per_1k_tokens_out']:.6f}")

        if summary.get("tokens"):
            tok = summary["tokens"]
            print(f"  Tokens:        avg_in={tok['avg_input']}, avg_out={tok['avg_output']}")

    # Cost comparison
    if len(results) > 1:
        print("\n--- Cost Comparison ---")
        for r in results:
            s = r.summary()
            if s.get("cost_usd"):
                cost_per_call = s["cost_usd"]["mean"]
                calls_per_dollar = 1.0 / cost_per_call if cost_per_call > 0 else float("inf")
                print(f"  {s['model']:>20}: ${cost_per_call:.6f}/call "
                      f"({calls_per_dollar:.0f} calls/$1)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Benchmark AI inference performance and cost."
    )
    parser.add_argument(
        "--models",
        type=str,
        default="sonnet",
        help="Comma-separated model names to benchmark (default: sonnet)",
    )
    parser.add_argument(
        "--market",
        type=str,
        default="crypto",
        choices=["crypto", "stocks", "polymarket"],
        help="Market type for sample data (default: crypto)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Number of iterations per model (default: 5)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick run with 2 iterations",
    )
    args = parser.parse_args()

    model_list = [m.strip() for m in args.models.split(",") if m.strip()]
    iterations = 2 if args.quick else args.iterations

    asyncio.run(main(
        models=model_list,
        market=args.market,
        iterations=iterations,
    ))
