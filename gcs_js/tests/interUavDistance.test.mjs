import assert from "node:assert/strict";
import { test } from "node:test";
import { getInterUavDistance } from "../src/utils/interUavDistance.ts";

const position = { slot: 3, lat: 0, lon: 0, altitude_m: 100, relative_alt_m: 30, gps_fix: 3 };
const distance = (first, second, firstStatus = "ARMED", secondStatus = "ARMED") =>
  getInterUavDistance(first, second, firstStatus, secondStatus);

test("uses current GPS without any APF result or mission phase", () => {
  assert.ok(Math.abs(distance(position, { ...position, lat: 0.001 }) - 111.1949266) < 0.001);
  assert.equal(distance(position, position, "DISARMED", "DISARMED"), 0);
});

test("combines horizontal distance and altitude in the same MSL reference", () => {
  const threeMetersLatitude = 3 / 6371000 * 180 / Math.PI;
  assert.ok(Math.abs(distance(position, { ...position, lat: threeMetersLatitude, altitude_m: 104 }) - 5) < 0.0001);
  assert.equal(distance(position, { ...position, altitude_m: 112 }), 12);
  assert.equal(distance(position, { ...position, relative_alt_m: 80 }), 0);
});

test("does not reuse a last-known position after either link disconnects", () => {
  assert.equal(distance(position, position, "DISCONNECTED"), null);
  assert.equal(distance(position, position, "ARMED", "DISCONNECTED"), null);
});

test("waits for both valid positions instead of treating missing values as zero", () => {
  assert.equal(distance(null, position), null);
  assert.equal(distance(position, null), null);
  for (const invalid of [
    { lat: undefined }, { lon: null }, { altitude_m: undefined },
    { lat: NaN }, { lon: Infinity }, { altitude_m: NaN },
    { lat: 91 }, { lon: -181 }, { gps_fix: 2 }, { gps_fix: NaN },
  ]) {
    assert.equal(distance({ ...position, ...invalid }, position), null);
    assert.equal(distance(position, { ...position, ...invalid }), null);
  }
});

test("handles the date line and opposite points without producing NaN", () => {
  assert.ok(distance({ ...position, lon: 179.999 }, { ...position, lon: -179.999 }) < 223);
  assert.ok(Math.abs(distance(position, { ...position, lon: 180 }) - Math.PI * 6371000) < 0.001);
});
