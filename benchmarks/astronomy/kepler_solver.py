r"""
Exact and High-Precision Kepler Equation Solver and Orbit Propagation.

Governing Equations:
====================
1. Kepler's Equation for Elliptic Orbits (0 <= e < 1):
   \begin{equation}
       M = E - e \sin E
   \end{equation}
   where M is mean anomaly, E is eccentric anomaly, and e is orbital eccentricity.

2. Kepler's Equation for Hyperbolic Orbits (e > 1):
   \begin{equation}
       M = e \sinh F - F
   \end{equation}
   where F is hyperbolic eccentric anomaly.

3. True Anomaly Conversion:
   \begin{equation}
       \tan\frac{\nu}{2} = \sqrt{\frac{1+e}{1-e}} \tan\frac{E}{2}
   \end{equation}

4. Invariant Energy (Vis-Viva Equation):
   \begin{equation}
       \mathcal{E} = \frac{v^2}{2} - \frac{\mu}{r} = -\frac{\mu}{2a}
   \end{equation}

5. Specific Angular Momentum:
   \begin{equation}
       \mathbf{h} = \mathbf{r} \times \mathbf{v}, \quad h = \sqrt{\mu a (1 - e^2)}
   \end{equation}

Reference:
==========
Danby, J. M. A. (1988). "Fundamentals of Celestial Mechanics", 2nd ed.,
Willmann-Bell, Chapter 6, pp. 147-154.
Prussing, J. E., & Conway, B. A. (1993). "Orbital Mechanics", Oxford University Press.
"""

from __future__ import annotations
import math
from typing import Tuple, Dict, Any


def solve_kepler_elliptic(
    mean_anomaly: float,
    eccentricity: float,
    tol: float = 1e-14,
    max_iter: int = 50,
) -> float:
    r"""
    Solve Kepler's equation M = E - e * sin(E) to machine precision.

    Uses cubic Halley acceleration with Danby conditioned initial starter to
    guarantee monotonic convergence without catastrophic cancellation near e ~ 1.

    Parameters:
        mean_anomaly: Mean anomaly M in radians (any real value; normalized to [0, 2*pi)).
        eccentricity: Orbital eccentricity e (0 <= e < 1).
        tol: Absolute convergence tolerance on |E_{k+1} - E_k|.
        max_iter: Maximum iterations before error raise.

    Returns:
        Eccentric anomaly E in radians in [0, 2*pi).
    """
    if not (0.0 <= eccentricity < 1.0):
        raise ValueError(f"Eccentricity must be in [0, 1) for elliptic orbits, got {eccentricity}")

    # Normalize M to [0, 2*pi)
    two_pi = 2.0 * math.pi
    M = mean_anomaly % two_pi
    if M < 0.0:
        M += two_pi

    # Exact trivial cases
    if eccentricity == 0.0 or M == 0.0 or abs(M - math.pi) < tol:
        return M

    # Danby's initial guess starter
    # For small M, M + 0.85*e is effective; for larger M, standard expansion avoids overshoot
    k = 0.85
    s = math.sin(M)
    c = math.cos(M)
    E = M + eccentricity * s / (1.0 - eccentricity * c) if eccentricity < 0.8 else M + k * eccentricity * math.copysign(1.0, s)

    # Halley's third-order iterative refinement
    for _ in range(max_iter):
        sin_E = math.sin(E)
        cos_E = math.cos(E)
        
        f = E - eccentricity * sin_E - M       # f(E)
        f_prime = 1.0 - eccentricity * cos_E   # f'(E)
        f_double = eccentricity * sin_E        # f''(E)

        # First-order Newton step
        delta_1 = -f / f_prime
        # Second-order Halley correction
        delta_halley = -f / (f_prime + 0.5 * delta_1 * f_double)

        E += delta_halley
        if abs(delta_halley) < tol:
            return E % two_pi

    raise RuntimeError(f"Kepler elliptic solver failed to converge after {max_iter} iterations (residual: {delta_halley})")


def true_anomaly_from_eccentric(eccentric_anomaly: float, eccentricity: float) -> float:
    r"""
    Compute true anomaly \nu from eccentric anomaly E using half-angle tan formulation.

    Avoids quadrant ambiguities and numerical loss of significance.
    """
    beta = math.sqrt((1.0 + eccentricity) / (1.0 - eccentricity))
    tan_half_E = math.tan(0.5 * eccentric_anomaly)
    nu = 2.0 * math.atan(beta * tan_half_E)
    return nu % (2.0 * math.pi)


