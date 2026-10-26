"""Base-station authority for route-planned, single-owner waypoint dispatch.

Waypoints are split between the UAVs and ordered by the min-max route planner
(route_planner.solve): the plan is made at START from the grounded positions, and
redone in the background when waypoints are appended or a UAV runs out of work
while its peer still has some. Each UAV then flies its own queue in order.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import math
import time
import uuid

from mission_scripts.swarm_protocol import SLOTS, digest, distance_m, health_errors, safety_hash, valid_position, validate_append, validate_plan, validate_safety, validate_target
from app.services.mission.dispatch_store import MissionStore
from app.services.mission.route_planner import solve as plan_routes

logger = logging.getLogger(__name__)
ACTIVE_TASKS = {"ASSIGNED", "ACKED", "EN_ROUTE", "HELD", "UNKNOWN"}
EDITABLE = {"DRAFT", "UPLOADED", "PARTIAL", "FAILED_UPLOAD", "COMPLETED", "ABORTED"}


class MissionConflict(ValueError):
    pass


def peer_of(slot):
    return 4 if slot == 3 else 3


class WaypointScheduler:
    def __init__(self, link, settings, legacy=None, store=None):
        self.link, self.settings, self.legacy = link, settings, legacy
        self.store = store or MissionStore(settings.SWARM_STORE_PATH)
        self.lock = asyncio.Lock()
        self.worker = None
        self.started_at = None
        self.deferred_at = {}
        self.replanning = None  # (asyncio task, (mission_id, version)) of a background route plan
        self.safety = {"center_lat": settings.SWARM_CENTER_LAT, "center_lon": settings.SWARM_CENTER_LON,
                       "radius_m": settings.SWARM_RADIUS_M, "min_alt_m": settings.SWARM_MIN_ALT_M,
                       "max_alt_m": settings.SWARM_MAX_ALT_M, "takeoff_alt_m": settings.SWARM_TAKEOFF_ALT_M,
                       "min_battery_pct": settings.SWARM_MIN_BATTERY_PCT, "min_separation_m": settings.APF_D_SAFE,
                       "apf": {"d_influence": settings.APF_D_INFLUENCE, "k_att": settings.APF_K_ATT,
                               "k_rep": settings.APF_K_REP, "max_lateral_offset_m": settings.APF_MAX_OFFSET,
                               "tick_rate_hz": settings.APF_TICK_RATE_HZ,
                               "hysteresis_enter_m": settings.APF_ENTER_M, "hysteresis_exit_m": settings.APF_EXIT_M,
                               "prediction_horizon": settings.APF_PREDICTION_HORIZON_S}}
        # Operator-set geofence (center + radius) persists in the store and overrides the .env defaults.
        override = self.store.load_config("geofence")
        if override:
            self.safety.update({k: override[k] for k in ("center_lat", "center_lon", "radius_m") if k in override})
        self.state = self.store.load() or {"phase": "DRAFT", "plan": {}, "tasks": [], "upload": {}, "commands": {}, "error": ""}
        if self.state["phase"] == "UPLOADING" and not self.state.get("flight_started"):
            self.state["phase"] = "PARTIAL"
            self.state["upload"] = {str(s): "UNKNOWN" for s in SLOTS}
            self.save("UPLOAD_INTERRUPTED", reason="Re-upload required after server restart")
        elif self.state["phase"] not in EDITABLE:
            self.state["phase"] = "RECOVERY_REQUIRED"
            for task in self.state["tasks"]:
                if task["status"] in ACTIVE_TASKS:
                    task["status"] = "UNKNOWN"
            self.save("SERVER_RESTART", reason="No dispatch until live reconciliation and explicit resume")

    def save(self, event, **details):
        self.store.save(self.state, event, **details)

    def safety_digest(self):
        try:
            return safety_hash(self.safety)
        except (TypeError, ValueError):
            return None  # geofence not configured yet; companions cannot reconcile

    async def update_geofence(self, center_lat, center_lon, radius_m):
        async with self.lock:
            if self.state["phase"] not in EDITABLE or self.legacy_busy():
                raise MissionConflict("Geofence hanya bisa diubah saat draft/idle, bukan selama operasi misi")
            if any(self.link.snapshot(s).get("armed") for s in SLOTS):
                raise MissionConflict("Kedua UAV harus DISARMED sebelum mengubah geofence")
            candidate = dict(self.safety, center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
            validate_safety(candidate)
            for wp in self.state["plan"].get("waypoints", []):
                if distance_m(wp["lat"], wp["lon"], center_lat, center_lon) > radius_m:
                    raise MissionConflict("Waypoint yang sudah ada berada di luar geofence baru; hapus atau perbesar radius")
            self.safety = candidate
            self.store.save_config("geofence", {"center_lat": center_lat, "center_lon": center_lon, "radius_m": radius_m})
            # A changed geofence changes the base-station safety hash, so any prior upload must be re-synced.
            if self.state["upload"]:
                self.state["upload"] = {str(s): "UNKNOWN" for s in SLOTS}
                if self.state["phase"] == "UPLOADED":
                    self.state["phase"] = "PARTIAL"
            self.save("GEOFENCE_UPDATED", center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
            return self.snapshot()

    def config_errors(self):
        errors = []
        try:
            validate_safety(self.safety)
        except ValueError as exc:
            errors.append(str(exc))
        if len(self.settings.SWARM_LINK_KEY) < 32:
            errors.append("Configure SWARM_LINK_KEY (minimum 32 characters)")
        if not self.settings.SWARM_OPERATOR_TOKEN:
            errors.append("Configure SWARM_OPERATOR_TOKEN")
        return errors

    def owns_copters(self):
        return bool(self.state["plan"]) and (self.state["phase"] not in ("DRAFT", "COMPLETED", "ABORTED")
                or (self.state.get("flight_started") and not self.confirmed_disarmed()))

    def confirmed_disarmed(self):
        return all(self.link.snapshot(s).get("connected")
                   and self.link.snapshot(s).get("heartbeat_age_s") is not None
                   and self.link.snapshot(s)["heartbeat_age_s"] <= self.settings.SWARM_FRESHNESS_S
                   and self.link.snapshot(s).get("armed") is False for s in SLOTS)

    def legacy_busy(self):
        return self.legacy and self.legacy.status().phase.value not in ("IDLE", "COMPLETED", "FAILED")

    def errors(self, slot, airborne=False, reconcile_plan=True):
        state = self.link.snapshot(slot)
        errors = health_errors(state, self.safety, self.settings.SWARM_FRESHNESS_S, airborne)
        if not state.get("connected"):
            errors.append("companion disconnected")
        plan = self.state["plan"]
        if reconcile_plan and plan and (state.get("mission_id"), state.get("version"), state.get("plan_hash")) != (plan["mission_id"], plan["version"], digest(self.wire_plan())):
            errors.append("plan/version not reconciled")
        if not state.get("home"):
            errors.append("actual FC home unavailable")
        if state.get("safety_hash") != safety_hash(self.safety):
            errors.append("companion/base-station safety configuration mismatch")
        return errors

    def precheck(self, airborne=False):
        errors = self.config_errors()
        if self.legacy_busy():
            errors.append("Legacy swarm session owns the copters")
        if errors:
            return errors
        for slot in SLOTS:
            errors.extend(f"UAV-{slot}: {reason}" for reason in self.errors(slot, airborne))
        drones = [self.link.snapshot(s) for s in SLOTS]
        if not errors:
            a, b = drones
            if distance_m(a["lat"], a["lon"], b["lat"], b["lon"]) < self.safety["min_separation_m"]:
                errors.append("Takeoff/dispatch positions below minimum horizontal separation")
        return errors

    def wire_plan(self):
        return {k: v for k, v in self.state["plan"].items() if k != "endpoints"}

    def snapshot(self):
        result = copy.deepcopy(self.state)
        blockers = self.precheck() if self.state["plan"] else self.config_errors()
        for slot in SLOTS:
            drone = self.link.snapshot(slot)
            if drone.get("armed") or drone.get("phase") != "IDLE":
                blockers.append(f"UAV-{slot}: START requires disarmed IDLE")
        result.update(drones=[self.link.snapshot(s) for s in SLOTS], events=self.store.events(),
                      ready_to_start=self.state["phase"] == "UPLOADED" and not blockers,
                      blockers=blockers, safety=self.safety, safety_hash=self.safety_digest(),
                      busy=self.lock.locked(), end_action=self.settings.SWARM_END_ACTION,
                      replanning=self.replanning is not None)
        result["edit_locked"] = self.state["phase"] not in EDITABLE or bool(self.state.get("flight_started") and not self.confirmed_disarmed())
        result["append_allowed"] = (self.state["phase"] in ("ACTIVE", "HELD")
            and not self.state.get("append_pending") and not self.lock.locked()
            and len(self.state["plan"].get("waypoints", [])) < 200
            and all(self.link.snapshot(s).get("connected")
                    and "PLAN_APPEND" in self.link.snapshot(s).get("capabilities", []) for s in SLOTS))
        for drone in result["drones"]:
            target = next((t for t in self.state["tasks"] if t["status"] in ACTIVE_TASKS and t["owner_drone_id"] == drone["drone_id"]), None)
            drone["distance_to_target_m"] = (distance_m(drone["lat"], drone["lon"], target["lat"], target["lon"])
                if target and drone.get("connected") and valid_position(drone.get("lat"), drone.get("lon")) else None)
        return result

    def require_mutation(self):
        if self.lock.locked():
            raise MissionConflict("Another mission mutation is in progress")

    async def save_plan(self, plan):
        self.require_mutation()
        async with self.lock:
            errors = self.config_errors()
            if errors:
                raise MissionConflict("; ".join(errors))
            if self.state["phase"] not in EDITABLE or self.legacy_busy():
                raise MissionConflict("Mission is locked while flight/recovery or legacy operation is active")
            if any(self.link.snapshot(s).get("armed") for s in SLOTS):
                raise MissionConflict("Both copters must be disarmed before replacing a plan")
            if self.state.get("flight_started") and not self.confirmed_disarmed():
                raise MissionConflict("Live disarmed confirmation required before replacing a flown mission")
            previous = self.state["plan"]
            if previous:
                expected = previous["version"] + 1 if previous["mission_id"] == plan["mission_id"] else 1
                if plan == previous:
                    return self.snapshot()
                if plan["version"] != expected:
                    raise MissionConflict(f"Stale mission version; expected {expected}")
            elif plan["version"] != 1:
                raise MissionConflict("First mission version must be 1")
            validate_plan(plan, self.safety)
            self.state = {"phase": "DRAFT", "plan": plan, "tasks": [dict(w, status="PENDING", owner_drone_id=None,
                          assignment_version=0) for w in plan["waypoints"]], "upload": {}, "commands": {}, "error": ""}
            self.save("PLAN_VALIDATED", plan=copy.deepcopy(plan))
        return self.snapshot()

    def require_version(self, mission_id, version):
        plan = self.state["plan"]
        if (plan.get("mission_id"), plan.get("version")) != (mission_id, version):
            raise MissionConflict("Mission/version changed; refresh the server snapshot")

    async def append_waypoints(self, mission_id, version, waypoints):
        """Durably stage one append revision; dispatch it only after both ACKs."""
        self.require_mutation()
        async with self.lock:
            last = self.state.get("last_append")
            if (last and self.state["plan"].get("mission_id") == mission_id
                    and last["base_version"] == version and last["waypoints"] == waypoints):
                return self.snapshot()  # HTTP response lost after a successful commit.
            self.require_version(mission_id, version)
            phase = self.state["phase"]
            if phase not in ("ACTIVE", "HELD") or self.legacy_busy():
                raise MissionConflict("Append requires ACTIVE or confirmed HELD; existing waypoints remain locked")
            pending = self.state.get("append_pending")
            if pending and pending["waypoints"] != waypoints:
                raise MissionConflict("Retry the pending append before adding more waypoints")
            errors = self.config_errors()
            for slot in SLOTS:
                drone = self.link.snapshot(slot)
                if "PLAN_APPEND" not in drone.get("capabilities", []):
                    errors.append(f"UAV-{slot}: update companion for live waypoint append")
                errors.extend(f"UAV-{slot}: {e}" for e in self.errors(
                    slot, airborne=phase == "ACTIVE", reconcile_plan=not pending))
                if pending and (drone.get("mission_id") != mission_id or
                        (drone.get("version"), drone.get("plan_hash")) not in (
                            (pending["base_version"], pending["base_hash"]),
                            (version, digest(self.wire_plan())))):
                    errors.append(f"UAV-{slot}: append base/candidate plan not reconciled")
            if errors:
                raise MissionConflict("; ".join(errors))
            if not pending:
                previous = self.wire_plan()
                candidate = dict(previous, version=version + 1,
                                 waypoints=previous["waypoints"] + copy.deepcopy(waypoints))
                validate_append(previous, candidate, version, digest(previous), self.safety)
                pending = dict(base_version=version, base_hash=digest(previous),
                               waypoints=copy.deepcopy(waypoints))
                self.state["append_pending"] = pending
                self.state["plan"] = dict(candidate, endpoints=self.state["plan"]["endpoints"])
            self.state["phase"] = "APPENDING"
            self.state["upload"] = {str(s): "SERVER_ACCEPTED" for s in SLOTS}
            self.save("APPEND_STARTED", append=copy.deepcopy(pending))

            async def append(slot):
                ok = await self.command(slot, "PLAN_APPEND", plan=self.wire_plan(),
                                        base_version=pending["base_version"], base_hash=pending["base_hash"])
                self.state["upload"][str(slot)] = "UAV_ACK" if ok else "FAILED"
                self.save("APPEND_ACK" if ok else "APPEND_FAILED", drone_id=slot)
                return ok

            ok = all(await asyncio.gather(*(append(s) for s in SLOTS)))
            if ok:
                # ACK confirms storage; wait for matching fresh telemetry before dispatch resumes.
                deadline = time.monotonic() + self.settings.SWARM_ACK_TIMEOUT_S
                while any(self.errors(s, airborne=phase == "ACTIVE") for s in SLOTS):
                    if time.monotonic() >= deadline:
                        ok = False
                        break
                    await asyncio.sleep(0.05)
            if not ok:
                await self.safe_hold("Sinkronisasi WP tambahan belum lengkap. Ulangi sinkronisasi setelah Hold terkonfirmasi.")
            else:
                self.state["tasks"].extend(dict(w, status="PENDING", owner_drone_id=None,
                    assignment_version=0) for w in pending["waypoints"])
                self.state["last_append"] = pending
                self.state.pop("append_pending")
                self.state.update(phase=phase, error="")
                self.save("APPEND_COMMITTED", count=len(pending["waypoints"]))
        return self.snapshot()

    async def command(self, slot, kind, **payload):
        ident = uuid.uuid4().hex
        plan = self.state["plan"]
        record = {"command_id": ident, "operation": kind, "status": "SERVER_ACCEPTED"}
        self.state["commands"][str(slot)] = record
        self.save("COMMAND_ACCEPTED", drone_id=slot, **record)
        try:
            reply = await self.link.request(slot, kind, command_id=ident, mission_id=plan["mission_id"], version=plan["version"], **payload)
            if kind in ("PLAN_SYNC", "PLAN_APPEND") and reply.get("plan_hash") != digest(self.wire_plan()):
                raise ValueError("Companion ACK plan hash mismatch")
            record.update(status="UAV_ACK", latency_ms=reply.get("latency_ms"))
        except Exception as exc:
            record.update(status="UNKNOWN", error=str(exc))
            self.save("COMMAND_UNKNOWN", drone_id=slot, **record)
            return False
        self.save("COMMAND_ACK", drone_id=slot, **record)
        return True

    async def both(self, kind, **payload):
        return all(await asyncio.gather(*(self.command(s, kind, **payload) for s in SLOTS)))

    async def action(self, mission_id, version, action, confirmation=""):
        self.require_mutation()
        async with self.lock:
            self.require_version(mission_id, version)
            if action != "upload" and confirmation != f"CONFIRM_{action.upper()}":
                raise MissionConflict(f"Explicit CONFIRM_{action.upper()} required")
            phase = self.state["phase"]
            if action == "upload":
                if phase not in EDITABLE or self.legacy_busy():
                    raise MissionConflict("Upload not allowed in this phase")
                validate_plan(self.wire_plan(), self.safety)
                self.link.configure(self.state["plan"]["endpoints"])
                self.state["phase"] = "UPLOADING"
                self.state["upload"] = {str(s): "SERVER_ACCEPTED" for s in SLOTS}
                self.rearm_tasks()
                self.save("UPLOAD_STARTED")
                async def upload(slot):
                    ok = await self.command(slot, "PLAN_SYNC", plan=self.wire_plan())
                    self.state["upload"][str(slot)] = "UAV_ACK" if ok else "FAILED"
                    self.save("PLAN_ACK" if ok else "PLAN_FAILED", drone_id=slot)
                    return ok
                results = await asyncio.gather(*(upload(s) for s in SLOTS))
                self.state["phase"] = "UPLOADED" if all(results) else "PARTIAL" if any(results) else "FAILED_UPLOAD"
                self.state["error"] = "" if all(results) else "Plan upload incomplete; inspect per-UAV ACK"
            elif action == "start":
                if phase != "UPLOADED" or not self.snapshot()["ready_to_start"]:
                    raise MissionConflict("START blocked: " + "; ".join(self.snapshot()["blockers"] or [phase]))
                validate_plan(self.wire_plan(), self.safety)
                # Plan while still on the ground: a planner failure must refuse START, not
                # strand two airborne copters without a route.
                try:
                    planned = await self.plan_route(airborne=False)
                except Exception as exc:
                    raise MissionConflict(f"Route planning failed: {exc}") from exc
                self.apply_route(*planned, event="ROUTE_PLANNED")
                self.state["phase"] = "PREPARING"
                self.state["flight_started"] = True
                self.state["error"] = ""
                self.clear_task_reasons()
                self.started_at = time.monotonic()
                self.save("START_CONFIRMED")
                if not await self.both("PREPARE"):
                    await self.safe_hold("Partial PREPARE/ACK failure")
            elif action == "hold":
                if phase not in ("ACTIVE", "PREPARING", "HELD", "HOLD_REQUIRED", "RECOVERY_REQUIRED"):
                    raise MissionConflict("HOLD not allowed in this phase")
                await self.safe_hold("Operator hold")
            elif action == "resume":
                if phase != "HELD":
                    raise MissionConflict("RESUME requires confirmed HOLD on both UAVs")
                if self.state.get("append_pending"):
                    raise MissionConflict("Finish pending waypoint synchronization before RESUME")
                errors = self.precheck()
                if errors:
                    raise MissionConflict("; ".join(errors))
                self.reconcile()
                if any(t["status"] == "UNKNOWN" for t in self.state["tasks"]):
                    raise MissionConflict("Unresolved task ownership; abort required")
                self.state["phase"] = "RESUMING"
                self.clear_task_reasons()
                self.save("RESUME_CONFIRMED")
                if await self.both("RESUME"):
                    self.state["phase"] = "PREPARING"
                    self.state["error"] = ""
                    self.started_at = time.monotonic()
                else:
                    await self.safe_hold("Partial RESUME/ACK failure")
            elif action == "abort":
                if not self.state["plan"]:
                    raise MissionConflict("No mission")
                self.state["phase"] = "ABORTING"
                for task in self.state["tasks"]:
                    if task["status"] == "PENDING":
                        task["status"] = "CANCELLED"
                self.save("ABORT_CONFIRMED")
                self.link.configure(self.state["plan"]["endpoints"])
                ok = await self.both("ABORT", action="RTL")
                for task in self.state["tasks"]:
                    if task["status"] in ACTIVE_TASKS:
                        task["status"] = "CANCELLED" if ok else "UNKNOWN"
                self.state["phase"] = "ABORTED" if ok else "HOLD_REQUIRED"
                self.state["error"] = ""
                if not ok:
                    self.state["error"] = "Abort ACK incomplete; flight state unknown"
            else:
                raise MissionConflict("Unsupported action")
            self.save("MISSION_STATE", phase=self.state["phase"])
        return self.snapshot()

    async def safe_hold(self, reason):
        self.state.update(phase="HOLD_REQUIRED", error=reason)
        self.save("HOLD_REQUIRED", reason=reason)
        ok = await self.both("HOLD")
        self.state["phase"] = "HELD" if ok else "HOLD_REQUIRED"
        self.save("HOLD_ACKS", confirmed=ok)

    def reconcile(self):
        for task in self.state["tasks"]:
            if task["status"] not in ACTIVE_TASKS:
                continue
            slot = task["owner_drone_id"]
            state = self.link.snapshot(slot)
            reported = state.get("task") or {}
            if self.errors(slot) or any(reported.get(k) != task.get(k) for k in ("task_id", "assignment_version", "command_id")):
                continue
            result = reported.get("status")
            if result == "REACHED" and (distance_m(state["lat"], state["lon"], task["lat"], task["lon"]) <= 2.5
                    and abs(state["alt_m"] - task["alt_m"]) <= 0.75):
                task["status"] = "REACHED"
                self.save("TASK_REACHED", task_id=task["task_id"], drone_id=slot)
            elif result in ("EN_ROUTE", "HELD") and task["status"] != result:
                task["status"] = result
                self.save("TASK_RECONCILED", task_id=task["task_id"], drone_id=slot, reported=result)

    def active_task(self, slot):
        return next((t for t in self.state["tasks"] if t.get("owner_drone_id") == slot
                     and t["status"] in ACTIVE_TASKS), None)

    def queue(self, slot):
        """PENDING waypoints the route plan gives this UAV, in flight order."""
        pending = {t["task_id"]: t for t in self.state["tasks"] if t["status"] == "PENDING"}
        planned = (self.state.get("route") or {}).get("queues", {}).get(str(slot), [])
        return [pending[i] for i in planned if i in pending]

    def blockers(self, slot, waypoint):
        """Why `slot` cannot take `waypoint` right now; empty when it can."""
        state = self.link.snapshot(slot)
        reasons = self.errors(slot, airborne=True)
        if state.get("phase") != "AVAILABLE":
            reasons.append(f"phase {state.get('phase') or 'unknown'}, needs AVAILABLE")
        if self.active_task(slot):
            reasons.append("already executing a task")
        peer = self.link.snapshot(peer_of(slot))
        targets = [t for t in self.state["tasks"] if t.get("owner_drone_id") != slot and t["status"] in ACTIVE_TASKS]
        # Avoid dispatching into a peer's occupied/claimed target area.
        if any(distance_m(waypoint["lat"], waypoint["lon"], t["lat"], t["lon"]) < self.safety["min_separation_m"] for t in targets):
            reasons.append("target within minimum separation of the peer's claimed waypoint")
        if peer.get("lat") is not None and distance_m(waypoint["lat"], waypoint["lon"], peer["lat"], peer["lon"]) < self.safety["min_separation_m"]:
            reasons.append("target within minimum separation of the peer's position")
        return reasons

    def planner_params(self, offsets):
        s = self.settings
        return dict(v_cruise_mps=s.SWARM_PLANNER_V_CRUISE_MPS, t_accel_s=s.SWARM_PLANNER_T_ACCEL_S,
                    yaw_rate_dps=s.SWARM_PLANNER_YAW_RATE_DPS or None, dwell_s=s.SWARM_PLANNER_DWELL_S,
                    wind_speed_mps=s.SWARM_PLANNER_WIND_SPEED_MPS, wind_from_deg=s.SWARM_PLANNER_WIND_FROM_DEG,
                    cpsat_time_limit_s=s.SWARM_PLANNER_TIME_LIMIT_S,
                    routing_time_limit_s=s.SWARM_PLANNER_TIME_LIMIT_S, start_offset_s=offsets)

    def route_inputs(self, airborne):
        """PENDING waypoints plus, per UAV, where and after how long it is next free: a busy
        UAV from its current target once it gets there, a grounded one from its takeoff point."""
        s = self.settings
        pending = [t for t in self.state["tasks"] if t["status"] == "PENDING"]
        starts, offsets = [], []
        for slot in SLOTS:
            drone, active = self.link.snapshot(slot), self.active_task(slot)
            if active:
                remaining = math.hypot(distance_m(drone["lat"], drone["lon"], active["lat"], active["lon"]),
                                       drone["alt_m"] - active["alt_m"])
                starts.append((active["lat"], active["lon"], active["alt_m"]))
                offsets.append(remaining / s.SWARM_PLANNER_V_CRUISE_MPS + s.SWARM_PLANNER_T_ACCEL_S
                               + s.SWARM_PLANNER_DWELL_S)
            else:
                starts.append((drone["lat"], drone["lon"], drone["alt_m"] if airborne else self.safety["takeoff_alt_m"]))
                offsets.append(0.0)
        return pending, starts, offsets

    async def solve_routes(self, pending, starts, offsets):
        # The solver can take seconds; a worker thread keeps heartbeats and ticks running.
        coords = [(t["lat"], t["lon"], t["alt_m"]) for t in pending]
        result = await asyncio.to_thread(plan_routes, coords, starts, self.planner_params(offsets))
        return result, [t["task_id"] for t in pending]

    async def plan_route(self, airborne):
        return await self.solve_routes(*self.route_inputs(airborne))

    def apply_route(self, result, task_ids, event):
        self.state["route"] = dict(
            queues={str(slot): [task_ids[i] for i in route] for slot, route in zip(SLOTS, result.routes)},
            planned_for=sorted(task_ids), method=result.method, makespan_s=round(result.makespan_s, 2),
            durations_s={str(slot): round(d, 2) for slot, d in zip(SLOTS, result.durations_s)},
            proven_optimal=result.proven_optimal,
            lower_bound_s=None if result.lower_bound_s is None else round(result.lower_bound_s, 2),
            solve_time_s=round(result.solve_time_s, 3), notes=result.notes, planned_at=time.time())
        self.save(event, route=copy.deepcopy(self.state["route"]))

    def replan_reason(self):
        """Why the remaining waypoints need a new plan, or None."""
        route = self.state.get("route") or {}
        queued = {i for ids in route.get("queues", {}).values() for i in ids}
        pending = sorted(t["task_id"] for t in self.state["tasks"] if t["status"] == "PENDING")
        if any(i not in queued for i in pending):
            return "waypoints without a planned owner"
        if pending == route.get("planned_for"):
            return None  # this exact remainder was already balanced
        for slot in SLOTS:
            if not self.queue(slot) and not self.active_task(slot) and self.queue(peer_of(slot)):
                return f"UAV-{slot} finished its route while UAV-{peer_of(slot)} still has waypoints"
        return None

    def request_replan(self, reason):
        key = (self.state["plan"]["mission_id"], self.state["plan"]["version"])
        job = asyncio.create_task(self.solve_routes(*self.route_inputs(airborne=True)))
        self.replanning = (job, key)
        self.save("ROUTE_REPLAN_STARTED", reason=reason)

    async def collect_replan(self):
        """Apply a finished background plan. False when it failed and the swarm was held."""
        if not self.replanning or not self.replanning[0].done():
            return True
        (job, key), self.replanning = self.replanning, None
        if key != (self.state["plan"]["mission_id"], self.state["plan"]["version"]):
            return True  # the mission changed while solving; plan again from fresh state
        try:
            planned = job.result()
        except Exception as exc:
            logger.exception("Route replanning failed")
            await self.safe_hold(f"Route planning failed: {exc}")
            return False
        self.apply_route(*planned, event="ROUTE_REPLANNED")
        return True

    def note_waiting(self, task, reason, event=True):
        if task.get("reason") != reason:
            task["reason"] = reason
            if event:
                self.save("TASK_WAITING", task_id=task["task_id"], reason=reason)

    def hand_over(self, slot, task):
        """Give `task` to the idle peer once its separation zone has blocked `slot` for
        SWARM_DEFER_S; otherwise an idle UAV hovering on the target would deadlock it."""
        since = self.deferred_at.setdefault(task["task_id"], time.monotonic())
        peer = peer_of(slot)
        if (time.monotonic() - since < self.settings.SWARM_DEFER_S or self.queue(peer)
                or self.active_task(peer) or self.blockers(peer, task)):
            return False
        queues = self.state["route"]["queues"]
        queues[str(slot)].remove(task["task_id"])
        queues[str(peer)].insert(0, task["task_id"])
        self.deferred_at.pop(task["task_id"], None)
        self.save("TASK_HANDOFF", task_id=task["task_id"], from_drone_id=slot, to_drone_id=peer,
                  reason="target inside the idle peer's separation zone")
        return True

    async def dispatch(self, slot):
        """Send `slot` the next waypoint of its route. False when a lost ACK held the swarm."""
        queue = self.queue(slot)
        if not queue:
            return True
        task = queue[0]
        validate_target(task, self.safety)
        reasons = self.blockers(slot, task)
        if reasons:
            if self.active_task(slot):
                self.note_waiting(task, f"Next for UAV-{slot} after its current waypoint", event=False)
            elif not (self.link.snapshot(slot).get("phase") == "AVAILABLE" and self.hand_over(slot, task)):
                self.note_waiting(task, f"Waiting for UAV-{slot} (planned owner) — " + "; ".join(reasons))
            return True
        self.deferred_at.pop(task["task_id"], None)
        drone = self.link.snapshot(slot)
        distance = distance_m(drone["lat"], drone["lon"], task["lat"], task["lon"])
        route = self.state["route"]
        planned = route["queues"][str(slot)]
        ident = uuid.uuid4().hex
        task.update(owner_drone_id=slot, assignment_version=1, command_id=ident,
                    status="ASSIGNED", distance_at_assignment_m=distance,
                    reason=f"Route plan UAV-{slot}, stop {planned.index(task['task_id']) + 1}/{len(planned)}; "
                           f"{route['method']}, planned makespan {route['makespan_s']:.1f} s")
        self.save("TASK_ASSIGN", task=copy.deepcopy(task), candidates=self.candidates_telemetry())
        try:
            target = next(w for w in self.wire_plan()["waypoints"] if w["task_id"] == task["task_id"])
            await self.link.request(slot, "TASK_ASSIGN", command_id=ident,
                mission_id=self.state["plan"]["mission_id"], version=self.state["plan"]["version"],
                task_id=task["task_id"], assignment_version=1, owner_drone_id=slot, target=target)
            task["status"] = "ACKED"
            self.save("TASK_ACK", task_id=task["task_id"], drone_id=slot, command_id=ident)
        except Exception as exc:
            task["status"] = "UNKNOWN"
            self.save("TASK_UNKNOWN", task_id=task["task_id"], error=str(exc))
            await self.safe_hold(str(exc))
            return False
        return True

    def clear_task_reasons(self):
        # Stale text from an earlier attempt would otherwise suppress this run's TASK_WAITING event.
        self.deferred_at.clear()
        for task in self.state["tasks"]:
            task.pop("reason", None)

    def rearm_tasks(self):
        """An upload re-arms every waypoint. Without this, CANCELLED tasks left by an
        abort (or REACHED ones from a finished run) survive into the next flight and the
        dispatch loop finds nothing PENDING, so both UAVs hover with no assignment."""
        self.deferred_at.clear()
        self.replanning = None
        self.state["route"] = {}  # planned afresh at START from the grounded positions
        self.state["tasks"] = [dict(w, status="PENDING", owner_drone_id=None, assignment_version=0)
                               for w in self.state["plan"]["waypoints"]]

    async def tick(self):
        if self.lock.locked():
            return
        async with self.lock:
            phase = self.state["phase"]
            if phase not in ("ACTIVE", "PREPARING", "HELD", "ENDING"):
                return
            self.reconcile()
            if phase == "HELD":
                return
            if phase == "ENDING":
                expected = "FINISHED_HOLD" if self.settings.SWARM_END_ACTION == "HOLD" else "COMPLETED"
                if all(self.link.snapshot(s).get("connected") and self.link.snapshot(s).get("phase") in (expected, "COMPLETED") for s in SLOTS):
                    self.state["phase"] = "COMPLETED"
                    self.save("MISSION_COMPLETED")
                return
            # ACTIVE means both companions finished takeoff, so hold them to the airborne
            # checks dispatch itself uses; otherwise a UAV that leaves GUIDED is silently
            # dropped from every candidate list and the mission hangs without a fault.
            errors = self.precheck(airborne=phase == "ACTIVE")
            if errors or any(self.link.snapshot(s).get("phase") == "FAULT" for s in SLOTS):
                for task in self.state["tasks"]:
                    if task["status"] in ACTIVE_TASKS:
                        task["status"] = "UNKNOWN"
                await self.safe_hold("; ".join(errors) or "Companion flight fault")
                return
            if phase == "PREPARING":
                if all(self.link.snapshot(s).get("phase") in ("AVAILABLE", "BUSY") for s in SLOTS):
                    self.state["phase"] = "ACTIVE"
                    self.save("SWARM_AVAILABLE")
                elif self.started_at and time.monotonic() - self.started_at > 90:
                    await self.safe_hold("Preparation timed out")
                return
            if not await self.collect_replan():
                return
            if self.replanning is None and (reason := self.replan_reason()):
                self.request_replan(reason)
            if self.replanning is None:  # new assignments wait for a plan in progress
                for slot in SLOTS:
                    if not await self.dispatch(slot):
                        return
            if all(t["status"] == "REACHED" for t in self.state["tasks"]):
                self.state["phase"] = "ENDING"
                self.save("END_ACTION", action=self.settings.SWARM_END_ACTION)
                if not await self.both("END", action=self.settings.SWARM_END_ACTION):
                    await self.safe_hold("End-action ACK incomplete")

    def candidates_telemetry(self):
        return [{k: self.link.snapshot(s).get(k) for k in ("drone_id", "lat", "lon", "phase", "position_age_s")} for s in SLOTS]

    async def start(self):
        if self.state["plan"] and not self.config_errors():
            self.link.configure(self.state["plan"]["endpoints"])
        await self.link.start()
        self.worker = asyncio.create_task(self.run(), name="route-waypoint-scheduler")

    async def run(self):
        try:
            while True:
                await self.tick()
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Swarm scheduler stopped")
            self.state.update(phase="RECOVERY_REQUIRED", error=str(exc))
            try:
                self.save("SCHEDULER_FAILURE", error=str(exc))
            finally:
                await self.link.close()  # stop heartbeats so companions invoke watchdog

    async def close(self):
        if self.replanning:
            self.replanning[0].cancel()
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        await self.link.close()
        self.store.close()
