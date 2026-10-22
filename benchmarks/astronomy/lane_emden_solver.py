r"""
Lane-Emden Polytropic Stellar Structure Solver.

Governing Differential Equation:
================================
\begin{equation}
    \frac{1}{\xi^2} \frac{d}{d\xi}\left( \xi^2 \frac{d\theta}{d\xi} \right) + \theta^n = 0
\end{equation}
or equivalently in first-order system form:
\begin{align}
    \frac{d\theta}{d\xi} &= u \\
    \frac{du}{d\xi} &= -\theta^n - \frac{2}{\xi} u
\end{align}

Boundary Conditions:
====================
At the stellar center ($\xi = 0$):
\begin{equation}
    \theta(0) = 1, \quad \theta'(0) = 0
\end{equation}

Near-Center Series Expansion (Singularity Removal):
===================================================
\begin{equation}
    \theta(\xi) \approx 1 - \frac{\xi^2}{6} + \frac{n \xi^4}{120} - \frac{n(8n - 5)\xi^6}{15120} + \mathcal{O}(\xi^8)
\end{equation}
\begin{equation}
    \theta'(\xi) \approx -\frac{\xi}{3} + \frac{n \xi^3}{30} - \frac{n(8n - 5)\xi^5}{2520}
\end{equation}

Stellar Structure Parameters:
=============================
- First zero $\xi_1$: Dimensionless stellar surface radius ($\theta(\xi_1) = 0$).
- Dimensionless mass factor: $\omega_n = -\xi_1^2 \theta'(\xi_1)$.
- Ratio of mean density to central density:
  \begin{equation}
      \frac{\bar{\rho}}{\rho_c} = -\frac{3}{\xi_1} \left(\frac{d\theta}{d\xi}\right)_{\xi_1}
  \end{equation}

Exact Analytical Benchmarks:
============================
- $n = 0$: $\theta(\xi) = 1 - \frac{\xi^2}{6}$, $\xi_1 = \sqrt{6} \approx 2.4494897$, $\omega_0 = \frac{2\sqrt{6}}{3} \approx 4.898979$
- $n = 1$: $\theta(\xi) = \frac{\sin\xi}{\xi}$, $\xi_1 = \pi \approx 3.14159265$, $\omega_1 = \pi \approx 3.14159265$
- $n = 5$: $\theta(\xi) = \left(1 + \frac{\xi^2}{3}\right)^{-1/2}$, $\xi_1 \to \infty$ (Plummer sphere)

Reference:
==========
Chandrasekhar, S. (1939). "An Introduction to the Study of Stellar Structure",
University of Chicago Press, Dover Publications, Chapter IV, pp. 84-105.
Hansen, C. J., Kawaler, S. D., & Trimble, V. (2004). "Stellar Interiors", 2nd ed., Springer.
"""

from __future__ import annotations
import math
from typing import Tuple, Dict, Any


def lane_emden_series_start(n: float, xi_0: float = 1e-4) -> Tuple[float, float]:
    r"""Compute (\theta, u = d\theta/d\xi) near center using series expansion to avoid 2/\xi singularity."""
    xi2 = xi_0 * xi_0
    xi3 = xi2 * xi_0
    xi4 = xi2 * xi2
    xi5 = xi4 * xi_0
    xi6 = xi4 * xi2

    theta = 1.0 - xi2 / 6.0 + (n * xi4) / 120.0 - (n * (8.0 * n - 5.0) * xi6) / 15120.0
    u = -xi_0 / 3.0 + (n * xi3) / 30.0 - (n * (8.0 * n - 5.0) * xi5) / 2520.0
    return theta, u


