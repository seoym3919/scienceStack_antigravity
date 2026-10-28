#!/usr/bin/env python3
r"""
check_against_reference.py - run YOUR solver on a canonical problem and compare its output with a reference.

    check_against_reference.py list
    check_against_reference.py run BENCHMARK --solver FILE.py:func [--tol X] [--json F] [--report F]
    check_against_reference.py compare --ref FILE --test FILE --rtol R --atol A
    check_against_reference.py run-manifest [--manifest reference-checks.json] [--baseline-ref GITREF]
    check_against_reference.py check-manifest [--manifest FILE]
    check_against_reference.py evidence verify|show|fresh

A solver is checked for reproducibility by default: `--repeat` (default 2) calls it that many times on every input and
fails the case if the answers differ by more than `--repeat-tol` (relative to 1 + |value|; default 0 = identical), which
catches unseeded randomness and unsynchronised threads. Pass `--repeat 1` to skip that check. Exit status: 0 every case
passed; 1 a case failed (wrong value, solver raised, NaN/Inf, timeout); 2 nothing was checked (bad arguments, tolerance
the reference cannot resolve, solver cannot be loaded, evidence could not be recorded); 3 verdict withheld: the tolerance
was loosened after a failure on unchanged files (a --justify sentence does not release it; a tolerance-approvals.json
entry does), or a manifest check was removed or relaxed against the baseline. Highest code wins.

Every `run` and `compare` appends a record to ./.verification/log.jsonl (see verification_evidence.py): the verdict,
the tolerance and the SHA-256 of the solver (or of the reference and test files). `--no-evidence` turns that off.

Benchmarks (`list` prints each contract and its reference):
  kepler       solver(M, e) -> E                      reference: bisection on Kepler's equation + its residual
  lane-emden   solver(n) -> {"xi_1", "omega_n"}       reference: closed forms (n=0, 1) and tabulated values
  sod          solver(x, t) -> {"x"?, "density", "velocity", "pressure"}   reference: exact Riemann solution
  robertson    solver(t) -> [y1, y2, y3]              reference: stored values cross-checked by 3 integrators

Tolerances are part of the verdict and are never chosen silently:
  * a benchmark whose error is set by the solver's own discretisation (lane-emden, sod, robertson) has NO default:
    --tol is required;
  * kepler has a documented default (1e-12); a larger --tol is allowed but the result is marked "relaxed";
  * a tolerance finer than 10x the reference's own uncertainty is refused (exit 2): it would not be a test.

The solver runs in this process with a per-call timeout. Nothing here is random.
"""

from __future__ import annotations

import argparse
import atexit
import copy
import hashlib
import importlib.util
import inspect
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verification_evidence as ve  # noqa: E402
import reference_manifest as rm  # noqa: E402
import reference_build as rb  # noqa: E402
import convergence as cv  # noqa: E402

CHECKER_VERSION = "2.0"
TOOL = "check_against_reference"
PLUGIN_NAME = "sciencestack"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
TWO_PI = 2.0 * math.pi


def fresh_bytecode_cache() -> None:
    """Give this process an empty bytecode cache.

    Python validates a cached .pyc by the source file's modification time (to the second) and size, so a solver edited
    within the same second to a same-sized variant would run its OLD code while the evidence is bound to the NEW file's
    hash. An empty cache makes every import compile from the current source."""
    directory = tempfile.mkdtemp(prefix="pyc_")
    sys.pycache_prefix = directory
    atexit.register(shutil.rmtree, directory, True)


class UsageError(Exception):
    """Nothing could be checked (exit status 2)."""


class CaseFailure(Exception):
    """The solver's answer for one case is unusable (exit status 1)."""


# --------------------------------------------------------------------------------------------------------------
# Loading and calling the user's solver
# --------------------------------------------------------------------------------------------------------------

def load_callable(target: str) -> Callable:
    """'module:func' or 'path/to/file.py:func'."""
    if ":" not in target:
        raise UsageError(f"--solver must be 'module:function' or 'path/file.py:function', got {target!r}")
    module_part, func_name = target.rsplit(":", 1)
    try:
        if os.path.isfile(module_part):
            unique = "solver_" + hashlib.sha256(os.path.abspath(module_part).encode()).hexdigest()[:12]
            spec = importlib.util.spec_from_file_location(unique, module_part)
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load {module_part}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[unique] = module
            solver_dir = str(Path(module_part).resolve().parent)
            if solver_dir not in sys.path:
                sys.path.append(solver_dir)               # lets the solver import its sibling modules
            spec.loader.exec_module(module)
        else:
            module = importlib.import_module(module_part)
    except Exception as exc:
        raise UsageError(f"cannot load solver module {module_part!r}: {type(exc).__name__}: {exc}")
    fn = getattr(module, func_name, None)
    if not callable(fn):
        raise UsageError(f"{func_name!r} is not a callable in {module_part!r}")
    return fn


def call_with_timeout(fn: Callable, args: Sequence[Any], timeout_s: int) -> Any:
    """Call fn(*args); a call that outlives timeout_s seconds raises CaseFailure (Unix; elsewhere no limit)."""
    if not hasattr(signal, "SIGALRM") or timeout_s <= 0:
        return fn(*args)

    def on_alarm(signum, frame):
        raise TimeoutError(f"solver did not return within {timeout_s} s")

    previous = signal.signal(signal.SIGALRM, on_alarm)
    signal.alarm(timeout_s)
    try:
        return fn(*args)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def as_float(value: Any, what: str) -> float:
    if isinstance(value, bool):
        raise CaseFailure(f"{what} is a bool, not a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise CaseFailure(f"{what} is not a number: {value!r}")
    if not math.isfinite(number):
        raise CaseFailure(f"{what} is not finite: {number}")
    return number


def answer_difference(a: Any, b: Any, depth: int = 0) -> float:
    """Largest |x - y| / (1 + |x|) over the numeric leaves of two solver answers; inf if their structure, keys, types
    or non-numeric values differ. NaN equals NaN and an infinity equals the same infinity (a solver that returns NaN
    twice is reproducible, and the benchmark check rejects NaN separately)."""
    if depth > 50:
        return math.inf
    if hasattr(a, "tolist"):
        a = a.tolist()
    if hasattr(b, "tolist"):
        b = b.tolist()
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str) or isinstance(b, str):
        return 0.0 if type(a) is type(b) and a == b else math.inf
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        x, y = float(a), float(b)
        if math.isnan(x) or math.isnan(y):
            return 0.0 if math.isnan(x) and math.isnan(y) else math.inf
        if math.isinf(x) or math.isinf(y):
            return 0.0 if x == y else math.inf
        return abs(x - y) / (1.0 + abs(x))
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return math.inf
        return max((answer_difference(a[k], b[k], depth + 1) for k in a), default=0.0)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return math.inf
        return max((answer_difference(x, y, depth + 1) for x, y in zip(a, b)), default=0.0)
    return 0.0 if type(a) is type(b) and repr(a) == repr(b) else math.inf


