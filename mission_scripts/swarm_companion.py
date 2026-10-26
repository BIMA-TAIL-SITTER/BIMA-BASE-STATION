"""Assignment-only GUIDED engine. One thread owns all FC and GCS reads/writes.

The existing legacy bridge is selected separately with --mission-mode legacy.
This engine reuses the repository's APF math; no simulated telemetry or ACKs.
"""
from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path

from pymavlink import mavutil
from pymavlink.dialects.v20 import common

from app.services.mavlink.apf_coordinator import APFConfig, APFEngine, UAVState
from mission_scripts.swarm_protocol import (
    COMPONENT, PAYLOAD_TYPE, PROTOCOL, Reassembler, apf_parameters, atomic_json, digest, distance_m,
    health_errors, safety_hash, send_packet, valid_position, validate_append, validate_plan, validate_safety,
    validate_target,
)

PEER_MAX_AGE_S = 2.0
# Operator HOLD and fault hold both stay in GUIDED and brake on the spot. LOITER
# tracks the pilot throttle stick, which companion-driven flight never supplies.
HOLD_MODE = "GUIDED"
# Right of way: the UAV with less distance left to its own waypoint holds while the
# other flies on. Within this margin the lower slot keeps moving, as in udp_com.py.
YIELD_TIE_M = 2.0
# Faster than the 2 s budget above, so normal jitter never exhausts it.
PUBLISH_INTERVAL_S = 0.2
ARM_COMMAND = common.MAV_CMD_COMPONENT_ARM_DISARM
TAKEOFF_COMMAND = common.MAV_CMD_NAV_TAKEOFF


