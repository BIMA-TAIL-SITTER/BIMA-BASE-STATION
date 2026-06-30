import asyncio
import logging
from typing import Any, Optional

import os
os.environ["MAVLINK20"] = "1"

# pyrefly: ignore [missing-import]
from pymavlink import mavutil

from app.services.mavlink.interfaces import MAVLinkConnection

logger = logging.getLogger(__name__)


class MavlinkTCPConnection(MAVLinkConnection):
    """
    Implementation of MAVLinkConnection for TCP.
    """
    def __init__(self, ip: str, port: int) -> None:
        self.ip = ip
        self.port = port
        self.conn_str = f"tcp:{ip}:{port}"
        self._master: Optional[mavutil.mavfile] = None

    async def connect(self) -> None:
        logger.info("Connecting to MAVLink at %s", self.conn_str)
        
        def _blocking_connect():
            # Pass retries=0 to prevent pymavlink from internally sleeping and retrying on refused connections
            self._master = mavutil.mavlink_connection(self.conn_str, retries=0)
            logger.info("Waiting for heartbeat from %s...", self.conn_str)
            # Short timeout on heartbeat wait so we don't hang if connected but no data
            hb = self._master.wait_heartbeat(timeout=2.0)
            if not hb:
                raise TimeoutError("Heartbeat timeout")
                
        try:
            # Use asyncio.wait instead of wait_for.
            # wait_for blocks until the task is cancelled, but thread tasks cannot be cancelled,
            # so wait_for would block the event loop for the full duration of the OS socket timeout!
            task = asyncio.create_task(asyncio.to_thread(_blocking_connect))
            done, pending = await asyncio.wait([task], timeout=3.0)
            
            if not done:
                # Timed out! The thread is orphaned and will die naturally in the background.
                # Consume its exception silently when it finishes to prevent asyncio warnings.
                task.add_done_callback(lambda t: t.exception())
                raise TimeoutError("Connection timed out (host unreachable)")
                
            # If done, raise exception if any occurred
            if task.exception():
                raise task.exception()
                
            logger.info("Heartbeat received from %s!", self.conn_str)
        except Exception as e:
            logger.error("Failed to connect to %s: %s", self.conn_str, e)
            if self._master:
                try:
                    self._master.close()
                except Exception:
                    pass
            self._master = None
            raise

    async def disconnect(self) -> None:
        if self._master:
            try:
                self._master.close()
            except Exception:
                pass
            self._master = None
            logger.info("Disconnected from %s", self.conn_str)

    def is_connected(self) -> bool:
        return self._master is not None

    async def send_message(self, message: Any) -> None:
        if self._master:
            self._master.mav.send(message)

    async def recv_match(
        self,
        msg_type: str,
        blocking: bool = False,
        timeout: Optional[float] = None,
    ) -> Optional[Any]:
        if not self._master:
            return None
        
        if blocking:
            return await asyncio.to_thread(
                self._master.recv_match,
                type=msg_type,
                blocking=True,
                timeout=timeout
            )
        else:
            return self._master.recv_match(type=msg_type, blocking=False)
            
    def recv_msg(self) -> Optional[Any]:
        """Non-blocking read of the next available MAVLink message."""
        if not self._master:
            return None
        return self._master.recv_msg()
