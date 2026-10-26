import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import ts from "typescript";

function mount(file, mission) {
  const states = [];
  let cursor = 0;
  let events;
  const jsx = (type, props) => ({ type, props });
  class Element { closest() { return null; } }
  const react = {
    useState(initial) {
      const i = cursor++;
      if (!(i in states)) states[i] = initial;
      return [states[i], value => { states[i] = value; }];
    },
    useRef: () => ({ current: null }), useEffect() {},
  };
  const modules = {
    react,
    "react/jsx-runtime": { jsx, jsxs: jsx },
    "next/link": { default: "a" },
    leaflet: { default: { divIcon: value => value } },
    "react-leaflet": { Marker: "Marker", Polyline: "Polyline", Popup: "Popup", Tooltip: "Tooltip",
      useMapEvents(value) { events = value; return { closePopup() {} }; } },
    "@/config/agents": { UAV_AGENT_BY_ID: { 3: { color: "blue" }, 4: { color: "red" } } },
    "./SwarmMissionContext": { useSwarmMission: () => mission },
    "@/components/swarm/SwarmMissionContext": { useSwarmMission: () => mission },
  };
  const output = ts.transpileModule(readFileSync(new URL(file, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const context = vm.createContext({ exports: {}, require: name => {
    assert.ok(name in modules, `Unexpected import ${name}`);
    return modules[name];
  }, Element, Date });
  vm.runInContext(output, context);
  return { render() { cursor = 0; return Object.values(context.exports)[0](); },
    contextmenu(lat, lng, blocked = false) { events.contextmenu({ latlng: { lat, lng }, containerPoint: { x: 5, y: 10 },
      originalEvent: { target: Object.assign(new Element(), { closest: () => blocked ? {} : null }) } }); } };
}

function nodes(tree, type) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(child => nodes(child, type));
  return [...(tree.type === type ? [tree] : []), ...nodes(tree.props?.children, type)];
}
const label = node => Array.isArray(node.props.children) ? node.props.children.join("") : node.props.children;
const button = (tree, text) => nodes(tree, "button").find(node => label(node) === text);
const waypoint = { task_id: "wp-1", sequence: 1, lat: -7, lon: 110, alt_m: 10 };
function model() {
  return { state: { phase: "UPLOADED", plan: { mission_id: "swarm-test", version: 1 },
    ready_to_start: true, busy: false, tasks: [{ ...waypoint, status: "PENDING" }], drones: [],
    commands: {}, upload: {}, events: [], blockers: [], safety: { min_alt_m: 2, max_alt_m: 50 }, end_action: "RTL" },
    draft: [waypoint], selected: null, dirty: false, busy: false, locked: false, canAdd: true, connected: true,
    altitude: 10, token: "test-operator", error: "", geoDraft: { lat: "", lon: "", radius: "" }, geoPicking: false,
    select() {}, edit() {}, add() {}, setToken() {}, setAltitude() {}, reload() {}, operate() {},
    updateGeofence() {}, setGeoDraft() {}, setGeoPicking() {} };
}

test("right-click uses Leaflet geographic coordinates and only creates a draft on submit", () => {
  const mission = model();
  const added = [];
  mission.add = (...args) => { added.push(args); return true; };
  const app = mount("../src/components/map/SwarmWaypointLayer.tsx", mission);
  app.render();
  app.contextmenu(-7.7710171, 110.3731779);
  const tree = app.render();
  assert.equal(added.length, 0);
  nodes(tree, "form")[0].props.onSubmit({ preventDefault() {} });
  assert.deepEqual(added, [[-7.7710171, 110.3731779, 10]]);
  assert.equal(button(tree, "Add Waypoint Here").props.disabled, false);
});

test("map controls are excluded and active missions disable marker dragging", () => {
  const mission = model();
  mission.locked = true;
  mission.canAdd = false;
  const app = mount("../src/components/map/SwarmWaypointLayer.tsx", mission);
  app.render();
  app.contextmenu(-7, 110, true);
  let tree = app.render();
  assert.equal(nodes(tree, "Popup").length, 0);
  assert.equal(nodes(tree, "Marker")[0].props.draggable, false);
  app.contextmenu(-7, 110);
  tree = app.render();
  assert.equal(button(tree, "Tambah ke misi aktif").props.disabled, true);
});

test("map draws only a fresh owner's active task line", () => {
  const mission = model();
  mission.state.tasks = [{ ...waypoint, status: "EN_ROUTE", owner_drone_id: 4 }];
  mission.state.drones = [{ drone_id: 3, connected: true, lat: -7, lon: 110, position_age_s: 0.1 },
    { drone_id: 4, connected: true, lat: -7.001, lon: 110.001, position_age_s: 0.1 }];
  const app = mount("../src/components/map/SwarmWaypointLayer.tsx", mission);
  assert.equal(nodes(app.render(), "Polyline").length, 1);
  mission.state.drones[1].position_age_s = 5;
  assert.equal(nodes(app.render(), "Polyline").length, 0);
  mission.state.drones[1].position_age_s = 0.1;
  mission.dirty = true;
  assert.equal(nodes(app.render(), "Polyline").length, 0);
});

test("upload never invokes start; START is explicitly confirmed and gated by live server state", () => {
  const mission = model();
  const calls = [];
  mission.operate = action => calls.push(action);
  const app = mount("../src/components/swarm/SwarmMissionPanel.tsx", mission);
  let tree = app.render();
  button(tree, "Upload").props.onClick();
  assert.deepEqual(calls, ["upload"]);
  button(tree, "Mulai").props.onClick();
  assert.deepEqual(calls, ["upload"]);
  tree = app.render();
  button(tree, "Konfirmasi Mulai").props.onClick();
  assert.deepEqual(calls, ["upload", "start"]);
  for (const field of ["dirty", "busy"]) {
    mission[field] = true;
    assert.equal(button(app.render(), "Mulai").props.disabled, true);
    mission[field] = false;
  }
  mission.connected = false;
  assert.equal(button(app.render(), "Mulai").props.disabled, true);
  mission.connected = true;
  mission.state.ready_to_start = false;
  assert.equal(button(app.render(), "Mulai").props.disabled, true);
});

test("active missions can append from the map while existing markers stay locked", async () => {
  const mission = model();
  mission.locked = true;
  mission.canAdd = true;
  mission.state.phase = "ACTIVE";
  const calls = [];
  mission.add = async (...args) => { calls.push(args); return true; };
  const app = mount("../src/components/map/SwarmWaypointLayer.tsx", mission);
  app.render();
  app.contextmenu(-7.001, 110.001);
  const tree = app.render();
  assert.equal(button(tree, "Tambah ke misi aktif").props.disabled, false);
  assert.equal(nodes(tree, "Marker")[0].props.draggable, false);
  await nodes(tree, "form")[0].props.onSubmit({ preventDefault() {} });
  assert.deepEqual(calls, [[-7.001, 110.001, 10]]);
  assert.equal(nodes(app.render(), "Popup").length, 0);
});

test("failed live additions stay in the popup and cannot submit when blocked", async () => {
  const mission = model();
  mission.locked = true;
  let calls = 0;
  mission.add = async () => { calls++; return false; };
  const app = mount("../src/components/map/SwarmWaypointLayer.tsx", mission);
  app.render(); app.contextmenu(-7, 110);
  await nodes(app.render(), "form")[0].props.onSubmit({ preventDefault() {} });
  assert.equal(nodes(app.render(), "Popup").length, 1);
  mission.canAdd = false;
  await nodes(app.render(), "form")[0].props.onSubmit({ preventDefault() {} });
  assert.equal(calls, 1);
});

test("pending append exposes retry and blocks resume without allowing old waypoint edits", () => {
  const mission = model();
  mission.locked = true;
  mission.canAdd = false;
  mission.state.phase = "HELD";
  mission.state.append_pending = { base_version: 1, waypoints: [waypoint] };
  const app = mount("../src/components/swarm/SwarmMissionPanel.tsx", mission);
  const tree = app.render();
  assert.equal(button(tree, "Lanjut").props.disabled, true);
  assert.equal(button(tree, "Ulangi sinkronisasi WP").props.disabled, false);
  assert.equal(button(tree, "Hapus").props.disabled, true);
  assert.ok(nodes(tree, "input").filter(n => n.props['aria-label']?.startsWith('WP-')).every(n=>n.props.disabled));
});
