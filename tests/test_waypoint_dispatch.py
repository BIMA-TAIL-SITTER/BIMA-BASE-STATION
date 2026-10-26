"""Safety and ownership tests. Test doubles here are never production transports."""
import asyncio
import copy
import tempfile
import time
import unittest
from pathlib import Path

from app.config.settings import Settings
from app.schemas.waypoint_dispatch import DispatchPlan
from app.services.mission.dispatch_store import MissionStore
from app.services.mission.waypoint_scheduler import MissionConflict, WaypointScheduler
from mission_scripts.swarm_protocol import Reassembler, digest, distance_m, frames, health_errors, safety_hash, validate_plan

KEY = "test-key-only-" + "a" * 32
SAFETY = dict(center_lat=-7.0, center_lon=110.0, radius_m=500.0, min_alt_m=2.0,
              max_alt_m=50.0, takeoff_alt_m=5.0, min_battery_pct=25.0, min_separation_m=10.0)


def plan():
    return {"mission_id": "mission-test", "version": 1, "coordinate_frame": "GLOBAL_RELATIVE_ALT",
            "endpoints": {"3": {"host": "127.0.0.1", "port": 14560}, "4": {"host": "127.0.0.1", "port": 14561}},
            "waypoints": [{"task_id": "wp-1", "sequence": 1, "lat": -7.0, "lon": 110.0004, "alt_m": 10.0},
                          {"task_id": "wp-2", "sequence": 2, "lat": -7.0004, "lon": 110.0, "alt_m": 10.0}]}


def healthy(slot):
    return dict(drone_id=slot, connected=True, lat=-7.0, lon=110.0 if slot == 3 else 110.0002,
                capabilities=["PLAN_APPEND"], alt_m=5.0, alt_msl_m=105.0, vx=0.0, vy=0.0, vz=0.0, gps_fix=3, battery_pct=80,
                sensors_ok=True, system_status=3, armed=False, mode="GUIDED", phase="IDLE",
                heartbeat_age_s=0.1, position_age_s=0.1, gps_age_s=0.1, health_age_s=0.1,
                home={"lat": -7.0, "lon": 110.0, "alt_msl_m": 100.0}, safety_hash=safety_hash(SAFETY))