def call_repeated(solver: Callable, call_args: Sequence[Any], args) -> Tuple[Any, float]:
    """The first answer, and the largest difference between it and the answers of the other `--repeat - 1` calls on the
    same input. A difference above --repeat-tol is a failure: a solver whose answer changes between identical calls is
    not deterministic (unseeded randomness, threading, uninitialised memory, hidden global state)."""
    first = call_with_timeout(solver, call_args, args.timeout_s)
    if args.repeat > 1:
        try:
            first = copy.deepcopy(first)          # a solver may return the very list it keeps mutating: snapshot it
        except Exception:                         # an uncopyable answer: compared as it is
            pass
    worst = 0.0
    for _ in range(args.repeat - 1):
        again = call_with_timeout(solver, call_args, args.timeout_s)
        worst = max(worst, answer_difference(first, again))
    if worst > args.repeat_tol:
        shown = "the answers have a different structure" if math.isinf(worst) else f"they differ by {worst:.3e}"
        raise CaseFailure(f"not reproducible: {args.repeat} calls on the same input disagree ({shown}; "
                          f"allowed {args.repeat_tol:g}, relative to 1 + |value|)")
    return first, worst


# --------------------------------------------------------------------------------------------------------------
# Benchmarks. Each yields cases; a case checker returns (passed, error, detail).
# --------------------------------------------------------------------------------------------------------------

def _fold(angle: float) -> float:
    """Fold an angle into [-pi, pi]."""
    return angle - TWO_PI * round(angle / TWO_PI)


def kepler_reference(mean_anomaly: float, e: float) -> float:
    """E in [0, 2 pi) solving E - e sin E = M mod 2 pi, by bisection (f is strictly increasing for 0 <= e < 1)."""
    m = mean_anomaly % TWO_PI
    lo, hi = 0.0, TWO_PI
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if mid - e * math.sin(mid) - m < 0.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


KEPLER_M = (0.0, 1e-8, 0.5, 1.0, 3.0, math.pi, 4.0, 6.0, TWO_PI - 1e-8, 7.0, -1.0, 100.0)
KEPLER_E = (0.0, 0.0167, 0.3, 0.7, 0.9, 0.99)


def kepler_cases(args) -> List[Dict[str, Any]]:
    return [{"name": f"M={m:g},e={e:g}", "args": (m, e), "M": m, "e": e} for e in KEPLER_E for m in KEPLER_M]


def kepler_check(case: Dict[str, Any], answer: Any, tol: float) -> Tuple[bool, Dict[str, float], str]:
    big_e = as_float(answer, "E")
    m, e = case["M"], case["e"]
    # Wrap M first: forming E - e sin E - M with |M| ~ 100 would itself lose ~1e-14 (the spacing of doubles there).
    residual = abs(_fold(big_e - e * math.sin(big_e) - m % TWO_PI))
    reference = kepler_reference(m, e)
    delta = abs(_fold(big_e - reference))
    passed = residual <= tol and delta <= tol
    return passed, {"residual": residual, "abs_error_vs_reference": delta}, f"E={big_e!r} reference={reference!r}"


LANE_EMDEN = {
    # n: (xi_1, omega_n = -xi_1^2 theta'(xi_1), source)
    0.0: (math.sqrt(6.0), 2.0 * math.sqrt(6.0), "closed form theta = 1 - xi^2/6: xi_1 = sqrt(6), omega = 2 sqrt(6)"),
    1.0: (math.pi, math.pi, "closed form theta = sin(xi)/xi: xi_1 = pi, omega = pi"),
    1.5: (3.6537537362, 2.7140551201, "DOP853 rtol 1e-13 (series start at xi=1e-4); agrees with Chandrasekhar (1939) "
                                      "tabulated 3.65375, 2.71406 to their rounding"),
    3.0: (6.8968486194, 2.0182359510, "DOP853 rtol 1e-13 (series start at xi=1e-4); agrees with Chandrasekhar (1939) "
                                      "tabulated 6.89685, 2.01824 to their rounding"),
}


def lane_emden_cases(args) -> List[Dict[str, Any]]:
    return [{"name": f"n={n:g}", "args": (n,), "n": n} for n in LANE_EMDEN]


def lane_emden_check(case: Dict[str, Any], answer: Any, tol: float) -> Tuple[bool, Dict[str, float], str]:
    if isinstance(answer, dict):
        missing = [k for k in ("xi_1", "omega_n") if k not in answer]
        if missing:
            raise CaseFailure(f"result dict lacks {missing}")
        xi_1, omega = as_float(answer["xi_1"], "xi_1"), as_float(answer["omega_n"], "omega_n")
    elif isinstance(answer, (list, tuple)) and len(answer) == 2:
        xi_1, omega = as_float(answer[0], "xi_1"), as_float(answer[1], "omega_n")
    else:
        raise CaseFailure("result must be {'xi_1': .., 'omega_n': ..} or a pair (xi_1, omega_n)")
    ref_xi, ref_omega, _ = LANE_EMDEN[case["n"]]
    err_xi, err_omega = abs(xi_1 - ref_xi) / ref_xi, abs(omega - ref_omega) / ref_omega
    return (err_xi <= tol and err_omega <= tol,
            {"rel_error_xi_1": err_xi, "rel_error_omega_n": err_omega},
            f"xi_1={xi_1!r} (ref {ref_xi!r}), omega_n={omega!r} (ref {ref_omega!r})")


SOD_STATE = {"rho_L": 1.0, "u_L": 0.0, "p_L": 1.0, "rho_R": 0.125, "u_R": 0.0, "p_R": 0.1, "gamma": 1.4,
             "x_diaphragm": 0.5}
SOD_TIME = 0.2


