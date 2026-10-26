#!/usr/bin/env python3
r"""
convergence.py - canonical problems with exact solutions, and the estimate of a solver's order of convergence.

Used by check_against_reference.py (benchmarks `convergence-ode` and `convergence-bvp`). Standard library only.

A solver's observed order is estimated from its error e_k at resolutions N, 2N, 4N, ... (the base N is `--steps`):

    p_k = log(e_k / e_{k+1}) / log 2

Judgement (deterministic, no sampling):
  * Errors at or below the ROUNDOFF FLOOR (1e-11 x max(1, |exact|)) are discarded together with every finer level:
    roundoff accumulated over thousands of steps is ~1e-13, so below 1e-11 the truncation error is no longer what is
    measured. Fewer than three levels above the floor is a FAILURE ("not enough resolved levels") with the advice to use a
    coarser base: a high-order method may need `--steps 4`.
  * The error must fall strictly with refinement over the resolved levels.
  * The two FINEST resolved pairwise orders must each be >= expected order - margin. Coarse levels are allowed to be
    pre-asymptotic; super-convergence (an observed order above the expected one) is never a failure.
  * A solver whose answer has the wrong size, or contains NaN/Inf, fails.

Why a margin: pairwise estimates differ from the asymptotic order by O(h) even for a method of exactly that order, so a
margin of 0 would fail correct solvers. The default margin 0.25 and the smallest accepted 0.05 are the plugin's choice, not
a mathematical constant; the margin used is recorded in the evidence, and a larger one than the default is marked relaxed.

ODE contract:   integrate(f, y0, t0, t1, n_steps) -> y(t1)
                f(t, y) -> dy/dt, with y and the result lists of floats; y0 a list; the result a list (or a float if
                the system has one component).
BVP contract:   solve(n, f) -> [u_0, ..., u_n]  for  -u'' = f(x) on (0, 1), u(0) = u(1) = 0, on the uniform grid x_i = i/n
                (u_0 and u_n are 0).
The error is the maximum norm of the final state (ODE), and both the maximum norm and the discrete L2 norm
sqrt(h * sum e_i^2) of the nodal error (BVP); every norm must meet the requirement.

Exact solutions (all derived by hand, and re-derived independently in the tests):
  decay       y' = -2 y,  y(0) = 1          on [0, 1]    y(1) = exp(-2)
  oscillator  x' = v, v' = -x, (1, 0)       on [0, 2]    (cos 2, -sin 2)
  nonlinear   y' = y^2,   y(0) = 1          on [0, 1/2]  y = 1/(1 - t), y(1/2) = 2
  timedep     y' = 2 t y, y(0) = 1          on [0, 1]    y = exp(t^2), y(1) = e
  poisson-sine  -u'' = pi^2 sin(pi x)       u = sin(pi x)
  poisson-poly  -u'' = 12 x^2 - 6 x         u = x^3 - x^4   (u'' = 6x - 12x^2; u(0) = u(1) = 0)
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

ROUNDOFF_FLOOR = 1e-11
MIN_LEVELS_ABOVE_FLOOR = 3
DEFAULT_MARGIN = 0.25
MIN_MARGIN = 0.05


class ConvergenceFailure(Exception):
    """The solver's answer cannot be used (wrong size, NaN, ...)."""


# --------------------------------------------------------------------------------------------------------------
# Problems
# --------------------------------------------------------------------------------------------------------------

ODE_PROBLEMS: Dict[str, Dict[str, Any]] = {
    "decay": {"f": lambda t, y: [-2.0 * y[0]], "y0": [1.0], "t0": 0.0, "t1": 1.0, "exact": [math.exp(-2.0)]},
    "oscillator": {"f": lambda t, y: [y[1], -y[0]], "y0": [1.0, 0.0], "t0": 0.0, "t1": 2.0,
                   "exact": [math.cos(2.0), -math.sin(2.0)]},
    "nonlinear": {"f": lambda t, y: [y[0] * y[0]], "y0": [1.0], "t0": 0.0, "t1": 0.5, "exact": [2.0]},
    "timedep": {"f": lambda t, y: [2.0 * t * y[0]], "y0": [1.0], "t0": 0.0, "t1": 1.0, "exact": [math.e]},
}

BVP_PROBLEMS: Dict[str, Dict[str, Any]] = {
    "poisson-sine": {"f": lambda x: math.pi ** 2 * math.sin(math.pi * x), "exact": lambda x: math.sin(math.pi * x)},
    "poisson-poly": {"f": lambda x: 12.0 * x * x - 6.0 * x, "exact": lambda x: x ** 3 - x ** 4},
}


def levels(base: int, count: int) -> List[int]:
    """Resolutions base, 2 base, 4 base, ..."""
    return [base * 2 ** k for k in range(count)]


