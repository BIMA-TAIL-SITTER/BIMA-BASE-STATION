"""Append-only airborne plan updates, retries, and execution preservation."""
import copy
import unittest
from app.services.mission.waypoint_scheduler import MissionConflict, WaypointScheduler
from mission_scripts.swarm_protocol import digest
import test_waypoint_dispatch as dispatch_cases
from test_waypoint_dispatch import plan
import test_swarm_companion as companion_cases
from test_swarm_companion import deliver, request, sync


def addition():
    return dict(task_id="wp-3", sequence=3, lat=-7.001, lon=110.001, alt_m=10.0)


class AppendSchedulerTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = dispatch_cases.DispatchTests.asyncSetUp
    asyncTearDown = dispatch_cases.DispatchTests.asyncTearDown
    upload = dispatch_cases.DispatchTests.upload
    activate = dispatch_cases.DispatchTests.activate
    settle_replan = dispatch_cases.DispatchTests.settle_replan
    reach = dispatch_cases.DispatchTests.reach

    async def test_active_append_preserves_assignments_then_new_task_is_planned(self):
        await self.activate()
        await self.scheduler.tick()
        old = copy.deepcopy(self.scheduler.state["tasks"])
        before = len(self.link.sent)
        result = await self.scheduler.append_waypoints("mission-test", 1, [addition()])
        self.assertEqual(result["phase"], "ACTIVE")
        self.assertEqual(result["plan"]["version"], 2)
        self.assertEqual(result["tasks"][:2], old)
        self.assertEqual(result["tasks"][2]["status"], "PENDING")
        self.assertEqual([k for _, k, _ in self.link.sent[before:]], ["PLAN_APPEND", "PLAN_APPEND"])
        # The appended waypoint has no planned owner yet: plan it in the background.
        await self.scheduler.tick()
        self.assertTrue(self.scheduler.snapshot()["replanning"])
        self.assertEqual(self.scheduler.state["tasks"][2]["status"], "PENDING")
        self.assertTrue(all(self.scheduler.state["upload"][str(s)] == "UAV_ACK" for s in (3, 4)))
        await self.settle_replan()
        owner = next(int(slot) for slot, ids in self.scheduler.state["route"]["queues"].items() if "wp-3" in ids)
        self.assertEqual(self.scheduler.state["tasks"][2]["status"], "PENDING")  # owner still busy
        # Once the planned owner reaches its original target, the appended waypoint is dispatched.
        self.reach(owner)
        await self.scheduler.tick()
        self.assertEqual(self.scheduler.state["tasks"][2]["status"], "ACKED")
        self.assertEqual(self.scheduler.state["tasks"][2]["owner_drone_id"], owner)

    async def test_failed_airborne_replan_holds_the_swarm(self):
        await self.activate()
        await self.scheduler.tick()
        await self.scheduler.append_waypoints("mission-test", 1, [addition()])
        self.settings.SWARM_PLANNER_WIND_SPEED_MPS = 9  # faster than cruise: planner rejects it
        await self.scheduler.tick()
        await self.settle_replan()
        self.assertEqual(self.scheduler.state["phase"], "HELD")
        self.assertIn("Route planning failed", self.scheduler.state["error"])
        self.assertEqual(self.scheduler.state["tasks"][2]["status"], "PENDING")

    async def test_lost_http_reply_is_idempotent_and_stale_different_append_rejected(self):
        await self.activate()
        await self.scheduler.append_waypoints("mission-test", 1, [addition()])
        count = len(self.link.sent)
        again = await self.scheduler.append_waypoints("mission-test", 1, [addition()])
        self.assertEqual(len(again["tasks"]), 3)
        self.assertEqual(len(self.link.sent), count)
        with self.assertRaises(MissionConflict):
            await self.scheduler.append_waypoints("mission-test", 1, [dict(addition(), task_id="different")])

    async def test_partial_append_holds_and_retry_never_duplicates_or_auto_resumes(self):
        await self.activate()
        self.link.fail.add((4, "PLAN_APPEND"))
        failed = await self.scheduler.append_waypoints("mission-test", 1, [addition()])
        self.assertEqual(failed["phase"], "HELD")
        self.assertEqual(len(failed["tasks"]), 2)
        self.assertIn("append_pending", failed)
        with self.assertRaises(MissionConflict):
            await self.scheduler.action("mission-test", 2, "resume", "CONFIRM_RESUME")
        with self.assertRaises(MissionConflict):
            await self.scheduler.append_waypoints("mission-test", 2, [dict(addition(), task_id="other")])
        self.link.fail.clear()
        result = await self.scheduler.append_waypoints("mission-test", 2, [addition()])
        self.assertEqual(result["phase"], "HELD")
        self.assertEqual(len(result["tasks"]), 3)
        self.assertNotIn("append_pending", result)
        self.assertFalse(any(k == "RESUME" for _, k, _ in self.link.sent))

    async def test_dispatch_waits_for_both_acks(self):
        import asyncio
        await self.activate()
        original = self.link.request
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(slot, kind, **body):
            if kind == "PLAN_APPEND" and slot == 4:
                entered.set()
                await release.wait()
            return await original(slot, kind, **body)
        self.link.request = delayed
        operation = asyncio.create_task(self.scheduler.append_waypoints("mission-test", 1, [addition()]))
        await entered.wait()
        try:
            self.assertEqual(self.scheduler.state["phase"], "APPENDING")
            self.assertEqual(len(self.scheduler.state["tasks"]), 2)
            await self.scheduler.tick()
            self.assertFalse(any(k == "TASK_ASSIGN" for _, k, _ in self.link.sent))
            with self.assertRaises(MissionConflict):
                await self.scheduler.append_waypoints("mission-test", 2, [addition()])
        finally:
            release.set()
            await operation

    async def test_rejects_old_companion_invalid_geometry_and_terminal_phase(self):
        await self.activate()
        self.link.states[4]["capabilities"] = []
        self.assertFalse(self.scheduler.snapshot()["append_allowed"])
        with self.assertRaises(MissionConflict):
            await self.scheduler.append_waypoints("mission-test", 1, [addition()])
        self.link.states[4]["capabilities"] = ["PLAN_APPEND"]
        for invalid in (dict(addition(), sequence=1), dict(addition(), task_id="wp-1"), dict(addition(), alt_m=100)):
            with self.assertRaises(ValueError):
                await self.scheduler.append_waypoints("mission-test", 1, [invalid])
            self.assertEqual(self.scheduler.state["plan"]["version"], 1)
        self.scheduler.state["phase"] = "ENDING"
        with self.assertRaises(MissionConflict):
            await self.scheduler.append_waypoints("mission-test", 1, [addition()])

    async def test_restart_keeps_pending_revision_and_requires_hold_before_retry(self):
        await self.activate()
        self.link.fail.add((4, "PLAN_APPEND"))
        await self.scheduler.append_waypoints("mission-test", 1, [addition()])
        recovered = WaypointScheduler(self.link, self.settings)
        try:
            self.assertEqual(recovered.state["phase"], "RECOVERY_REQUIRED")
            self.assertIn("append_pending", recovered.state)
            self.link.fail.clear()
            with self.assertRaises(MissionConflict):
                await recovered.append_waypoints("mission-test", 2, [addition()])
            await recovered.action("mission-test", 2, "hold", "CONFIRM_HOLD")
            result = await recovered.append_waypoints("mission-test", 2, [addition()])
            self.assertEqual(result["phase"], "HELD")
            self.assertEqual(len(result["tasks"]), 3)
        finally:
            recovered.store.close()

    async def test_ack_without_matching_telemetry_does_not_commit(self):
        await self.activate()
        self.settings.SWARM_ACK_TIMEOUT_S = .02
        original = self.link.request
        async def delayed_state(slot, kind, **body):
            if kind == "PLAN_APPEND":
                return {"accepted": True, "plan_hash": digest(body["plan"])}
            return await original(slot, kind, **body)
        self.link.request = delayed_state
        result = await self.scheduler.append_waypoints("mission-test", 1, [addition()])
        self.assertEqual(result["phase"], "HELD")
        self.assertEqual(len(result["tasks"]), 2)
        self.assertIn("append_pending", result)


