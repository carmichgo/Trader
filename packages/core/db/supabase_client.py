"""Supabase persistence client for the trading system.

Uses httpx to make REST API calls to Supabase PostgREST.
All methods are async and designed for non-blocking use within the trading loop.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Defaults -- override via environment variables
_DEFAULT_SUPABASE_URL = "https://lfxurrpkcsgragqbbypw.supabase.co"
_DEFAULT_SUPABASE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxmeHVycnBrY3NncmFncWJieXB3Iiwi"
    "cm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NDQ1ODk3OCwiZXhwIjoyMDkw"
    "MDM0OTc4fQ.4YyhOZMSaycQx3xX3ZjRyPG4_FSuD9zajMzUO2EoaSM"
)


class SupabaseDB:
    """Async Supabase persistence layer using httpx + PostgREST.

    Usage::

        db = SupabaseDB()
        await db.insert_trade({...})
    """

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
    ) -> None:
        self._url = (url or os.getenv("SUPABASE_URL", _DEFAULT_SUPABASE_URL)).rstrip("/")
        self._key = key or os.getenv("SUPABASE_SERVICE_ROLE_KEY", _DEFAULT_SUPABASE_KEY)
        self._rest_url = f"{self._url}/rest/v1"
        self._headers = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Client lifecycle
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """Return (and lazily create) the shared httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self._headers,
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    async def _post(self, table: str, data: dict | list[dict]) -> list[dict]:
        """INSERT into *table* via PostgREST POST."""
        client = await self._get_client()
        url = f"{self._rest_url}/{table}"
        resp = await client.post(url, json=data)
        resp.raise_for_status()
        return resp.json()

    async def _patch(self, table: str, filters: str, data: dict) -> list[dict]:
        """UPDATE rows in *table* matching *filters* (PostgREST query string)."""
        client = await self._get_client()
        url = f"{self._rest_url}/{table}?{filters}"
        resp = await client.patch(url, json=data)
        resp.raise_for_status()
        return resp.json()

    async def _get(self, table: str, query: str = "") -> list[dict]:
        """SELECT from *table* with optional PostgREST query string."""
        client = await self._get_client()
        url = f"{self._rest_url}/{table}"
        if query:
            url = f"{url}?{query}"
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    async def insert_trade(self, trade_data: dict) -> dict:
        """Insert a new row into the ``trades`` table.

        Returns the inserted row (with server-generated fields).
        """
        rows = await self._post("trades", trade_data)
        logger.info("supabase_trade_inserted", trade_id=rows[0].get("id") if rows else None)
        return rows[0] if rows else {}

    async def update_trade(self, trade_id: int, updates: dict) -> dict:
        """Update an existing trade by *trade_id*."""
        rows = await self._patch("trades", f"id=eq.{trade_id}", updates)
        logger.info("supabase_trade_updated", trade_id=trade_id)
        return rows[0] if rows else {}

    async def close_trade(
        self,
        trade_id: int | str,
        exit_price: float,
        gross_pnl: float,
        net_pnl: float,
        close_reason: str,
        costs: float,
    ) -> dict:
        """Mark a trade as closed with P&L and reason."""
        updates = {
            "exit_price": exit_price,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "close_reason": close_reason,
            "costs": costs,
            "status": "closed",
            "closed_at": datetime.utcnow().isoformat(),
        }
        rows = await self._patch("trades", f"trade_id=eq.{trade_id}", updates)
        logger.info("supabase_trade_closed", trade_id=trade_id, net_pnl=net_pnl)
        return rows[0] if rows else {}

    async def get_open_trades(self, trader: str | None = None) -> list[dict]:
        """Return all open trades, optionally filtered by *trader* name."""
        query = "status=eq.open&order=created_at.desc"
        if trader:
            query += f"&strategy=eq.{trader}"
        return await self._get("trades", query)

    # ------------------------------------------------------------------
    # Portfolio snapshots
    # ------------------------------------------------------------------

    async def insert_portfolio_snapshot(self, snapshot: dict) -> dict:
        """Insert a row into ``portfolio_snapshots``."""
        rows = await self._post("portfolio_snapshots", snapshot)
        logger.debug("supabase_snapshot_inserted")
        return rows[0] if rows else {}

    # ------------------------------------------------------------------
    # AI decisions
    # ------------------------------------------------------------------

    async def insert_ai_decision(self, decision: dict) -> dict:
        """Insert a row into ``ai_decisions``."""
        rows = await self._post("ai_decisions", decision)
        logger.debug("supabase_ai_decision_inserted", decision_type=decision.get("decision_type"))
        return rows[0] if rows else {}

    # ------------------------------------------------------------------
    # Daily performance
    # ------------------------------------------------------------------

    async def upsert_daily_performance(self, perf: dict) -> dict:
        """Upsert a row into ``daily_performance``.

        Uses PostgREST ``on_conflict`` merge-duplicates to update existing
        rows for the same (trader, date) pair.
        """
        client = await self._get_client()
        url = f"{self._rest_url}/daily_performance"
        headers = {**self._headers, "Prefer": "return=representation,resolution=merge-duplicates"}
        resp = await client.post(url, json=perf, headers=headers)
        resp.raise_for_status()
        rows = resp.json()
        logger.debug("supabase_daily_perf_upserted", date=perf.get("date"))
        return rows[0] if rows else {}

    async def get_recent_performance(self, trader: str, days: int = 30) -> list[dict]:
        """Return the last *days* of daily performance for *trader*."""
        since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        query = f"trader=eq.{trader}&date=gte.{since}&order=date.desc"
        return await self._get("daily_performance", query)

    # ------------------------------------------------------------------
    # Goals
    # ------------------------------------------------------------------

    async def insert_goal(self, goal: dict) -> dict:
        """Insert a row into ``goals``."""
        rows = await self._post("goals", goal)
        logger.info("supabase_goal_inserted", goal_id=rows[0].get("id") if rows else None)
        return rows[0] if rows else {}

    async def get_active_goal(self) -> dict | None:
        """Return the currently active goal, or ``None``."""
        rows = await self._get("goals", "status=eq.active&order=created_at.desc&limit=1")
        return rows[0] if rows else None

    # ------------------------------------------------------------------
    # Strategist plans
    # ------------------------------------------------------------------

    async def insert_strategist_plan(self, plan: dict) -> dict:
        """Insert a row into ``strategist_plans``."""
        rows = await self._post("strategist_plans", plan)
        logger.info("supabase_strategist_plan_inserted")
        return rows[0] if rows else {}
