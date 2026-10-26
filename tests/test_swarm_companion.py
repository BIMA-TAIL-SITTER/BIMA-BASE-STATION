"""Companion state machine and real UDP/MAVLink framing (not a SITL flight test)."""
import asyncio
import copy
import json
import os
import socket
import tempfile
import time
import unittest
import unittest.mock
from unittest.mock import Mock
from pathlib import Path
from types import SimpleNamespace

from pymavlink import mavutil
from pymavlink.dialects.v20 import common

from app.services.mavlink.swarm_link import SwarmLink, remaining_m
from mission_scripts.swarm_companion import SwarmCompanion
from mission_scripts.swarm_protocol import Reassembler, atomic_json, digest, distance_m, frames
from test_waypoint_dispatch import KEY, SAFETY, healthy, plan


class RecordingMav:
    srcSystem = 1

    def __init__(self):
        self.sent = []

    def __getattr__(self, name):
        def send(*args):
            self.sent.append((name, args))
        return send


def connection():
    return SimpleNamespace(target_system=1, target_component=1, mav=RecordingMav())


def controller(tmp, slot=3, gcs=None):
    result = SwarmCompanion(connection(), gcs or connection(), slot, KEY, SAFETY,
                           Path(tmp) / f"companion-{slot}.json",
                           dict(gcs_heartbeat_timeout=3, hover_alt_tolerance=0.5,
                                hover_vz_threshold=0.2, hover_min_duration=3, hold_duration_s=1))
    result.session = "test-session"
    result.telemetry = healthy(slot)
    result.home = healthy(slot)["home"]
    result.received = {k: time.monotonic() for k in ("HEARTBEAT", "GLOBAL_POSITION_INT", "GPS_RAW_INT", "SYS_STATUS")}
    result.last_gcs = time.monotonic()
    result.peer = healthy(4 if slot == 3 else 3)
    return result


def request(engine, kind, ident="cmd-test", **extra):
    if not hasattr(engine, "test_sequences"):
        engine.test_sequences = {}
    engine.test_sequences.setdefault(ident, len(engine.test_sequences) + 1)
    return dict(protocol=1, kind=kind, session_id=engine.session, drone_id=engine.slot,
                boot_id=engine.boot, command_id=ident, command_seq=engine.test_sequences[ident],
                mission_id="mission-test", version=1, **extra)


def deliver(engine, body):
    for payload in frames(body, KEY):
        message = common.MAVLink_tunnel_message(engine.slot, 191, 32768, len(payload), list(payload.ljust(128, b"\0")))
        message._header.srcSystem = 255
        message._header.srcComponent = 190
        engine.receive_gcs(message)


def sync(engine):
    wire = plan()
    wire.pop("endpoints")
    deliver(engine, request(engine, "PLAN_SYNC", "upload", plan=wire))