class StubLink:
    def __init__(self):
        self.states = {s: healthy(s) for s in (3, 4)}
        self.sent = []
        self.fail = set()

    def snapshot(self, slot):
        return copy.deepcopy(self.states[slot])

    def configure(self, endpoints):
        self.endpoints = endpoints

    async def request(self, slot, kind, **body):
        self.sent.append((slot, kind, copy.deepcopy(body)))
        if (slot, kind) in self.fail:
            raise TimeoutError("lost ACK")
        state = self.states[slot]
        if kind in ("PLAN_SYNC", "PLAN_APPEND"):
            state.update(mission_id=body["mission_id"], version=body["version"], plan_hash=digest(body["plan"]))
        elif kind == "PREPARE":
            state.update(phase="PREPARING")
        elif kind == "TASK_ASSIGN":
            state.update(phase="BUSY", task=dict(body, status="EN_ROUTE"))
        elif kind == "HOLD":
            state.update(phase="HELD", mode="LOITER")
            if state.get("task"):
                state["task"]["status"] = "HELD"
        elif kind == "RESUME":
            state.update(phase="BUSY" if state.get("task") else "AVAILABLE", mode="GUIDED")
        elif kind in ("ABORT", "END"):
            state.update(phase="RTL", mode="RTL")
        return {"accepted": True, "plan_hash": state.get("plan_hash"), "latency_ms": 1}

    async def close(self):
        pass


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(_env_file=None, SWARM_CENTER_LAT=-7, SWARM_CENTER_LON=110,
                                 SWARM_RADIUS_M=500, SWARM_LINK_KEY=KEY, SWARM_OPERATOR_TOKEN="operator-test",
                                 SWARM_STORE_PATH=str(Path(self.tmp.name) / "state.sqlite3"))
        self.link = StubLink()
        self.scheduler = WaypointScheduler(self.link, self.settings)
        await self.scheduler.save_plan(plan())

    async def asyncTearDown(self):
        self.scheduler.store.close()
        self.tmp.cleanup()

    async def upload(self):
        return await self.scheduler.action("mission-test", 1, "upload")

    async def activate(self):
        await self.upload()
        await self.scheduler.action("mission-test", 1, "start", "CONFIRM_START")
        for state in self.link.states.values():
            state.update(phase="AVAILABLE", armed=True)
        await self.scheduler.tick()

    async def settle_replan(self):
        """Let a background route plan finish, then tick so it is applied."""
        if self.scheduler.replanning:
            await asyncio.wait([self.scheduler.replanning[0]])  # failures surface via tick, not here
        await self.scheduler.tick()

    def reach(self, slot):
        """UAV `slot` arrives at its assigned target and reports it."""
        task = next(t for t in self.scheduler.state["tasks"]
                    if t["owner_drone_id"] == slot and t["status"] in ("ACKED", "EN_ROUTE"))
        drone = self.link.states[slot]
        drone.update(lat=task["lat"], lon=task["lon"], alt_m=task["alt_m"], phase="AVAILABLE")
        drone["task"]["status"] = "REACHED"
        return task

    async def test_upload_plan_to_both_without_arming(self):
        state = await self.upload()
        self.assertEqual(state["phase"], "UPLOADED")
        self.assertTrue(state["ready_to_start"])
        self.assertEqual([kind for _, kind, _ in self.link.sent], ["PLAN_SYNC", "PLAN_SYNC"])
        self.assertEqual(self.link.sent[0][2]["plan"], self.link.sent[1][2]["plan"])
        self.assertFalse(any(s["armed"] for s in self.link.states.values()))

    async def test_partial_upload_blocks_start(self):
        self.link.fail.add((4, "PLAN_SYNC"))
        state = await self.upload()
        self.assertEqual(state["phase"], "PARTIAL")
        with self.assertRaises(MissionConflict):
            await self.scheduler.action("mission-test", 1, "start", "CONFIRM_START")
        self.assertFalse(any(kind == "PREPARE" for _, kind, _ in self.link.sent))

    async def test_reupload_allowed_after_abort_and_completed(self):
        # Re-syncing the same plan must work from every EDITABLE phase, not just the
        # pre-flight ones; companions themselves accept PLAN_SYNC while IDLE or COMPLETED.
        for terminal_phase in ("ABORTED", "COMPLETED"):
            self.scheduler.state["phase"] = terminal_phase
            for state in self.link.states.values():
                state.update(armed=False)
            state = await self.upload()
            self.assertEqual(state["phase"], "UPLOADED")

    async def test_start_needs_confirmation_and_fresh_gps(self):
        await self.upload()
        with self.assertRaises(MissionConflict):
            await self.scheduler.action("mission-test", 1, "start")
        self.link.states[3]["position_age_s"] = 4
        with self.assertRaises(MissionConflict):
            await self.scheduler.action("mission-test", 1, "start", "CONFIRM_START")

    async def test_geofence_update_persists_and_reloads(self):
        snap = await self.scheduler.update_geofence(-7.00001, 110.00001, 400.0)
        self.assertEqual(snap["safety"]["radius_m"], 400.0)
        self.assertAlmostEqual(self.scheduler.safety["center_lat"], -7.00001)
        self.assertEqual(self.scheduler.store.load_config("geofence"),
                         {"center_lat": -7.00001, "center_lon": 110.00001, "radius_m": 400.0})
        reloaded = WaypointScheduler(self.link, self.settings)
        try:
            self.assertEqual(reloaded.safety["radius_m"], 400.0)
            self.assertAlmostEqual(reloaded.safety["center_lat"], -7.00001)
        finally:
            reloaded.store.close()

    async def test_geofence_rejects_waypoints_outside_new_circle(self):
        with self.assertRaises(MissionConflict):
            await self.scheduler.update_geofence(-6.99, 110.0, 500.0)
        self.assertEqual(self.scheduler.safety["center_lat"], -7)

    async def test_geofence_rejects_while_armed(self):
        for state in self.link.states.values():
            state["armed"] = True
        with self.assertRaises(MissionConflict):
            await self.scheduler.update_geofence(-7.00001, 110.00001, 400.0)

    async def test_geofence_change_resets_upload(self):
        await self.upload()
        self.assertEqual(self.scheduler.state["phase"], "UPLOADED")
        await self.scheduler.update_geofence(-7.00001, 110.00001, 400.0)
        self.assertEqual(self.scheduler.state["phase"], "PARTIAL")
        self.assertEqual(set(self.scheduler.state["upload"].values()), {"UNKNOWN"})

    async def test_assignment_follows_route_plan_single_owner_parallel(self):
        await self.activate()
        route = self.scheduler.state["route"]
        self.assertEqual(route["queues"], {"3": ["wp-2"], "4": ["wp-1"]})
        self.assertTrue(route["proven_optimal"])
        self.assertEqual(route["makespan_s"], max(route["durations_s"].values()))
        await self.scheduler.tick()
        tasks = self.scheduler.state["tasks"]
        self.assertEqual([t["owner_drone_id"] for t in tasks], [4, 3])
        self.assertEqual([t["status"] for t in tasks], ["ACKED", "ACKED"])
        self.assertIn("Route plan UAV-4", tasks[0]["reason"])
        commands = [(s, b["task_id"]) for s, k, b in self.link.sent if k == "TASK_ASSIGN"]
        self.assertEqual(commands, [(3, "wp-2"), (4, "wp-1")])
        await self.scheduler.tick()
        self.assertEqual(len([k for _, k, _ in self.link.sent if k == "TASK_ASSIGN"]), 2)
        types = [e["type"] for e in self.scheduler.store.events()]
        self.assertIn("ROUTE_PLANNED", types)
        self.assertIn("TASK_ASSIGN", types)

    async def test_route_is_planned_at_start_before_any_flight_command(self):
        await self.upload()
        self.assertEqual(self.scheduler.state["route"], {})
        await self.scheduler.action("mission-test", 1, "start", "CONFIRM_START")
        planned = [e for e in self.scheduler.store.events() if e["type"] == "ROUTE_PLANNED"]
        prepare = [e for e in self.scheduler.store.events() if e["type"] == "COMMAND_ACCEPTED" and e["operation"] == "PREPARE"]
        self.assertEqual(len(planned), 1)
        self.assertLess(planned[0]["id"], min(e["id"] for e in prepare))

    async def test_start_refused_when_route_planning_fails(self):
        await self.upload()
        self.settings.SWARM_PLANNER_WIND_SPEED_MPS = 9  # faster than cruise: no feasible cost model
        with self.assertRaises(MissionConflict):
            await self.scheduler.action("mission-test", 1, "start", "CONFIRM_START")
        self.assertEqual(self.scheduler.state["phase"], "UPLOADED")
        self.assertFalse(any(kind == "PREPARE" for _, kind, _ in self.link.sent))

    async def test_each_uav_flies_its_own_queue_in_order(self):
        extra = plan()
        extra["waypoints"] += [{"task_id": "wp-3", "sequence": 3, "lat": -7.0, "lon": 110.0008, "alt_m": 10.0},
                               {"task_id": "wp-4", "sequence": 4, "lat": -7.0008, "lon": 110.0, "alt_m": 10.0}]
        extra["version"] = 2
        await self.scheduler.save_plan(extra)
        await self.scheduler.action("mission-test", 2, "upload")
        await self.scheduler.action("mission-test", 2, "start", "CONFIRM_START")
        for state in self.link.states.values():
            state.update(phase="AVAILABLE", armed=True)
        for _ in range(3):  # activate, first assignments, then the queued heads wait
            await self.scheduler.tick()
        queues = self.scheduler.state["route"]["queues"]
        self.assertEqual(queues, {"3": ["wp-2", "wp-4"], "4": ["wp-1", "wp-3"]})
        waiting = {t["task_id"]: t for t in self.scheduler.state["tasks"]}
        self.assertEqual(waiting["wp-3"]["status"], "PENDING")
        self.assertIn("UAV-4 after its current waypoint", waiting["wp-3"]["reason"])
        self.reach(4)
        await self.scheduler.tick()
        self.assertEqual((waiting["wp-3"]["status"], waiting["wp-3"]["owner_drone_id"]), ("ACKED", 4))
        self.assertEqual(waiting["wp-4"]["status"], "PENDING")

    async def test_idle_uav_takes_over_when_peer_still_has_waypoints(self):
        extra = plan()
        extra["waypoints"] += [{"task_id": "wp-3", "sequence": 3, "lat": -7.0, "lon": 110.0008, "alt_m": 10.0},
                               {"task_id": "wp-4", "sequence": 4, "lat": -7.0, "lon": 110.0012, "alt_m": 10.0}]
        extra["version"] = 2
        await self.scheduler.save_plan(extra)
        await self.scheduler.action("mission-test", 2, "upload")
        await self.scheduler.action("mission-test", 2, "start", "CONFIRM_START")
        for state in self.link.states.values():
            state.update(phase="AVAILABLE", armed=True)
        await self.scheduler.tick()
        await self.scheduler.tick()
        self.assertEqual(self.scheduler.state["route"]["queues"], {"3": ["wp-1", "wp-2"], "4": ["wp-3", "wp-4"]})
        # Pretend the plan left UAV-3 nothing after wp-1 while UAV-4 still has two waypoints.
        self.scheduler.state["route"]["queues"] = {"3": ["wp-1"], "4": ["wp-3", "wp-2", "wp-4"]}
        self.reach(3)
        await self.scheduler.tick()
        types = [e["type"] for e in self.scheduler.store.events()]
        self.assertIn("ROUTE_REPLAN_STARTED", types)
        self.assertTrue(self.scheduler.snapshot()["replanning"])
        await self.settle_replan()
        self.assertIn("ROUTE_REPLANNED", [e["type"] for e in self.scheduler.store.events()])
        queues = self.scheduler.state["route"]["queues"]
        self.assertEqual(sorted(queues["3"] + queues["4"]), ["wp-2", "wp-4"])
        self.assertIn("wp-2", queues["3"])  # right next to UAV-3, far behind UAV-4's queue
        self.assertEqual(self.scheduler.state["tasks"][1]["owner_drone_id"], 3)

    async def test_blocked_target_is_handed_to_the_idle_peer(self):
        self.settings.SWARM_DEFER_S = 0
        await self.activate()
        self.scheduler.state["route"]["queues"] = {"3": ["wp-2", "wp-1"], "4": []}
        self.scheduler.state["route"]["planned_for"] = ["wp-1"]  # a rebalance already left it with UAV-3
        # UAV-4 idles right on wp-1, so UAV-3 may never fly there.
        self.link.states[4].update(lat=-7.0, lon=110.0004)
        self.scheduler.state["tasks"][1]["status"] = "REACHED"
        await self.scheduler.tick()
        handoff = [e for e in self.scheduler.store.events() if e["type"] == "TASK_HANDOFF"]
        self.assertEqual((handoff[0]["from_drone_id"], handoff[0]["to_drone_id"]), (3, 4))
        self.assertEqual(self.scheduler.state["tasks"][0]["owner_drone_id"], 4)

    async def test_reupload_rearms_cancelled_tasks_for_the_next_flight(self):
        # Regression: an abort leaves every task CANCELLED. Re-uploading the same plan
        # must re-arm them, otherwise the next flight has nothing PENDING to dispatch
        # and both UAVs hover until the operator gives up.
        await self.upload()
        await self.scheduler.action("mission-test", 1, "abort", "CONFIRM_ABORT")
        self.assertTrue(all(t["status"] == "CANCELLED" for t in self.scheduler.state["tasks"]))
        for state in self.link.states.values():
            state.update(armed=False, phase="IDLE", mode="GUIDED")
        await self.upload()
        self.assertTrue(all(t["status"] == "PENDING" for t in self.scheduler.state["tasks"]))
        self.assertTrue(all(t["owner_drone_id"] is None for t in self.scheduler.state["tasks"]))

    async def test_lost_guided_holds_instead_of_hanging_undispatched(self):
        # Regression: candidates() enforces the airborne checks, so a UAV that leaves
        # GUIDED must raise a hold rather than silently stall every assignment.
        await self.activate()
        for task in self.scheduler.state["tasks"]:
            task.update(status="PENDING", owner_drone_id=None, command_id=None)
        self.link.states[3]["mode"] = "STABILIZE"
        await self.scheduler.tick()
        self.assertIn(self.scheduler.state["phase"], ("HELD", "HOLD_REQUIRED"))
        self.assertIn("not armed in GUIDED", self.scheduler.state["error"])

    async def test_waiting_reason_names_the_planned_owner(self):
        await self.activate()
        for state in self.link.states.values():
            state["phase"] = "BUSY"
        await self.scheduler.tick()
        first, second = self.scheduler.state["tasks"]
        self.assertIn("UAV-4", first["reason"])
        self.assertIn("UAV-3", second["reason"])
        self.assertIn("needs AVAILABLE", first["reason"])
        self.assertTrue(any(e["type"] == "TASK_WAITING" for e in self.scheduler.store.events()))

    async def test_busy_drone_keeps_its_waypoint_while_peer_flies_its_own(self):
        await self.activate()
        self.link.states[4]["phase"] = "BUSY"
        await self.scheduler.tick()
        first, second = self.scheduler.state["tasks"]
        self.assertEqual((second["owner_drone_id"], second["status"]), (3, "ACKED"))
        self.assertEqual(first["status"], "PENDING")
        self.assertIn("UAV-4", first["reason"])

    async def test_task_ack_timeout_never_reassigns(self):
        await self.activate()
        self.link.fail.add((4, "TASK_ASSIGN"))
        await self.scheduler.tick()
        first = self.scheduler.state["tasks"][0]
        self.assertEqual((first["status"], first["owner_drone_id"]), ("UNKNOWN", 4))
        await self.scheduler.tick()
        self.assertEqual(len([b for _, k, b in self.link.sent if k == "TASK_ASSIGN" and b["task_id"] == "wp-1"]), 1)

    async def test_reached_requires_owner_command_version_and_real_position(self):
        await self.activate()
        await self.scheduler.tick()
        task = self.scheduler.state["tasks"][0]
        drone = self.link.states[4]
        drone["task"]["status"] = "REACHED"
        self.scheduler.reconcile()
        self.assertNotEqual(task["status"], "REACHED")
        drone.update(lat=task["lat"], lon=task["lon"], alt_m=task["alt_m"], phase="AVAILABLE")
        original = drone["task"]["command_id"]
        drone["task"]["command_id"] = "wrong"
        self.scheduler.reconcile()
        self.assertNotEqual(task["status"], "REACHED")
        drone["task"]["command_id"] = original
        self.scheduler.reconcile()
        self.assertEqual(task["status"], "REACHED")

    async def test_link_loss_stops_new_dispatch_and_preserves_owner(self):
        await self.activate()
        self.link.states[3]["position_age_s"] = 3
        await self.scheduler.tick()
        self.assertIn(self.scheduler.state["phase"], ("HELD", "HOLD_REQUIRED"))
        self.assertFalse(any(k == "TASK_ASSIGN" for _, k, _ in self.link.sent))

    async def test_partial_prepare_holds_both(self):
        await self.upload()
        self.link.fail.add((4, "PREPARE"))
        await self.scheduler.action("mission-test", 1, "start", "CONFIRM_START")
        self.assertEqual(self.scheduler.state["phase"], "HELD")
        self.assertEqual({s for s, k, _ in self.link.sent if k == "HOLD"}, {3, 4})

    async def test_mission_version_and_midflight_edit_lock(self):
        changed = plan()
        changed["waypoints"][0]["alt_m"] = 20
        with self.assertRaises(MissionConflict):
            await self.scheduler.save_plan(changed)
        changed["version"] = 2
        await self.scheduler.save_plan(changed)
        versions = [e for e in self.scheduler.store.events() if e["type"] == "PLAN_VALIDATED"]
        self.assertEqual([e["mission_version"] for e in versions], [2, 1])
        self.assertEqual(versions[0]["plan"]["waypoints"][0]["alt_m"], 20)
        self.assertEqual(versions[1]["plan"]["waypoints"][0]["alt_m"], 10)
        self.assertEqual(self.scheduler.state["phase"], "DRAFT")
        self.scheduler.state["phase"] = "ACTIVE"
        changed["version"] = 3
        with self.assertRaises(MissionConflict):
            await self.scheduler.save_plan(changed)

    async def test_restart_retains_unknown_owner_and_cannot_auto_dispatch(self):
        await self.activate()
        await self.scheduler.tick()
        recovered = WaypointScheduler(self.link, self.settings)
        try:
            self.assertEqual(recovered.state["phase"], "RECOVERY_REQUIRED")
            self.assertEqual(recovered.state["tasks"][0]["owner_drone_id"], 4)
            self.assertEqual(recovered.state["tasks"][0]["status"], "UNKNOWN")
            before = len(self.link.sent)
            await recovered.tick()
            self.assertEqual(len(self.link.sent), before)
        finally:
            recovered.store.close()

    async def test_abort_incomplete_ack_is_not_reported_safe(self):
        await self.activate()
        await self.scheduler.tick()
        self.link.fail.add((4, "ABORT"))
        result = await self.scheduler.action("mission-test", 1, "abort", "CONFIRM_ABORT")
        self.assertEqual(result["phase"], "HOLD_REQUIRED")
        self.assertEqual(result["tasks"][0]["status"], "UNKNOWN")

    async def test_terminal_airborne_or_unreconciled_cannot_release_ownership(self):
        await self.activate()
        self.scheduler.state["phase"] = "ABORTED"
        for state in self.link.states.values():
            state.update(connected=False, armed=False)
        self.assertTrue(self.scheduler.owns_copters())
        new = plan()
        new["version"] = 2
        with self.assertRaises(MissionConflict):
            await self.scheduler.save_plan(new)

    async def test_only_one_mutation_at_a_time(self):
        async with self.scheduler.lock:
            with self.assertRaises(MissionConflict):
                await self.upload()

    async def test_interrupted_upload_can_be_retried_after_restart(self):
        self.scheduler.state["phase"] = "UPLOADING"
        self.scheduler.save("UPLOAD_STARTED")
        recovered = WaypointScheduler(self.link, self.settings)
        try:
            self.assertEqual(recovered.state["phase"], "PARTIAL")
            result = await recovered.action("mission-test", 1, "upload")
            self.assertEqual(result["phase"], "UPLOADED")
        finally:
            recovered.store.close()


