"""
Tests for the min-max multi-quadcopter route planner.
Run with: python -m pytest tests/test_route_planner.py -v
"""

import itertools
import math

import numpy as np
import pytest

from app.services.mission.route_cost import angle_diff_deg
from app.services.mission.route_planner import (
    CLUSTER, CPSAT, EXACT, ROUTING, PlannerParams, _to_local, build_costs, select_method, solve,
)


def local(**overrides):
    return PlannerParams(coordinate_frame="local", **overrides)


def costs_for(coords, starts, params):
    waypoints, start_points = _to_local(coords, starts, params.coordinate_frame)
    return build_costs(waypoints, start_points, params)


def brute_force_makespan(coords, starts, params):
    """Min-max optimum by trying every assignment and every visiting order."""
    costs = costs_for(coords, starts, params)
    n = len(coords)
    offsets = np.broadcast_to(np.asarray(params.start_offset_s, dtype=float), (len(starts),))
    best_route = {}

    def subset_time(agent, subset):
        key = (agent, subset)
        if key not in best_route:
            best_route[key] = min((costs[agent].route_duration(p) for p in itertools.permutations(subset)), default=0.0)
        return best_route[key]

    best = math.inf
    for owner in itertools.product(range(len(starts)), repeat=n):
        span = max(offsets[a] + subset_time(a, tuple(w for w in range(n) if owner[w] == a)) for a in range(len(starts)))
        best = min(best, span)
    return best


def random_instance(seed, n, m=2):
    rng = np.random.default_rng(seed)
    coords = np.column_stack((rng.uniform(-150, 150, (n, 2)), rng.uniform(20, 40, n)))
    starts = np.column_stack((rng.uniform(-150, 150, (m, 2)), np.zeros(m)))
    return coords.tolist(), starts.tolist()


# ─── Cost model ──────────────────────────────────────────────────────

class TestCostModel:
    def test_wind_makes_matrix_asymmetric(self):
        coords, starts = [(0, 0), (100, 0)], [(0, -50)]
        calm = costs_for(coords, starts, local())[0].leg
        windy = costs_for(coords, starts, local(wind_speed_mps=3, wind_from_deg=270))[0].leg
        assert calm[0, 1] == pytest.approx(calm[1, 0])
        assert windy[0, 1] < windy[1, 0]  # wind from the west pushes eastbound legs

    def test_leg_is_seconds_with_accel_and_dwell(self):
        cost = costs_for([(0, 0), (50, 0)], [(0, -10)], local(t_accel_s=2, dwell_s=[1, 4]))[0]
        assert cost.leg[0, 1] == pytest.approx(50 / 5.0 + 2 + 4)

    def test_vertical_component_counts(self):
        cost = costs_for([(0, 0, 30)], [(0, 0, 0)], local(t_accel_s=0, dwell_s=0))[0]
        assert cost.start_cost()[0] == pytest.approx(30 / 5.0)

    def test_yaw_penalty_from_turn_angle(self):
        cost = costs_for([(0, 0), (0, 100), (0, 0.5)], [(0, -100)], local(yaw_rate_dps=30))[0]
        assert cost.turn(3, 0, 1) == pytest.approx(0.0)        # straight on
        assert cost.turn(0, 1, 2) == pytest.approx(180 / 30)   # U-turn
        assert angle_diff_deg(350, 10) == pytest.approx(20)

    def test_no_yaw_model_when_rate_is_none(self):
        cost = costs_for([(0, 0), (0, 100), (0, 0.5)], [(0, -100)], local(yaw_rate_dps=None))[0]
        assert cost.turn(0, 1, 2) == 0


# ─── Exact branch ────────────────────────────────────────────────────

class TestHeldKarp:
    @pytest.mark.parametrize("overrides", [
        {},
        {"yaw_rate_dps": None},
        {"wind_speed_mps": 4, "wind_from_deg": 200},
        {"return_to_start": True, "initial_heading_deg": [90, 270]},
        {"v_cruise_mps": [4, 7], "yaw_rate_dps": [20, 90], "dwell_s": [0, 5, 1, 2, 3, 0]},
        {"start_offset_s": [0, 60]},
    ])
    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_matches_brute_force(self, overrides, seed):
        coords, starts = random_instance(seed, 6)
        params = local(**overrides)
        plan = solve(coords, starts, params)
        assert plan.method == EXACT and plan.proven_optimal
        assert plan.makespan_s == pytest.approx(brute_force_makespan(coords, starts, params), rel=1e-5)

    def test_three_agents_match_brute_force(self):
        coords, starts = random_instance(7, 5, m=3)
        plan = solve(coords, starts, local())
        assert plan.method == EXACT
        assert plan.makespan_s == pytest.approx(brute_force_makespan(coords, starts, local()), rel=1e-5)

    def test_reported_durations_match_routes(self):
        coords, starts = random_instance(4, 9)
        params = local(wind_speed_mps=3)
        plan = solve(coords, starts, params)
        costs = costs_for(coords, starts, params)
        assert plan.durations_s == [pytest.approx(c.route_duration(r)) for c, r in zip(costs, plan.routes)]
        assert plan.makespan_s == max(plan.durations_s)

    def test_minimises_makespan_not_total_time(self):
        # From a shared start on one line, the min-sum optimum sends a single copter down
        # the whole line; min-max accepts a larger total to finish sooner.
        coords = [(x, 0) for x in (20, 40, 60, 80, 100, 120)]
        starts = [(0, 0), (0, 0)]
        plan = solve(coords, starts, local())
        alone = solve(coords, starts[:1], local())
        assert all(plan.routes)
        assert plan.makespan_s < alone.makespan_s
        assert sum(plan.durations_s) > alone.makespan_s

    def test_open_path_ends_at_last_waypoint(self):
        coords, starts = random_instance(5, 6)
        open_plan = solve(coords, starts, local())
        rtl_plan = solve(coords, starts, local(return_to_start=True))
        assert rtl_plan.makespan_s > open_plan.makespan_s


