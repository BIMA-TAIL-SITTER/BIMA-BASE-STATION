"""
MAVLink Interfaces
──────────────────
Abstract base classes and data contracts for future MAVLink integration.

HOW TO USE:
  1. Install `pymavlink` and add it to requirements.txt.
  2. Create `services/mavlink/connection.py` that subclasses MAVLinkConnection.
  3. Create `services/mavlink/telemetry_bridge.py` that subclasses
     MAVLinkTelemetryBridge and replaces TelemetryGenerator.
  4. Wire the concrete implementations into main.py via dependency injection.

Nothing in this file executes any MAVLink code.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Optional


# ─── Data Contracts ──────────────────────────────────────────────────────────

@dataclass
class VehicleIdentity:
    system_id: int
    component_id: int
    autopilot_type: str
    vehicle_type: str
    firmware_version: str


@dataclass
class MissionItem:
    seq: int
    frame: int
    command: int
    current: bool
    autocontinue: bool
    param1: float
    param2: float
    param3: float
    param4: float
    x: float  # latitude or local x
    y: float  # longitude or local y
    z: float  # altitude or local z


# ─── Abstract Interfaces ─────────────────────────────────────────────────────

class MAVLinkConnection(abc.ABC):
    """
    Manages the physical or virtual link to a MAVLink autopilot.

    Implementations can use:
      - Serial (USB / UART)  — pymavlink mavutil.mavlink_connection("COM3", baud=57600)
      - UDP                  — pymavlink mavutil.mavlink_connection("udp:0.0.0.0:14550")
      - TCP                  — pymavlink mavutil.mavlink_connection("tcp:127.0.0.1:5760")
    """

    @abc.abstractmethod
    async def connect(self) -> None:
        """Open the connection and wait for heartbeat."""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Close the connection cleanly."""

    @abc.abstractmethod
    def is_connected(self) -> bool:
        """Return True if the link is currently up."""

    @abc.abstractmethod
    async def send_message(self, message: Any) -> None:
        """Send a raw MAVLink message object."""

    @abc.abstractmethod
    async def recv_match(
        self,
        msg_type: str,
        blocking: bool = False,
        timeout: Optional[float] = None,
    ) -> Optional[Any]:
        """
        Receive the next message of the given type.

        Parameters
        ----------
        msg_type:
            MAVLink message name, e.g. ``"HEARTBEAT"``, ``"GPS_RAW_INT"``.
        blocking:
            If True, wait until a message arrives or timeout is reached.
        timeout:
            Maximum seconds to wait (None = no timeout).
        """


class MAVLinkTelemetryBridge(abc.ABC):
    """
    Reads MAVLink messages and converts them to the ground station's
    internal TelemetryPacket format.

    Replace TelemetryGenerator with a concrete subclass of this class
    once a real autopilot is available.
    """

    @abc.abstractmethod
    async def broadcast_loop(self) -> None:
        """Continuously read telemetry and broadcast to WebSocket clients."""

    @abc.abstractmethod
    def get_latest(self) -> Optional[dict]:
        """Return the most-recently received telemetry snapshot as a dict."""


class MAVLinkMissionManager(abc.ABC):
    """Upload, download, and monitor flight missions."""

    @abc.abstractmethod
    async def upload_mission(self, items: list[MissionItem]) -> bool:
        """
        Upload a list of mission items to the autopilot.

        Returns True on success, False on failure or timeout.
        """

    @abc.abstractmethod
    async def download_mission(self) -> list[MissionItem]:
        """Download the current mission from the autopilot."""

    @abc.abstractmethod
    async def clear_mission(self) -> bool:
        """Clear the mission stored on the autopilot."""

    @abc.abstractmethod
    async def set_current_waypoint(self, seq: int) -> None:
        """Jump to the given waypoint index."""


class MAVLinkCommandSender(abc.ABC):
    """Send MAVLink long commands and wait for ACK."""

    @abc.abstractmethod
    async def arm(self, force: bool = False) -> bool:
        """Arm the vehicle. Returns True if ACK received."""

    @abc.abstractmethod
    async def disarm(self, force: bool = False) -> bool:
        """Disarm the vehicle. Returns True if ACK received."""

    @abc.abstractmethod
    async def set_mode(self, mode: str) -> bool:
        """
        Change the flight mode.

        `mode` should be a string recognised by the autopilot, e.g.
        ``"STABILIZE"``, ``"LOITER"``, ``"AUTO"``, ``"RTL"``.
        Returns True if ACK received.
        """

    @abc.abstractmethod
    async def takeoff(self, altitude_m: float) -> bool:
        """Command a takeoff to the given altitude. Returns True if ACK received."""

    @abc.abstractmethod
    async def return_to_launch(self) -> bool:
        """Command RTL. Returns True if ACK received."""