class SwarmCompanion:
    def __init__(self, fc, gcs, slot, key, safety, journal, config):
        validate_safety(safety)
        if slot not in (3, 4) or len(key) < 32:
            raise ValueError("Swarm requires --uav-id 3 or 4 and SWARM_LINK_KEY >=32 characters")
        self.fc, self.gcs, self.slot, self.key = fc, gcs, slot, key
        self.safety, self.journal, self.config = safety, Path(journal), config
        self.boot = uuid.uuid4().hex
        self.parser = Reassembler(key)
        self.session = None
        self.counter = -1
        self.last_command_seq = -1
        self.state_seq = 0
        self.last_gcs = 0.0
        self.peer = {}
        self.received = {}
        self.telemetry = {}
        self.home = None
        self.phase = "IDLE"
        self.plan = None
        self.task = None
        self.commands = {}
        self.pending_mode = None
        self.stage_at = time.monotonic()
        self.stable_since = None
        self.hold_target = None
        self.error = ""
        self.command_acks = {}
        self.last_setpoint = 0.0
        self.loiter_retry_at = 0.0
        self.apf_status = {}
        self.apf_at = 0.0
        self.apf_target = None
        self.yield_role = None
        self.yield_target = None
        self.yield_key = None
        self.link_error = ""
        self.journal_error = ""
        self.apf_corrected = None
        self.apf = APFEngine(APFConfig(
            d_safe=safety["min_separation_m"], altitude_floor_m=safety["min_alt_m"],
            altitude_ceiling_m=safety["max_alt_m"], **apf_parameters(safety),
        ))
        if self.journal.exists():
            saved = json.loads(self.journal.read_text())
            self.plan = saved.get("plan")
            self.task = saved.get("task")
            self.commands = saved.get("commands", {})
            if saved.get("phase") not in ("IDLE", "COMPLETED"):
                self.phase = "FAULT"
                self.error = "Companion restarted; HOLD/abort and reconciliation required"
                if self.task and self.task["status"] not in ("REACHED", "CANCELLED"):
                    self.task["status"] = "UNKNOWN"

    def persist(self):
        try:
            atomic_json(self.journal, {"plan": self.plan, "task": self.task,
                                       "commands": self.commands, "phase": self.phase})
            self.journal_error = ""
        except OSError as exc:
            # Losing the journal costs restart deduplication, not the aircraft, so
            # hold from tick() instead of killing the only thread that flies it.
            self.journal_error = f"journal write failed: {exc}"

    def snapshot(self):
        now = time.monotonic()
        state = dict(self.telemetry)
        for key, kind in (("heartbeat", "HEARTBEAT"), ("position", "GLOBAL_POSITION_INT"),
                          ("gps", "GPS_RAW_INT"), ("health", "SYS_STATUS")):
            state[key + "_age_s"] = now - self.received[kind] if kind in self.received else None
        state.update(phase=self.phase, task=self.task, home=self.home, error=self.error,
                     capabilities=["PLAN_APPEND"],
                     gcs_counter=self.counter,
                     safety_hash=safety_hash(self.safety),
                     mission_id=self.plan["mission_id"] if self.plan else None,
                     version=self.plan["version"] if self.plan else None,
                     plan_hash=digest(self.plan) if self.plan else None, apf=self.apf_status or None)
        return state

    def reply(self, body):
        send_packet(self.gcs, 255, dict(body, protocol=PROTOCOL, drone_id=self.slot,
                    boot_id=self.boot, session_id=self.session), self.key, target_component=190)

    def publish(self):
        if self.session:
            self.state_seq += 1
            self.reply(dict(self.snapshot(), kind="STATE", state_seq=self.state_seq))

    def ack(self, request, accepted, error=""):
        response = {"kind": "ACK", "command_id": request["command_id"], "operation": request["kind"],
                    "mission_id": request.get("mission_id"), "version": request.get("version"),
                    "accepted": accepted, "error": error,
                    "plan_hash": digest(self.plan) if self.plan else None}
        self.commands[request["command_id"]] = {"fingerprint": digest(request), "response": response}
        self.persist()  # durable deduplication before ACK
        self.reply(response)

    def receive_fc(self, msg):
        if (msg.get_srcSystem() != self.fc.target_system
                or msg.get_srcComponent() != self.fc.target_component):
            return
        kind = msg.get_type()
        self.received[kind] = time.monotonic()
        t = self.telemetry
        if kind == "HEARTBEAT":
            t.update(armed=bool(msg.base_mode & 128), system_status=msg.system_status,
                     mode={0: "STABILIZE", 3: "AUTO", 4: "GUIDED", 5: "LOITER", 6: "RTL", 9: "LAND"}.get(msg.custom_mode, str(msg.custom_mode)))
        elif kind == "GLOBAL_POSITION_INT":
            t.update(lat=msg.lat / 1e7, lon=msg.lon / 1e7, alt_m=msg.relative_alt / 1000,
                     alt_msl_m=msg.alt / 1000, vx=msg.vx / 100, vy=msg.vy / 100, vz=msg.vz / 100,
                     heading_deg=msg.hdg / 100 if msg.hdg != 65535 else None)
        elif kind == "GPS_RAW_INT":
            t.update(gps_fix=msg.fix_type, satellites=msg.satellites_visible)
        elif kind == "SYS_STATUS":
            enabled = msg.onboard_control_sensors_enabled
            t.update(battery_pct=msg.battery_remaining,
                     sensors_ok=bool(enabled) and (enabled & msg.onboard_control_sensors_health) == enabled)
        elif kind == "HOME_POSITION":
            self.home = {"lat": msg.latitude / 1e7, "lon": msg.longitude / 1e7, "alt_msl_m": msg.altitude / 1000}
        elif kind == "COMMAND_ACK" and getattr(msg, "target_system", 0) in (0, self.fc.mav.srcSystem):
            self.command_acks[msg.command] = msg.result

    def set_mode(self, mode):
        self.fc.mav.set_mode_send(self.fc.target_system, 1, {"GUIDED": 4, "LOITER": 5, "RTL": 6, "LAND": 9}[mode])

    def command(self, command, *params):
        self.command_acks.pop(command, None)
        self.fc.mav.command_long_send(self.fc.target_system, self.fc.target_component,
                                      command, 0, *(list(params) + [0] * (7 - len(params))))

    def stage(self, phase):
        self.phase = phase
        self.stage_at = time.monotonic()
        self.stable_since = None
        self.persist()

    def peer_errors(self):
        peer = self.peer
        elapsed = time.monotonic() - self.last_gcs
        if not peer.get("connected"):
            return [f"peer telemetry stale (peer link down, gcs_gap={elapsed:.1f}s)"]
        # Name the age that overran its budget; the sum is normally far below it.
        overrun = [f"{label}=unknown" if peer.get(field) is None else f"{label}={peer[field] + elapsed:.1f}s"
                   for label, field in (("pos", "position_age_s"), ("hb", "heartbeat_age_s"))
                   if peer.get(field) is None or peer[field] + elapsed > PEER_MAX_AGE_S]
        if overrun:
            return [f"peer telemetry stale ({', '.join(overrun)} > {PEER_MAX_AGE_S}s"
                    f"; gcs_gap={elapsed:.1f}s)"]
        if "lat" not in self.telemetry:
            return ["own position missing"]
        separation = distance_m(self.telemetry["lat"], self.telemetry["lon"], peer["lat"], peer["lon"])
        # Use MSL altitude, not incompatible relative-home references.
        separation = math.hypot(separation, self.telemetry.get("alt_msl_m", 0) - peer.get("alt_msl_m", 0))
        return ["minimum UAV separation breached"] if separation < self.safety["min_separation_m"] else []

    def precheck(self, airborne=False):
        errors = health_errors(self.snapshot(), self.safety, airborne=airborne) + self.peer_errors()
        if self.home is None:
            errors.append("actual FC home unavailable")
        if time.monotonic() - self.last_gcs > self.config["gcs_heartbeat_timeout"]:
            errors.append("GCS heartbeat stale")
        if errors:
            raise ValueError("; ".join(errors))

    def receive_gcs(self, msg):
        if (msg.get_type() != "TUNNEL" or msg.payload_type != PAYLOAD_TYPE
                or msg.get_srcSystem() != 255 or msg.get_srcComponent() != 190
                or msg.target_system != self.slot or msg.target_component != COMPONENT):
            return
        req = self.parser.feed(bytes(msg.payload[:msg.payload_length]))
        if not req or req.get("drone_id") != self.slot:
            return
        kind = req.get("kind")
        if kind == "HELLO":
            if req.get("session_id") != self.session:
                if self.session and time.monotonic() - self.last_gcs <= self.config["gcs_heartbeat_timeout"]:
                    return
                if self.telemetry.get("armed"):
                    self.fail_hold("GCS session changed; reconciliation required")
                self.session = req["session_id"]
                self.counter = -1
                self.last_command_seq = -1
            self.publish()
            return
        if req.get("session_id") != self.session or req.get("boot_id") != self.boot:
            return
        if kind == "GCS_HEARTBEAT":
            if req.get("counter", -1) > self.counter:
                self.counter = req["counter"]
                self.last_gcs = time.monotonic()
                self.peer = req.get("peer", {})
            return
        if not isinstance(req.get("command_id"), str):
            return
        previous = self.commands.get(req["command_id"])
        if previous:
            if previous["fingerprint"] == digest(req):
                self.reply(previous["response"])
            return
        if self.pending_mode and self.pending_mode["request"]["command_id"] == req["command_id"]:
            return  # same in-flight command; ACK follows actual FC confirmation
        sequence = req.get("command_seq")
        if not isinstance(sequence, int) or sequence <= self.last_command_seq:
            self.ack(req, False, "Stale/out-of-order command sequence")
            return
        self.last_command_seq = sequence
        if self.pending_mode and kind not in ("ABORT", "HOLD"):
            self.ack(req, False, "Flight mode transition in progress")
            return
        try:
            self.handle_command(req)
        except (ValueError, KeyError, TypeError) as exc:
            self.ack(req, False, str(exc))

    def handle_command(self, req):
        kind = req["kind"]
        if kind == "PLAN_APPEND":
            plan = req["plan"]
            if not self.plan or self.phase not in ("AVAILABLE", "BUSY", "HELD"):
                raise ValueError("Append requires an active or held mission")
            if plan.get("mission_id") != req["mission_id"] or plan.get("version") != req["version"]:
                raise ValueError("Append command/plan mismatch")
            validate_append(self.plan, plan, req["base_version"], req["base_hash"], self.safety)
            # Preserve current target, phase, dwell timer and execution ledger.
            for command in self.commands.values():
                if (command.get("mission_id") == self.plan["mission_id"]
                        and command.get("version") == self.plan["version"]):
                    command["version"] = plan["version"]
            self.plan = plan
            self.ack(req, True)
            self.publish()
            return
        if kind == "PLAN_SYNC":
            if self.telemetry.get("armed") or self.phase not in ("IDLE", "COMPLETED"):
                raise ValueError("Plan sync requires idle, disarmed companion")
            plan = req["plan"]
            validate_plan(plan, self.safety)
            if plan["mission_id"] != req["mission_id"] or plan["version"] != req["version"]:
                raise ValueError("Plan/version mismatch")
            if self.plan and self.plan["mission_id"] == plan["mission_id"]:
                if plan["version"] < self.plan["version"] or (plan["version"] == self.plan["version"] and digest(plan) != digest(self.plan)):
                    raise ValueError("Stale/conflicting plan version")
            # An explicit re-sync re-arms the mission, matching the base station's
            # rearm_tasks(). Safe because PLAN_SYNC is only taken disarmed and idle.
            self.commands = {k: v for k, v in self.commands.items()
                             if not (v["response"].get("operation") == "TASK_ASSIGN"
                                     and v.get("mission_id") == plan["mission_id"])}
            self.plan, self.task, self.phase = plan, None, "IDLE"
            self.error = ""  # a synced plan is the reconciliation an earlier restart asked for
            self.ack(req, True)  # plan only: never sends anything to FC
            return
        if kind not in ("HOLD", "ABORT") and (not self.plan or (req.get("mission_id"), req.get("version")) != (self.plan["mission_id"], self.plan["version"])):
            raise ValueError("Mission/version not synchronized")
        if kind == "PREPARE":
            self.precheck()
            if self.phase != "IDLE" or self.telemetry.get("armed"):
                raise ValueError("PREPARE requires disarmed IDLE")
            validate_target({**self.telemetry, "alt_m": self.safety["takeoff_alt_m"]}, self.safety)
            self.hold_target = {k: self.telemetry[k] for k in ("lat", "lon")}
            self.hold_target["alt_m"] = self.safety["takeoff_alt_m"]
            self.stage("PREPARING")
            self.ack(req, True)
            self.set_mode("GUIDED")
        elif kind == "TASK_ASSIGN":
            self.precheck(airborne=True)
            if self.phase != "AVAILABLE" or req.get("owner_drone_id") != self.slot:
                raise ValueError("Not the available task owner")
            target = next((w for w in self.plan["waypoints"] if w["task_id"] == req["task_id"]), None)
            if target is None or req.get("target") != target or req.get("assignment_version") != 1:
                raise ValueError("Task target/version differs from synchronized plan")
            if self.task and self.task["task_id"] == req["task_id"]:
                raise ValueError("Task already executed/owned")
            # Durable execution ledger survives replacement of the current task.
            if any(v["response"].get("operation") == "TASK_ASSIGN" and v.get("task_id") == req["task_id"]
                   and v.get("mission_id") == self.plan["mission_id"] and v.get("version") == self.plan["version"]
                   for v in self.commands.values()):
                raise ValueError("Task already in execution ledger")
            validate_target(target, self.safety)
            self.task = {"task_id": req["task_id"], "assignment_version": 1,
                         "command_id": req["command_id"], "status": "EN_ROUTE", "target": target}
            self.stage("BUSY")
            self.ack(req, True)
            self.commands[req["command_id"]].update(task_id=req["task_id"], mission_id=self.plan["mission_id"], version=self.plan["version"])
            self.persist()
        elif kind in ("HOLD", "ABORT", "END"):
            self.apf_status = {}
            action = "HOLD" if kind == "HOLD" else req.get("action", "RTL")
            if action not in ("HOLD", "RTL", "LAND"):
                raise ValueError("Invalid end action")
            if self.pending_mode:
                previous = self.pending_mode["request"]
                self.pending_mode = None
                self.ack(previous, False, "Superseded by safety command")
            self.phase = "HOLD_REQUIRED" if kind == "HOLD" else "ABORTING" if kind == "ABORT" else "ENDING"
            if self.task and self.task["status"] not in ("REACHED", "CANCELLED"):
                if kind != "HOLD" or self.task["status"] != "UNKNOWN":
                    self.task["status"] = "HELD" if kind == "HOLD" else "CANCELLED"
            self.persist()
            if not self.telemetry.get("armed") and self.snapshot().get("heartbeat_age_s") is not None and self.snapshot()["heartbeat_age_s"] <= 2:
                self.phase = "IDLE" if kind == "HOLD" else "COMPLETED"
                self.ack(req, True)
            else:
                mode = HOLD_MODE if action == "HOLD" else action
                if action == "HOLD" and not self.brake_here():
                    mode = "LOITER"  # no fresh fix to hold on to; let the FC hold itself
                self.pending_mode = {"request": req, "mode": mode, "at": time.monotonic()}
                self.set_mode(mode)
        elif kind == "RESUME":
            self.precheck()
            if self.phase != "HELD" or not self.telemetry.get("armed"):
                raise ValueError("RESUME requires confirmed airborne hold")
            if self.task and self.task["status"] == "UNKNOWN":
                raise ValueError("Unknown task after restart; abort required")
            if math.hypot(self.telemetry.get("vx", 99), self.telemetry.get("vy", 99)) > 0.5:
                raise ValueError("Drone not stationary in hold")
            self.hold_target = {k: self.telemetry[k] for k in ("lat", "lon", "alt_m")}
            self.pending_mode = {"request": req, "mode": "GUIDED", "at": time.monotonic()}
            self.set_mode("GUIDED")
        else:
            raise ValueError("Unsupported swarm operation")

    def fail_hold(self, error):
        self.error = error
        self.apf_status = {}
        self.phase = "FAULT"
        # Flight action must still run if durable storage has failed.
        if self.telemetry.get("mode") not in ("RTL", "LAND"):
            self.set_mode("LOITER")
            self.loiter_retry_at = time.monotonic() + 1
        if self.task and self.task["status"] == "EN_ROUTE":
            self.task["status"] = "HELD"
        if self.pending_mode:
            pending = self.pending_mode["request"]
            self.pending_mode = None
            self.ack(pending, False, error)
        self.persist()

    def tick(self):
        now = time.monotonic()
        state = self.snapshot()
        if self.phase == "FAULT" and state.get("armed") and state.get("mode") not in ("LOITER", "RTL", "LAND") and now >= self.loiter_retry_at:
            self.set_mode("LOITER")
            self.loiter_retry_at = now + 1
        if self.pending_mode:
            pending = self.pending_mode
            if (state.get("heartbeat_age_s") is not None and state["heartbeat_age_s"] <= 2
                    and state.get("mode") == pending["mode"] and self.hold_settled(state, pending)):
                req = pending["request"]
                self.pending_mode = None
                if req["kind"] == "RESUME":
                    self.error = ""
                    if self.task and self.task["status"] == "HELD":
                        self.task["status"] = "EN_ROUTE"
                        self.phase = "BUSY"
                    else:
                        self.phase = "AVAILABLE"
                    self.stage_at = now
                    self.stable_since = None
                else:
                    self.phase = "HELD" if req["kind"] == "HOLD" else "FINISHED_HOLD" if pending["mode"] in (HOLD_MODE, "LOITER") else pending["mode"]
                self.ack(req, True)  # ACK only after actual FC mode confirmation
            elif now - pending["at"] > 5:
                self.pending_mode = None
                self.phase = "FAULT"
                self.ack(pending["request"], False, "FC mode confirmation timeout")
            return
        if self.phase in ("RTL", "LAND", "FINISHED_HOLD"):
            self.apf_status = {}
            self.refresh_hold(state, now)
            if state.get("heartbeat_age_s") is not None and state["heartbeat_age_s"] <= 2 and not state.get("armed"):
                self.stage("COMPLETED")
            return
        active = self.phase in ("PREPARING", "ARMING", "TAKEOFF", "HOVER_STABILIZING", "AVAILABLE", "BUSY")
        if not active:
            self.apf_status = {}
            self.refresh_hold(state, now)
            return
        errors = health_errors(state, self.safety) + self.peer_errors()
        if now - self.last_gcs > self.config["gcs_heartbeat_timeout"]:
            errors.append("GCS heartbeat lost")
        if self.journal_error:
            errors.append(self.journal_error)
        if errors:
            self.fail_hold("; ".join(errors))
            return
        if self.phase == "PREPARING":
            if state.get("mode") == "GUIDED":
                self.stage("ARMING")
                self.command(ARM_COMMAND, 1)  # force=0; FC pre-arm checks remain enabled
            elif now - self.stage_at > 5:
                self.fail_hold("GUIDED confirmation timeout")
            return
        if self.phase == "ARMING":
            result = self.command_acks.get(ARM_COMMAND)
            if result not in (None, 0, 5):
                self.fail_hold(f"FC rejected ARM: {result}")
            elif state.get("armed") and result == 0:
                self.stage("TAKEOFF")
                self.command(TAKEOFF_COMMAND, 0, 0, 0, 0, 0, 0, self.safety["takeoff_alt_m"])
            elif now - self.stage_at > 10:
                self.fail_hold("ARM ACK/heartbeat timeout")
            return
        if not state.get("armed") or state.get("mode") != "GUIDED":
            self.fail_hold("FC disarmed/mode changed; navigation stopped")
            return
        if self.phase == "TAKEOFF":
            result = self.command_acks.get(TAKEOFF_COMMAND)
            if result not in (None, 0, 5):
                self.fail_hold(f"FC rejected TAKEOFF: {result}")
            elif result == 0 and abs(state["alt_m"] - self.safety["takeoff_alt_m"]) <= self.config["hover_alt_tolerance"]:
                self.stage("HOVER_STABILIZING")
            elif now - self.stage_at > 30:
                self.fail_hold("TAKEOFF ACK/altitude timeout")
            return
        target = self.task["target"] if self.phase == "BUSY" else self.hold_target
        if self.phase == "HOVER_STABILIZING":
            stable = (abs(state["alt_m"] - self.safety["takeoff_alt_m"]) <= self.config["hover_alt_tolerance"]
                      and abs(state["vz"]) <= self.config["hover_vz_threshold"]
                      and math.hypot(state["vx"], state["vy"]) <= 0.5)
            self.stable_since = (self.stable_since or now) if stable else None
            if self.stable_since and now - self.stable_since >= self.config["hover_min_duration"]:
                self.stage("AVAILABLE")
            elif now - self.stage_at > 30:
                self.fail_hold("Hover stabilization timeout")
                return
        if target and now - self.last_setpoint >= 0.1:
            corrected = self.corrected_target(target)
            if self.yields_to_peer(state, target):
                if self.yield_target is None:
                    self.yield_target = {"lat": state["lat"], "lon": state["lon"], "alt_m": state["alt_m"]}
                self.send_setpoint(self.yield_target)  # one frozen point, not a drifting one
            else:
                try:
                    validate_target(corrected, self.safety)
                except ValueError as exc:
                    self.fail_hold(str(exc))
                    return
                self.send_setpoint(corrected)
                self.last_setpoint = now
        if self.phase == "BUSY":
            reached = (distance_m(state["lat"], state["lon"], target["lat"], target["lon"]) <= 2
                       and abs(state["alt_m"] - target["alt_m"]) <= 0.5
                       and math.hypot(state["vx"], state["vy"]) <= 0.5 and abs(state["vz"]) <= 0.2)
            self.stable_since = (self.stable_since or now) if reached else None
            if self.stable_since and now - self.stable_since >= max(1, self.config["hold_duration_s"]):
                self.task["status"] = "REACHED"
                self.hold_target = dict(target)
                self.stage("AVAILABLE")
            elif now - self.stage_at > 300:
                self.fail_hold("Task navigation timeout")

    def send_setpoint(self, target):
        self.fc.mav.set_position_target_global_int_send(
            0, self.fc.target_system, self.fc.target_component, 6, 3576,
            int(round(target["lat"] * 1e7)), int(round(target["lon"] * 1e7)), target["alt_m"],
            0, 0, 0, 0, 0, 0, 0, 0,
        )
        self.last_setpoint = time.monotonic()

    def brake_here(self):
        """Hold the present position; GUIDED alone would fly on to the previous target."""
        age = self.snapshot().get("position_age_s")
        if (not valid_position(self.telemetry.get("lat"), self.telemetry.get("lon"))
                or age is None or age > PEER_MAX_AGE_S):
            return False  # Without a fresh fix the companion must not steer at all.
        # Deliberately not validate_target: staying put commands no new movement.
        self.hold_target = {"lat": self.telemetry["lat"], "lon": self.telemetry["lon"],
                            "alt_m": self.telemetry.get("alt_m", self.safety["takeoff_alt_m"])}
        self.send_setpoint(self.hold_target)
        return True

    def hold_settled(self, state, pending):
        """A GUIDED hold is confirmed by the drone stopping, not by a mode flip."""
        if pending["mode"] != HOLD_MODE or pending["request"]["kind"] not in ("HOLD", "END"):
            return True
        return math.hypot(state.get("vx", 99), state.get("vy", 99)) <= 0.5

    def refresh_hold(self, state, now):
        """Keep the frozen hold target current while no phase is navigating."""
        if (self.hold_target and state.get("armed") and state.get("mode") == HOLD_MODE
                and now - self.last_setpoint >= 0.1):
            self.send_setpoint(self.hold_target)

    def yields_to_peer(self, state, target):
        """Hold if this UAV is the closer one to its own waypoint.

        Both companions see the same two distances, so they reach opposite roles
        without another round trip. The role is latched while both assignments
        stay the same, so the mover's shrinking distance cannot swap the roles;
        a new assignment on either side (e.g. after a tie at takeoff) decides again.
        """
        if not self.apf_status.get("active"):
            self.yield_role = self.yield_target = self.yield_key = None
            return False
        key = (target["lat"], target["lon"], target["alt_m"], self.peer.get("task_id"))
        if key != self.yield_key:
            self.yield_role = self.yield_target = None
            self.yield_key = key
        if self.yield_role is None:
            peer_left = self.peer.get("remaining_m")
            mine = distance_m(state["lat"], state["lon"], target["lat"], target["lon"])
            lower = self.slot < (self.peer.get("drone_id") or 0)
            if peer_left is None or abs(mine - peer_left) <= YIELD_TIE_M:
                self.yield_role = "MOVE" if lower else "HOLD"  # tie or unknown peer
            else:
                self.yield_role = "HOLD" if mine < peer_left else "MOVE"
        self.apf_status["role"] = self.yield_role
        return self.yield_role == "HOLD"

    def corrected_target(self, target):
        now = time.monotonic()
        if target == self.apf_target and now - self.apf_at < 1 / self.apf.config.tick_rate_hz:
            return self.apf_corrected
        self.apf_at = now
        self.apf_target = dict(target)
        own = self.telemetry
        peer = self.peer
        home_msl = own["alt_msl_m"] - own["alt_m"]
        a = UAVState(self.slot, timestamp=time.time(), lat=own["lat"], lon=own["lon"],
                     alt_relative_m=own["alt_m"], vx=own["vx"], vy=own["vy"], vz=own["vz"],
                     target_lat=target["lat"], target_lon=target["lon"], target_alt_m=target["alt_m"])
        b = UAVState(peer["drone_id"], timestamp=time.time() - (peer["position_age_s"] or 0),
                     lat=peer["lat"], lon=peer["lon"], alt_relative_m=peer["alt_msl_m"] - home_msl,
                     vx=peer["vx"], vy=peer["vy"], vz=peer["vz"],
                     target_lat=peer["lat"], target_lon=peer["lon"], target_alt_m=peer["alt_msl_m"] - home_msl)
        result = self.apf.tick(a, b)[0] if self.slot == 3 else self.apf.tick(b, a)[1]
        self.apf_status = {"active": result.avoidance_active, "d_ij": result.d_ij,
                           "d_cpa": result.d_cpa, "t_cpa": result.t_cpa, "offset_m": result.offset_m}
        if result.avoidance_active:
            self.apf_corrected = {"lat": result.corrected_lat, "lon": result.corrected_lon, "alt_m": result.corrected_alt_m}
        else:
            self.apf_corrected = dict(target)
        return self.apf_corrected

    def drain(self, connection, handler):
        """Read what is queued. A UDP peer that restarted must not end the flight.

        Windows reports an ICMP port-unreachable as 10054 on the next read, so a
        bare loop dies the moment the base station or SITL is bounced. Link
        freshness already drives the failsafe; the loop only has to survive.
        """
        try:
            for _ in range(100):
                msg = connection.recv_match(blocking=False)
                if msg is None:
                    return
                handler(msg)
        except OSError as exc:
            self.link_error = f"link read failed: {exc}"

    def run(self):
        self.gcs.mav = common.MAVLink(self.gcs, srcSystem=self.slot, srcComponent=COMPONENT)
        self.fc.mav.request_data_stream_send(self.fc.target_system, self.fc.target_component, 0, 5, 1)
        self.command(common.MAV_CMD_REQUEST_MESSAGE, common.MAVLINK_MSG_ID_HOME_POSITION)
        publish_at = 0.0
        try:
            while True:
                for connection, handler in ((self.fc, self.receive_fc), (self.gcs, self.receive_gcs)):
                    self.drain(connection, handler)
                self.tick()
                if time.monotonic() >= publish_at:
                    try:
                        self.publish()
                    except OSError as exc:
                        self.link_error = f"link write failed: {exc}"
                    publish_at = time.monotonic() + PUBLISH_INTERVAL_S
                time.sleep(0.01)
        finally:
            try:
                if self.telemetry.get("armed"):
                    self.fail_hold("Companion stopping")
            finally:
                self.fc.close()
                self.gcs.close()
