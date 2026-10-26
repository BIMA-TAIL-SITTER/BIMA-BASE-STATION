"""BIMA swarm v1 over MAVLink 2 TUNNEL (private payload type 32768).

Shared by GCS and companion. No flight commands in the plan-sync transport.
See docs/SWARM_IMPLEMENTATION.md for framing, authentication and deployment.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import struct
import time

PROTOCOL = 1
PAYLOAD_TYPE = 32768
COMPONENT = 191
SLOTS = (3, 4)
HEADER = struct.Struct("!2s8sHH")
CHUNK_SIZE = 128 - HEADER.size
MAX_CHUNKS = 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def frames(body, key):
    if len(key) < 32:
        raise ValueError("SWARM_LINK_KEY must contain at least 32 characters")
    data = canonical({"body": body, "mac": hmac.new(key.encode(), canonical(body), "sha256").hexdigest()})
    ident = hashlib.sha256(data).digest()[:8]
    total = math.ceil(len(data) / CHUNK_SIZE)
    if total > MAX_CHUNKS:
        raise ValueError("Swarm packet too large")
    return [HEADER.pack(b"S1", ident, i, total) + data[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE]
            for i in range(total)]


class Reassembler:
    def __init__(self, key):
        self.key = key
        self.pending = {}

    def feed(self, payload):
        now = time.monotonic()
        self.pending = {k: v for k, v in self.pending.items() if now - v[0] < 5}
        if len(payload) <= HEADER.size:
            return None
        magic, ident, index, count = HEADER.unpack(payload[:HEADER.size])
        if magic != b"S1" or not 0 <= index < count <= MAX_CHUNKS:
            return None
        if ident not in self.pending:
            if len(self.pending) >= 16:
                return None
            self.pending[ident] = (now, count, {})
        _, expected, parts = self.pending[ident]
        if count != expected:
            return None
        parts[index] = payload[HEADER.size:]
        if len(parts) != count:
            return None
        del self.pending[ident]
        data = b"".join(parts[i] for i in range(count))
        if hashlib.sha256(data).digest()[:8] != ident:
            return None
        try:
            envelope = json.loads(data)
            body = envelope["body"]
            mac = hmac.new(self.key.encode(), canonical(body), "sha256").hexdigest()
            if not hmac.compare_digest(mac, envelope["mac"]) or body.get("protocol") != PROTOCOL:
                return None
            return body
        except (ValueError, KeyError, TypeError, AttributeError):
            return None


def send_packet(connection, target_system, body, key, target_component=COMPONENT):
    for payload in frames(body, key):
        connection.mav.tunnel_send(target_system, target_component, PAYLOAD_TYPE,
                                   len(payload), list(payload.ljust(128, b"\0")))


def atomic_json(path, value, attempts=5):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    # Windows virus scanners and editors hold brief handles that fail the rename.
    for attempt in range(attempts):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05)


def distance_m(lat1, lon1, lat2, lon2):
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, a))))


def valid_position(lat, lon):
    return (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
            and math.isfinite(lat) and math.isfinite(lon)
            and -90 <= lat <= 90 and -180 <= lon <= 180 and (lat, lon) != (0, 0))


def validate_target(wp, safety):
    lat, lon, alt = wp["lat"], wp["lon"], wp["alt_m"]
    if not valid_position(lat, lon) or not math.isfinite(alt):
        raise ValueError("Invalid waypoint coordinates/altitude")
    if not safety["min_alt_m"] <= alt <= safety["max_alt_m"]:
        raise ValueError("Waypoint altitude outside configured limits")
    if distance_m(lat, lon, safety["center_lat"], safety["center_lon"]) > safety["radius_m"]:
        raise ValueError("Waypoint outside site geofence")


def validate_safety(safety):
    required = ("center_lat", "center_lon", "radius_m", "min_alt_m", "max_alt_m",
                "takeoff_alt_m", "min_battery_pct", "min_separation_m")
    if any(not isinstance(safety.get(k), (int, float)) or not math.isfinite(safety[k]) for k in required):
        raise ValueError("Configure finite site geofence and safety limits first")
    if (not valid_position(safety["center_lat"], safety["center_lon"])
            or not 0 < safety["radius_m"] <= 10000
            or not 0 < safety["min_alt_m"] <= safety["takeoff_alt_m"] <= safety["max_alt_m"] <= 500
            or not 0 < safety["min_battery_pct"] <= 100 or safety["min_separation_m"] <= 0):
        raise ValueError("Invalid site safety configuration")
    apf_parameters(safety)


def apf_parameters(safety):
    # Avoidance engages when the predicted closest approach within prediction_horizon
    # seconds drops below hysteresis_enter_m, and releases above hysteresis_exit_m.
    values = dict(d_influence=30.0, k_att=1.0, k_rep=100.0, max_lateral_offset_m=20.0, tick_rate_hz=5.0,
                  hysteresis_enter_m=15.0, hysteresis_exit_m=20.0, prediction_horizon=4.0)
    overrides = safety.get("apf", {})
    if not isinstance(overrides, dict) or set(overrides) - set(values):
        raise ValueError("Unknown APF safety configuration")
    values.update(overrides)
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in values.values()):
        raise ValueError("APF parameters must be finite and positive")
    if not safety.get("min_separation_m", 0) < values["hysteresis_enter_m"] < values["hysteresis_exit_m"]:
        raise ValueError("APF needs min_separation_m < hysteresis_enter_m < hysteresis_exit_m")
    return {k: float(v) for k, v in values.items()}


def safety_hash(safety):
    # JSON 5 and 5.0 describe the same configured limit on GCS and companion.
    keys = ("center_lat", "center_lon", "radius_m", "min_alt_m", "max_alt_m",
            "takeoff_alt_m", "min_battery_pct", "min_separation_m")
    return digest(dict({k: float(safety[k]) for k in keys}, apf=apf_parameters(safety)))


def validate_plan(plan, safety):
    validate_safety(safety)
    if plan.get("coordinate_frame") != "GLOBAL_RELATIVE_ALT":
        raise ValueError("Only GLOBAL_RELATIVE_ALT is supported")
    items = plan.get("waypoints", [])
    if not 1 <= len(items) <= 200:
        raise ValueError("Plan must contain 1..200 waypoints")
    if len({w["task_id"] for w in items}) != len(items):
        raise ValueError("Duplicate task_id")
    if [w["sequence"] for w in items] != list(range(1, len(items) + 1)):
        raise ValueError("Waypoint sequence must be contiguous from 1")
    for wp in items:
        validate_target(wp, safety)


def validate_append(previous, candidate, base_version, base_hash, safety):
    """An airborne revision can only extend an identical committed prefix."""
    validate_plan(candidate, safety)
    if (candidate.get("mission_id") != previous.get("mission_id")
            or candidate.get("version") != base_version + 1):
        raise ValueError("Append mission/version mismatch")
    # A retry after a lost ACK is harmless, including after companion restart.
    if candidate == previous:
        return
    if previous.get("version") != base_version or digest(previous) != base_hash:
        raise ValueError("Append base plan/version/hash mismatch")
    if ({k: v for k, v in candidate.items() if k not in ("version", "waypoints")}
            != {k: v for k, v in previous.items() if k not in ("version", "waypoints")}):
        raise ValueError("Append cannot change mission settings")
    old = previous["waypoints"]
    if len(candidate["waypoints"]) <= len(old) or candidate["waypoints"][:len(old)] != old:
        raise ValueError("Append cannot edit, delete, or reorder existing waypoints")


def health_errors(state, safety, max_age=2.0, airborne=False):
    errors = []
    for field in ("heartbeat_age_s", "position_age_s", "gps_age_s", "health_age_s"):
        age = state.get(field)
        if age is None or not math.isfinite(age) or not 0 <= age <= max_age:
            errors.append(f"stale {field}")
    if not valid_position(state.get("lat"), state.get("lon")) or state.get("gps_fix", 0) < 3:
        errors.append("invalid GPS")
    if state.get("battery_pct", -1) < safety["min_battery_pct"]:
        errors.append("battery below limit/unknown")
    if not state.get("sensors_ok", False) or state.get("system_status", 0) >= 5:
        errors.append("FC health/failsafe")
    if airborne and (not state.get("armed") or state.get("mode") != "GUIDED"):
        errors.append("not armed in GUIDED")
    if valid_position(state.get("lat"), state.get("lon")):
        if distance_m(state["lat"], state["lon"], safety["center_lat"], safety["center_lon"]) > safety["radius_m"]:
            errors.append("outside site geofence")
    return errors