class GeometryProtocolTests(unittest.TestCase):
    def test_invalid_stale_positions_and_geofence(self):
        for update in ({"lat": 0, "lon": 0}, {"lat": float("nan")}, {"gps_fix": 2},
                       {"position_age_s": 3}, {"health_age_s": None}, {"battery_pct": -1}, {"sensors_ok": False}):
            with self.subTest(update=update):
                self.assertTrue(health_errors(dict(healthy(3), **update), SAFETY))
        bad = plan()
        bad["waypoints"][0]["lat"] = 0
        with self.assertRaises(ValueError):
            validate_plan(bad, SAFETY)
        bad = plan()
        bad["waypoints"][0]["alt_m"] = 100
        with self.assertRaises(ValueError):
            validate_plan(bad, SAFETY)

    def test_protocol_fragment_reorder_duplicates_tamper_wrong_key(self):
        body = dict(protocol=1, kind="PLAN_SYNC", plan=plan())
        packets = frames(body, KEY)
        parser = Reassembler(KEY)
        parser.feed(packets[-1])
        result = None
        for packet in reversed(packets):
            result = parser.feed(packet) or result
        self.assertEqual(result, body)
        wrong = Reassembler("b" * 32)
        self.assertFalse(any(wrong.feed(p) for p in packets))
        tampered = list(packets)
        tampered[-1] = tampered[-1][:-1] + b"x"
        parser = Reassembler(KEY)
        self.assertFalse(any(parser.feed(p) for p in tampered))

    def test_schema_rejects_same_endpoints_and_nonfinite_altitude(self):
        bad = plan()
        bad["endpoints"]["4"] = bad["endpoints"]["3"]
        with self.assertRaises(ValueError):
            DispatchPlan.model_validate(bad)
        bad = plan()
        bad["waypoints"][0]["alt_m"] = float("nan")
        with self.assertRaises(ValueError):
            DispatchPlan.model_validate(bad)
