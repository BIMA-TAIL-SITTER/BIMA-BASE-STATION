import socket
import json
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

class UdpTelemetryReceiver:
    def __init__(self, host: str = "0.0.0.0", port: int = 5005):
        self._host = host
        self._port = port
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._latest_data = {}
        self._lock = threading.Lock()

    def start(self):
        if self._running.is_set():
            return
        
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((self._host, self._port))
            self._sock.settimeout(0.5)
            logger.info("UdpTelemetryReceiver listening on %s:%d", self._host, self._port)
        except Exception as e:
            logger.error("Failed to bind UDP telemetry on port %d: %s", self._port, e)
            return

        self._running.set()
        self._thread = threading.Thread(target=self._receive_loop, daemon=True, name="udp-telem")
        self._thread.start()

    def stop(self):
        self._running.clear()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("UdpTelemetryReceiver stopped.")

    def _receive_loop(self):
        logger.debug("UDP Telemetry loop started")
        while self._running.is_set():
            try:
                data, addr = self._sock.recvfrom(4096)
                if not data:
                    continue
                
                json_str = data.decode("utf-8")
                parsed = json.loads(json_str)
                
                with self._lock:
                    self._latest_data = parsed
                    self._latest_data["_received_at"] = time.time()
                    
            except socket.timeout:
                continue
            except json.JSONDecodeError:
                logger.debug("Failed to decode telemetry JSON")
            except OSError:
                break
            except Exception as e:
                logger.debug("UDP Telemetry error: %s", e)
        logger.debug("UDP Telemetry loop exited")

    @property
    def latest_data(self) -> dict:
        with self._lock:
            return dict(self._latest_data)
