#!/usr/bin/env python3
r"""
engineering_references.py - reference data and judgements for the engineering benchmarks of check_against_reference.py.

    beam-timoshenko        cantilever tip deflection under an end load, with the shear correction
    linear-solve-hilbert   backward error of a linear solver on Hilbert matrices, with the exact condition number
    cavity-ghia            lid-driven cavity centreline velocity, Ghia, Ghia & Shin (1982), Table I

Standard library only. Every number here is a closed form evaluated at run time, except GHIA_U, which is a transcription: see
its comment for how it was checked. A value that could not be sourced is not in this file.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Any, Dict, List, Sequence, Tuple


class ReferenceFailure(Exception):
    """The answer cannot be judged (wrong shape, not finite)."""


def finite_vector(values: Any, size: int, what: str) -> List[float]:
    if hasattr(values, "tolist"):
        values = values.tolist()
    if not isinstance(values, (list, tuple)) or len(values) != size:
        raise ReferenceFailure(f"{what} must hold {size} numbers")
    out = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ReferenceFailure(f"{what} holds {value!r}, not a finite number")
        out.append(float(value))
    return out


# --------------------------------------------------------------------------------------------------------------
# Timoshenko cantilever
# --------------------------------------------------------------------------------------------------------------

STEEL_E = 200.0e9                       # Pa
STEEL_G = STEEL_E / (2.0 * (1.0 + 0.3))  # Pa; isotropic G = E / (2 (1 + nu)) with nu = 0.3
RECTANGLE_KAPPA = 5.0 / 6.0             # the usual shear coefficient of a rectangular section


def rectangle(name: str, length: float, width: float, height: float, load: float) -> Dict[str, Any]:
    return {"name": name, "L": length, "E": STEEL_E, "G": STEEL_G, "I": width * height ** 3 / 12.0, "A": width * height,
            "kappa": RECTANGLE_KAPPA, "P": load}


BEAM_CASES = (rectangle("steel section", 1.0, 0.05, 0.10, 1000.0),
              rectangle("slender, Euler-Bernoulli limit", 10.0, 0.01, 0.01, 1.0),   # shear term 7.8e-7 of the bending term
              rectangle("short and deep", 1.0, 0.10, 0.50, 5.0e5))                  # shear term 19.5 % of the bending term


def beam_tip_deflection(L: float, E: float, G: float, I: float, A: float, kappa: float, P: float) -> float:
    r"""\delta = P L^3 / (3 E I) + P L / (\kappa G A): bending, plus the rotation of the section under the shear force P."""
    return P * L ** 3 / (3.0 * E * I) + P * L / (kappa * G * A)


# --------------------------------------------------------------------------------------------------------------
# Hilbert matrices
# --------------------------------------------------------------------------------------------------------------

HILBERT_SIZES = tuple(range(3, 13))


def hilbert(n: int) -> List[List[float]]:
    return [[1.0 / (i + j + 1) for j in range(n)] for i in range(n)]


def hilbert_solution(n: int) -> List[float]:
    """Alternating and non-constant, so that a solver cannot pass by returning a guessed vector."""
    return [(-1.0) ** i * (1.0 + i / n) for i in range(n)]


def hilbert_inverse_entry(n: int, i: int, j: int) -> int:
    """(H_n^-1)_ij for 1-based i, j: an integer, by the closed form of Choi (1983), Amer. Math. Monthly 90, 301-312."""
    return ((-1) ** (i + j) * (i + j - 1) * math.comb(n + i - 1, n - j) * math.comb(n + j - 1, n - i)
            * math.comb(i + j - 2, i - 1) ** 2)


def hilbert_condition_inf(n: int) -> float:
    r"""\kappa_\infty(H_n), exactly: the largest row sum of H_n times that of its inverse."""
    norm = max(sum(Fraction(1, i + j - 1) for j in range(1, n + 1)) for i in range(1, n + 1))
    inverse_norm = max(sum(abs(hilbert_inverse_entry(n, i, j)) for j in range(1, n + 1)) for i in range(1, n + 1))
    return float(norm * inverse_norm)


def linear_errors(A: Sequence[Sequence[float]], b: Sequence[float], x: Sequence[float], truth: Sequence[float]) -> Tuple[float, float]:
    r"""(\|A x - b\|_2 / \|b\|_2, \|x - x_true\|_\infty / \|x_true\|_\infty)."""
    residual = [math.fsum([*(a * v for a, v in zip(row, x)), -bi]) for row, bi in zip(A, b)]
    return math.hypot(*residual) / math.hypot(*b), max(abs(v - t) for v, t in zip(x, truth)) / max(abs(t) for t in truth)


# --------------------------------------------------------------------------------------------------------------
# Lid-driven cavity
# --------------------------------------------------------------------------------------------------------------

# Ghia, Ghia & Shin (1982), J. Comput. Phys. 48, 387-411, Table I: u along the vertical line through the centre, (y, Re=100,
# Re=1000). Not read from the paper itself. Taken from two independently kept copies, compared by program, equal in every
# value of these columns: gist ivan-pi/3e9326d18a366ffe6a8e5bfda6353219, and barbagroup/PetIBM
# examples/data/ghia_et_al_1982_lid_driven_cavity.dat.
GHIA_U = ((0.0000, 0.00000, 0.00000), (0.0547, -0.03717, -0.18109), (0.0625, -0.04192, -0.20196), (0.0703, -0.04775, -0.22220),
          (0.1016, -0.06434, -0.29730), (0.1719, -0.10150, -0.38289), (0.2813, -0.15662, -0.27805), (0.4531, -0.21090, -0.10648),
          (0.5000, -0.20581, -0.06080), (0.6172, -0.13641, 0.05702), (0.7344, 0.00332, 0.18719), (0.8516, 0.23151, 0.33304),
          (0.9531, 0.68717, 0.46604), (0.9609, 0.73722, 0.51117), (0.9688, 0.78871, 0.57492), (0.9766, 0.84123, 0.65928),
          (1.0000, 1.00000, 1.00000))
GHIA_COLUMN = {100.0: 1, 1000.0: 2}


def interpolate(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    """Piecewise linear; xs strictly increasing and covering x."""
    low, high = 0, len(xs) - 1
    while high - low > 1:
        middle = (low + high) // 2
        if xs[middle] <= x:
            low = middle
        else:
            high = middle
    weight = (x - xs[low]) / (xs[high] - xs[low])
    return ys[low] + weight * (ys[high] - ys[low])


def cavity_error(reynolds: float, y: Sequence[float], u: Sequence[float]) -> float:
    r"""\sum |u(y_k) - u_k| / \sum |u_k| over the 17 points of the table, with u interpolated linearly in the solver's y."""
    if any(y[k + 1] <= y[k] for k in range(len(y) - 1)):
        raise ReferenceFailure("y must be strictly increasing")
    if y[0] > 0.0 or y[-1] < 1.0:
        raise ReferenceFailure("y must span the centreline, 0 to 1")
    column = GHIA_COLUMN[reynolds]
    difference = math.fsum(abs(interpolate(y, u, row[0]) - row[column]) for row in GHIA_U)
    return difference / math.fsum(abs(row[column]) for row in GHIA_U)