class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = controller(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def assign(self, engine=None, ident="assign"):
        engine = engine or self.engine
        deliver(engine, request(engine, "TASK_ASSIGN", ident, task_id="wp-2", assignment_version=1,
                                owner_drone_id=engine.slot, target=plan()["waypoints"][1]))

    def test_plan_resync_rearms_the_task_ledger_for_a_repeat_run(self):
        sync(self.engine)
        self.engine.phase = "AVAILABLE"
        self.engine.telemetry["armed"] = True
        self.assign()
        self.assertTrue(self.engine.commands["assign"]["response"]["accepted"])
        # Same mission flown again: the base station re-arms its tasks on upload,
        # so a stale ledger here would deadlock every waypoint for that mission.
        self.engine.telemetry["armed"] = False
        self.engine.phase = "COMPLETED"
        wire = plan()
        wire.pop("endpoints")
        deliver(self.engine, request(self.engine, "PLAN_SYNC", "upload-2", plan=wire))
        self.engine.phase = "AVAILABLE"
        self.engine.telemetry["armed"] = True
        self.assign(ident="assign-again")
        self.assertTrue(self.engine.commands["assign-again"]["response"]["accepted"])
        self.assertEqual(self.engine.phase, "BUSY")

    def test_plan_sync_sends_no_fc_commands_and_preserves_home(self):
        sync(self.engine)
        self.assertEqual(self.engine.fc.mav.sent, [])
        self.assertEqual(self.engine.phase, "IDLE")
        self.assertEqual(self.engine.home, healthy(3)["home"])
        self.assertEqual(self.engine.plan["waypoints"][0]["task_id"], "wp-1")

    def test_nonowner_rejects_task_even_with_identical_plan(self):
        sync(self.engine)
        self.engine.phase = "AVAILABLE"
        self.engine.telemetry["armed"] = True
        deliver(self.engine, request(self.engine, "TASK_ASSIGN", "wrong-owner", task_id="wp-1", assignment_version=1,
                                    owner_drone_id=4, target=plan()["waypoints"][0]))
        self.assertIsNone(self.engine.task)
        self.assertEqual(self.engine.fc.mav.sent, [])
        self.assertFalse(self.engine.commands["wrong-owner"]["response"]["accepted"])

    def test_idempotent_task_retransmission_and_new_id_same_task_denied(self):
        sync(self.engine)
        self.engine.phase = "AVAILABLE"
        self.engine.telemetry["armed"] = True
        self.assign()
        self.engine.task["status"] = "REACHED"
        self.engine.phase = "AVAILABLE"
        self.assign()
        self.assertEqual(self.engine.task["status"], "REACHED")
        self.assign(ident="different-command")
        self.assertFalse(self.engine.commands["different-command"]["response"]["accepted"])

    def test_prepare_waits_for_real_arm_ack_and_heartbeat(self):
        sync(self.engine)
        deliver(self.engine, request(self.engine, "PREPARE", "prepare"))
        self.assertEqual(self.engine.phase, "PREPARING")
        self.engine.tick()
        self.assertEqual(self.engine.phase, "ARMING")
        self.engine.tick()
        self.assertFalse(any(args[2] == 22 for name, args in self.engine.fc.mav.sent if name == "command_long_send"))
        self.engine.command_acks[400] = 0
        self.engine.telemetry["armed"] = True
        self.engine.tick()
        self.assertEqual(self.engine.phase, "TAKEOFF")
        self.assertTrue(any(args[2] == 22 for name, args in self.engine.fc.mav.sent if name == "command_long_send"))

    def test_hold_ack_requires_a_stopped_drone_and_deduplicates_inflight(self):
        sync(self.engine)
        self.engine.phase = "AVAILABLE"
        self.engine.telemetry.update(armed=True, vx=2.5)
        body = request(self.engine, "HOLD", "hold")
        deliver(self.engine, body)
        deliver(self.engine, body)
        self.assertNotIn("hold", self.engine.commands)
        self.engine.tick()
        self.assertNotIn("hold", self.engine.commands)  # still decelerating
        self.engine.telemetry["vx"] = 0.0
        self.engine.tick()
        self.assertTrue(self.engine.commands["hold"]["response"]["accepted"])
        self.assertEqual(self.engine.phase, "HELD")

    def test_hold_brakes_at_the_current_position_or_falls_back_to_loiter(self):
        sync(self.engine)
        self.engine.phase = "AVAILABLE"
        self.engine.telemetry["armed"] = True
        self.assign()
        target = self.engine.task["target"]
        self.engine.fc.mav.sent.clear()
        deliver(self.engine, request(self.engine, "HOLD", "hold"))
        setpoints = [args for name, args in self.engine.fc.mav.sent
                     if name == "set_position_target_global_int_send"]
        # GUIDED keeps the previous target until a new one arrives, so HOLD must
        # command the present position rather than let the drone fly on.
        self.assertEqual(len(setpoints), 1)
        self.assertEqual(setpoints[0][5], round(self.engine.telemetry["lat"] * 1e7))
        self.assertNotEqual(setpoints[0][5], round(target["lat"] * 1e7))
        self.assertFalse(any(name == "set_mode_send" and args[-1] == 5
                             for name, args in self.engine.fc.mav.sent))  # stays GUIDED

        stale = controller(self.tmp.name, slot=3)
        stale.commands = {}
        sync(stale)
        stale.phase = "AVAILABLE"
        stale.telemetry["armed"] = True
        stale.received["GLOBAL_POSITION_INT"] = time.monotonic() - 6
        stale.fc.mav.sent.clear()
        deliver(stale, request(stale, "HOLD", "hold-stale"))
        self.assertFalse(any(name == "set_position_target_global_int_send"
                             for name, _ in stale.fc.mav.sent))
        self.assertTrue(any(name == "set_mode_send" and args[-1] == 5
                            for name, args in stale.fc.mav.sent))

    def test_gcs_loss_overrides_navigation_without_disarming(self):
        sync(self.engine)
        self.engine.phase = "AVAILABLE"
        self.engine.telemetry["armed"] = True
        self.assign()
        self.engine.last_gcs = time.monotonic() - 4
        self.engine.tick()
        self.assertEqual(self.engine.phase, "FAULT")
        self.assertEqual(self.engine.task["status"], "HELD")
        self.assertTrue(any(name == "set_mode_send" and args[-1] == 5 for name, args in self.engine.fc.mav.sent))
        self.assertFalse(any(name == "set_position_target_global_int_send" for name, _ in self.engine.fc.mav.sent))
        self.assertFalse(any(name == "command_long_send" and args[2] == 400 for name, args in self.engine.fc.mav.sent))

    def test_unwritable_journal_holds_instead_of_killing_the_flight_loop(self):
        sync(self.engine)
        self.engine.phase = "AVAILABLE"
        self.engine.telemetry["armed"] = True
        denied = PermissionError(5, "Access is denied")
        with unittest.mock.patch("mission_scripts.swarm_companion.atomic_json", side_effect=denied):
            self.engine.persist()  # a Windows scanner may hold the journal briefly
            self.engine.tick()
        self.assertEqual(self.engine.phase, "FAULT")
        self.assertIn("journal write failed", self.engine.error)
        self.assertTrue(any(name == "set_mode_send" and args[-1] == 5
                            for name, args in self.engine.fc.mav.sent))

    def test_atomic_json_survives_a_transient_windows_lock(self):
        target = Path(self.tmp.name) / "journal.json"
        real, calls = os.replace, []

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) < 3:
                raise PermissionError(5, "Access is denied")
            real(src, dst)

        with unittest.mock.patch("mission_scripts.swarm_protocol.os.replace", flaky):
            atomic_json(target, {"phase": "BUSY"})
        self.assertEqual(json.loads(target.read_text()), {"phase": "BUSY"})
        self.assertEqual(len(calls), 3)

    def setpoint_latlon(self, engine=None):
        engine = engine or self.engine
        sent = [a for n, a in engine.fc.mav.sent if n == "set_position_target_global_int_send"]
        return (sent[-1][5] / 1e7, sent[-1][6] / 1e7) if sent else None

    def test_closer_uav_holds_while_the_farther_one_flies_on(self):
        for peer_left, expect_hold in ((1000.0, True), (0.0, False)):
            with self.subTest(peer_left=peer_left):
                engine = controller(self.tmp.name, slot=3)
                engine.plan, engine.phase, engine.commands = None, "IDLE", {}
                sync(engine)
                engine.phase = "AVAILABLE"
                engine.telemetry["armed"] = True
                self.assign(engine)
                engine.peer.update(remaining_m=peer_left, lat=-7.0 + 12 / 111320, lon=110.0)
                engine.fc.mav.sent.clear()
                engine.tick()
                self.assertTrue(engine.apf_status["active"])  # 12 m apart: inside the 15 m enter distance
                self.assertEqual(engine.apf_status["role"], "HOLD" if expect_hold else "MOVE")
                lat, lon = self.setpoint_latlon(engine)
                here = (engine.telemetry["lat"], engine.telemetry["lon"])
                if expect_hold:
                    self.assertAlmostEqual(distance_m(lat, lon, *here), 0, places=1)
                else:
                    self.assertGreater(distance_m(lat, lon, *here), 1.0)

    def test_yield_role_is_latched_for_the_whole_avoidance_episode(self):
        sync(self.engine)
        self.engine.phase = "AVAILABLE"
        self.engine.telemetry["armed"] = True
        self.assign()
        self.engine.peer.update(remaining_m=1000.0, lat=-7.0 + 12 / 111320, lon=110.0)  # inside 15 m
        self.engine.tick()
        self.assertEqual(self.engine.apf_status["role"], "HOLD")
        held = self.engine.yield_target
        # The moving UAV closes in; that must not hand the roles back and forth.
        self.engine.peer["remaining_m"] = 0.0
        self.engine.last_setpoint = 0
        self.engine.tick()
        self.assertEqual(self.engine.apf_status["role"], "HOLD")
        self.assertEqual(self.engine.yield_target, held)
        # Clearing the conflict releases the role.
        self.engine.apf_status["active"] = False
        self.assertFalse(self.engine.yields_to_peer(self.engine.telemetry, self.engine.task["target"]))
        self.assertIsNone(self.engine.yield_role)

    def test_new_assignment_redecides_a_role_latched_at_takeoff(self):
        engine = controller(self.tmp.name, slot=4)
        engine.apf_status = {"active": True}
        here = {"lat": -7.0, "lon": 110.0002, "alt_m": 5.0}
        # Hover before any task: equal distances, so slot 4 holds on the tie.
        engine.peer = {"drone_id": 3, "remaining_m": 0.0, "task_id": None}
        self.assertTrue(engine.yields_to_peer(here, here))
        # It is now assigned 24 m away while still within the 35 m exit distance.
        task = {"lat": -7.0 + 24 / 111320, "lon": 110.0002, "alt_m": 5.0}
        self.assertFalse(engine.yields_to_peer(here, task))
        self.assertEqual(engine.yield_role, "MOVE")
        # The peer taking a longer task decides again as well.
        engine.peer.update(remaining_m=60.0, task_id="wp-far")
        self.assertTrue(engine.yields_to_peer(here, task))

    def test_peer_remaining_distance_reports_only_an_en_route_task(self):
        state = dict(healthy(4), task={"status": "EN_ROUTE", "target": {"lat": -7.0, "lon": 110.0005}})
        self.assertAlmostEqual(remaining_m(state), 33.1, places=0)
        self.assertEqual(remaining_m(dict(state, task={"status": "REACHED", "target": {"lat": -7.1, "lon": 110.0}})), 0.0)
        self.assertEqual(remaining_m(dict(state, task=None)), 0.0)
        self.assertIsNone(remaining_m(dict(state, lat=0, lon=0)))

    def test_reset_udp_peer_does_not_end_the_flight_loop(self):
        handled = []
        link = SimpleNamespace(recv_match=Mock(side_effect=ConnectionResetError(
            10054, "An existing connection was forcibly closed by the remote host")))
        self.engine.drain(link, handled.append)  # Windows ICMP port-unreachable
        self.assertIn("10054", self.engine.link_error)
        self.assertEqual(handled, [])
        link.recv_match = Mock(side_effect=["a", "b", None])
        self.engine.drain(link, handled.append)
        self.assertEqual(handled, ["a", "b"])

    def test_fc_or_peer_stale_stops_guided_setpoints(self):
        for failure in ("fc", "peer"):
            with self.subTest(failure=failure):
                engine = controller(self.tmp.name, slot=3)
                engine.plan = None
                engine.phase = "IDLE"
                engine.commands = {}
                sync(engine)
                engine.phase = "AVAILABLE"
                engine.telemetry["armed"] = True
                self.assign(engine)
                if failure == "fc":
                    engine.received["HEARTBEAT"] = time.monotonic() - 6
                else:
                    engine.peer["position_age_s"] = 5
                engine.tick()
                self.assertEqual(engine.phase, "FAULT")
                self.assertFalse(any(name == "set_position_target_global_int_send" for name, _ in engine.fc.mav.sent))

    def test_reached_requires_dwell_and_altitude_not_just_latlon(self):
        sync(self.engine)
        self.engine.phase = "AVAILABLE"
        self.engine.telemetry["armed"] = True
        self.assign()
        target = self.engine.task["target"]
        self.engine.telemetry.update(lat=target["lat"], lon=target["lon"], alt_m=target["alt_m"] - 3)
        self.engine.tick()
        self.assertEqual(self.engine.task["status"], "EN_ROUTE")
        self.engine.telemetry["alt_m"] = target["alt_m"]
        self.engine.tick()
        self.assertEqual(self.engine.task["status"], "EN_ROUTE")
        self.engine.stable_since = time.monotonic() - 2
        self.engine.tick()
        self.assertEqual(self.engine.task["status"], "REACHED")
        self.assertEqual(self.engine.phase, "AVAILABLE")

    def test_companion_restart_cannot_resume_unknown_task(self):
        sync(self.engine)
        self.engine.phase = "AVAILABLE"
        self.engine.telemetry["armed"] = True
        self.assign()
        restarted = controller(self.tmp.name)
        restarted.telemetry["armed"] = True
        self.assertEqual(restarted.task["status"], "UNKNOWN")
        deliver(restarted, request(restarted, "HOLD", "hold-restart"))
        restarted.telemetry["mode"] = "LOITER"
        restarted.tick()
        self.assertEqual(restarted.task["status"], "UNKNOWN")
        deliver(restarted, request(restarted, "RESUME", "resume-restart"))
        self.assertFalse(restarted.commands["resume-restart"]["response"]["accepted"])

    def test_wrong_system_and_old_boot_packets_ignored(self):
        sync(self.engine)
        body = request(self.engine, "PREPARE", "old")
        body["boot_id"] = "old-boot"
        deliver(self.engine, body)
        self.assertNotIn("old", self.engine.commands)
        self.assertEqual(self.engine.fc.mav.sent, [])

    def test_delayed_prepare_cannot_restart_after_abort(self):
        sync(self.engine)
        late = request(self.engine, "PREPARE", "delayed-prepare")
        deliver(self.engine, request(self.engine, "ABORT", "abort", action="RTL"))
        deliver(self.engine, late)
        self.assertFalse(self.engine.commands["delayed-prepare"]["response"]["accepted"])
        self.assertEqual(self.engine.fc.mav.sent, [])

    def test_safety_abort_works_when_plan_version_is_not_reconciled(self):
        sync(self.engine)
        body = request(self.engine, "ABORT", "abort-unsynced", action="RTL")
        body["version"] = 2
        deliver(self.engine, body)
        self.assertTrue(self.engine.commands["abort-unsynced"]["response"]["accepted"])
        self.assertEqual(self.engine.phase, "COMPLETED")

    def test_swarm_probe_does_not_refresh_legacy_watchdog(self):
        from mission_scripts.companion_bridge import BridgeState, gcs_listener_thread
        state = BridgeState()
        state.last_gcs_heartbeat = 123.0
        class ProbeConnection:
            def recv_match(self, **_kwargs):
                state.stop_event.set()
                return SimpleNamespace(get_type=lambda: "TUNNEL")
        gcs_listener_thread(ProbeConnection(), self.engine.fc, state, {})
        self.assertEqual(state.last_gcs_heartbeat, 123.0)


class UDPProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_real_udp_mavlink_links_plan_acks_and_telemetry_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            engines = []
            endpoints = {}
            for slot in (3, 4):
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
                    reservation.bind(("127.0.0.1", 0))
                    port = reservation.getsockname()[1]
                conn = mavutil.mavlink_connection(f"udpin:127.0.0.1:{port}", source_system=slot, source_component=191)
                conn.mav = common.MAVLink(conn, srcSystem=slot, srcComponent=191)
                engine = controller(tmp, slot, conn)
                engine.session = None
                engines.append(engine)
                endpoints[str(slot)] = {"host": "127.0.0.1", "port": port}
            link = SwarmLink(KEY, timeout=1)
            link.configure(endpoints)
            await link.start()

            async def serve():
                while True:
                    for engine in engines:
                        for _ in range(100):
                            msg = engine.gcs.recv_match(blocking=False)
                            if msg is None:
                                break
                            engine.receive_gcs(msg)
                    await asyncio.sleep(0.005)

            worker = asyncio.create_task(serve())
            try:
                wire = plan()
                wire.pop("endpoints")
                replies = await asyncio.gather(*(link.request(s, "PLAN_SYNC", mission_id="mission-test", version=1, plan=wire) for s in (3, 4)))
                self.assertTrue(all(r["accepted"] and r["plan_hash"] == digest(wire) for r in replies))
                self.assertEqual(engines[0].plan, engines[1].plan)
                self.assertTrue(all(e.fc.mav.sent == [] for e in engines))
                before = link.snapshot(3)["position_age_s"]
                link.received[3] -= 3
                after = link.snapshot(3)
                self.assertGreater(after["position_age_s"], before + 2.9)
                self.assertFalse(after["connected"])
                again = await link.request(3, "PLAN_SYNC", command_id="same-upload", mission_id="mission-test", version=1, plan=wire)
                duplicate = await link.request(3, "PLAN_SYNC", command_id="same-upload", mission_id="mission-test", version=1, plan=wire)
                self.assertEqual(again["plan_hash"], duplicate["plan_hash"])
                # Append over the same two real UDP links while both UAVs are airborne.
                for engine in engines:
                    engine.phase = "AVAILABLE"
                    engine.telemetry["armed"] = True
                extended = dict(wire, version=2, waypoints=wire["waypoints"] + [
                    dict(task_id="wp-3", sequence=3, lat=-7.001, lon=110.001, alt_m=10)])
                replies = await asyncio.gather(*(link.request(s, "PLAN_APPEND", mission_id="mission-test",
                    version=2, base_version=1, base_hash=digest(wire), plan=extended) for s in (3, 4)))
                self.assertTrue(all(r["accepted"] and r["plan_hash"] == digest(extended) for r in replies))
                self.assertTrue(all(e.plan == extended and e.phase == "AVAILABLE" for e in engines))
                self.assertTrue(all(e.fc.mav.sent == [] for e in engines))
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
                await link.close()
                for engine in engines:
                    engine.gcs.close()