def _exact_riemann():
    path = PLUGIN_ROOT / "benchmarks" / "cfd" / "exact_riemann.py"
    spec = importlib.util.spec_from_file_location("psm_exact_riemann", path)
    if spec is None or spec.loader is None:
        raise UsageError(f"cannot load the reference solver {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.exact_riemann_solver


def _sod_reference_on(xs: List[float]) -> Dict[str, List[float]]:
    """Exact solution sampled at arbitrary x: the reference solver samples a uniform grid on [0, 1], so evaluate it
    one point at a time through its own x -> s = (x - x0)/t mapping."""
    solver = _exact_riemann()
    out: Dict[str, List[float]] = {"density": [], "velocity": [], "pressure": []}
    for x in xs:
        # num_points=2 gives the grid {0, 1}; shifting the diaphragm moves x to the sample 0 without changing s.
        sample = solver(**SOD_STATE | {"x_diaphragm": SOD_STATE["x_diaphragm"] - x}, t_target=SOD_TIME, num_points=2)
        out["density"].append(sample["density"][0])
        out["velocity"].append(sample["velocity"][0])
        out["pressure"].append(sample["pressure"][0])
    return out


def sod_cases(args) -> List[Dict[str, Any]]:
    n = args.points
    if n < 3:
        raise UsageError("--points must be at least 3")
    xs = [i / (n - 1) for i in range(n)]
    return [{"name": f"sod t={SOD_TIME:g}", "args": (xs, SOD_TIME), "x": xs}]


def _trapezoid(xs: List[float], ys: List[float]) -> float:
    return sum(0.5 * (ys[i] + ys[i + 1]) * (xs[i + 1] - xs[i]) for i in range(len(xs) - 1))


def sod_check(case: Dict[str, Any], answer: Any, tol: float) -> Tuple[bool, Dict[str, float], str]:
    if not isinstance(answer, dict):
        raise CaseFailure("result must be a dict with 'density', 'velocity', 'pressure' (and optionally 'x')")
    xs = [as_float(v, "x") for v in answer["x"]] if "x" in answer else case["x"]
    fields = {}
    for key in ("density", "velocity", "pressure"):
        if key not in answer:
            raise CaseFailure(f"result lacks {key!r}")
        fields[key] = [as_float(v, key) for v in answer[key]]
        if len(fields[key]) != len(xs):
            raise CaseFailure(f"{key} has {len(fields[key])} values for {len(xs)} x points")
    if len(xs) < 3 or any(xs[i + 1] <= xs[i] for i in range(len(xs) - 1)):
        raise CaseFailure("x must be strictly increasing with at least 3 points")
    if xs[0] < 0.0 or xs[-1] > 1.0:
        raise CaseFailure("x must lie in the Sod domain [0, 1]")
    reference = _sod_reference_on(xs)
    errors = {}
    for key, values in fields.items():
        numerator = _trapezoid(xs, [abs(a - b) for a, b in zip(values, reference[key])])
        denominator = _trapezoid(xs, [abs(b) for b in reference[key]])
        errors["rel_L1_" + key] = numerator / denominator
    return all(v <= tol for v in errors.values()), errors, f"{len(xs)} points on [{xs[0]:g}, {xs[-1]:g}]"


ROBERTSON_RATES = {"k1": 0.04, "k2": 1.0e4, "k3": 3.0e7}
ROBERTSON = {
    # t: (y1, y2, y3) from Radau/BDF/LSODA at rtol 1e-12, atol 1e-22; the three agree to <= 5e-11 relative
    0.4: (9.8517211386e-01, 3.3863953790e-05, 1.4794022185e-02),
    4.0: (9.0551867858e-01, 2.2404756876e-05, 9.4458916659e-02),
    40.0: (7.1582706872e-01, 9.1855347646e-06, 2.8416374575e-01),
    400.0: (4.5051866847e-01, 3.2229014417e-06, 5.4947810863e-01),
    4000.0: (1.8320225778e-01, 8.9423712528e-07, 8.1679684799e-01),
    40000.0: (3.8983377085e-02, 1.6217683159e-07, 9.6101646074e-01),
    100000.0: (1.7865921142e-02, 7.2747514684e-08, 9.8213400611e-01),
}


def robertson_cases(args) -> List[Dict[str, Any]]:
    return [{"name": f"t={t:g}", "args": (t,), "t": t} for t in ROBERTSON]


def robertson_check(case: Dict[str, Any], answer: Any, tol: float) -> Tuple[bool, Dict[str, float], str]:
    try:
        values = [as_float(v, "y component") for v in answer]
    except TypeError:
        raise CaseFailure("result must be a sequence [y1, y2, y3]")
    if len(values) != 3:
        raise CaseFailure(f"result has {len(values)} components, expected 3")
    reference = ROBERTSON[case["t"]]
    errors = {f"rel_error_y{i + 1}": abs(values[i] - reference[i]) / reference[i] for i in range(3)}
    errors["mass_drift"] = abs(sum(values) - 1.0)          # y1 + y2 + y3 = 1 exactly (dy1 + dy2 + dy3 = 0)
    return all(v <= tol for v in errors.values()), errors, f"y={values!r}"


def convergence_settings(args, default_steps: int) -> Tuple[float, int, int]:
    """(expected order, base resolution, number of levels) from --order/--steps/--levels, validated."""
    if args.order is None:
        raise UsageError("convergence benchmarks need --order: the order of accuracy you claim for the method "
                         "(1 = first order, 2, 4, ...); the check fails if the observed order is lower")
    if not (math.isfinite(args.order) and 0.0 < args.order <= 12.0):
        raise UsageError("--order must be a number in (0, 12]")
    steps = default_steps if args.steps is None else args.steps
    levels = 5 if args.levels is None else args.levels
    if steps < 2:
        raise UsageError("--steps must be at least 2")
    if not 3 <= levels <= 8:
        raise UsageError("--levels must be between 3 and 8")
    return float(args.order), steps, levels


def convergence_ode_cases(args) -> List[Dict[str, Any]]:
    order, steps, levels = convergence_settings(args, 16)
    return [{"name": name, "problem": name, "order": order, "calls": cv.ode_calls(name, steps, levels)}
            for name in cv.ODE_PROBLEMS]


def convergence_bvp_cases(args) -> List[Dict[str, Any]]:
    order, steps, levels = convergence_settings(args, 8)
    return [{"name": name, "problem": name, "order": order, "calls": cv.bvp_calls(name, steps, levels)}
            for name in cv.BVP_PROBLEMS]


def _verdicts(case: Dict[str, Any], series: Dict[str, List[float]], margin: float, scale: float):
    """Assess every error series (norm) of one problem; the problem passes only if all of them do."""
    passed, errors, notes = True, {}, []
    worst = None
    for norm, values in series.items():
        verdict = cv.assess(values, case["order"], margin, scale)
        passed = passed and verdict["passed"]
        if "observed" in verdict:
            worst = verdict["observed"] if worst is None else min(worst, verdict["observed"])
        shown = ", ".join(f"{v:.2e}" for v in values)
        orders = ", ".join(f"{o:.2f}" for o in verdict["orders"]) or "n/a"
        notes.append(f"{norm}: errors [{shown}] orders [{orders}]" + ("" if verdict["passed"] else f" -> {verdict['reason']}"))
        errors[f"finest_error_{norm}"] = values[-1]
    errors["required_order"] = case["order"] - margin
    if worst is not None:
        errors["observed_order"] = worst
    return passed, errors, "; ".join(notes)


def convergence_ode_check(case: Dict[str, Any], answers: Any, margin: float) -> Tuple[bool, Dict[str, float], str]:
    try:
        series = {"max-norm": cv.ode_errors(case["problem"], answers)}
    except cv.ConvergenceFailure as exc:
        raise CaseFailure(str(exc))
    scale = max(abs(v) for v in cv.ODE_PROBLEMS[case["problem"]]["exact"])
    return _verdicts(case, series, margin, scale)


def convergence_bvp_check(case: Dict[str, Any], answers: Any, margin: float) -> Tuple[bool, Dict[str, float], str]:
    try:
        series = cv.bvp_errors(case["problem"], answers, [call[0] for call in case["calls"]])
    except cv.ConvergenceFailure as exc:
        raise CaseFailure(str(exc))
    return _verdicts(case, series, margin, 1.0)


class Benchmark:
    def __init__(self, name, contract, reference, default_tol, tol_required, min_tol, uncertainty, units,
                 cases, check, sources, kind="single", parameters=None):
        self.name, self.contract, self.reference = name, contract, reference
        self.default_tol, self.tol_required, self.min_tol = default_tol, tol_required, min_tol
        self.uncertainty, self.units = uncertainty, units
        self.cases, self.check, self.sources = cases, check, sources
        self.kind = kind                      # "single": one solver call per case; "convergence": one per resolution level
        self.parameters = parameters or {}

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "solver_contract": self.contract, "reference": self.reference,
                "default_tolerance": self.default_tol, "tolerance_required": self.tol_required,
                "smallest_tolerance_accepted": self.min_tol, "reference_uncertainty": self.uncertainty,
                "error_measure": self.units, "parameters": self.parameters, "sources": self.sources}