def solve_lane_emden(
    n: float,
    dxi: float = 1e-4,
    xi_max: float = 50.0,
) -> Dict[str, Any]:
    r"""
    Integrate Lane-Emden equation of index n using classical 4th-order Runge-Kutta.

    Parameters:
        n: Polytropic index (0 <= n < 5).
        dxi: Step size for radial integration.
        xi_max: Maximum search boundary for stellar radius.

    Returns:
        Dict containing surface radius xi_1, mass factor omega_n, rho_ratio, and trajectory.
    """
    if n < 0.0 or n >= 5.0:
        raise ValueError(f"Polytropic index must be 0 <= n < 5 for finite stellar radius, got {n}")

    xi_0 = 1e-4
    theta, u = lane_emden_series_start(n, xi_0)
    xi = xi_0

    def derivatives(x: float, th: float, vel: float) -> Tuple[float, float]:
        th_pos = max(th, 0.0)
        dth = vel
        du = - (th_pos ** n) - (2.0 / x) * vel
        return dth, du

    # RK4 integration loop
    while xi < xi_max:
        # Check if surface reached
        if theta <= 0.0:
            break

        k1_th, k1_u = derivatives(xi, theta, u)
        k2_th, k2_u = derivatives(xi + 0.5 * dxi, theta + 0.5 * dxi * k1_th, u + 0.5 * dxi * k1_u)
        k3_th, k3_u = derivatives(xi + 0.5 * dxi, theta + 0.5 * dxi * k2_th, u + 0.5 * dxi * k2_u)
        k4_th, k4_u = derivatives(xi + dxi, theta + dxi * k3_th, u + dxi * k3_u)

        theta_next = theta + (dxi / 6.0) * (k1_th + 2.0 * k2_th + 2.0 * k3_th + k4_th)
        u_next = u + (dxi / 6.0) * (k1_u + 2.0 * k2_u + 2.0 * k3_u + k4_u)
        xi_next = xi + dxi

        if theta_next <= 0.0:
            # Linear/Hermite interpolation to find exact root xi_1 where theta = 0
            fraction = -theta / (theta_next - theta)
            xi_surface = xi + fraction * dxi
            u_surface = u + fraction * (u_next - u)
            xi = xi_surface
            theta = 0.0
            u = u_surface
            break

        theta = theta_next
        u = u_next
        xi = xi_next

    xi_1 = xi
    dtheta_surface = u
    omega_n = - (xi_1 ** 2) * dtheta_surface
    rho_ratio = -(3.0 / xi_1) * dtheta_surface  # rho_mean / rho_central

    return {
        "n": n,
        "xi_1": xi_1,
        "dtheta_surface": dtheta_surface,
        "omega_n": omega_n,
        "rho_ratio": rho_ratio,
    }


def verify_polytrope_against_analytical(n: float, tol: float = 1e-4) -> Dict[str, Any]:
    r"""Audit numerical polytrope solver against exact closed-form solutions for n=0 and n=1."""
    res = solve_lane_emden(n)
    xi_1 = res["xi_1"]
    omega_n = res["omega_n"]

    if abs(n - 0.0) < 1e-9:
        exact_xi_1 = math.sqrt(6.0)
        exact_omega = 2.0 * math.sqrt(6.0)
    elif abs(n - 1.0) < 1e-9:
        exact_xi_1 = math.pi
        exact_omega = math.pi
    elif abs(n - 1.5) < 1e-9:
        # Standard tabulated benchmark (Chandrasekhar 1939)
        exact_xi_1 = 3.65375
        exact_omega = 2.71406
    elif abs(n - 3.0) < 1e-9:
        # Chandrasekhar white dwarf limit
        exact_xi_1 = 6.89685
        exact_omega = 2.01824
    else:
        raise ValueError(f"No canonical benchmark for n={n}")

    err_xi = abs(xi_1 - exact_xi_1) / exact_xi_1
    err_omega = abs(omega_n - exact_omega) / exact_omega
    passed = (err_xi < tol) and (err_omega < tol)

    return {
        "n": n,
        "numerical_xi_1": xi_1,
        "exact_xi_1": exact_xi_1,
        "err_xi": err_xi,
        "numerical_omega": omega_n,
        "exact_omega": exact_omega,
        "err_omega": err_omega,
        "passed": passed,
    }


if __name__ == "__main__":
    print("Lane-Emden Stellar Structure Benchmark:")
    for n_val in [0.0, 1.0, 1.5, 3.0]:
        check = verify_polytrope_against_analytical(n_val)
        print(f"  Index n = {n_val:3.1f}:")
        print(f"    xi_1 (surface): {check['numerical_xi_1']:.6f} vs exact {check['exact_xi_1']:.6f} (rel error: {check['err_xi']:.2e})")
        print(f"    omega_n (mass): {check['numerical_omega']:.6f} vs exact {check['exact_omega']:.6f} (rel error: {check['err_omega']:.2e})")
        assert check["passed"], f"Polytrope verification failed for n={n_val}"
    print("  [PASS] All stellar structure benchmarks matched theoretical limits.")
