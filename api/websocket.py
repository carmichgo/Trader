"""WebSocket manager for broadcasting real-time trading events to connected clients."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["websocket"])


class EventType(str, Enum):
    """Event types that can be broadcast over WebSocket."""

    TRADE_OPENED = "trade.opened"
    TRADE_CLOSED = "trade.closed"
    TRADE_UPDATED = "trade.updated"
    PORTFOLIO_SNAPSHOT = "portfolio.snapshot"
    AI_DECISION = "ai.decision"
    RISK_ALERT = "risk.alert"
    PACE_UPDATE = "pace.update"
    COST_UPDATE = "cost.update"
    SYSTEM_STATUS = "system.status"
    TRADER_PAUSED = "trader.paused"
    TRADER_RESUMED = "trader.resumed"
    KILL_SWITCH = "kill_switch"


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts events."""

    def __init__(self) -> None:
        # All connected clients
        self._connections: list[WebSocket] = []
        # Topic-based subscriptions: topic -> set of WebSocket
        self._subscriptions: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)
        logger.info("ws_connected", total=len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection and clean up subscriptions."""
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
            # Remove from all topic subscriptions
            for topic_subs in self._subscriptions.values():
                topic_subs.discard(websocket)
        logger.info("ws_disconnected", total=len(self._connections))

    async def subscribe(self, websocket: WebSocket, topic: str) -> None:
        """Subscribe a connection to a specific topic (e.g., 'trades', 'portfolio')."""
        async with self._lock:
            if topic not in self._subscriptions:
                self._subscriptions[topic] = set()
            self._subscriptions[topic].add(websocket)
        logger.debug("ws_subscribed", topic=topic)

    async def unsubscribe(self, websocket: WebSocket, topic: str) -> None:
        """Unsubscribe a connection from a topic."""
        async with self._lock:
            if topic in self._subscriptions:
                self._subscriptions[topic].discard(websocket)

    async def broadcast(
        self,
        event_type: EventType,
        data: dict[str, Any],
        *,
        topic: str | None = None,
    ) -> None:
        """Broadcast an event to all connected clients, or only to topic subscribers.

        Parameters
        ----------
        event_type:
            The type of event being broadcast.
        data:
            JSON-serialisable payload.
        topic:
            If provided, only send to clients subscribed to this topic.
            If ``None``, broadcast to all connected clients.
        """
        message = json.dumps(
            {
                "event": event_type.value,
                "data": data,
                "timestamp": datetime.utcnow().isoformat(),
            },
            default=str,
        )

        async with self._lock:
            if topic and topic in self._subscriptions:
                targets = list(self._subscriptions[topic])
            else:
                targets = list(self._connections)

        stale: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                stale.append(ws)

        # Clean up dead connections
        for ws in stale:
            await self.disconnect(ws)

    async def send_personal(
        self,
        websocket: WebSocket,
        event_type: EventType,
        data: dict[str, Any],
    ) -> None:
        """Send a message to a single client."""
        message = json.dumps(
            {
                "event": event_type.value,
                "data": data,
                "timestamp": datetime.utcnow().isoformat(),
            },
            default=str,
        )
        await websocket.send_text(message)

    @property
    def active_connections(self) -> int:
        return len(self._connections)


# Global singleton
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Main WebSocket endpoint.

    Clients can send JSON messages to subscribe/unsubscribe from topics::

        {"action": "subscribe", "topic": "trades"}
        {"action": "unsubscribe", "topic": "trades"}

    The server pushes events matching ``EventType`` as they occur.
    """
    await manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send_personal(
                    websocket,
                    EventType.SYSTEM_STATUS,
                    {"error": "Invalid JSON"},
                )
                continue

            action = msg.get("action")
            topic = msg.get("topic")

            if action == "subscribe" and topic:
                await manager.subscribe(websocket, topic)
                await manager.send_personal(
                    websocket,
                    EventType.SYSTEM_STATUS,
                    {"subscribed": topic},
                )
            elif action == "unsubscribe" and topic:
                await manager.unsubscribe(websocket, topic)
                await manager.send_personal(
                    websocket,
                    EventType.SYSTEM_STATUS,
                    {"unsubscribed": topic},
                )
            elif action == "ping":
                await manager.send_personal(
                    websocket,
                    EventType.SYSTEM_STATUS,
                    {"pong": True},
                )
            else:
                await manager.send_personal(
                    websocket,
                    EventType.SYSTEM_STATUS,
                    {"error": f"Unknown action: {action}"},
                )
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