class AppendCompanionTests(unittest.TestCase):
    setUp = companion_cases.CompanionTests.setUp
    tearDown = companion_cases.CompanionTests.tearDown
    assign = companion_cases.CompanionTests.assign

    def append(self, ident="append", mutate=None):
        old = copy.deepcopy(self.engine.plan)
        candidate = dict(old, version=old["version"] + 1, waypoints=old["waypoints"] + [addition()])
        if mutate:
            mutate(candidate)
        req = request(self.engine, "PLAN_APPEND", ident, plan=candidate,
                      base_version=old["version"], base_hash=digest(old))
        req["version"] = candidate["version"]
        deliver(self.engine, req)
        return req

    def test_busy_append_preserves_target_timers_and_deduplication_across_versions(self):
        sync(self.engine)
        self.engine.phase = "AVAILABLE"
        self.engine.telemetry["armed"] = True
        self.assign()
        before = copy.deepcopy(self.engine.task)
        self.engine.stable_since = 123.0
        self.engine.fc.mav.sent.clear()
        req = self.append()
        self.assertTrue(self.engine.commands["append"]["response"]["accepted"])
        self.assertEqual(self.engine.task, before)
        self.assertEqual(self.engine.phase, "BUSY")
        self.assertEqual(self.engine.stable_since, 123.0)
        self.assertEqual(self.engine.fc.mav.sent, [])
        deliver(self.engine, req)
        retry = dict(req, command_id="append-retry", command_seq=req["command_seq"] + 1)
        deliver(self.engine, retry)
        self.assertEqual(len(self.engine.plan["waypoints"]), 3)
        self.assertTrue(self.engine.commands["append-retry"]["response"]["accepted"])
        # Prior task execution remains recorded even when it is no longer current.
        self.engine.task = None
        self.engine.phase = "AVAILABLE"
        reassigned = request(self.engine, "TASK_ASSIGN", "repeat-task", task_id="wp-2",
            assignment_version=1, owner_drone_id=3, target=plan()["waypoints"][1])
        reassigned.update(version=2, command_seq=retry["command_seq"] + 1)
        deliver(self.engine, reassigned)
        self.assertFalse(self.engine.commands["repeat-task"]["response"]["accepted"])

    def test_append_rejects_changed_existing_waypoint_or_reorder(self):
        sync(self.engine)
        self.engine.phase = "AVAILABLE"
        for ident, mutate in (("edit", lambda p: p["waypoints"][0].update(alt_m=12)),
                              ("reorder", lambda p: p["waypoints"].reverse())):
            self.append(ident, mutate)
            self.assertFalse(self.engine.commands[ident]["response"]["accepted"])
            self.assertEqual(self.engine.plan["version"], 1)

    def test_held_append_does_not_resume_or_send_fc_commands(self):
        sync(self.engine)
        self.engine.phase = "HELD"
        self.engine.fc.mav.sent.clear()
        self.append()
        self.assertEqual(self.engine.phase, "HELD")
        self.assertEqual(self.engine.fc.mav.sent, [])
        self.assertEqual(self.engine.plan["version"], 2)