BENCHMARKS = {b.name: b for b in (
    Benchmark("kepler", "solver(M, e) -> E (radians; |M| <= 100; 0 <= e < 1; E may be shifted by multiples of 2 pi)",
              "bisection on E - e sin E = M mod 2 pi, plus the residual of the equation itself", 1e-12, False, 1e-12,
              "<= 1e-13 rad (measured worst 4.5e-14 vs mpmath at e=0.99, M=2pi-1e-8: limited by the 1/(1-e) "
              "conditioning of a double-precision M)", "absolute, radians: residual and |E - E_ref|",
              kepler_cases, kepler_check,
              ["Kepler's equation M = E - e sin E; f is strictly increasing for 0 <= e < 1, so the root is unique "
               "(Danby 1988, Fundamentals of Celestial Mechanics, ch. 6)",
               "default 1e-12: residual roundoff is ~1e-15; any double-precision answer is uncertain by about "
               "ulp(2 pi)/(1 - e) ~ 1e-13 at e = 0.99, so tighter tolerances cannot be certified",
               "|M| <= 100: reducing a larger M modulo 2 pi is ambiguous at double precision (2 pi is rounded)"]),
    Benchmark("lane-emden", "solver(n) -> {'xi_1', 'omega_n'} for n in 0, 1, 1.5, 3 (theta(0)=1, theta'(0)=0)",
              "closed forms for n=0, 1; high-accuracy integration for n=1.5, 3", None, True, 1e-9,
              "<= 1e-10 relative (n = 1.5, 3); exact (n = 0, 1)", "relative error of xi_1 and of omega_n",
              lane_emden_cases, lane_emden_check,
              ["Lane-Emden equation theta'' + (2/xi) theta' + theta^n = 0 (Chandrasekhar 1939, ch. IV)",
               "n=0: xi_1 = sqrt(6), omega = 2 sqrt(6); n=1: xi_1 = omega = pi (closed forms, derived from the solutions)",
               "n=1.5, 3: " + LANE_EMDEN[1.5][2]]),
    Benchmark("sod", "solver(x, t) -> {'density', 'velocity', 'pressure'[, 'x']} at t = 0.2 on x in [0, 1]",
              "exact Riemann solution (benchmarks/cfd/exact_riemann.py), star state checked against its defining equation",
              None, True, 1e-9, "<= 1e-10 relative L1", "relative L1 error per field: int|f - f_ref| / int|f_ref|",
              sod_cases, sod_check,
              ["Toro (2009), Riemann Solvers and Numerical Methods for Fluid Dynamics, 3rd ed., ch. 4 and Table 4.1 test 1: "
               "rho_L=1, u_L=0, p_L=1, rho_R=0.125, u_R=0, p_R=0.1, gamma=1.4, diaphragm at 0.5, t=0.2",
               "star state p*=0.30313018, u*=0.92745262"]),
    Benchmark("robertson", "solver(t) -> [y1, y2, y3] from y(0)=(1,0,0), k1=0.04, k2=1e4, k3=3e7, for t = 0.4 ... 1e5",
              "stored values from three implicit integrators at rtol 1e-12 (agree to <= 5e-11 relative)",
              None, True, 1e-8, "<= 1e-9 relative per component", "relative error per component, and |y1+y2+y3-1|",
              robertson_cases, robertson_check,
              ["Robertson (1966); Hairer & Wanner (1996), Solving ODEs II, sec. IV.1: rates 0.04, 1e4, 3e7",
               "Radau, BDF and LSODA (scipy 1.18.1), rtol 1e-12, atol 1e-22; consistent with the widely printed 5-digit values"]),
    Benchmark("convergence-ode", "integrate(f, y0, t0, t1, n_steps) -> y(t1); f(t, y) -> dy/dt (lists of floats)",
              "four problems with exact solutions: decay, oscillator, nonlinear y' = y^2, time-dependent y' = 2ty",
              cv.DEFAULT_MARGIN, False, cv.MIN_MARGIN,
              "none for the problems; the order estimate itself differs from the asymptotic order by O(h)",
              "order margin: the two finest resolved pairwise orders must be >= --order minus the margin",
              convergence_ode_cases, convergence_ode_check,
              ["Order of accuracy from errors at N, 2N, 4N, ... steps: p = log2(e_N / e_2N); see convergence.py",
               "decay y' = -2y: exp(-2) at t = 1; oscillator x' = v, v' = -x: (cos 2, -sin 2) at t = 2; "
               "nonlinear y' = y^2, y(0) = 1: 1/(1 - t) = 2 at t = 1/2; time-dependent y' = 2ty: e at t = 1",
               "exact values re-derived in the tests with scipy DOP853 (rtol 1e-13)",
               "default margin 0.25 and smallest accepted 0.05 are this plugin's choice (documented in convergence.py)"],
              kind="convergence",
              parameters={"--order": "required: the order of accuracy claimed (1, 2, 4, ...)",
                          "--steps": "base number of steps N (default 16); levels are N, 2N, 4N, ...",
                          "--levels": "number of resolutions, 3-8 (default 5)"}),
    Benchmark("convergence-bvp", "solve(n, f) -> [u_0 ... u_n] for -u'' = f(x) on (0, 1), u(0) = u(1) = 0, grid x_i = i/n",
              "two problems with exact solutions: -u'' = pi^2 sin(pi x) (u = sin(pi x)) and -u'' = 12x^2 - 6x (u = x^3 - x^4)",
              cv.DEFAULT_MARGIN, False, cv.MIN_MARGIN,
              "none for the problems; the order estimate itself differs from the asymptotic order by O(h)",
              "order margin on both the max-norm and the discrete L2 norm of the nodal error",
              convergence_bvp_cases, convergence_bvp_check,
              ["Order of accuracy from errors at n, 2n, 4n, ... intervals; see convergence.py",
               "u = sin(pi x): -u'' = pi^2 sin(pi x); u = x^3 - x^4: u'' = 6x - 12x^2, so -u'' = 12x^2 - 6x; both vanish at 0 and 1",
               "exact solutions re-derived in the tests with mpmath (second derivative at 30 digits)",
               "default margin 0.25 and smallest accepted 0.05 are this plugin's choice (documented in convergence.py)"],
              kind="convergence",
              parameters={"--order": "required: the order of accuracy claimed (2 for central differences)",
                          "--steps": "base number of intervals n (default 8); levels are n, 2n, 4n, ...",
                          "--levels": "number of resolutions, 3-8 (default 5)"}),
)}


# --------------------------------------------------------------------------------------------------------------
# Running a benchmark
# --------------------------------------------------------------------------------------------------------------

def resolve_tolerance(bench: Benchmark, requested: Optional[float]) -> Tuple[float, Optional[bool]]:
    """(tolerance to use, relaxed flag). Raises UsageError for a missing or unresolvable tolerance."""
    if requested is not None and not (requested > 0.0 and math.isfinite(requested)):
        raise UsageError("--tol must be a positive finite number")
    if requested is None:
        if bench.tol_required:
            raise UsageError(f"benchmark {bench.name!r} needs --tol: its error depends on your discretisation, so the "
                             f"tolerance must be your stated, justified choice (smallest accepted: {bench.min_tol:g})")
        return bench.default_tol, False
    if requested < bench.min_tol:
        raise UsageError(f"--tol {requested:g} is finer than this benchmark's reference can resolve "
                         f"(reference uncertainty {bench.uncertainty}; smallest accepted: {bench.min_tol:g})")
    relaxed = None if bench.default_tol is None else requested > bench.default_tol
    return requested, relaxed


