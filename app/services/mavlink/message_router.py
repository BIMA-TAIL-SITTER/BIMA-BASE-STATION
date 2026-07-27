"""
Single-owner MAVLink receive router.

Every physical connection is read by exactly one ``receive_loop``. Messages
are then fanned out to long-lived handlers (telemetry and parameter cache) and
short-lived futures used by request/response protocols (mission and PARAM_SET).
No consumer is allowed to call ``recv_msg`` or ``recv_match`` directly.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Collection, Mapping, Optional

from app.services.mavlink.interfaces import MAVLinkConnection

logger = logging.getLogger(__name__)

ConnectionRegistry = Mapping[int, Optional[MAVLinkConnection]]
MessageHandler = Callable[[int, Any], Awaitable[None]]
MessagePredicate = Callable[[Any], bool]


class MavlinkRoutingError(RuntimeError):
    """Base exception raised by the shared receive router."""


class MavlinkNotConnectedError(MavlinkRoutingError):
    """Raised when a transaction targets a disconnected UAV slot."""


@dataclass
class _MessageWaiter:
    message_types: frozenset[str]
    predicate: Optional[MessagePredicate]
    future: asyncio.Future[Any]


class MavlinkMessageRouter:
    """Own per-slot reads and distribute messages without queue contention."""

    def __init__(self, connections: ConnectionRegistry) -> None:
        self._connections = connections
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._waiters: dict[int, list[_MessageWaiter]] = {
            slot: [] for slot in connections
        }
        self._transaction_locks: dict[int, asyncio.Lock] = {
            slot: asyncio.Lock() for slot in connections
        }
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._running = False

    def register_handler(
        self,
        message_types: Collection[str],
        handler: MessageHandler,
    ) -> None:
        """Register an async handler for message names or the ``"*"`` wildcard."""
        for message_type in message_types:
            handlers = self._handlers.setdefault(message_type, [])
            if handler not in handlers:
                handlers.append(handler)

    def unregister_handler(self, handler: MessageHandler) -> None:
        """Remove a handler from every message-type registration."""
        for handlers in self._handlers.values():
            while handler in handlers:
                handlers.remove(handler)

    def get_connection(self, slot: int) -> MAVLinkConnection:
        """Return a connected slot or raise a transaction-friendly error."""
        connection = self._connections.get(slot)
        if connection is None or not connection.is_connected():
            raise MavlinkNotConnectedError(
                f"UAV slot {slot} has no active MAVLink connection",
            )
        return connection

    def transaction_lock(self, slot: int) -> asyncio.Lock:
        """Serialize mission and parameter request/response transactions."""
        try:
            return self._transaction_locks[slot]
        except KeyError as exc:
            raise MavlinkRoutingError(f"Unknown UAV slot {slot}") from exc

    def expect(
        self,
        slot: int,
        message_types: Collection[str],
        predicate: Optional[MessagePredicate] = None,
    ) -> asyncio.Future[Any]:
        """
        Register a future before sending a request to avoid response races.

        The caller owns timeout handling with ``asyncio.wait_for``. A timed-out
        future is automatically removed from the waiter collection.
        """
        if slot not in self._waiters:
            raise MavlinkRoutingError(f"Unknown UAV slot {slot}")
        future = asyncio.get_running_loop().create_future()
        waiter = _MessageWaiter(
            message_types=frozenset(message_types),
            predicate=predicate,
            future=future,
        )
        self._waiters[slot].append(waiter)
        future.add_done_callback(
            lambda _future: self._remove_waiter(slot, waiter),
        )
        return future

    def cancel_slot_waiters(self, slot: int, reason: str) -> None:
        """Fail all pending request/response operations for a disconnected slot."""
        for waiter in list(self._waiters.get(slot, [])):
            if not waiter.future.done():
                waiter.future.set_exception(MavlinkRoutingError(reason))

    async def start(self) -> None:
        """Start one receive-loop task for every configured UAV slot."""
        if self._running:
            return
        self._running = True
        self._tasks = {
            slot: asyncio.create_task(
                self.receive_loop(slot),
                name=f"mavlink-receive-slot-{slot}",
            )
            for slot in self._connections
        }

    async def receive_loop(self, slot: int) -> None:
        """Continuously drain one slot's non-blocking receive queue."""
        previous_connection = self._connections.get(slot)
        try:
            while self._running:
                connection = self._connections.get(slot)
                if connection is not previous_connection:
                    if previous_connection is not None:
                        self.cancel_slot_waiters(
                            slot,
                            f"MAVLink connection for slot {slot} changed",
                        )
                    previous_connection = connection

                if connection is None or not connection.is_connected():
                    await asyncio.sleep(0.05)
                    continue

                received = 0
                while self._running and received < 100:
                    message = connection.recv_msg()
                    if message is None:
                        break
                    received += 1
                    await self.dispatch(slot, message)

                await asyncio.sleep(0 if received else 0.01)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("MAVLink receive loop failed for slot %d", slot)
            self.cancel_slot_waiters(
                slot,
                f"MAVLink receive loop failed for slot {slot}",
            )

    async def dispatch(self, slot: int, message: Any) -> None:
        """Notify stream handlers, then resolve matching transaction futures."""
        message_type = message.get_type()
        matched_waiters: list[_MessageWaiter] = []

        for waiter in list(self._waiters.get(slot, [])):
            if waiter.future.done() or message_type not in waiter.message_types:
                continue
            try:
                matches = (
                    waiter.predicate(message)
                    if waiter.predicate is not None
                    else True
                )
            except Exception as exc:
                waiter.future.set_exception(exc)
                continue
            if matches:
                matched_waiters.append(waiter)

        handlers: list[MessageHandler] = []
        seen: set[int] = set()
        for registered in (
            self._handlers.get(message_type, []),
            self._handlers.get("*", []),
        ):
            for handler in registered:
                handler_id = id(handler)
                if handler_id not in seen:
                    handlers.append(handler)
                    seen.add(handler_id)

        if handlers:
            results = await asyncio.gather(
                *(handler(slot, message) for handler in handlers),
                return_exceptions=True,
            )
            for handler, result in zip(handlers, results):
                if isinstance(result, Exception):
                    logger.error(
                        "MAVLink handler %r failed for %s on slot %d: %s",
                        handler,
                        message_type,
                        slot,
                        result,
                    )

        for waiter in matched_waiters:
            if not waiter.future.done():
                waiter.future.set_result(message)

    async def stop(self) -> None:
        """Stop receive loops and cancel unresolved transactions."""
        if not self._running and not self._tasks:
            return
        self._running = False
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        for waiters in self._waiters.values():
            for waiter in list(waiters):
                if not waiter.future.done():
                    waiter.future.cancel()

    def _remove_waiter(self, slot: int, waiter: _MessageWaiter) -> None:
        waiters = self._waiters.get(slot)
        if waiters is not None and waiter in waiters:
            waiters.remove(waiter)
