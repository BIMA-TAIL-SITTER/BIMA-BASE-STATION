"""Min-max makespan route planning for a quadcopter swarm over n waypoints.

solve(coords, starts, params) splits the waypoints among the agents and orders each
agent's share so that the slowest agent finishes as early as possible (min-max mTSP,
open path unless return_to_start). The search method is picked from the total
waypoint count n at runtime; every threshold is a parameter:

    n <= 15 with yaw (20 without), m <= 3   Held-Karp + partition enumeration      proven optimum
    n <= 40                                 CP-SAT, min-max objective               optimum if it converges
    n <= 300                                OR-Tools Routing + global span cost     near-optimal, yaw approximated
    n >  300                                cluster-first route-second              heuristic

LKH-3 is not part of this stack, so the last tier is cluster-first route-second.
Every tier shares the cost model in route_cost, and reported durations always use its
exact triplet yaw term, whatever a solver optimised internally.
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field, fields
from typing import Mapping, Optional, Sequence, Union

import numpy as np

from app.services.mission.route_cost import AgentCost, build_agent_cost, wind_vector
from app.services.mission.survey_generator import latlon_to_enu

EXACT = "held_karp"
CPSAT = "cp_sat"
ROUTING = "or_tools_routing"
CLUSTER = "cluster_first_route_second"
METHODS = (EXACT, CPSAT, ROUTING, CLUSTER)

PerAgent = Union[float, Sequence[float]]


@dataclass
class PlannerParams:
    """Cost-model inputs plus solver controls. Defaults follow ArduCopter/companion defaults;
    set them from the real FC parameters."""
    coordinate_frame: str = "geodetic"     # "geodetic": (lat, lon[, alt_m]); "local": (east, north[, up]) m
    v_cruise_mps: PerAgent = 5.0           # WPNAV_SPEED default 500 cm/s
    t_accel_s: PerAgent = 2.0              # ~ v_cruise / WPNAV_ACCEL (2.5 m/s^2) lost per stop
    yaw_rate_dps: Optional[PerAgent] = 60.0  # ATC_SLEW_YAW default 6000 cdeg/s; None drops the yaw penalty
    dwell_s: PerAgent = 3.0                # scalar or one per waypoint; companion hold default 3 s
    wind_speed_mps: float = 0.0
    wind_from_deg: float = 0.0             # direction the wind blows from
    initial_heading_deg: Optional[PerAgent] = None
    return_to_start: bool = False
    start_offset_s: PerAgent = 0.0         # time before each agent is free at its start (e.g. finishing a task)
    method: str = "auto"                   # or one of METHODS, e.g. to measure an optimality gap
    exact_max_n_yaw: int = 15
    exact_max_n_no_yaw: int = 20
    exact_max_agents: int = 3
    exact_memory_limit_mb: float = 2048.0
    cpsat_max_n: int = 40
    routing_max_n: int = 300
    cpsat_time_limit_s: float = 60.0
    routing_time_limit_s: float = 10.0
    cluster_route_time_limit_s: float = 1.0
    cluster_balance_rounds: int = 3
    span_cost_coefficient: int = 100
    time_resolution_s: float = 0.01        # integer tick for CP-SAT / Routing costs
    yaw_approx_neighbors: int = 4
    workers: int = 8

    @classmethod
    def coerce(cls, params) -> "PlannerParams":
        if params is None:
            return cls()
        if isinstance(params, cls):
            return params
        unknown = set(params) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown planner parameters: {sorted(unknown)}")
        return cls(**params)


@dataclass
class RoutePlan:
    routes: list[list[int]]        # waypoint indices into coords, in flight order, per agent
    durations_s: list[float]       # finish time per agent from now, start_offset_s included
    makespan_s: float
    method: str
    proven_optimal: bool
    n: int
    agents: int
    lower_bound_s: Optional[float] = None
    solve_time_s: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def solve(coords, starts, params: Union[PlannerParams, Mapping, None] = None) -> RoutePlan:
    """Plan one route per start position over all `coords`, minimising the makespan.

    coords / starts are (lat, lon[, alt_m]) tuples or {"lat", "lon", "alt_m"} dicts, or
    local (east, north[, up]) metres with coordinate_frame="local". The number of
    waypoints is free; the method follows from it (see module docstring).
    """
    params = PlannerParams.coerce(params)
    began = time.perf_counter()
    waypoints, start_points = _to_local(coords, starts, params.coordinate_frame)
    n, m = len(waypoints), len(start_points)
    if m < 1:
        raise ValueError("At least one start position is required")
    costs = build_costs(waypoints, start_points, params)
    offsets = [float(o) for o in _per_agent(params.start_offset_s, m, "start_offset_s")]
    if any(not o >= 0 for o in offsets):
        raise ValueError("start_offset_s must be >= 0")
    method = select_method(n, m, any(c.models_yaw for c in costs), params)
    notes, lower_bound, proven = [], None, False
    if n == 0:
        routes, proven = [[] for _ in range(m)], True
    elif method == EXACT:
        routes, proven = _solve_exact(costs, params, offsets), True
    elif method == CPSAT:
        routes, proven, lower_bound, notes = _solve_cpsat(costs, params, offsets)
    elif method == ROUTING:
        routes = _route_with_ortools(costs, np.arange(n), params.routing_time_limit_s, params, offsets=offsets)
        notes.append("yaw approximated inside the solver; durations re-evaluated exactly")
    else:
        routes = _solve_cluster(costs, waypoints, start_points, params, offsets)
        notes.append("LKH-3 unavailable; cluster-first route-second used")
    _check_cover(routes, n)
    durations = [offset + cost.route_duration(route) for cost, route, offset in zip(costs, routes, offsets)]
    makespan = max(durations)
    if proven:
        lower_bound = makespan
    return RoutePlan(routes=routes, durations_s=durations, makespan_s=makespan, method=method,
                     proven_optimal=proven, n=n, agents=m, lower_bound_s=lower_bound,
                     solve_time_s=time.perf_counter() - began, notes=notes)


def select_method(n: int, m: int, models_yaw: bool, params: PlannerParams) -> str:
    if params.method != "auto":
        if params.method not in METHODS:
            raise ValueError(f"method must be 'auto' or one of {METHODS}")
        return params.method
    exact_max_n = params.exact_max_n_yaw if models_yaw else params.exact_max_n_no_yaw
    if m <= params.exact_max_agents and n <= exact_max_n:
        return EXACT
    if n <= params.cpsat_max_n:
        return CPSAT
    if n <= params.routing_max_n:
        return ROUTING
    return CLUSTER


# ── inputs ───────────────────────────────────────────────────────────────

def _as_points(items, frame: str) -> np.ndarray:
    rows = []
    for item in items:
        if isinstance(item, Mapping):
            item = (item["lat"], item["lon"], item.get("alt_m", 0.0)) if frame == "geodetic" \
                else (item["east"], item["north"], item.get("up", 0.0))
        values = [float(v) for v in item]
        if len(values) not in (2, 3):
            raise ValueError("Each coordinate needs 2 or 3 components")
        rows.append(values + [0.0] * (3 - len(values)))
    points = np.array(rows, dtype=float).reshape(-1, 3)
    if not np.isfinite(points).all():
        raise ValueError("Coordinates must be finite")
    return points


def _to_local(coords, starts, frame: str):
    if frame not in ("geodetic", "local"):
        raise ValueError("coordinate_frame must be 'geodetic' or 'local'")
    waypoints, start_points = _as_points(coords, frame), _as_points(starts, frame)
    if frame == "local":
        return waypoints, start_points
    ref_lat, ref_lon = np.vstack((waypoints, start_points))[:, :2].mean(axis=0)

    def project(points):
        return np.array([(*latlon_to_enu(lat, lon, ref_lat, ref_lon), alt) for lat, lon, alt in points]).reshape(-1, 3)

    return project(waypoints), project(start_points)


def _per_agent(value, m: int, name: str) -> list:
    if value is None or np.isscalar(value):
        return [value] * m
    values = list(value)
    if len(values) != m:
        raise ValueError(f"{name} needs one value per agent ({m})")
    return values


def build_costs(waypoints: np.ndarray, starts: np.ndarray, params: PlannerParams) -> list[AgentCost]:
    n, m = len(waypoints), len(starts)
    dwell = np.asarray(params.dwell_s, dtype=float)
    if dwell.ndim == 0:
        dwell = np.full(n, float(dwell))
    if dwell.shape != (n,) or (dwell < 0).any():
        raise ValueError("dwell_s must be a non-negative scalar or one value per waypoint")
    wind = wind_vector(params.wind_speed_mps, params.wind_from_deg)
    costs = []
    for v, accel, yaw_rate, heading, start in zip(
            _per_agent(params.v_cruise_mps, m, "v_cruise_mps"), _per_agent(params.t_accel_s, m, "t_accel_s"),
            _per_agent(params.yaw_rate_dps, m, "yaw_rate_dps"),
            _per_agent(params.initial_heading_deg, m, "initial_heading_deg"), starts):
        if not v > abs(params.wind_speed_mps):
            raise ValueError("v_cruise_mps must exceed the wind speed")
        if accel < 0 or (yaw_rate is not None and not yaw_rate > 0):
            raise ValueError("t_accel_s must be >= 0 and yaw_rate_dps > 0 (or None to ignore yaw)")
        costs.append(build_agent_cost(waypoints, start, v_cruise_mps=v, t_accel_s=accel, dwell_s=dwell,
                                      yaw_rate_dps=yaw_rate, wind_en=wind, initial_heading_deg=heading,
                                      return_to_start=params.return_to_start))
    return costs


def _check_cover(routes, n: int):
    visited = sorted(w for route in routes for w in route)
    if visited != list(range(n)):
        raise RuntimeError("Planner produced routes that do not visit every waypoint exactly once")


# ── exact: Held-Karp per agent + enumeration of the split ───────────────

def _popcount(values: np.ndarray) -> np.ndarray:
    count, rest = np.zeros_like(values), values.copy()
    while rest.any():
        count += rest & 1
        rest >>= 1
    return count


def _exact_memory_bytes(n: int, m: int, models_yaw: bool) -> int:
    states = (1 << n) * ((n + 1) * n if models_yaw else n)
    return states * (m + 8)  # int8 parents kept per agent + float32 dp and totals while building


def _held_karp(cost: AgentCost):
    """Best duration for every subset of waypoints, plus a backtracker for its route.

    With yaw the turn at a node depends on the node before it, so the state is
    dp[S][prev][last] (prev == n is the start); without yaw it is dp[S][last].
    """
    n = cost.n
    size = 1 << n
    masks = np.arange(size, dtype=np.int64)
    layers = _popcount(masks)
    bits = np.int64(1) << np.arange(n, dtype=np.int64)
    leg = cost.leg[:n, :n].astype(np.float32)
    end = cost.end_cost().astype(np.float32)  # [prev, last]
    if cost.models_yaw:
        turn = cost.turn_tensor()[:, :, :n].astype(np.float32)  # [q, p, last]
        dp = np.full((size, n + 1, n), np.inf, np.float32)
        parent = np.full((size, n + 1, n), -1, np.int8)
        dp[bits, n, np.arange(n)] = cost.start_cost()
        for k in range(2, n + 1):
            layer = masks[layers == k]
            for last in range(n):
                target = layer[((layer >> last) & 1).astype(bool)]
                via = dp[target ^ bits[last]] + turn[None, :, :, last]  # (B, q, p)
                parent[target, :n, last] = via.argmin(axis=1)
                dp[target, :n, last] = via.min(axis=1) + leg[:, last]
        totals = (dp + end[None]).reshape(size, -1)
    else:
        dp = np.full((size, n), np.inf, np.float32)
        parent = np.full((size, n), -1, np.int8)
        dp[bits, np.arange(n)] = cost.start_cost()
        for k in range(2, n + 1):
            layer = masks[layers == k]
            for last in range(n):
                target = layer[((layer >> last) & 1).astype(bool)]
                via = dp[target ^ bits[last]] + leg[None, :, last]  # (B, p)
                parent[target, last] = via.argmin(axis=1)
                dp[target, last] = via.min(axis=1)
        totals = dp + end[n][None, :]
    del dp
    arg = totals.argmin(axis=1)
    best = totals[masks, arg]
    best[0] = 0.0
    del totals

    def route(subset: int) -> list[int]:
        order = []
        if not subset:
            return order
        if cost.models_yaw:
            prev, last = divmod(int(arg[subset]), n)
            while True:
                order.append(last)
                if prev == n:
                    break
                before = int(parent[subset, prev, last])
                subset ^= 1 << last
                prev, last = before, prev
        else:
            last = int(arg[subset])
            while subset:
                order.append(last)
                before = int(parent[subset, last])
                subset ^= 1 << last
                last = before
        return order[::-1]

    return best, route


def _submasks(mask: int) -> np.ndarray:
    subs = np.zeros(1, dtype=np.int64)
    bit = 1
    while bit <= mask:
        if mask & bit:
            subs = np.concatenate((subs, subs | bit))
        bit <<= 1
    return subs


def _best_split(bests: list[np.ndarray], mask: int):
    """(makespan, total, parts): min-max split of `mask` among agents, ties broken by total time."""
    if len(bests) == 1:
        value = float(bests[0][mask])
        return value, value, [mask]
    subs = _submasks(mask)
    if len(bests) == 2:
        a, b = bests[0][subs], bests[1][mask ^ subs]
        i = np.lexsort((a + b, np.maximum(a, b)))[0]
        return float(max(a[i], b[i])), float(a[i] + b[i]), [int(subs[i]), mask ^ int(subs[i])]
    best = (math.inf, math.inf, None)
    for sub in subs.tolist():
        head = float(bests[0][sub])
        if head > best[0]:
            continue
        span, total, parts = _best_split(bests[1:], mask ^ sub)
        if (max(head, span), head + total) < best[:2]:
            best = (max(head, span), head + total, [sub] + parts)
    return best


def _solve_exact(costs: list[AgentCost], params: PlannerParams, offsets: list[float]) -> list[list[int]]:
    n, m = costs[0].n, len(costs)
    needed = _exact_memory_bytes(n, m, any(c.models_yaw for c in costs)) / 2 ** 20
    if needed > params.exact_memory_limit_mb:
        raise ValueError(f"Held-Karp needs ~{needed:.0f} MB for n={n}, m={m}; "
                         f"above exact_memory_limit_mb={params.exact_memory_limit_mb:.0f}")
    tables = [_held_karp(cost) for cost in costs]
    _, _, parts = _best_split([best + offset for (best, _), offset in zip(tables, offsets)], (1 << n) - 1)
    return [route(part) for (_, route), part in zip(tables, parts)]


# ── CP-SAT: min-max over one circuit per agent ───────────────────────────

def _solve_cpsat(costs: list[AgentCost], params: PlannerParams, offsets: list[float]):
    """Returns (routes, proven_optimal, lower_bound_s, notes).

    Node 0 is the agent's depot and node w + 1 waypoint w. A self-loop marks a waypoint
    the agent skips; each waypoint is visited by exactly one agent. With yaw, a boolean
    per (prev, at, next) triplet is tied to both arcs so the turn cost stays exact.
    A short Routing run seeds the search; a second phase keeps the makespan and
    minimises total time so the non-critical agents do not wander.
    """
    from ortools.sat.python import cp_model

    n, m = costs[0].n, len(costs)
    warm = _route_with_ortools(costs, np.arange(n), min(params.routing_time_limit_s, params.cpsat_time_limit_s / 4),
                               params, offsets=offsets)
    scale = 1.0 / params.time_resolution_s
    offset_ticks = [int(round(offset * scale)) for offset in offsets]
    model = cp_model.CpModel()
    durations, arc_vars, upper = [], [], 0
    skips = [[None] * n for _ in range(m)]
    for a, cost in enumerate(costs):
        route = [-1, *warm[a], -1] if warm[a] else []
        hint_arcs = set(zip(route, route[1:]))
        hint_turns = set(zip(route, route[1:], route[2:]))
        start, lits, coeffs = cost.start_cost(), [], []
        unused = model.NewBoolVar(f"unused_{a}")
        model.AddHint(unused, not warm[a])
        arcs = [(0, 0, unused)]
        for w in range(n):
            skips[a][w] = model.NewBoolVar(f"skip_{a}_{w}")
            model.AddHint(skips[a][w], w not in warm[a])
            model.AddImplication(unused, skips[a][w])
            arcs.append((w + 1, w + 1, skips[a][w]))
        x = {}
        for i in range(-1, n):
            for j in range(-1, n):
                if i == j:
                    continue
                lit = x[i, j] = model.NewBoolVar(f"x_{a}_{i}_{j}")
                model.AddHint(lit, (i, j) in hint_arcs)
                arcs.append((i + 1, j + 1, lit))
                if i < 0:
                    seconds = start[j]
                elif j < 0:
                    seconds = cost.leg[i, n] if cost.return_to_start else 0.0
                else:
                    seconds = cost.leg[i, j]
                lits.append(lit)
                coeffs.append(int(round(seconds * scale)))
        model.AddCircuit(arcs)
        for w in range(n):  # implied by the circuit, stated so the LP relaxation sees them
            model.Add(sum(x[i, w] for i in range(-1, n) if i != w) + skips[a][w] == 1)
            model.Add(sum(x[w, k] for k in range(-1, n) if k != w) + skips[a][w] == 1)
        if cost.models_yaw:
            for j in range(n):
                into, out = {}, {}
                for i in range(-1, n):
                    for k in range(-1, n):
                        if j in (i, k) or (i == k and i >= 0):
                            continue
                        if k < 0 and not cost.return_to_start:
                            seconds = 0.0
                        else:
                            seconds = float(cost.turn(n if i < 0 else i, j, n if k < 0 else k))
                        lit = model.NewBoolVar(f"y_{a}_{i}_{j}_{k}")
                        model.AddHint(lit, (i, j, k) in hint_turns)
                        into.setdefault(i, []).append(lit)
                        out.setdefault(k, []).append(lit)
                        if seconds:
                            lits.append(lit)
                            coeffs.append(int(round(seconds * scale)))
                for i, group in into.items():
                    model.Add(sum(group) == x[i, j])
                for k, group in out.items():
                    model.Add(sum(group) == x[j, k])
        durations.append(cp_model.LinearExpr.WeightedSum(lits, coeffs))
        arc_vars.append(x)
        upper = max(upper, sum(coeffs) + offset_ticks[a])
    for w in range(n):
        model.Add(sum(skips[a][w] for a in range(m)) == m - 1)
    makespan = model.NewIntVar(0, upper, "makespan")
    for duration, offset in zip(durations, offset_ticks):
        model.Add(makespan >= duration + offset)
    model.Add(m * makespan >= sum(durations) + sum(offset_ticks))  # redundant; gives the LP a bound to work from
    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = params.cpsat_time_limit_s
    solver.parameters.num_workers = params.workers
    solver.parameters.linearization_level = 2
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return warm, False, None, ["CP-SAT found no solution in time; Routing warm start returned"]
    proven = status == cp_model.OPTIMAL
    lower_bound = solver.BestObjectiveBound() / scale
    routes = _cpsat_routes(solver, arc_vars, m)

    # Phase 2: hold the makespan, shorten the other agents' routes.
    model.ClearHints()
    for x in arc_vars:
        for lit in x.values():
            model.AddHint(lit, solver.Value(lit))
    model.Add(makespan <= solver.Value(makespan))
    model.Minimize(sum(durations))
    polish = cp_model.CpSolver()
    polish.parameters.max_time_in_seconds = params.cpsat_time_limit_s / 4
    polish.parameters.num_workers = params.workers
    if polish.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        routes = _cpsat_routes(polish, arc_vars, m)
    notes = [f"CP-SAT status {'OPTIMAL' if proven else 'FEASIBLE'} on costs rounded to "
             f"{params.time_resolution_s} s"]
    return routes, proven, lower_bound, notes


def _cpsat_routes(solver, arc_vars, m: int) -> list[list[int]]:
    routes = []
    for a in range(m):
        succ = {i: j for (i, j), lit in arc_vars[a].items() if solver.Value(lit)}
        route, node = [], succ.get(-1, -1)
        while node != -1:
            route.append(node)
            node = succ[node]
        routes.append(route)
    return routes


# ── OR-Tools Routing with a global span cost ─────────────────────────────

def _approx_turn(cost: AgentCost, nodes: np.ndarray, neighbors: int) -> np.ndarray:
    """(r, r+1) expected yaw time at nodes[i] when leaving for nodes[j] (last column: home).

    Arc costs in Routing are pairwise, so the unknown predecessor is replaced by an
    average over the `neighbors` cheapest ways of arriving at the node.
    """
    r = len(nodes)
    if not cost.models_yaw or r == 0:
        return np.zeros((r, r + 1))
    preds = np.append(nodes, cost.n)
    k = max(1, min(neighbors, len(preds) - 1))
    nearest = preds[np.argsort(cost.leg[np.ix_(preds, nodes)], axis=0)[:k]]  # (k, r)
    succ = np.append(nodes, cost.n)
    turn = cost.turn(nearest[:, :, None], nodes[None, :, None], succ[None, None, :])
    turn[:, np.arange(r), np.arange(r)] = 0.0
    return turn.mean(axis=0)


def _route_with_ortools(costs: list[AgentCost], nodes: np.ndarray, time_limit_s: float,
                        params: PlannerParams, guided: bool = True, offsets=None) -> list[list[int]]:
    """One route per agent over waypoint ids `nodes`; min-max through SetGlobalSpanCostCoefficient.
    An agent's start offset becomes the fixed time at its start node."""
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    m, r = len(costs), len(nodes)
    size, scale = r + 2 * m, 1.0 / params.time_resolution_s
    matrices = []
    for a, cost in enumerate(costs):
        turn = _approx_turn(cost, nodes, params.yaw_approx_neighbors)
        seconds = np.zeros((size, size))
        seconds[:r, :r] = cost.leg[np.ix_(nodes, nodes)] + turn[:, :r]
        np.fill_diagonal(seconds, 0.0)
        seconds[r + a, :r] = cost.start_cost()[nodes]
        if cost.return_to_start:  # open path: reaching the dummy end is free
            seconds[:r, r + m + a] = cost.leg[nodes, cost.n] + turn[:, r]
        matrices.append(np.rint(seconds * scale).astype(np.int64))
    manager = pywrapcp.RoutingIndexManager(size, m, [r + a for a in range(m)], [r + m + a for a in range(m)])
    routing = pywrapcp.RoutingModel(manager)
    transits = [routing.RegisterTransitMatrix(matrix.tolist()) for matrix in matrices]
    for a, transit in enumerate(transits):
        routing.SetArcCostEvaluatorOfVehicle(transit, a)
    offset_ticks = [int(round(o * scale)) for o in (offsets or [0.0] * m)]
    horizon = int(max(matrix.max(axis=1).sum() for matrix in matrices)) + max(offset_ticks) + 1
    routing.AddDimensionWithVehicleTransits(transits, 0, horizon, False, "Waktu")
    clock = routing.GetDimensionOrDie("Waktu")
    for a, offset in enumerate(offset_ticks):
        clock.CumulVar(routing.Start(a)).SetValue(offset)
    clock.SetGlobalSpanCostCoefficient(params.span_cost_coefficient)
    search = pywrapcp.DefaultRoutingSearchParameters()
    search.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    if guided:
        search.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search.time_limit.FromMilliseconds(max(1, int(time_limit_s * 1000)))
    solution = routing.SolveWithParameters(search)
    if solution is None:
        raise RuntimeError("OR-Tools Routing found no solution")
    routes = []
    for a in range(m):
        route, index = [], solution.Value(routing.NextVar(routing.Start(a)))
        while not routing.IsEnd(index):
            route.append(int(nodes[manager.IndexToNode(index)]))
            index = solution.Value(routing.NextVar(index))
        routes.append(route)
    return routes


