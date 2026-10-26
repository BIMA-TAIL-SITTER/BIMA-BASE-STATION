"""Persistent, single-reader real MAVLink links to the two companions."""
from __future__ import annotations

import asyncio
import copy
import logging
import time
import uuid

from mission_scripts.swarm_protocol import (
    COMPONENT, PAYLOAD_TYPE, PROTOCOL, Reassembler, SLOTS, distance_m, send_packet, valid_position,
)

logger = logging.getLogger(__name__)

# Peer freshness is budgeted at 2 s end to end; keep the echo granularity small.
HEARTBEAT_INTERVAL_S = 0.2


def en_route_task(state):
    """Which assignment the peer is flying, so right of way is re-decided on change."""
    task = state.get("task") or {}
    return task.get("task_id") if task.get("status") == "EN_ROUTE" else None


def remaining_m(state):
    """Distance a UAV still has to fly, so each companion can resolve right of way.

    Only this side knows both assignments, and a stopped UAV counts as arrived.
    """
    task = state.get("task") or {}
    target = task.get("target")
    if task.get("status") != "EN_ROUTE" or not isinstance(target, dict):
        return 0.0
    if not valid_position(state.get("lat"), state.get("lon")):
        return None
    return distance_m(state["lat"], state["lon"], target["lat"], target["lon"])


