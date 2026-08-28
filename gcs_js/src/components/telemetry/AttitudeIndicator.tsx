"use client";

import { memo } from "react";

interface AttitudeIndicatorProps {
  roll: number;
  pitch: number;
  heading: number;
  altitude: number;
  panelId: number;
}

function AttitudeIndicatorInner({ roll, pitch, heading, altitude, panelId }: AttitudeIndicatorProps) {
  return (
    <div className="attitude-indicator">
      {/* Roll container — rotates the entire horizon */}
      <div
        className="attitude-roll"
        id={`attitude-roll-${panelId}`}
        style={{ transform: `translate(-50%, -50%) rotate(${-roll}deg)` }}
      >
        {/* Pitch container — vertical shift */}
        <div
          className="attitude-pitch"
          id={`attitude-pitch-${panelId}`}
          style={{ transform: `translateY(${pitch}px)` }}
        >
          <svg
            width="300"
            height="300"
            viewBox="-150 -150 300 300"
            style={{ position: "absolute", top: 0, left: 0 }}
          >
            {/* Sky — softer blue-gray */}
            <rect x="-150" y="-150" width="300" height="150" fill="#4A5580" />
            {/* Ground — warmer brown */}
            <rect x="-150" y="0" width="300" height="150" fill="#6B4040" />
            {/* Horizon line */}
            <line x1="-150" y1="0" x2="150" y2="0" stroke="rgba(255,255,255,0.8)" strokeWidth="2" />
            {/* Pitch ladder */}
            <line x1="-30" y1="-20" x2="30" y2="-20" stroke="rgba(255,255,255,0.6)" strokeWidth="1.5" />
            <line x1="-15" y1="-10" x2="15" y2="-10" stroke="rgba(255,255,255,0.4)" strokeWidth="1.5" />
            <line x1="-15" y1="10" x2="15" y2="10" stroke="rgba(255,255,255,0.4)" strokeWidth="1.5" />
            <line x1="-30" y1="20" x2="30" y2="20" stroke="rgba(255,255,255,0.6)" strokeWidth="1.5" />
          </svg>
        </div>
      </div>

      {/* Rotating Heading Compass Ring */}
      <div className="attitude-overlay">
        <svg
          width="120"
          height="120"
          viewBox="-60 -60 120 120"
          id={`heading-compass-${panelId}`}
          style={{ transform: `rotate(${-heading}deg)` }}
        >
          <g
            stroke="rgba(255,255,255,0.7)"
            strokeWidth="1.5"
            textAnchor="middle"
            fontSize="9"
            fontFamily="var(--font-display)"
            fill="rgba(255,255,255,0.8)"
            fontWeight="500"
          >
            <line x1="0" y1="-55" x2="0" y2="-60" strokeWidth="2.5" />
            <text x="0" y="-44" stroke="none">N</text>
            <line x1="0" y1="-55" x2="0" y2="-60" transform="rotate(30)" />
            <line x1="0" y1="-55" x2="0" y2="-60" transform="rotate(60)" />
            <line x1="0" y1="-55" x2="0" y2="-60" strokeWidth="2.5" transform="rotate(90)" />
            <text x="0" y="-44" stroke="none" transform="rotate(90)">E</text>
            <line x1="0" y1="-55" x2="0" y2="-60" transform="rotate(120)" />
            <line x1="0" y1="-55" x2="0" y2="-60" transform="rotate(150)" />
            <line x1="0" y1="-55" x2="0" y2="-60" strokeWidth="2.5" transform="rotate(180)" />
            <text x="0" y="-44" stroke="none" transform="rotate(180)">S</text>
            <line x1="0" y1="-55" x2="0" y2="-60" transform="rotate(210)" />
            <line x1="0" y1="-55" x2="0" y2="-60" transform="rotate(240)" />
            <line x1="0" y1="-55" x2="0" y2="-60" strokeWidth="2.5" transform="rotate(270)" />
            <text x="0" y="-44" stroke="none" transform="rotate(270)">W</text>
            <line x1="0" y1="-55" x2="0" y2="-60" transform="rotate(300)" />
            <line x1="0" y1="-55" x2="0" y2="-60" transform="rotate(330)" />
          </g>
        </svg>
      </div>

      {/* Fixed aircraft wings overlay */}
      <div className="attitude-overlay">
        <svg width="120" height="120" viewBox="-60 -60 120 120">
          <circle cx="0" cy="0" r="3" fill="#FBBF24" />
          <path d="M -40 0 L -10 0 L -10 5" fill="none" stroke="#FBBF24" strokeWidth="2.5" strokeLinejoin="round" />
          <path d="M 40 0 L 10 0 L 10 5" fill="none" stroke="#FBBF24" strokeWidth="2.5" strokeLinejoin="round" />
          <polygon points="-5,-45 5,-45 0,-55" fill="#FBBF24" stroke="#FBBF24" strokeWidth="1" />
        </svg>
      </div>

      {/* Altitude tape container INSIDE attitude-indicator matching index.html */}
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

      {/* Heading text */}
      <div className="hud-heading" id={`hud-head-${panelId}`}>
        {String(Math.round(heading)).padStart(3, "0")}&deg;
      </div>
    </div>
  );
}

export const AttitudeIndicator = memo(AttitudeIndicatorInner);