# --------------------------------------------------------------------------------------------------------------
# The order estimate
# --------------------------------------------------------------------------------------------------------------

def observed_orders(errors: Sequence[float]) -> List[float]:
    """Pairwise orders log2(e_k / e_{k+1}) for a refinement ratio of 2."""
    return [math.log(errors[k] / errors[k + 1]) / math.log(2.0) for k in range(len(errors) - 1)]


def assess(errors: Sequence[float], expected: float, margin: float, scale: float = 1.0) -> Dict[str, Any]:
    """Verdict for one error sequence (one problem, one norm). `errors` are for resolutions N, 2N, 4N, ..."""
    floor = ROUNDOFF_FLOOR * max(1.0, scale)
    if not all(math.isfinite(e) and e >= 0.0 for e in errors):
        return {"passed": False, "reason": "an error is not a finite non-negative number", "errors": list(errors),
                "orders": [], "resolved": 0}
    resolved = []
    for e in errors:
        if e <= floor:
            break
        resolved.append(e)
    result: Dict[str, Any] = {"errors": list(errors), "floor": floor, "resolved": len(resolved), "orders": [],
                              "expected": expected, "required": expected - margin}
    if len(resolved) < MIN_LEVELS_ABOVE_FLOOR:
        result.update(passed=False, reason=(f"only {len(resolved)} of {len(errors)} levels are above the roundoff floor "
                                            f"{floor:.0e} (need {MIN_LEVELS_ABOVE_FLOOR}): use a coarser base (--steps) or fewer "
                                            f"levels; a high-order method may need --steps 4"))
        return result
    if any(resolved[k + 1] >= resolved[k] for k in range(len(resolved) - 1)):
        result.update(passed=False, reason="the error does not fall with every refinement")
        return result
    orders = observed_orders(resolved)
    result["orders"] = orders
    finest = orders[-2:]
    result["observed"] = min(finest)
    if min(finest) < expected - margin:
        result.update(passed=False, reason=(f"observed order {min(finest):.3f} at the finest levels is below the required "
                                            f"{expected - margin:.3f} (expected {expected:g}, margin {margin:g})"))
        return result
    result.update(passed=True, reason=None)
    return result


# --------------------------------------------------------------------------------------------------------------
# ODE
# --------------------------------------------------------------------------------------------------------------

def ode_vector(answer: Any, size: int) -> List[float]:
    if hasattr(answer, "tolist"):
        answer = answer.tolist()
    if isinstance(answer, (int, float)) and not isinstance(answer, bool):
        answer = [answer]
    if not isinstance(answer, (list, tuple)) or len(answer) != size:
        raise ConvergenceFailure(f"the integrator must return the final state as a list of {size} number(s)")
    out = []
    for value in answer:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConvergenceFailure(f"state component {value!r} is not a number")
        if not math.isfinite(value):
            raise ConvergenceFailure("the final state contains NaN or Inf")
        out.append(float(value))
    return out


def ode_calls(problem: str, base: int, count: int) -> List[Tuple[Any, ...]]:
    spec = ODE_PROBLEMS[problem]
    return [(spec["f"], list(spec["y0"]), spec["t0"], spec["t1"], n) for n in levels(base, count)]


def ode_errors(problem: str, answers: Sequence[Any]) -> List[float]:
    exact = ODE_PROBLEMS[problem]["exact"]
    return [max(abs(a - e) for a, e in zip(ode_vector(answer, len(exact)), exact)) for answer in answers]


# --------------------------------------------------------------------------------------------------------------
# BVP
# --------------------------------------------------------------------------------------------------------------

def bvp_calls(problem: str, base: int, count: int) -> List[Tuple[Any, ...]]:
    return [(n, BVP_PROBLEMS[problem]["f"]) for n in levels(base, count)]


def bvp_errors(problem: str, answers: Sequence[Any], sizes: Sequence[int]) -> Dict[str, List[float]]:
    exact = BVP_PROBLEMS[problem]["exact"]
    linf: List[float] = []
    l2: List[float] = []
    for answer, n in zip(answers, sizes):
        if hasattr(answer, "tolist"):
            answer = answer.tolist()
        if not isinstance(answer, (list, tuple)) or len(answer) != n + 1:
            raise ConvergenceFailure(f"the solver must return n + 1 = {n + 1} nodal values for n = {n}")
        for value in answer:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ConvergenceFailure(f"nodal value {value!r} is not a finite number")
        diffs = [abs(float(answer[i]) - exact(i / n)) for i in range(n + 1)]
        linf.append(max(diffs))
        l2.append(math.sqrt(sum(d * d for d in diffs) / n))                  # sqrt(h * sum e_i^2) with h = 1/n
    return {"max-norm": linf, "L2-norm": l2}