def run_benchmark(bench: Benchmark, solver: Callable, tol: float, relaxed: Optional[bool], args) -> Dict[str, Any]:
    cases = bench.cases(args)
    if not cases:
        raise UsageError("the benchmark produced no cases")
    results = []
    timed_out = False
    for case in cases:
        entry: Dict[str, Any] = {"case": case["name"]}
        if timed_out:                                      # do not wait out the timeout once per remaining case
            entry.update(passed=False, reason="not run: an earlier call timed out")
            results.append(entry)
            continue
        try:
            if "calls" in case:                              # a convergence case: one solver call per resolution level
                gathered = [call_repeated(solver, call, args) for call in case["calls"]]
                answer, spread = [g[0] for g in gathered], max(g[1] for g in gathered)
            else:
                answer, spread = call_repeated(solver, case["args"], args)
            passed, errors, detail = bench.check(case, answer, tol)
            entry.update(passed=bool(passed), errors=errors, detail=detail)
            if args.repeat > 1:
                entry["repeat_max_difference"] = spread
        except CaseFailure as exc:
            entry.update(passed=False, reason=str(exc))
        except TimeoutError as exc:
            timed_out = True
            entry.update(passed=False, reason=str(exc))
        except Exception as exc:                          # the solver crashed on this case: a failure, not a bug here
            entry.update(passed=False, reason=f"solver raised {type(exc).__name__}: {exc}")
        results.append(entry)
    return {"benchmark": bench.name, "checker_version": CHECKER_VERSION, "passed": all(r["passed"] for r in results),
            "tolerance_used": tol, "tolerance_default": bench.default_tol, "relaxed": relaxed,
            "repeat": {"calls": args.repeat, "tolerance": args.repeat_tol},
            "runtime": ve.pin_runtime_env(),
            "convergence": ({"order": cases[0]["order"], "levels": len(cases[0]["calls"]), "base": cases[0]["calls"][0][-1]
                             if bench.name == "convergence-ode" else cases[0]["calls"][0][0]}
                            if bench.kind == "convergence" else None),
            "smallest_tolerance_accepted": bench.min_tol, "reference_uncertainty": bench.uncertainty,
            "error_measure": bench.units, "sources": bench.sources, "cases": results}


def format_report(result: Dict[str, Any]) -> str:
    lines = [f"# check_against_reference: {result['benchmark']}", "",
             f"- Status: **{'PASSED' if result['passed'] else 'FAILED'}**",
             f"- Tolerance used: {result['tolerance_used']:g} ({result['error_measure']})"]
    if result["relaxed"]:
        lines.append(f"- **Tolerance relaxed** above the documented default {result['tolerance_default']:g}")
    elif result["tolerance_default"] is None:
        lines.append("- Tolerance chosen by the caller (this benchmark has no default)")
    evidence = result.get("evidence")
    if evidence and evidence.get("error"):
        lines.append(f"- **Evidence NOT recorded**: {evidence['error']}")
    elif evidence:
        lines.append(f"- Evidence: appended to `{evidence['log']}` (exit status {evidence['exit_status']})")
        if "tolerance_loosened_after_failure" in evidence["flags"]:
            lines.append("- **Tolerance was loosened after a failed run of this check** "
                         f"({'files unchanged' if 'subjects_unchanged' in evidence['flags'] else 'files changed since'})")
        if "withheld" in evidence["flags"]:
            lines.append("- **VERDICT WITHHELD**: loosened after a failure on unchanged files; a --justify sentence does not release it")
        if evidence.get("justification"):
            lines.append(f"- Justification recorded: {evidence['justification']}")
    else:
        lines.append("- Evidence not recorded (--no-evidence)")
    if result.get("convergence"):
        c = result["convergence"]
        lines.append(f"- Expected order {c['order']:g}, {c['levels']} resolutions starting at {c['base']}, "
                     f"required observed order >= {c['order'] - result['tolerance_used']:g}")
    repeat = result.get("repeat", {"calls": 1})
    if repeat["calls"] > 1:
        worst = max((c.get("repeat_max_difference", 0.0) for c in result["cases"]), default=0.0)
        lines.append(f"- Reproducibility: {repeat['calls']} calls per case, largest difference {worst:.3e} "
                     f"(allowed {repeat['tolerance']:g})")
    else:
        lines.append("- Reproducibility not checked (--repeat 1)")
    lines += [f"- Reference uncertainty: {result['reference_uncertainty']}", "- Sources:"]
    lines += [f"  - {s}" for s in result["sources"]]
    lines += ["", "| Case | Result | Errors / reason |", "|---|:---:|---|"]
    for r in result["cases"]:
        detail = r.get("reason") or ", ".join(f"{k}={v:.3e}" for k, v in r["errors"].items())
        if not r["passed"] and r.get("detail") and not r.get("reason"):
            detail += " | " + r["detail"]
        lines.append(f"| `{r['case']}` | {'PASS' if r['passed'] else 'FAIL'} | {detail} |")
    failed = sum(1 for r in result["cases"] if not r["passed"])
    lines += ["", f"{len(result['cases']) - failed} of {len(result['cases'])} cases passed."]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------------------------------
# Golden-data comparison
# --------------------------------------------------------------------------------------------------------------

def load_values(path: str) -> List[float]:
    """Numbers from a text file (whitespace/commas; Fortran D exponents; '#'/'!' comment lines) or a .npy array."""
    if path.endswith(".npy"):
        try:
            import numpy as np
            return [float(x) for x in np.load(path).flatten()]
        except ImportError:
            raise UsageError(f"{path}: reading .npy needs numpy; use a text file")
        except (OSError, ValueError) as exc:
            raise UsageError(f"{path}: {exc}")
    try:
        text = Path(path).read_text(errors="replace")
    except OSError as exc:
        raise UsageError(f"{path}: {exc.strerror or exc}")
    values: List[float] = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line[0] in "#!":
            continue
        for token in line.replace(",", " ").split():
            try:
                values.append(float(token.replace("D", "E").replace("d", "e")))
            except ValueError:
                raise UsageError(f"{path}, line {number}: {token!r} is not a number")
    return values


def compare_values(ref: List[float], test: List[float], rtol: float, atol: float) -> Dict[str, Any]:
    """Elementwise |test - ref| <= atol + rtol |ref|. Different lengths, no values, NaN or Inf fail."""
    result: Dict[str, Any] = {"mode": "compare", "checker_version": CHECKER_VERSION, "passed": False,
                              "rtol": rtol, "atol": atol, "n_ref": len(ref), "n_test": len(test),
                              "runtime": ve.pin_runtime_env()}
    if not ref and not test:
        result["reason"] = "both files hold no numbers: nothing was compared"
    elif len(ref) != len(test):
        result["reason"] = f"length mismatch: reference {len(ref)} values, test {len(test)}"
    elif not all(map(math.isfinite, ref)) or not all(map(math.isfinite, test)):
        result["reason"] = "NaN or Inf in the reference or the test output"
    else:
        worst, worst_i, bad = 0.0, 0, 0
        for i, (r, t) in enumerate(zip(ref, test)):
            allowed = atol + rtol * abs(r)
            excess = abs(t - r) / allowed if allowed > 0 else (0.0 if t == r else math.inf)
            bad += excess > 1.0
            if excess > worst:
                worst, worst_i = excess, i
        result.update(points_outside_tolerance=bad, worst_error_over_allowed=worst, worst_index=worst_i,
                      passed=bad == 0)
    return result


