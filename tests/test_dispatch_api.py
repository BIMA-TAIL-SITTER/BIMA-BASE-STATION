"""Operator auth, conflict responses, legacy isolation and snapshot recovery."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.routers import waypoint_dispatch, swarm, control
from app.services.mission.waypoint_scheduler import WaypointScheduler
from test_waypoint_dispatch import KEY, StubLink, plan


class DispatchAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        settings = Settings(_env_file=None, SWARM_CENTER_LAT=-7, SWARM_CENTER_LON=110,
                            SWARM_RADIUS_M=500, SWARM_LINK_KEY=KEY, SWARM_OPERATOR_TOKEN="test-token",
                            SWARM_STORE_PATH=str(Path(self.tmp.name) / "api.sqlite3"))
        self.scheduler = WaypointScheduler(StubLink(), settings)
        self.patches = [patch.object(waypoint_dispatch, "scheduler_instance", self.scheduler),
                        patch.object(waypoint_dispatch, "settings", settings),
                        patch.object(swarm, "dispatcher_instance", self.scheduler),
                        patch.object(control, "dispatcher_instance", self.scheduler)]
        for item in self.patches:
            item.start()
        app = FastAPI()
        app.include_router(waypoint_dispatch.router)
        app.include_router(swarm.router)
        app.include_router(control.api_router)
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer test-token"}

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.scheduler.store.close()
        self.tmp.cleanup()

    def test_authorization_and_version_conflicts(self):
        self.assertEqual(self.client.post("/api/swarm/missions", json=plan()).status_code, 401)
        self.assertEqual(self.client.post("/api/swarm/missions", json=plan(), headers=self.headers).status_code, 200)
        changed = plan()
        changed["waypoints"][0]["alt_m"] = 20
        self.assertEqual(self.client.post("/api/swarm/missions", json=changed, headers=self.headers).status_code, 409)
        response = self.client.post("/api/swarm/missions/mission-test/start", json={"version": 1, "confirmation": "CONFIRM_START"}, headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.scheduler.link.sent)

    def test_legacy_and_direct_mission_commands_cannot_take_over(self):
        self.client.post("/api/swarm/missions", json=plan(), headers=self.headers)
        self.scheduler.state["phase"] = "ACTIVE"
        self.assertEqual(self.client.post("/api/swarm/reset").status_code, 409)
        response = self.client.post("/api/control/companion/start", json={"ip": "127.0.0.1", "port": 14560})
        self.assertEqual(response.status_code, 409)
        response = self.client.post("/api/control/3/arm", json={"force": False})
        self.assertEqual(response.status_code, 409)

    def test_ws_reconnect_gets_authoritative_snapshot(self):
        self.client.post("/api/swarm/missions", json=plan(), headers=self.headers)
        for _ in range(2):
            with self.client.websocket_connect("/ws/swarm") as websocket:
                value = websocket.receive_json()
                self.assertEqual(value["plan"]["mission_id"], "mission-test")
                self.assertEqual(value["phase"], "DRAFT")
                self.assertFalse(value["ready_to_start"])

    def test_live_append_is_authenticated_confirmed_and_versioned(self):
        self.client.post("/api/swarm/missions", json=plan(), headers=self.headers)
        self.client.post("/api/swarm/missions/mission-test/upload", json={"version": 1}, headers=self.headers)
        self.scheduler.state["phase"] = "ACTIVE"
        for drone in self.scheduler.link.states.values():
            drone.update(phase="AVAILABLE", armed=True)
        url = "/api/swarm/missions/mission-test/append"
        body = {"version": 1, "confirmation": "CONFIRM_APPEND", "waypoints": [
            {"task_id": "wp-3", "sequence": 3, "lat": -7.001, "lon": 110.001, "alt_m": 10}]}
        self.assertEqual(self.client.post(url, json=body).status_code, 401)
        self.assertEqual(self.client.post(url, json=dict(body, confirmation=""), headers=self.headers).status_code, 422)
        result = self.client.post(url, json=body, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["plan"]["version"], 2)
        self.assertEqual(len(result.json()["tasks"]), 3)
        self.assertEqual(self.client.post(url, json=body, headers=self.headers).status_code, 200)
        self.assertEqual(len(self.scheduler.state["tasks"]), 3)
