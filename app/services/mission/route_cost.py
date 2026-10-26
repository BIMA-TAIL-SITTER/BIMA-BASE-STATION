"""Time cost model, in seconds, for multi-quadcopter waypoint routing.

A leg i -> j costs  d(i, j) / v_ground + t_accel + t_dwell(j), where d is the 3-D
Euclidean distance and v_ground follows from the wind triangle, so with wind the
matrix is asymmetric. The yaw penalty dtheta / omega_yaw depends on the leg into and
the leg out of a waypoint, so it is kept as a separate turn term over triplets.

Each agent gets its own (n + 1) x (n + 1) matrix whose last node is that agent's
start (and home when returning), so agents may differ in speed or yaw rate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np


def angle_diff_deg(a, b):
    """Absolute heading change from a to b in [0, 180]; an undefined heading (nan) is no turn."""
    diff = np.abs((np.asarray(b, dtype=float) - np.asarray(a, dtype=float) + 180.0) % 360.0 - 180.0)
    return np.nan_to_num(diff, nan=0.0)


def wind_vector(speed_mps: float, from_deg: float) -> np.ndarray:
    """East/north components of a wind blowing from `from_deg` (meteorological convention)."""
    rad = math.radians(from_deg)
    return np.array([-speed_mps * math.sin(rad), -speed_mps * math.cos(rad)])


def travel_time_matrix(points: np.ndarray, v_cruise: float, wind_en: np.ndarray) -> np.ndarray:
    """(N, N) flight time between ENU points (N, 3) flown along the track at airspeed v_cruise."""
    delta = points[None, :, :] - points[:, None, :]  # delta[i, j] = p_j - p_i
    dist = np.linalg.norm(delta, axis=2)
    with np.errstate(invalid="ignore", divide="ignore"):
        unit = delta / dist[..., None]
    # Ground speed g along the track solves |g * u - w| = v_cruise.
    along = np.nan_to_num(unit[..., 0] * wind_en[0] + unit[..., 1] * wind_en[1])
    ground = along + np.sqrt(v_cruise ** 2 - wind_en @ wind_en + along ** 2)
    return dist / ground


def bearing_matrix(points: np.ndarray, eps_m: float = 1e-6) -> np.ndarray:
    """(N, N) compass bearing of each leg in degrees; nan where the leg has no horizontal extent."""
    delta = points[None, :, :2] - points[:, None, :2]
    bearing = np.degrees(np.arctan2(delta[..., 0], delta[..., 1])) % 360.0
    bearing[np.hypot(delta[..., 0], delta[..., 1]) < eps_m] = np.nan
    return bearing


@dataclass
class AgentCost:
    """Costs for one agent over n waypoints; node index n is the agent's start/home."""
    leg: np.ndarray                # (n+1, n+1) s: flight + t_accel + dwell at the destination
    bearing: np.ndarray            # (n+1, n+1) track bearing in degrees, nan for vertical legs
    yaw_rate_dps: Optional[float]  # None leaves yaw out of the model
    initial_heading_deg: Optional[float] = None
    return_to_start: bool = False

    @property
    def n(self) -> int:
        return self.leg.shape[0] - 1

    @property
    def models_yaw(self) -> bool:
        return self.yaw_rate_dps is not None

    def turn(self, i, j, k):
        """Yaw time at waypoint j between legs i -> j and j -> k; broadcasts over index arrays."""
        if not self.models_yaw:
            return np.zeros(np.broadcast(np.asarray(i), np.asarray(j), np.asarray(k)).shape)
        return angle_diff_deg(self.bearing[i, j], self.bearing[j, k]) / self.yaw_rate_dps

    def turn_tensor(self) -> np.ndarray:
        """(n+1, n, n+1) yaw times indexed [prev, at, next]; index n is the start/home."""
        n = self.n
        return self.turn(np.arange(n + 1)[:, None, None], np.arange(n)[None, :, None],
                         np.arange(n + 1)[None, None, :])

    def start_cost(self) -> np.ndarray:
        """(n,) cost of the first leg to each waypoint, including the yaw off the initial heading."""
        n = self.n
        cost = self.leg[n, :n].copy()
        if self.models_yaw and self.initial_heading_deg is not None:
            cost += angle_diff_deg(self.initial_heading_deg, self.bearing[n, :n]) / self.yaw_rate_dps
        return cost

    def end_cost(self) -> np.ndarray:
        """(n+1, n) cost after the last waypoint, indexed [prev, last]; zero for an open path."""
        n = self.n
        if not self.return_to_start:
            return np.zeros((n + 1, n))
        last = np.arange(n)
        return self.leg[last, n][None, :] + self.turn(np.arange(n + 1)[:, None], last[None, :], n)

    def route_duration(self, route: Sequence[int]) -> float:
        """Exact duration of flying `route` (waypoint indices) from this agent's start."""
        if not len(route):
            return 0.0
        n = self.n
        nodes = [n, *route]
        total = float(self.start_cost()[route[0]])
        total += sum(float(self.leg[a, b]) for a, b in zip(route, route[1:]))
        total += sum(float(self.turn(p, j, k)) for p, j, k in zip(nodes, route, route[1:]))
        if self.return_to_start:
            total += float(self.end_cost()[nodes[-2], route[-1]])
        return total


def build_agent_cost(waypoints: np.ndarray, start: np.ndarray, *, v_cruise_mps: float,
                     t_accel_s: float, dwell_s: np.ndarray, yaw_rate_dps: Optional[float],
                     wind_en: np.ndarray, initial_heading_deg: Optional[float] = None,
                     return_to_start: bool = False) -> AgentCost:
    """Cost model of one agent; `waypoints` (n, 3) and `start` (3,) are local ENU metres."""
    points = np.vstack((waypoints.reshape(-1, 3), start.reshape(1, 3)))
    arrive = np.append(dwell_s, 0.0)  # no dwell when arriving home
    leg = travel_time_matrix(points, v_cruise_mps, wind_en) + t_accel_s + arrive[None, :]
    np.fill_diagonal(leg, np.inf)
    return AgentCost(leg=leg, bearing=bearing_matrix(points), yaw_rate_dps=yaw_rate_dps,
                     initial_heading_deg=initial_heading_deg, return_to_start=return_to_start)