# --------------------------------------------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------------------------------------------

def solver_source_file(solver: Callable) -> str:
    module = sys.modules.get(getattr(solver, "__module__", "") or "")
    path = getattr(module, "__file__", None) or inspect.getsourcefile(solver)
    if not path:
        raise UsageError("cannot find the solver's source file, so the evidence cannot be tied to it (use --no-evidence)")
    return path


def run_manifest_command(args) -> int:
    manifest_path = Path(args.manifest).resolve()
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError) as exc:
        raise UsageError(f"cannot read manifest {manifest_path}: {exc}")
    errors = rm.validate(manifest, BENCHMARKS, resolve_tolerance)
    if errors:
        raise UsageError("manifest is invalid:\n  " + "\n  ".join(errors))
    checks = manifest["checks"]
    if args.only:
        unknown = sorted(set(args.only) - {c["id"] for c in checks})
        if unknown:
            raise UsageError(f"--only names unknown check ids: {unknown}")
        checks = [c for c in checks if c["id"] in args.only]
    if args.validate_only:
        print(f"{manifest_path.name}: valid, {len(manifest['checks'])} checks")
        return 0

    base = manifest_path.parent
    if getattr(args, "refresh_reference", None):
        return refresh_reference(manifest, args.refresh_reference, base)
    ratchet = {"violations": [], "approved": [], "added": [], "removed_allowed": []}
    if args.baseline_ref:
        ratchet = rm.ratchet(manifest, load_baseline(manifest_path, args.baseline_ref), BENCHMARKS, args.allow_removed or [])
        for item in ratchet["approved"]:
            print(f"APPROVED RELAXATION [{item['id']}]: {item['problem']} -- {item['approved_relaxation']}")
        for item in ratchet["violations"]:
            print(f"RATCHET VIOLATION [{item['id']}]: {item['problem']} ({item['detail']})", file=sys.stderr)

    outcomes = []
    for check in checks:
        outcomes.append(run_one_check(check, base, args))
    codes = [o["exit_status"] for o in outcomes] + ([3] if ratchet["violations"] else [])
    final = max(codes) if codes else 0
    print("\n| Check | Exit | Verdict |\n|---|:---:|---|")
    for o in outcomes:
        verdict = {0: "PASS", 1: "FAIL", 2: "NOT CHECKED", 3: "WITHHELD"}.get(o["exit_status"], "?")
        print(f"| `{o['id']}` | {o['exit_status']} | {verdict} |")
    print(f"\n{sum(1 for o in outcomes if o['exit_status'] == 0)} of {len(outcomes)} checks passed"
          + (f"; {len(ratchet['violations'])} ratchet violation(s)" if ratchet["violations"] else ""))
    if args.json:
        Path(args.json).write_text(json.dumps({"checks": outcomes, "ratchet": ratchet, "exit_status": final}, indent=2))
    return final


def load_baseline(manifest_path: Path, ref: str) -> Optional[Dict[str, Any]]:
    """The manifest as committed at `ref`, or None if it did not exist there. Unreadable refs are a usage error."""
    folder = manifest_path.parent

    def git(*cmd: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(folder), *cmd], capture_output=True, text=True, timeout=60)
    if git("rev-parse", "--verify", f"{ref}^{{commit}}").returncode != 0:
        raise UsageError(f"--baseline-ref {ref!r} is not a commit in this repository, so the ratchet cannot be checked")
    prefix = git("rev-parse", "--show-prefix").stdout.strip()
    spec = f"{ref}:{prefix}{manifest_path.name}"
    if git("cat-file", "-e", spec).returncode != 0:
        print(f"note: no {manifest_path.name} at {ref}: new manifest, ratchet skipped")
        return None
    shown = git("show", spec)
    try:
        return json.loads(shown.stdout)
    except ValueError:
        raise UsageError(f"the manifest at {ref} is not valid JSON")


