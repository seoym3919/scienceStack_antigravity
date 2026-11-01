r"""
What a tolerance means for the `sod` benchmark.

The `sod` benchmark has no default tolerance, because the error is set by the solver's own discretisation. This script gives
the numbers to judge one by: the relative L1 error of

  (a) the exact solution with the diaphragm displaced by one cell of 100, so a shock-capturing error of a single cell;
  (b) a first-order Godunov scheme with the HLL flux on 100, 200, 400 and 800 cells, sampled at the benchmark's 201 points.

The first-order scheme is written out here so that the table can be regenerated:

    python3 benchmarks/cfd/sod_calibration.py [cells ...]

Errors are measured by the checker's own sod_check. HLL flux: Harten, Lax & van Leer (1983), SIAM Review 25, 35-61; wave speed
bounds from Davis (1988), SIAM J. Sci. Stat. Comput. 9, 445-473 (S_L = min(u_L - c_L, u_R - c_R), S_R = max(u_L + c_L, u_R + c_R)).
Ideal gas, gamma = 1.4, CFL 0.8, transmissive ends (the waves do not reach them by t = 0.2).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import check_against_reference as car  # noqa: E402

GAMMA = 1.4
CFL = 0.8
POINTS = [i / 200 for i in range(201)]


def primitive(U: np.ndarray):
    rho = U[0]
    velocity = U[1] / rho
    return rho, velocity, (GAMMA - 1.0) * (U[2] - 0.5 * rho * velocity * velocity)


def flux(U: np.ndarray) -> np.ndarray:
    rho, velocity, pressure = primitive(U)
    return np.array([rho * velocity, rho * velocity * velocity + pressure, velocity * (U[2] + pressure)])


def godunov_hll(cells: int, x: Sequence[float], t_end: float = 0.2) -> Dict[str, List[float]]:
    dx = 1.0 / cells
    centres = (np.arange(cells) + 0.5) * dx
    rho = np.where(centres < 0.5, 1.0, 0.125)
    pressure = np.where(centres < 0.5, 1.0, 0.1)
    U = np.array([rho, np.zeros(cells), pressure / (GAMMA - 1.0)])
    t = 0.0
    while t < t_end:
        rho, velocity, pressure = primitive(U)
        sound = np.sqrt(GAMMA * pressure / rho)
        dt = min(CFL * dx / np.max(np.abs(velocity) + sound), t_end - t)
        left, right = U[:, :-1], U[:, 1:]
        S_L = np.minimum(velocity[:-1] - sound[:-1], velocity[1:] - sound[1:])
        S_R = np.maximum(velocity[:-1] + sound[:-1], velocity[1:] + sound[1:])
        F_L, F_R = flux(left), flux(right)
        F = np.where(S_L >= 0.0, F_L, np.where(S_R <= 0.0, F_R, (S_R * F_L - S_L * F_R + S_L * S_R * (right - left)) / (S_R - S_L)))
        U[:, 1:-1] -= dt / dx * (F[:, 1:] - F[:, :-1])
        t += dt
    rho, velocity, pressure = primitive(U)
    return {"density": list(np.interp(x, centres, rho)), "velocity": list(np.interp(x, centres, velocity)),
            "pressure": list(np.interp(x, centres, pressure))}


def displaced_exact(x: Sequence[float], shift: float = 0.01, t_end: float = 0.2) -> Dict[str, List[float]]:
    solver = car._exact_riemann()
    state = dict(car.SOD_STATE)
    out: Dict[str, List[float]] = {"density": [], "velocity": [], "pressure": []}
    for xi in x:
        state["x_diaphragm"] = car.SOD_STATE["x_diaphragm"] + shift - xi
        sample = solver(**state, t_target=t_end, num_points=2)
        for key in out:
            out[key].append(sample[key][0])
    return out


def errors(answer: Dict[str, List[float]]) -> Dict[str, float]:
    case = {"x": POINTS}
    return car.sod_check(case, answer, 1.0)[1]


def table(cells: Sequence[int] = (100, 200, 400, 800)) -> List[tuple]:
    rows = [("exact, diaphragm moved by 0.01", errors(displaced_exact(POINTS)))]
    rows += [(f"first-order HLL, {n} cells", errors(godunov_hll(n, POINTS))) for n in cells]
    return rows


def main() -> int:
    cells = [int(a) for a in sys.argv[1:]] or [100, 200, 400, 800]
    print("| Solution | rel. L1 density | rel. L1 velocity | rel. L1 pressure |")
    print("|---|:---:|:---:|:---:|")
    for name, e in table(cells):
        print(f"| {name} | {e['rel_L1_density']:.2e} | {e['rel_L1_velocity']:.2e} | {e['rel_L1_pressure']:.2e} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