def orbital_elements_to_cartesian(
    a: float,
    e: float,
    inc: float,
    raan: float,
    argp: float,
    M: float,
    mu: float = 1.0,
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    r"""
    Convert classical Keplerian orbital elements to 3D Cartesian position and velocity vectors.

    Parameters:
        a: Semi-major axis (> 0)
        e: Eccentricity (0 <= e < 1)
        inc: Inclination in radians
        raan: Right Ascension of Ascending Node (\Omega) in radians
        argp: Argument of Periapsis (\omega) in radians
        M: Mean anomaly in radians
        mu: Gravitational parameter G * (M1 + M2), default 1.0 (canonical units)

    Returns:
        r: Cartesian position vector (x, y, z)
        v: Cartesian velocity vector (vx, vy, vz)
    """
    if a <= 0.0:
        raise ValueError("Semi-major axis a must be positive")
    if not (0.0 <= e < 1.0):
        raise ValueError("Eccentricity e must be in [0, 1)")

    E = solve_kepler_elliptic(M, e)
    nu = true_anomaly_from_eccentric(E, e)

    # Orbital radius
    r_orbit = a * (1.0 - e * math.cos(E))

    # Position in orbital plane (perifocal frame PQW)
    p_x = r_orbit * math.cos(nu)
    p_y = r_orbit * math.sin(nu)
    p_z = 0.0

    # Velocity in perifocal frame
    h = math.sqrt(mu * a * (1.0 - e * e))
    v_x = -(mu / h) * math.sin(nu)
    v_y = (mu / h) * (e + math.cos(nu))
    v_z = 0.0

    # Euler rotation matrix from perifocal to inertial frame
    cos_O = math.cos(raan)
    sin_O = math.sin(raan)
    cos_w = math.cos(argp)
    sin_w = math.sin(argp)
    cos_i = math.cos(inc)
    sin_i = math.sin(inc)

    # Direction cosine matrix elements
    P11 = cos_O * cos_w - sin_O * sin_w * cos_i
    P12 = -cos_O * sin_w - sin_O * cos_w * cos_i
    P21 = sin_O * cos_w + cos_O * sin_w * cos_i
    P22 = -sin_O * sin_w + cos_O * cos_w * cos_i
    P31 = sin_w * sin_i
    P32 = cos_w * sin_i

    # Transform position
    rx = P11 * p_x + P12 * p_y
    ry = P21 * p_x + P22 * p_y
    rz = P31 * p_x + P32 * p_y

    # Transform velocity
    vx = P11 * v_x + P12 * v_y
    vy = P21 * v_x + P22 * v_y
    vz = P31 * v_x + P32 * v_y

    return (rx, ry, rz), (vx, vy, vz)


def verify_orbital_invariants(
    r: Tuple[float, float, float],
    v: Tuple[float, float, float],
    a: float,
    e: float,
    mu: float = 1.0,
    tol: float = 1e-12,
) -> Dict[str, Any]:
    r"""
    Assert and audit physical conservation invariants for an orbital state:
    1. Vis-Viva specific orbital energy: E_vis = v^2/2 - mu/r == -mu/(2*a)
    2. Specific angular momentum magnitude: |h| = |r x v| == sqrt(mu * a * (1 - e^2))
    """
    rx, ry, rz = r
    vx, vy, vz = v

    r_mag = math.sqrt(rx * rx + ry * ry + rz * rz)
    v_sq = vx * vx + vy * vy + vz * vz

    # Specific energy
    energy_actual = 0.5 * v_sq - mu / r_mag
    energy_theoretical = -mu / (2.0 * a)
    energy_error = abs(energy_actual - energy_theoretical) / abs(energy_theoretical)

    # Angular momentum vector h = r x v
    hx = ry * vz - rz * vy
    hy = rz * vx - rx * vz
    hz = rx * vy - ry * vx
    h_mag_actual = math.sqrt(hx * hx + hy * hy + hz * hz)
    h_mag_theoretical = math.sqrt(mu * a * (1.0 - e * e))
    h_error = abs(h_mag_actual - h_mag_theoretical) / h_mag_theoretical

    passed = (energy_error < tol) and (h_error < tol)

    return {
        "passed": passed,
        "energy_error": energy_error,
        "angular_momentum_error": h_error,
        "r_mag": r_mag,
        "v_mag": math.sqrt(v_sq),
        "h_vector": (hx, hy, hz),
    }


if __name__ == "__main__":
    # Self-test: Earth-like orbit around central mass
    a_orbit = 1.0  # AU
    e_orbit = 0.0167
    inc_orbit = math.radians(23.44)
    raan_orbit = math.radians(45.0)
    argp_orbit = math.radians(102.0)
    M_orbit = math.radians(72.5)

    pos, vel = orbital_elements_to_cartesian(a_orbit, e_orbit, inc_orbit, raan_orbit, argp_orbit, M_orbit)
    audit = verify_orbital_invariants(pos, vel, a_orbit, e_orbit)

    print("Kepler Solver & Invariant Audit:")
    print(f"  Position: {pos}")
    print(f"  Velocity: {vel}")
    print(f"  Energy Relative Error: {audit['energy_error']:.3e}")
    print(f"  Angular Momentum Rel Error: {audit['angular_momentum_error']:.3e}")
    assert audit["passed"], "Kepler solver self-test failed invariant audit!"
    print("  [PASS] All invariants strictly conserved.")
