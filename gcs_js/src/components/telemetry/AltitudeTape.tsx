"use client";

import { memo } from "react";

interface AltitudeTapeProps {
  altitude: number;
  panelId: 1 | 2;
}

function AltitudeTapeInner({ altitude, panelId }: AltitudeTapeProps) {
  return (
    <div className="alt-tape-container">
      <div
        className="alt-tape-ticks"
        id={`alt-tape-ticks-${panelId}`}
        style={{ backgroundPositionY: `calc(50% + ${altitude * 4}px)` }}
      />
      <div className="alt-tape-pointer" id={`alt-tape-val-${panelId}`}>
        {Math.round(altitude)}
      </div>
    </div>
  );
}

export const AltitudeTape = memo(AltitudeTapeInner);
