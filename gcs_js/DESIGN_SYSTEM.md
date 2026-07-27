# BIMA Swarm GCS Visual System

## Design read

Reading this as: a preservation-first redesign of a dense UAV ground control station for trained operators, using the supplied motorsport telemetry board as its visual reference and a custom semantic CSS system on top of the existing Next.js and Tailwind foundation.

The anti-slop frontend skill is intentionally applied only for its audit, preservation, token, accessibility, and pre-flight disciplines. Its landing-page composition rules are out of scope for a cockpit-style product UI and are not being forced onto the dashboard or its data tables.

## Reference direction: motorsport telemetry board

The single real-world reference is the supplied motorsport telemetry board. It fits this product for operational reasons:

- Both products expose fast-changing machine telemetry to a trained operator.
- Both require large numeric readouts, compact labels, threshold awareness, and instant comparison.
- The near-black field lets video, maps, charts, and status values carry the visual weight.
- Off-white, gray, and flat red create hierarchy without neon glow or generic dashboard cards.
- Dense information remains readable because type size and weight do more work than color.

The result should feel like a serious performance telemetry instrument adapted to flight operations, not a racing skin pasted onto a GCS. UAV identity and aviation safety meanings remain intact.

## Design dials

- `DESIGN_VARIANCE: 4` - layout asymmetry is allowed only when it reflects the operator workflow.
- `MOTION_INTENSITY: 2` - motion is limited to focus, press, loading, and true state changes.
- `VISUAL_DENSITY: 9` - the cockpit remains compact; prominent metrics use condensed tabular numerals, precision fields use monospace, and panels are separated by rails rather than floating cards.

## Core color tokens

| Token | Hex | Operational meaning |
| --- | --- | --- |
| `scope-void` | `#050505` | Application background and video blackout |
| `scope-surface` | `#0A0A0B` | Instrument, table, and modal surfaces |
| `information` | `#E6E6E2` | Primary data, navigation, focusable tools, and main actions |
| `signal` | `#F02F2C` | Selected telemetry, calibration rails, and active visual emphasis |
| `nominal` | `#86A38D` | Connected, acknowledged, live, and healthy |
| `caution` | `#B99A68` | Pending, stale, missing, or operator attention required |
| `critical` | `#D85750` | Destructive actions, write warnings, and unsafe states |

Text, borders, and disabled states are neutral tonal derivatives. They do not introduce another semantic accent. UAV identity colors remain a separate namespace:

- UAV 01: blue
- UAV 02: yellow
- UAV 03: orange
- UAV 04: pink

Those four colors identify an aircraft only. They are not reused for global success, warning, or danger semantics.

## Typography

- `Barlow Condensed` is the display, control, and prominent-number face. Its narrow industrial proportions match the reference and keep large values readable in dense panels.
- `IBM Plex Mono` is the precision-data face. It is reserved for coordinates, parameter IDs, timestamps, ports, and editable numeric fields where alignment matters.

Both are open-license Google Fonts loaded and self-hosted through `next/font`.

## Layout and spacing

The spacing scale is `4, 8, 12, 16, 24, 32px`. Panels use square 2px corners, 1px rails, and minimal elevation. The global hierarchy is:

```text
+------------------------------------------------------------------+
| identity + route tabs                link / detection / theme     |
+------------------+-------------------------------+---------------+
| fixed-wing stack | central surveillance map     | copter stack  |
| video + telemetry| track data blocks            | dense metrics |
+------------------+-------------------------------+---------------+
```

Mission and parameter pages reuse the same header rail, UAV selector, command bar, section heading, table, empty-state, dialog, and focus treatment.

## Signature element: segmented telemetry rail

The signature element is the `segmented telemetry rail`: a restrained red tick sequence around map and video surfaces, paired with squared data blocks that use the real UAV identity colors. It is derived from the segmented bars, circular scales, and line-chart ticks in the reference. The rail is functional:

- It distinguishes live spatial and optical instruments from command surfaces.
- It gives UAV data blocks a consistent anchor.
- It creates one recognisable BIMA detail without spreading glow, gradients, or red fills across every component.

The no-signal state borrows the same rail and uses a static scan texture. A single short acquisition sweep may run when motion is permitted; it does not loop.

## Pre-build self-critique

### What was initially too generic

The first concept still leaned on a familiar blue-gray ATC dashboard recipe. Although it was more disciplined than the original neon theme, the cool information color and subtle grid did not match the directness of the supplied reference.

### What changed

- The cool palette was replaced with near-black, off-white, neutral gray, and flat red.
- The page-wide decorative grid was removed.
- Red was limited to selected telemetry and the segmented signature rail.
- Primary actions became off-white with dark text instead of bright UAV-color fills.
- UAV colors were restricted to aircraft identity and aircraft-scoped actions.
- Status colors were mapped to nominal, caution, and critical meanings.
- Scan texture was limited to video loss and spatial instruments.
- The signature moved from a generic scope frame to segmented telemetry rails around actual map, video, and progress data.
- Motion was reduced from ambient pulsing to state feedback only.
- Rounded floating cards were replaced with square instrument rails.

This revision combines the reference's typography and color restraint with the real operational needs of a four-aircraft GCS.

## Post-render critique

- The first browser render exposed a real typography fault: the font aliases were defined above the element carrying the `next/font` variables, so the browser fell back to Times New Roman. The font variables now live on the root element and the rendered interface resolves to `Barlow Condensed` and `IBM Plex Mono`.
- At 1440 by 900, the active red state is visible without overpowering the off-white data hierarchy. The muted UAV colors read as identity rails instead of competing global accents.
- Mission and Params retain deliberately quiet empty regions. Those areas are reserved for route, map, and parameter data; they are not filled with decorative cards or fake metrics.
- At 390 by 844, navigation remains reachable, UAV selection becomes a 2 by 2 matrix, command buttons stack, and the connection setup becomes a vertically scrollable single-column instrument.
- Browser measurements confirm no horizontal overflow on Mission, Params, or the connection setup at the tested desktop and mobile widths.

## Preservation boundaries

- Routes, navigation labels, field order, input names, API calls, WebSocket behavior, local state, and mission or parameter logic remain unchanged.
- The four UAV identity associations remain blue, yellow, orange, and pink.
- Existing empty, loading, error, confirmation, and disabled states remain present and are visually normalized.
- The existing responsive layout mechanics and resizable dashboard columns remain intact.
