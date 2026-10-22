r"""
Exact Riemann Solver for 1D Compressible Euler Equations (Sod Shock Tube).

Governing Equations:
====================
\begin{equation}
    \frac{\partial \mathbf{U}}{\partial t} + \frac{\partial \mathbf{F}(\mathbf{U})}{\partial x} = \mathbf{0}
\end{equation}
where:
\begin{equation}
    \mathbf{U} = \begin{bmatrix} \rho \\ \rho u \\ E \end{bmatrix}, \quad
    \mathbf{F}(\mathbf{U}) = \begin{bmatrix} \rho u \\ \rho u^2 + p \\ u(E + p) \end{bmatrix}
\end{equation}
Equation of state for ideal gas:
\begin{equation}
    p = (\gamma - 1)\left( E - \frac{1}{2}\rho u^2 \right)
\end{equation}

Sod Shock Tube Initial State:
=============================
- Left state:  $\rho_L = 1.0, u_L = 0.0, p_L = 1.0$
- Right state: $\rho_R = 0.125, u_R = 0.0, p_R = 0.1$
- Adiabatic index: $\gamma = 1.4$
- Discontinuity at $x_0 = 0.5$ in domain $[0, 1]$.

Reference:
==========
Toro, E. F. (2009). "Riemann Solvers and Numerical Methods for Fluid Dynamics",
3rd ed., Springer, Chapter 4: Exact Riemann Solvers.
"""

from __future__ import annotations
import math
from typing import Tuple, Dict, Any, List


