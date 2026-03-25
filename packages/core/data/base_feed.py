"""Abstract base class for market data feeds."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Awaitable, Callable, Optional

from packages.core.models import NormalizedSignal


class BaseDataFeed(ABC):
    """Common interface for all market data sources.

    Concrete implementations wrap a specific provider (WebSocket stream,
    REST poller, on-chain listener, etc.) and expose data through
    :py:meth:`get_latest` or the push-based :py:meth:`subscribe` callback.
    """

    def __init__(self) -> None:
        self._connected: bool = False
        self._last_update_time: Optional[datetime] = None
        self._subscribers: list[Callable[[list[NormalizedSignal]], Awaitable[None]]] = []

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def connect(self) -> None:
        """Establish a connection to the data source.

        Implementations must set :py:attr:`_connected` to ``True`` on
        success.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully tear down the connection.

        Implementations must set :py:attr:`_connected` to ``False``.
        """

    # ------------------------------------------------------------------
    # Data retrieval
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_latest(self) -> list[NormalizedSignal]:
        """Return the most recent batch of normalized signals.

        Implementations should update :py:attr:`_last_update_time` each
        time fresh data is returned.
        """

    # ------------------------------------------------------------------
    # Push-based subscription
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        callback: Callable[[list[NormalizedSignal]], Awaitable[None]],
    ) -> None:
        """Register *callback* to be invoked whenever new data arrives.

        Parameters
        ----------
        callback:
            An async callable that receives a list of ``NormalizedSignal``.
        """
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    async def _notify_subscribers(self, signals: list[NormalizedSignal]) -> None:
        """Fan-out *signals* to every registered subscriber."""
        for cb in self._subscribers:
            try:
                await cb(signals)
            except Exception:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).exception(
                    "Subscriber %r raised an exception", cb
                )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """Whether the feed currently has an active connection."""
        return self._connected

    @property
    def last_update_time(self) -> Optional[datetime]:
        """Timestamp of the last data update, or ``None`` if no data yet."""
        return self._last_update_time