class SwarmLink:
    def __init__(self, key, timeout=3.0):
        self.key = key
        self.timeout = timeout
        self.session = uuid.uuid4().hex
        self.connections = {}
        self.endpoints = {}
        self.states = {}
        self.received = {}
        self.boots = {}
        self.sequences = {}
        self.parsers = {}
        self.waiters = {}
        self.task = None
        self.counter = 0
        self.command_seq = 0
        self.command_bodies = {}
        self.retired_boots = {slot: set() for slot in SLOTS}
        self.heartbeat_sent = {}
        self.transit_bound = {}

    def configure(self, endpoints):
        from pymavlink import mavutil
        from pymavlink.dialects.v20 import common

        if len(self.key) < 32:
            raise ValueError("Configure SWARM_LINK_KEY (minimum 32 characters)")
        for slot in SLOTS:
            endpoint = endpoints.get(slot, endpoints.get(str(slot)))
            if self.endpoints.get(slot) == endpoint:
                continue
            if slot in self.connections:
                self.connections[slot].close()
            connection = mavutil.mavlink_connection(
                f"udpout:{endpoint['host']}:{endpoint['port']}",
                source_system=255, source_component=190,
            )
            # Explicit v2 dialect: TUNNEL must work regardless of import order.
            connection.mav = common.MAVLink(connection, srcSystem=255, srcComponent=190)
            self.connections[slot] = connection
            self.endpoints[slot] = dict(endpoint)
            self.parsers[slot] = Reassembler(self.key)
            self.states.pop(slot, None)
            self.received.pop(slot, None)
            self.boots.pop(slot, None)
            self.sequences.pop(slot, None)

    async def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self._loop(), name="swarm-companion-links")

    def snapshot(self, slot):
        state = copy.deepcopy(self.states.get(slot, {}))
        age = time.monotonic() - self.received.get(slot, 0)
        state.update(drone_id=slot, connected=age <= 2.0, link_age_s=age if slot in self.received else None)
        for field in ("heartbeat_age_s", "position_age_s", "gps_age_s", "health_age_s"):
            value = state.get(field)
            state[field] = value + age + self.transit_bound.get(slot, 0) if value is not None else None
        return state

    def send(self, slot, payload):
        body = dict(payload, protocol=PROTOCOL, session_id=self.session, drone_id=slot)
        send_packet(self.connections[slot], slot, body, self.key)

    async def request(self, slot, kind, *, command_id=None, **payload):
        if slot not in self.connections:
            raise ConnectionError(f"UAV-{slot}: companion endpoint not configured")
        if slot not in self.boots:
            deadline = time.monotonic() + self.timeout
            while slot not in self.boots and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            if slot not in self.boots:
                raise TimeoutError(f"UAV-{slot}: swarm-v1 capability handshake timed out")
        ident = command_id or uuid.uuid4().hex
        base = dict(payload, kind=kind, command_id=ident, boot_id=self.boots[slot])
        body = self.command_bodies.get((slot, ident))
        if body:
            if {k: v for k, v in body.items() if k != "command_seq"} != base:
                raise ValueError("command_id reused with a different payload/companion boot")
        else:
            self.command_seq += 1
            body = dict(base, command_seq=self.command_seq)
            self.command_bodies[(slot, ident)] = body
        if (slot, ident) in self.waiters:
            raise ValueError("Command is already in flight")
        future = asyncio.get_running_loop().create_future()
        self.waiters[(slot, ident)] = (future, body)
        started = time.monotonic()
        try:
            for _ in range(3):
                self.send(slot, body)
                try:
                    reply = await asyncio.wait_for(asyncio.shield(future), self.timeout)
                    if not reply.get("accepted"):
                        raise ValueError(f"UAV-{slot}: {reply.get('error', 'command rejected')}")
                    return dict(reply, latency_ms=round((time.monotonic() - started) * 1000))
                except asyncio.TimeoutError:
                    pass
            raise TimeoutError(f"UAV-{slot}: {kind} ACK timeout (execution unknown)")
        finally:
            self.waiters.pop((slot, ident), None)
            if not future.done():
                future.cancel()

    def _receive(self, slot, message):
        if (message.get_type() != "TUNNEL" or message.payload_type != PAYLOAD_TYPE
                or message.get_srcSystem() != slot or message.get_srcComponent() != COMPONENT
                or message.target_system != 255 or message.target_component != 190):
            return
        body = self.parsers[slot].feed(bytes(message.payload[:message.payload_length]))
        if not body or body.get("session_id") != self.session or body.get("drone_id") != slot:
            return
        if body.get("kind") == "STATE":
            boot = body.get("boot_id")
            if not isinstance(boot, str) or boot in self.retired_boots[slot]:
                return
            seq = body.get("state_seq", -1)
            if boot == self.boots.get(slot) and seq <= self.sequences.get(slot, -1):
                return
            # A reboot invalidates all pending commands. No automatic re-execution.
            if slot in self.boots and boot != self.boots[slot]:
                self.retired_boots[slot].add(self.boots[slot])
                for (owner, _), (future, _) in list(self.waiters.items()):
                    if owner == slot and not future.done():
                        future.set_exception(ConnectionError(f"UAV-{slot}: companion restarted"))
            self.boots[slot] = boot
            self.sequences[slot] = seq
            self.states[slot] = body
            self.received[slot] = time.monotonic()
            echoed_at = self.heartbeat_sent.get(body.get("gcs_counter"))
            # Round-trip upper bound detects delayed signed snapshots without
            # relying on synchronized wall clocks between Pi and base station.
            self.transit_bound[slot] = time.monotonic() - echoed_at if echoed_at is not None else 999.0
        elif body.get("kind") == "ACK":
            waiter = self.waiters.get((slot, body.get("command_id")))
            if waiter:
                future, sent = waiter
                if (body.get("boot_id") == sent["boot_id"] and body.get("operation") == sent["kind"]
                        and body.get("mission_id") == sent.get("mission_id")
                        and body.get("version") == sent.get("version") and not future.done()):
                    future.set_result(body)

    async def _loop(self):
        heartbeat_at = 0.0
        try:
            while True:
                now = time.monotonic()
                if now >= heartbeat_at:
                    self.counter += 1
                    self.heartbeat_sent[self.counter] = now
                    self.heartbeat_sent = {k: v for k, v in self.heartbeat_sent.items() if now - v <= 10}
                    for slot in list(self.connections):
                        peer = self.snapshot(4 if slot == 3 else 3)
                        # Only the fields consumed by the local safety controller.
                        peer = dict({k: peer.get(k) for k in (
                            "drone_id", "connected", "lat", "lon", "alt_msl_m", "alt_m",
                            "vx", "vy", "vz", "position_age_s", "heartbeat_age_s")},
                            remaining_m=remaining_m(peer), task_id=en_route_task(peer))
                        try:
                            self.send(slot, {"kind": "HELLO", "counter": self.counter})
                            if slot in self.boots:
                                self.send(slot, {"kind": "GCS_HEARTBEAT", "boot_id": self.boots[slot],
                                                 "counter": self.counter, "peer": peer})
                        except OSError:
                            logger.debug("UAV-%s UDP send unavailable; awaiting reconnect", slot, exc_info=True)
                    heartbeat_at = now + HEARTBEAT_INTERVAL_S
                for slot, connection in list(self.connections.items()):
                    try:
                        for _ in range(100):
                            message = connection.recv_match(blocking=False)
                            if message is None:
                                break
                            self._receive(slot, message)
                    except OSError:
                        # ICMP port-unreachable (notably Windows 10054) must not
                        # permanently kill the receiver. Freshness still expires.
                        logger.debug("UAV-%s UDP receive unavailable; awaiting reconnect", slot, exc_info=True)
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A dead receive loop must also stop heartbeats, invoking local failsafe.
            logger.exception("Swarm transport stopped; companion watchdog remains authoritative")

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        for connection in self.connections.values():
            connection.close()
        self.connections.clear()
