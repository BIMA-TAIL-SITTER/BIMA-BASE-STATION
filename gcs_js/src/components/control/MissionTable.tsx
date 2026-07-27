/** Editable MAVLink mission table used by the unified mission workspace. */

"use client";

import {
  COMMAND_NAME_BY_ID,
  FRAME_NAME_BY_ID,
  MISSION_COMMANDS,
  MISSION_FRAMES,
} from "@/config/mission";
import type { MissionItem } from "@/types/control";

type MissionItemUpdate = Partial<Omit<MissionItem, "seq">>;
type NumericMissionField =
  | "lat"
  | "lon"
  | "alt"
  | "param1"
  | "param2"
  | "param3"
  | "param4";

interface MissionTableProps {
  items: MissionItem[];
  label: string;
  editable?: boolean;
  onMove?: (index: number, direction: -1 | 1) => void;
  onRemove?: (index: number) => void;
  onUpdate?: (index: number, update: MissionItemUpdate) => void;
}

function formatNumber(value: number, decimals = 3): string {
  return Number.isFinite(value) ? value.toFixed(decimals) : "--";
}

export function MissionTable({
  items,
  label,
  editable = false,
  onMove,
  onRemove,
  onUpdate,
}: MissionTableProps) {
  if (!items.length) {
    return (
      <div className="operations-empty-state">
        <strong>NO MISSION ITEMS</strong>
        <span>Fetch a mission or click the map to add a waypoint.</span>
      </div>
    );
  }

  const commitNumber = (
    index: number,
    field: NumericMissionField,
    rawValue: string,
    fallback: number,
    input: HTMLInputElement,
  ) => {
    const value = Number(rawValue);
    const outsideCoordinateRange = (
      field === "lat" && (value < -90 || value > 90)
    ) || (
      field === "lon" && (value < -180 || value > 180)
    );
    if (!Number.isFinite(value) || outsideCoordinateRange) {
      input.value = String(fallback);
      return;
    }
    onUpdate?.(index, { [field]: value });
  };

  return (
    <div className="operations-table-scroll">
      <table
        className={`operations-table mission-table ${
          editable ? "is-editable" : ""
        }`}
        aria-label={label}
      >
        <thead>
          <tr>
            <th>SEQ</th>
            <th>COMMAND</th>
            <th>FRAME</th>
            <th>LAT</th>
            <th>LON</th>
            <th>ALT</th>
            <th>P1</th>
            <th>P2</th>
            <th>P3</th>
            <th>P4</th>
            <th>CURRENT</th>
            <th>AUTO</th>
            {editable && <th>ACTIONS</th>}
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => (
            <tr key={`${item.seq}-${index}`}>
              <td>{item.seq}</td>
              <td className="operations-table-primary">
                {editable ? (
                  <select
                    value={item.command}
                    onChange={(event) => onUpdate?.(index, {
                      command: Number(event.target.value),
                      command_name: null,
                    })}
                    aria-label={`Waypoint ${item.seq} command`}
                  >
                    {!MISSION_COMMANDS.some(
                      (command) => command.id === item.command,
                    ) && (
                      <option value={item.command}>
                        MAV_CMD_{item.command}
                      </option>
                    )}
                    {MISSION_COMMANDS.map((command) => (
                      <option key={command.id} value={command.id}>
                        {command.name} ({command.id})
                      </option>
                    ))}
                  </select>
                ) : (
                  <>
                    {item.command_name
                      || COMMAND_NAME_BY_ID[item.command]
                      || `MAV_CMD_${item.command}`}
                    <small>{item.command}</small>
                  </>
                )}
              </td>
              <td>
                {editable ? (
                  <select
                    value={item.frame}
                    onChange={(event) => onUpdate?.(index, {
                      frame: Number(event.target.value),
                      frame_name: null,
                    })}
                    aria-label={`Waypoint ${item.seq} frame`}
                  >
                    {!MISSION_FRAMES.some(
                      (frame) => frame.id === item.frame,
                    ) && (
                      <option value={item.frame}>
                        MAV_FRAME_{item.frame}
                      </option>
                    )}
                    {MISSION_FRAMES.map((frame) => (
                      <option key={frame.id} value={frame.id}>
                        {frame.name} ({frame.id})
                      </option>
                    ))}
                  </select>
                ) : (
                  item.frame_name
                  || FRAME_NAME_BY_ID[item.frame]
                  || `MAV_FRAME_${item.frame}`
                )}
              </td>
              {(
                [
                  ["lat", item.lat, "0.0000001", 7],
                  ["lon", item.lon, "0.0000001", 7],
                  ["alt", item.alt, "0.1", 1],
                  ["param1", item.param1, "any", 3],
                  ["param2", item.param2, "any", 3],
                  ["param3", item.param3, "any", 3],
                  ["param4", item.param4, "any", 3],
                ] as const
              ).map(([field, value, step, decimals]) => (
                <td key={field}>
                  {editable ? (
                    <input
                      key={`${item.seq}-${field}-${value}`}
                      type="number"
                      step={step}
                      min={field === "lat" ? -90 : field === "lon" ? -180 : undefined}
                      max={field === "lat" ? 90 : field === "lon" ? 180 : undefined}
                      defaultValue={value}
                      onBlur={(event) => commitNumber(
                        index,
                        field,
                        event.currentTarget.value,
                        value,
                        event.currentTarget,
                      )}
                      aria-label={`Waypoint ${item.seq} ${field}`}
                    />
                  ) : (
                    formatNumber(value, decimals)
                  )}
                </td>
              ))}
              <td>
                {editable ? (
                  <input
                    type="checkbox"
                    checked={item.current}
                    onChange={(event) => onUpdate?.(index, {
                      current: event.target.checked,
                    })}
                    aria-label={`Waypoint ${item.seq} current item`}
                  />
                ) : (
                  <span
                    className={`operations-state ${
                      item.current ? "is-ok" : ""
                    }`}
                  >
                    {item.current ? "YES" : "NO"}
                  </span>
                )}
              </td>
              <td>
                {editable ? (
                  <input
                    type="checkbox"
                    checked={item.autocontinue}
                    onChange={(event) => onUpdate?.(index, {
                      autocontinue: event.target.checked,
                    })}
                    aria-label={`Waypoint ${item.seq} autocontinue`}
                  />
                ) : (
                  item.autocontinue ? "YES" : "NO"
                )}
              </td>
              {editable && (
                <td>
                  <div className="mission-row-actions">
                    <button
                      type="button"
                      onClick={() => onMove?.(index, -1)}
                      disabled={index === 0}
                      aria-label={`Move waypoint ${item.seq} up`}
                    >
                      UP
                    </button>
                    <button
                      type="button"
                      onClick={() => onMove?.(index, 1)}
                      disabled={index === items.length - 1}
                      aria-label={`Move waypoint ${item.seq} down`}
                    >
                      DOWN
                    </button>
                    <button
                      type="button"
                      className="is-danger"
                      onClick={() => onRemove?.(index)}
                      aria-label={`Remove waypoint ${item.seq}`}
                    >
                      REMOVE
                    </button>
                  </div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