def exact_riemann_solver(
    rho_L: float = 1.0, u_L: float = 0.0, p_L: float = 1.0,
    rho_R: float = 0.125, u_R: float = 0.0, p_R: float = 0.1,
    gamma: float = 1.4,
    x_diaphragm: float = 0.5,
    t_target: float = 0.2,
    num_points: int = 100,
) -> Dict[str, Any]:
    r"""
    Solve exact Riemann problem across the star region using Newton-Raphson on p_star.
    """
    g1 = (gamma - 1.0) / (2.0 * gamma)
    g2 = (gamma + 1.0) / (2.0 * gamma)
    g3 = 2.0 * gamma / (gamma - 1.0)
    g4 = 2.0 / (gamma - 1.0)
    g5 = 2.0 / (gamma + 1.0)
    g6 = (gamma - 1.0) / (gamma + 1.0)

    c_L = math.sqrt(gamma * p_L / rho_L)
    c_R = math.sqrt(gamma * p_R / rho_R)

    # Check for vacuum generation
    if g4 * (c_L + c_R) <= (u_R - u_L):
        raise ValueError("Initial states produce vacuum: exact solver requires modification.")

    def f_k(p: float, p_k: float, rho_k: float, c_k: float) -> Tuple[float, float]:
        if p <= p_k:
            # Rarefaction wave
            ratio = p / p_k
            f = g4 * c_k * (ratio ** g1 - 1.0)
            f_prime = (1.0 / (rho_k * c_k)) * (ratio ** (-g2))
        else:
            # Shock wave
            A_k = g5 / rho_k
            B_k = g6 * p_k
            diff = p - p_k
            denom = math.sqrt(A_k / (p + B_k))
            f = diff * denom
            f_prime = (1.0 - 0.5 * diff / (p + B_k)) * denom
        return f, f_prime

    # Initial guess via Two-Rarefaction approximation (Toro 2009)
    p_pv = max(1e-6, 0.5 * (p_L + p_R) - 0.125 * (u_R - u_L) * (rho_L + rho_R) * (c_L + c_R))
    p_star = p_pv

    # Newton-Raphson iteration for pressure in star region
    tol = 1e-12
    max_iter = 100
    for _ in range(max_iter):
        f_L_val, f_L_prime = f_k(p_star, p_L, rho_L, c_L)
        f_R_val, f_R_prime = f_k(p_star, p_R, rho_R, c_R)

        phi = f_L_val + f_R_val + (u_R - u_L)
        phi_prime = f_L_prime + f_R_prime

        dp = -phi / phi_prime
        p_star += dp
        if abs(dp) / max(p_star, 1e-6) < tol:
            break
        p_star = max(p_star, 1e-10)

    # Velocity in star region
    u_star = 0.5 * (u_L + u_R) + 0.5 * (f_R_val - f_L_val)

    # Sample solution along spatial domain [0, 1]
    xs = [i / (num_points - 1) for i in range(num_points)]
    densities = []
    velocities = []
    pressures = []

    for x in xs:
        s = (x - x_diaphragm) / t_target

        if s <= u_star:
            # Left of contact discontinuity
            if p_star <= p_L:
                # Left rarefaction
                s_head = u_L - c_L
                c_star_L = c_L * (p_star / p_L) ** g1
                s_tail = u_star - c_star_L

                if s <= s_head:
                    rho, u, p = rho_L, u_L, p_L
                elif s >= s_tail:
                    rho = rho_L * (p_star / p_L) ** (1.0 / gamma)
                    u = u_star
                    p = p_star
                else:
                    u = g5 * (c_L + 0.5 * (gamma - 1.0) * u_L + s)
                    c = g5 * (c_L + 0.5 * (gamma - 1.0) * (u_L - s))
                    rho = rho_L * (c / c_L) ** g4
                    p = p_L * (c / c_L) ** g3
            else:
                # Left shock
                s_shock = u_L - c_L * math.sqrt(g2 * (p_star / p_L) + g1)
                if s <= s_shock:
                    rho, u, p = rho_L, u_L, p_L
                else:
                    rho = rho_L * ((p_star / p_L) + g6) / ((p_star / p_L) * g6 + 1.0)
                    u = u_star
                    p = p_star
        else:
            # Right of contact discontinuity
            if p_star > p_R:
                # Right shock
                s_shock = u_R + c_R * math.sqrt(g2 * (p_star / p_R) + g1)
                if s >= s_shock:
                    rho, u, p = rho_R, u_R, p_R
                else:
                    rho = rho_R * ((p_star / p_R) + g6) / ((p_star / p_R) * g6 + 1.0)
                    u = u_star
                    p = p_star
            else:
                # Right rarefaction
                s_head = u_R + c_R
                c_star_R = c_R * (p_star / p_R) ** g1
                s_tail = u_star + c_star_R

                if s >= s_head:
                    rho, u, p = rho_R, u_R, p_R
                elif s <= s_tail:
                    rho = rho_R * (p_star / p_R) ** (1.0 / gamma)
                    u = u_star
                    p = p_star
                else:
                    u = g5 * (-c_R + 0.5 * (gamma - 1.0) * u_R + s)
                    c = g5 * (c_R - 0.5 * (gamma - 1.0) * (u_R - s))
                    rho = rho_R * (c / c_R) ** g4
                    p = p_R * (c / c_R) ** g3

        densities.append(rho)
        velocities.append(u)
        pressures.append(p)

    return {
        "p_star": p_star,
        "u_star": u_star,
        "x": xs,
        "density": densities,
        "velocity": velocities,
        "pressure": pressures,
    }


if __name__ == "__main__":
    sol = exact_riemann_solver(t_target=0.2, num_points=101)
    print("Exact 1D Euler Riemann Solver (Sod Shock Tube Benchmark):")
    print(f"  Star Region Pressure: {sol['p_star']:.6f} (expected ~ 0.303130)")
    print(f"  Star Region Velocity: {sol['u_star']:.6f} (expected ~ 0.927453)")
    assert abs(sol["p_star"] - 0.303130) < 1e-4, "Exact Riemann pressure deviated from standard Sod benchmark!"
    assert abs(sol["u_star"] - 0.927453) < 1e-4, "Exact Riemann velocity deviated from standard Sod benchmark!"
    print("  [PASS] Exact shock tube solution verified against canonical Toro (2009) benchmark.")
