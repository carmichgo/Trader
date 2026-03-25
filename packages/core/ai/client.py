"""Anthropic API wrapper with token tracking and structured logging."""

from __future__ import annotations

import time
from dataclasses import dataclass

import anthropic
import structlog

from packages.core.config import SystemConfig

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Pricing per million tokens (USD)
# ---------------------------------------------------------------------------

MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
}

SONNET_MODEL = "claude-sonnet-4-20250514"
OPUS_MODEL = "claude-opus-4-20250514"


@dataclass
class AIResponse:
    """Structured response from an AI inference call."""

    content: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    model: str


def _calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate USD cost from token counts using model pricing."""
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        logger.warning("unknown_model_pricing", model=model)
        return 0.0
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)


class AIClient:
    """Thin async wrapper around the Anthropic Python SDK.

    Provides ``call_sonnet`` and ``call_opus`` convenience methods that
    automatically track tokens, compute cost, and emit structured logs.

    Usage::

        from packages.core.config import SystemConfig
        client = AIClient(SystemConfig())
        response = await client.call_sonnet("You are a trader.", "Analyze BTC.")
    """

    def __init__(self, config: SystemConfig | None = None) -> None:
        cfg = config or SystemConfig()
        self._client = anthropic.AsyncAnthropic(api_key=cfg.ai.anthropic_api_key)
        self._max_tokens = cfg.ai.max_tokens
        self._temperature = cfg.ai.temperature

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    async def call_sonnet(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AIResponse:
        """Call Claude Sonnet and return a tracked :class:`AIResponse`."""
        return await self._call(
            model=SONNET_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def call_opus(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AIResponse:
        """Call Claude Opus and return a tracked :class:`AIResponse`."""
        return await self._call(
            model=OPUS_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _call(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AIResponse:
        """Execute an API call, measure latency, compute cost, and log."""
        max_tokens = max_tokens or self._max_tokens
        temperature = temperature if temperature is not None else self._temperature

        start = time.perf_counter()
        message = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens
        cost_usd = _calculate_cost(model, input_tokens, output_tokens)

        # Extract text content from the response
        content = ""
        for block in message.content:
            if block.type == "text":
                content += block.text

        response = AIResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            model=model,
        )

        logger.info(
            "ai_call_complete",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            content_length=len(content),
        )

        return response
