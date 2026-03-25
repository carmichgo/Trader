"""Control routes: pause, resume, and kill-switch for traders."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_redis
from api.websocket import manager, EventType

router = APIRouter(prefix="/api/controls", tags=["controls"])

# Redis keys used for inter-process coordination of trader state.
_PAUSE_KEY_PREFIX = "trader:paused:"
_KILL_SWITCH_KEY = "system:kill_switch"
_VALID_TRADERS = {"polymarket", "crypto", "stocks"}


class PauseRequest(BaseModel):
    """Optional body for pause requests with a reason."""

    reason: str = Field(default="Manual pause via API")
    duration_minutes: int | None = Field(
        None,
        ge=1,
        le=1440,
        description="Auto-resume after N minutes (None = indefinite)",
    )


def _validate_trader(trader: str) -> None:
    if trader not in _VALID_TRADERS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown trader: {trader}. Must be one of {sorted(_VALID_TRADERS)}",
        )


@router.post("/pause/{trader}")
async def pause_trader(
    trader: str,
    body: PauseRequest | None = None,
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict[str, Any]:
    """Pause a specific trader.

    Sets a Redis key that the trader process checks before each cycle.
    Optionally specify a duration for automatic resume.
    """
    _validate_trader(trader)
    body = body or PauseRequest()

    key = f"{_PAUSE_KEY_PREFIX}{trader}"
    value = f"{body.reason}|{datetime.utcnow().isoformat()}"

    if body.duration_minutes:
        await redis_client.set(key, value, ex=body.duration_minutes * 60)
    else:
        await redis_client.set(key, value)

    # Broadcast pause event to dashboard
    await manager.broadcast(
        EventType.TRADER_PAUSED,
        {
            "trader": trader,
            "reason": body.reason,
            "duration_minutes": body.duration_minutes,
            "paused_at": datetime.utcnow().isoformat(),
        },
    )

    return {
        "trader": trader,
        "status": "paused",
        "reason": body.reason,
        "duration_minutes": body.duration_minutes,
        "auto_resume": body.duration_minutes is not None,
    }


@router.post("/resume/{trader}")
async def resume_trader(
    trader: str,
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict[str, Any]:
    """Resume a paused trader by removing its pause key from Redis."""
    _validate_trader(trader)

    key = f"{_PAUSE_KEY_PREFIX}{trader}"
    was_paused = await redis_client.delete(key)

    # Broadcast resume event
    await manager.broadcast(
        EventType.TRADER_RESUMED,
        {
            "trader": trader,
            "resumed_at": datetime.utcnow().isoformat(),
        },
    )

    return {
        "trader": trader,
        "status": "resumed",
        "was_paused": was_paused > 0,
    }


@router.post("/pause-all")
async def pause_all(
    body: PauseRequest | None = None,
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict[str, Any]:
    """Pause all traders simultaneously."""
    body = body or PauseRequest(reason="Manual pause-all via API")
    results = {}

    for trader in sorted(_VALID_TRADERS):
        key = f"{_PAUSE_KEY_PREFIX}{trader}"
        value = f"{body.reason}|{datetime.utcnow().isoformat()}"

        if body.duration_minutes:
            await redis_client.set(key, value, ex=body.duration_minutes * 60)
        else:
            await redis_client.set(key, value)

        results[trader] = "paused"

    await manager.broadcast(
        EventType.TRADER_PAUSED,
        {
            "trader": "all",
            "reason": body.reason,
            "duration_minutes": body.duration_minutes,
            "paused_at": datetime.utcnow().isoformat(),
        },
    )

    return {
        "status": "all_paused",
        "traders": results,
        "reason": body.reason,
        "duration_minutes": body.duration_minutes,
    }


@router.post("/kill")
async def kill_switch(
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict[str, Any]:
    """Activate the kill switch: pause all traders and set a global halt flag.

    The kill switch persists until manually cleared. All traders check this
    flag before entering their trading cycle and will refuse to trade.
    """
    # Set global kill switch
    kill_value = f"activated|{datetime.utcnow().isoformat()}"
    await redis_client.set(_KILL_SWITCH_KEY, kill_value)

    # Also pause all traders
    for trader in sorted(_VALID_TRADERS):
        key = f"{_PAUSE_KEY_PREFIX}{trader}"
        value = f"Kill switch activated|{datetime.utcnow().isoformat()}"
        await redis_client.set(key, value)

    # Broadcast kill switch event
    await manager.broadcast(
        EventType.KILL_SWITCH,
        {
            "activated": True,
            "activated_at": datetime.utcnow().isoformat(),
            "message": "Emergency kill switch activated. All trading halted.",
        },
    )

    return {
        "status": "kill_switch_activated",
        "message": "All trading has been halted. Remove the kill switch manually to resume.",
        "activated_at": datetime.utcnow().isoformat(),
    }