def _approval_entry(check: Dict[str, Any], base: Path, args, new_tolerance: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One tolerance-approvals entry for a manifest approved_relaxation, or None if nothing is withheld yet."""
    reason = (check.get("approved_relaxation") or "").strip()
    if not reason:
        return None
    log = ve.log_path(str(args.evidence_dir or base / ".verification"))
    records, _problems = ve.read_log(log)
    key = f"manifest:{check['id']}"
    previous = next((r for r in reversed(records)
                     if r.get("key") == key and r.get("exit_status") != ve.EXIT_WITHHELD), None)
    if previous is None or previous.get("passed") is not False or not isinstance(previous.get("_line"), str):
        return None
    return {"key": key, "prev": previous["_line"], "old_tolerance": previous.get("tolerance") or {},
            "new_tolerance": new_tolerance, "reason": "approved relaxation: " + reason}


def _planned_run_tolerance(check: Dict[str, Any]) -> Dict[str, Any]:
    """The tolerance dict the child `run` records, including the default repeat of 2."""
    bench = BENCHMARKS[check["benchmark"]]
    namespace = argparse.Namespace(
        repeat=2 if check.get("repeat") is None else int(check["repeat"]),
        repeat_tol=0.0 if check.get("repeat_tol") is None else float(check["repeat_tol"]),
        order=None if check.get("order") is None else float(check["order"]),
        levels=check.get("levels"),
    )
    requested = None if check.get("tol") is None else float(check["tol"])
    tol, _relaxed = resolve_tolerance(bench, requested)
    return run_tolerance(bench, tol, namespace)


def run_built_compare(check: Dict[str, Any], base: Path, args) -> Dict[str, Any]:
    """A manifest compare check whose reference and/or test output is PRODUCED by running programs (see reference_build.py).

    Evidence is bound to the pinned sources and inputs (stable repo-relative paths, so the withheld-verdict rule works) and to
    the committed reference file. The rebuilt reference is what is compared; the committed one must reproduce it."""
    inner = check["compare"]
    ref_spec, test_spec = inner.get("ref_from"), inner.get("test_from")
    rtol, atol = float(inner["rtol"]), float(inner["atol"])
    result: Dict[str, Any] = {"mode": "compare", "checker_version": CHECKER_VERSION, "passed": False, "rtol": rtol, "atol": atol,
                              "built": {}}
    try:
        committed = load_values(str(base / inner["ref"]))
        reference = committed
        if ref_spec:
            rebuilt, info = rb.produce(ref_spec, base, load_values)
            reproduced = rb.reproduction(committed, rebuilt, float(ref_spec["reproduce_rtol"]), float(ref_spec["reproduce_atol"]))
            result["built"]["reference"] = dict(info, reproduction=reproduced)
            if not reproduced["reproduces"]:
                raise rb.BuildFailure("the committed reference does not reproduce from its sources: " + str(reproduced["reason"])
                                      + " (if the legacy code or inputs changed on purpose, review the new numbers and run "
                                        "`run-manifest --refresh-reference ID`)")
            reference = rebuilt
        if test_spec:
            test_values, info = rb.produce(test_spec, base, load_values)
            result["built"]["test"] = info
        else:
            test_values = load_values(str(base / inner["test"]))
        comparison = compare_values(reference, test_values, rtol, atol)
        result.update({k: v for k, v in comparison.items() if k not in ("mode", "checker_version")})
    except rb.BuildFailure as exc:
        result["reason"] = str(exc)
    subjects = [str(base / inner["ref"])]
    if not test_spec:
        subjects.append(str(base / inner["test"]))
    for spec in (ref_spec, test_spec):
        if spec:
            subjects += [str(base / rel) for rel in spec["pinned"]]
    tolerance: Dict[str, Any] = {"rtol": rtol, "atol": atol, "ref_from_min": 1 if ref_spec else 0}
    if ref_spec:
        tolerance.update(reproduce_rtol=float(ref_spec["reproduce_rtol"]), reproduce_atol=float(ref_spec["reproduce_atol"]))
    evidence = None
    if not args.no_evidence:
        entry = _approval_entry(check, base, args, tolerance)
        ns = argparse.Namespace(no_evidence=False, evidence_dir=str(args.evidence_dir or base / ".verification"),
                                justify=None, tolerance_approval=None, approvals=[entry] if entry else None,
                                subject=None, check_id=check["id"])
        evidence = ve.record_cli(ns, tool=TOOL, plugin=PLUGIN_NAME, kind="compare", name="compare", key="compare:" + check["id"],
                                 passed=result["passed"], tolerance=tolerance, subject_paths=list(dict.fromkeys(subjects)),
                                 detail={"built": result["built"], "reason": result.get("reason"),
                                         "checker_version": CHECKER_VERSION, "runtime": ve.pin_runtime_env()})
    result["evidence"] = evidence
    return {"id": check["id"], "exit_status": ve.finish("check_against_reference", result["passed"], evidence),
            "stderr": result.get("reason", "") or "", "passed": result["passed"], "result": result}


def refresh_reference(manifest: Dict[str, Any], check_id: str, base: Path) -> int:
    """Rewrite the committed reference file of one check from its recipe. A deliberate act: the result is a diff to review."""
    check = next((c for c in manifest["checks"] if c["id"] == check_id), None)
    if check is None or "compare" not in check or "ref_from" not in check["compare"]:
        raise UsageError(f"--refresh-reference {check_id!r}: no compare check with that id has a ref_from recipe")
    inner = check["compare"]
    try:
        old = load_values(str(base / inner["ref"])) if (base / inner["ref"]).exists() else []
        rebuilt, info = rb.produce(inner["ref_from"], base, load_values)
    except rb.BuildFailure as exc:
        print(f"check_against_reference: cannot rebuild the reference: {exc}", file=sys.stderr)
        return 1
    target = base / inner["ref"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(repr(v) for v in rebuilt) + "\n")
    if old and len(old) == len(rebuilt):
        worst = max(abs(a - b) / (1.0 + abs(b)) for a, b in zip(old, rebuilt))
        print(f"{inner['ref']}: {len(rebuilt)} values rewritten; largest change vs the previous file {worst:.3e} (relative to 1 + |value|)")
    else:
        print(f"{inner['ref']}: {len(rebuilt)} values written (the previous file had {len(old)})")
    for line in info.get("versions", []):
        print(f"built with: {line}")
    print("Review `git diff`: the reference changed, so the manifest check must be re-run and the change approved by a person.")
    return 0


def run_one_check(check: Dict[str, Any], base: Path, args) -> Dict[str, Any]:
    """Run one manifest check in a fresh interpreter (no shared state, own timeout handling)."""
    if "compare" in check and ("ref_from" in check["compare"] or "test_from" in check["compare"]):
        try:
            return run_built_compare(check, base, args)
        except rb.BuildUnavailable as exc:
            return {"id": check["id"], "exit_status": 2, "stderr": str(exc), "passed": False, "result": None}
        except UsageError as exc:
            return {"id": check["id"], "exit_status": 2, "stderr": str(exc), "passed": False, "result": None}
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.json"
        common = ["--json", str(out), "--check-id", check["id"], "--evidence-dir", str(args.evidence_dir or base / ".verification")]
        if args.no_evidence:
            common.append("--no-evidence")
        if "compare" in check:
            inner = check["compare"]
            cmd = ["compare", "--ref", str(base / inner["ref"]), "--test", str(base / inner["test"]),
                   "--rtol", repr(float(inner["rtol"])), "--atol", repr(float(inner["atol"])), *common]
        else:
            path, _, func = check["solver"].rpartition(":")
            cmd = ["run", check["benchmark"], "--solver", f"{base / path}:{func}", *common]
            if check.get("tol") is not None:
                cmd += ["--tol", repr(float(check["tol"]))]
            if check.get("points") is not None:
                cmd += ["--points", str(check["points"])]
            for key in ("order", "steps", "levels"):
                if check.get(key) is not None:
                    cmd += [f"--{key}", repr(float(check[key])) if key == "order" else str(check[key])]
            if check.get("repeat") is not None:
                cmd += ["--repeat", str(check["repeat"])]
            if check.get("repeat_tol") is not None:
                cmd += ["--repeat-tol", repr(float(check["repeat_tol"]))]
            if check.get("timeout_s") is not None:
                cmd += ["--timeout-s", str(check["timeout_s"])]
        if check.get("approved_relaxation"):
            if "compare" in check:
                inner = check["compare"]
                new_tolerance = {"rtol": float(inner["rtol"]), "atol": float(inner["atol"])}
            else:
                new_tolerance = _planned_run_tolerance(check)
            entry = _approval_entry(check, base, args, new_tolerance)
            if entry:
                approval_path = Path(tmp) / "tolerance-approvals.json"
                approval_path.write_text(json.dumps({"schema": ve.APPROVAL_SCHEMA, "approvals": [entry]}))
                cmd += ["--tolerance-approval", str(approval_path)]
        done = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), *cmd], capture_output=True, text=True,
                              cwd=base)
        result = json.loads(out.read_text()) if out.exists() else None
    return {"id": check["id"], "exit_status": done.returncode, "stderr": done.stderr.strip()[-500:],
            "passed": bool(result and result.get("passed")), "result": result}


def run_tolerance(bench: Benchmark, tol: float, args) -> Dict[str, Any]:
    """The tolerance entry recorded in the evidence. Keys ending in _min are minimums (smaller = looser)."""
    entry: Dict[str, Any] = {"tol": tol, "default": bench.default_tol, "repeat_min": args.repeat,
                             "repeat_tol": args.repeat_tol}
    if bench.kind == "convergence":
        # the margin is folded into order_min (the minimum observed order), so it is not compared on its own
        entry.pop("tol")
        entry.pop("default")
        entry["order_min"] = args.order - tol
        entry["levels_min"] = 5 if args.levels is None else args.levels
    return entry


def evidence_command(args) -> int:
    return ve.evidence_command(args.action, args.evidence_dir, args.last, args.subject, args.name, args.kind)


# --------------------------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list", help="show every benchmark's solver contract, reference and tolerance rules")
    run = sub.add_parser("run", help="run your solver on a benchmark")
    run.add_argument("benchmark", choices=sorted(BENCHMARKS))
    run.add_argument("--solver", required=True, help="'module:func' or 'path/file.py:func'")
    run.add_argument("--tol", type=float, help="tolerance (required unless the benchmark has a default)")
    run.add_argument("--points", type=int, default=201, help="sod: number of x points handed to the solver (default 201)")
    run.add_argument("--timeout-s", type=int, default=120, help="per solver call (default 120; 0 = no limit)")
    run.add_argument("--order", type=float, help="convergence benchmarks: the order of accuracy you claim (required there)")
    run.add_argument("--steps", type=int, help="convergence benchmarks: base resolution N (default 16 for ode, 8 for bvp)")
    run.add_argument("--levels", type=int, help="convergence benchmarks: number of resolutions N, 2N, 4N, ... (3-8, default 5)")
    run.add_argument("--repeat", type=int, default=2,
                     help="call the solver this many times on each input and require the same answer (1-10; default 2)")
    run.add_argument("--repeat-tol", type=float, default=0.0,
                     help="allowed difference between repeated answers, relative to 1 + |value| (default 0: identical)")
    run.add_argument("--json", help="write the full result as JSON")
    run.add_argument("--report", help="write a Markdown report")
    ve.add_cli_options(run)
    cmp_ = sub.add_parser("compare", help="compare your output with golden data you supply")
    cmp_.add_argument("--ref", required=True, help="golden values (text or .npy)")
    cmp_.add_argument("--test", required=True, help="your values for the same inputs (text or .npy)")
    cmp_.add_argument("--rtol", type=float, required=True, help="relative tolerance (no default: state it)")
    cmp_.add_argument("--atol", type=float, required=True, help="absolute tolerance (no default: state it)")
    cmp_.add_argument("--json", help="write the result as JSON")
    ve.add_cli_options(cmp_)
    for name, help_text in (("run-manifest", "run every check in reference-checks.json"),
                            ("check-manifest", "validate reference-checks.json without running anything")):
        man = sub.add_parser(name, help=help_text)
        man.add_argument("--manifest", default="reference-checks.json")
        man.add_argument("--only", action="append", help="run only this check id (repeatable)")
        man.add_argument("--baseline-ref", help="git ref (e.g. origin/main) whose manifest the current one must not weaken")
        man.add_argument("--allow-removed", action="append", help="check id that may be deleted on purpose (repeatable)")
        man.add_argument("--evidence-dir", help="evidence log directory (default <manifest dir>/.verification)")
        man.add_argument("--no-evidence", action="store_true")
        man.add_argument("--refresh-reference", metavar="ID",
                         help="rewrite the committed reference file of this compare check from its ref_from recipe, then stop")
        man.add_argument("--json", help="write the summary as JSON")
        man.set_defaults(validate_only=name == "check-manifest")
    ev = sub.add_parser("evidence", help="inspect the evidence log")
    ev.add_argument("action", choices=("verify", "show", "fresh"))
    ev.add_argument("--evidence-dir")
    ev.add_argument("--last", type=int, default=10, help="show: number of records (default 10)")
    ev.add_argument("--subject", help="fresh: the solver or output file to look up")
    ev.add_argument("--name", help="fresh: restrict to this benchmark name")
    ev.add_argument("--kind", help="fresh: restrict to this kind (benchmark, compare, tests, ratchet)")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    fresh_bytecode_cache()
    ve.pin_runtime_env()
    try:
        if args.command == "list":
            print(json.dumps([b.describe() for b in BENCHMARKS.values()], indent=2))
            return 0
        if args.command == "run":
            bench = BENCHMARKS[args.benchmark]
            if bench.kind != "convergence" and any(v is not None for v in (args.order, args.steps, args.levels)):
                raise UsageError("--order, --steps and --levels apply to the convergence benchmarks only")
            if not 1 <= args.repeat <= 10:
                raise UsageError("--repeat must be between 1 and 10")
            if not (args.repeat_tol >= 0.0 and math.isfinite(args.repeat_tol)):
                raise UsageError("--repeat-tol must be a finite number >= 0")
            tol, relaxed = resolve_tolerance(bench, args.tol)
            solver = load_callable(args.solver)
            result = run_benchmark(bench, solver, tol, relaxed, args)
            evidence = None
            if not args.no_evidence:
                source = solver_source_file(solver)
                failed = [c for c in result["cases"] if not c["passed"]]
                worst = max((v for c in result["cases"] for v in c.get("errors", {}).values()), default=None)
                subject_key = ve.subject(source, ve.log_path(args.evidence_dir).parent.parent)["path"]
                evidence = ve.record_cli(
                    args, tool=TOOL, plugin=PLUGIN_NAME, kind="benchmark", name=bench.name, key=f"benchmark:{bench.name}:{subject_key}",
                    passed=result["passed"], subject_paths=[source],
                    tolerance=run_tolerance(bench, tol, args),
                    detail={"cases": len(result["cases"]), "failed_cases": len(failed), "largest_error": worst,
                            "relaxed": relaxed, "checker_version": CHECKER_VERSION, "runtime": ve.pin_runtime_env()})
            result["evidence"] = evidence
            report = format_report(result)
            print(report)
            if args.report:
                Path(args.report).write_text(report)
            if args.json:
                Path(args.json).write_text(json.dumps(result, indent=2))
            return ve.finish("check_against_reference", result["passed"], evidence)
        if args.command == "compare":
            if not (args.rtol >= 0 and args.atol >= 0 and (args.rtol > 0 or args.atol > 0)):
                raise UsageError("--rtol and --atol must be non-negative and not both zero")
            result = compare_values(load_values(args.ref), load_values(args.test), args.rtol, args.atol)
            evidence = None
            if not args.no_evidence:
                base = ve.log_path(args.evidence_dir).parent.parent
                key = "compare:" + "|".join(ve.subject(p, base)["path"] for p in (args.ref, args.test))
                evidence = ve.record_cli(
                    args, tool=TOOL, plugin=PLUGIN_NAME, kind="compare", name="compare", key=key, passed=result["passed"],
                    subject_paths=[args.ref, args.test], tolerance={"rtol": args.rtol, "atol": args.atol},
                    detail={"n_ref": result["n_ref"], "n_test": result["n_test"],
                            "worst_error_over_allowed": result.get("worst_error_over_allowed"),
                            "checker_version": CHECKER_VERSION, "runtime": ve.pin_runtime_env()})
            result["evidence"] = evidence
            print(json.dumps(result, indent=2))
            if args.json:
                Path(args.json).write_text(json.dumps(result, indent=2))
            return ve.finish("check_against_reference", result["passed"], evidence)
        if args.command in ("run-manifest", "check-manifest"):
            return run_manifest_command(args)
        if args.command == "evidence":
            return evidence_command(args)
        parser.print_help(sys.stderr)
        print("\ncheck_against_reference: choose a command (nothing was checked).", file=sys.stderr)
        return 2
    except UsageError as exc:
        print(f"check_against_reference: {exc} (nothing was checked)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