# ── cluster-first route-second (n beyond Routing's range) ────────────────

def _solve_cluster(costs: list[AgentCost], waypoints: np.ndarray, starts: np.ndarray,
                   params: PlannerParams, offsets: list[float]) -> list[list[int]]:
    """Cut the waypoints into m stripes along their principal axis, give each stripe to the
    agent at the matching position on that axis, and route it alone. Each cut is then
    moved by bisection to balance the flight times of its two neighbouring stripes,
    which targets the makespan rather than spatial compactness."""
    n, m = len(waypoints), len(costs)
    centre = waypoints[:, :2].mean(axis=0)
    axis = np.linalg.svd(waypoints[:, :2] - centre, full_matrices=False)[2][0]
    order = np.argsort((waypoints[:, :2] - centre) @ axis)
    agent_at = np.argsort((starts[:, :2] - centre) @ axis)
    cache = {}

    def stripe(slot: int, lo: int, hi: int, guided: bool = False):
        key = (slot, lo, hi, guided)
        if key not in cache:
            cost = costs[agent_at[slot]]
            route = _route_with_ortools([cost], order[lo:hi], params.cluster_route_time_limit_s,
                                        params, guided)[0] if hi > lo else []
            cache[key] = (offsets[agent_at[slot]] + cost.route_duration(route), route)
        return cache[key]

    def pair_span(b: int, cut: int, lo: int, hi: int) -> float:
        return max(stripe(b - 1, lo, cut)[0], stripe(b, cut, hi)[0])

    cuts = [round(i * n / m) for i in range(m + 1)]
    for _ in range(params.cluster_balance_rounds):
        moved = False
        for b in range(1, m):
            lo, hi = cuts[b - 1], cuts[b + 1]
            left, right = lo, hi  # left stripe is faster at `left`, not faster at `right`
            while right - left > 1:
                mid = (left + right) // 2
                if stripe(b - 1, lo, mid)[0] < stripe(b, mid, hi)[0]:
                    left = mid
                else:
                    right = mid
            cut = min((left, right), key=lambda c: pair_span(b, c, lo, hi))
            if pair_span(b, cut, lo, hi) < pair_span(b, cuts[b], lo, hi):
                cuts[b], moved = cut, True
        if not moved:
            break
    routes = [[] for _ in range(m)]
    for slot in range(m):
        lo, hi = cuts[slot], cuts[slot + 1]
        routes[agent_at[slot]] = min(stripe(slot, lo, hi), stripe(slot, lo, hi, guided=True))[1]
    return routes