# ─── Method selection and dynamic n ──────────────────────────────────

class TestSelection:
    @pytest.mark.parametrize("n, m, yaw, expected", [
        (15, 2, True, EXACT), (16, 2, True, CPSAT), (16, 2, False, EXACT), (20, 2, False, EXACT),
        (21, 2, False, CPSAT), (40, 2, True, CPSAT), (41, 2, True, ROUTING), (300, 2, True, ROUTING),
        (301, 2, True, CLUSTER), (10, 4, True, CPSAT), (13, 3, True, EXACT),
    ])
    def test_branches_on_total_n(self, n, m, yaw, expected):
        assert select_method(n, m, yaw, PlannerParams()) == expected

    def test_thresholds_are_parameters(self):
        assert select_method(12, 2, True, PlannerParams(exact_max_n_yaw=10)) == CPSAT
        assert select_method(12, 2, True, PlannerParams(method=ROUTING)) == ROUTING

    def test_no_waypoints(self):
        plan = solve([], [(0, 0), (5, 0)], local())
        assert plan.routes == [[], []] and plan.makespan_s == 0

    def test_single_waypoint_goes_to_one_agent(self):
        plan = solve([(10, 0)], [(0, 0), (500, 0)], local())
        assert plan.routes == [[0], []]

    def test_geodetic_dicts_from_dispatch_plan(self):
        waypoints = [{"lat": -6.2000 + i * 1e-4, "lon": 106.8000 + (i % 3) * 1e-4, "alt_m": 20} for i in range(7)]
        plan = solve(waypoints, [(-6.2001, 106.7999, 0), (-6.2001, 106.8003, 0)])
        assert sorted(w for r in plan.routes for w in r) == list(range(7))
        assert plan.method == EXACT

    def test_rejects_wind_faster_than_cruise(self):
        with pytest.raises(ValueError):
            solve([(0, 0)], [(1, 1)], local(wind_speed_mps=6))

    def test_rejects_per_agent_length_mismatch(self):
        with pytest.raises(ValueError):
            solve([(0, 0)], [(1, 1), (2, 2)], local(v_cruise_mps=[5, 5, 5]))


# ─── Solver tiers against the proven optimum ─────────────────────────

class TestSolversAgainstOptimum:
    """Same instance through every tier: the gap to the exact optimum is measured, not assumed."""

    @pytest.fixture(scope="class")
    def instance(self):
        coords, starts = random_instance(11, 9)
        params = dict(coordinate_frame="local", wind_speed_mps=3, wind_from_deg=300)
        return coords, starts, params, solve(coords, starts, dict(params, method=EXACT)).makespan_s

    def test_cpsat_reaches_optimum(self, instance):
        coords, starts, params, optimum = instance
        plan = solve(coords, starts, dict(params, method=CPSAT, cpsat_time_limit_s=30, routing_time_limit_s=1))
        assert plan.proven_optimal
        # CP-SAT is exact on costs rounded to 0.01 s per term.
        assert plan.makespan_s == pytest.approx(optimum, abs=0.01 * 2 * 9)
        assert plan.lower_bound_s <= plan.makespan_s + 1e-6

    def test_cpsat_respects_start_offsets(self, instance):
        coords, starts, params, _ = instance
        params = dict(params, start_offset_s=[0, 45])
        optimum = solve(coords, starts, dict(params, method=EXACT)).makespan_s
        plan = solve(coords, starts, dict(params, method=CPSAT, cpsat_time_limit_s=30, routing_time_limit_s=1))
        assert plan.makespan_s == pytest.approx(optimum, abs=0.01 * 2 * 9)
        assert plan.durations_s[1] >= 45

    @pytest.mark.parametrize("method", [ROUTING, CLUSTER])
    def test_heuristics_cover_and_never_beat_optimum(self, instance, method):
        coords, starts, params, optimum = instance
        plan = solve(coords, starts, dict(params, method=method, routing_time_limit_s=1, cluster_route_time_limit_s=0.5))
        assert sorted(w for r in plan.routes for w in r) == list(range(9))
        assert not plan.proven_optimal
        assert plan.makespan_s >= optimum - 1e-6

    def test_routing_handles_large_n(self):
        coords, starts = random_instance(3, 60)
        plan = solve(coords, starts, local(routing_time_limit_s=2))
        assert plan.method == ROUTING
        assert sorted(w for r in plan.routes for w in r) == list(range(60))
        assert all(plan.routes)
