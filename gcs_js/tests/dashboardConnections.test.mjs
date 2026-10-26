import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import ts from "typescript";

test("dashboard mount, effect replay and return from swarm never request a MAVLink connection", async () => {
  const requests = [];
  const effects = [];
  const timers = new Set();
  const store = {
    config: { ws_host: "localhost:8000" },
    isConfigured: true,
    setConfig() {},
    uavs: {
      3: { tcpIp: "100.95.70.29", mavlinkPort: "14550" },
      4: { tcpIp: "100.95.70.29", mavlinkPort: "14560" },
    },
  };
  // Run the page's own effects with cached settings. Child rendering and browser
  // layout are stubbed; delayed connection effects still run and are observable.
  const react = {
    useState: (initial) => [typeof initial === "function" ? initial() : initial, () => {}],
    useRef: (current) => ({ current }),
    useCallback: (callback) => callback,
    useEffect: (effect) => effects.push(effect),
  };
  const jsx = (type, props) => ({ type, props });
  const imports = {
    react,
    "react/jsx-runtime": { jsx, jsxs: jsx },
    "next/dynamic": { default: () => () => null },
    "@/config/agents": { UAV_IDS: [1, 2, 3, 4] },
    "@/hooks/useGCSStore": { useGCSStore: () => store },
    "@/hooks/useWebSocket": { useWebSocket() {} },
  };
  const source = readFileSync(new URL("../src/app/page.tsx", import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  });
  const context = vm.createContext({
    exports: {},
    require: (name) => {
      if (name in imports) return imports[name];
      if (name.startsWith("@/components/")) return {};
      throw new Error(`Unexpected import: ${name}`);
    },
    process: { env: {} },
    console,
    window: {
      addEventListener() {}, removeEventListener() {},
      setInterval() {}, clearInterval() {},
      setTimeout(callback) { timers.add(callback); return callback; },
      clearTimeout(callback) { timers.delete(callback); },
    },
    document: { body: { style: { removeProperty() {} } } },
    fetch: async (url, options) => {
      requests.push({ url, method: options?.method ?? "GET" });
      return { ok: true, json: async () => store.config };
    },
  });
  vm.runInContext(outputText, context);

  for (let visit = 0; visit < 3; visit++) {
    const dashboard = context.exports.default();
    dashboard.type(dashboard.props);
    const mountedEffects = effects.splice(0);
    // Includes Strict Mode's setup/cleanup/setup cycle.
    for (let replay = 0; replay < 2; replay++) {
      const cleanups = mountedEffects.map((effect) => effect());
      for (const callback of timers) await callback();
      timers.clear();
      await Promise.resolve();
      for (const cleanup of cleanups) cleanup?.();
    }
  }

  assert.ok(requests.some(({ url }) => url.endsWith("/api/config")));
  assert.deepEqual(requests.filter(({ method }) => method !== "GET"), []);
  assert.equal(requests.some(({ url }) => /\/api\/telemetry\/(connect|disconnect)$/.test(url)), false);
});
