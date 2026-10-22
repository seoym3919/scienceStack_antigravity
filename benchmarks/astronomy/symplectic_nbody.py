r"""
Symplectic N-Body Gravitational Integrator.

Governing Equations:
====================
1. Hamiltonian Formulation:
   \begin{equation}
       H(\mathbf{q}, \mathbf{p}) = T(\mathbf{p}) + V(\mathbf{q}) = \sum_{i=1}^N \frac{\mathbf{p}_i^2}{2 m_i} - \sum_{1 \le i < j \le N} \frac{G m_i m_j}{\|\mathbf{q}_i - \mathbf{q}_j\|}
   \end{equation}

2. Equations of Motion:
   \begin{equation}
       \frac{d\mathbf{q}_i}{dt} = \mathbf{v}_i, \quad \frac{d\mathbf{v}_i}{dt} = \mathbf{a}_i(\mathbf{q}) = -G \sum_{j \neq i} m_j \frac{\mathbf{q}_i - \mathbf{q}_j}{\|\mathbf{q}_i - \mathbf{q}_j\|^3}
   \end{equation}

3. Symplectic Drift-Kick-Drift (Verlet/Leapfrog, 2nd Order):
   \begin{align}
       \mathbf{q}^{n+1/2} &= \mathbf{q}^n + \frac{\Delta t}{2} \mathbf{v}^n \\
       \mathbf{v}^{n+1} &= \mathbf{v}^n + \Delta t \, \mathbf{a}(\mathbf{q}^{n+1/2}) \\
       \mathbf{q}^{n+1} &= \mathbf{q}^{n+1/2} + \frac{\Delta t}{2} \mathbf{v}^{n+1}
   \end{align}

4. Invariants (Noetherian Conservation Laws):
   - Total Energy: $E = T + V$ (bounded oscillation, zero secular growth)
   - Linear Momentum: $\mathbf{P} = \sum_i m_i \mathbf{v}_i \equiv \text{const}$
   - Angular Momentum: $\mathbf{L} = \sum_i m_i (\mathbf{q}_i \times \mathbf{v}_i) \equiv \text{const}$

Reference:
==========
Yoshida, H. (1990). "Construction of higher order symplectic integrators."
Physics Letters A, 150(5-7), 262-268.
Hairer, E., Lubich, C., & Wanner, G. (2006). "Geometric Numerical Integration:
Structure-Preserving Algorithms for Ordinary Differential Equations", Springer.
"""

from __future__ import annotations
import math
from typing import List, Tuple, Dict, Any


# =============================================================================
# Modular Physics Functions (Driver-agnostic, callable by external codes)
# =============================================================================

def compute_gravitational_accelerations(
    positions: List[List[float]],
    masses: List[float],
    G: float = 1.0,
    softening: float = 0.0
) -> List[List[float]]:
    r"""
    Compute pairwise Newtonian gravitational accelerations for an N-body system.

    Governing Equation:
    \begin{equation}
        \mathbf{a}_i = -G \sum_{j \neq i} m_j \frac{\mathbf{q}_i - \mathbf{q}_j}{(\|\mathbf{q}_i - \mathbf{q}_j\|^2 + \epsilon^2)^{3/2}}
    \end{equation}

    Parameters
    ----------
    positions : List[List[float]]
        3D Cartesian coordinate vectors [length].
    masses : List[float]
        Point masses [mass].
    G : float, optional
        Gravitational constant, by default 1.0.
    softening : float, optional
        Plummer softening parameter \epsilon to prevent unphysical singular forces [length].

    Returns
    -------
    List[List[float]]
        3D acceleration vectors [length / time^2].
    """
    n = len(masses)
    acc = [[0.0, 0.0, 0.0] for _ in range(n)]
    soft_sq = softening * softening

    for i in range(n):
        qi = positions[i]
        for j in range(i + 1, n):
            qj = positions[j]
            dx = qi[0] - qj[0]
            dy = qi[1] - qj[1]
            dz = qi[2] - qj[2]
            r_sq = dx * dx + dy * dy + dz * dz + soft_sq
            r = math.sqrt(r_sq)
            inv_r3 = 1.0 / (r * r_sq)

            f_factor = G * inv_r3
            ax = f_factor * dx
            ay = f_factor * dy
            az = f_factor * dz

            acc[i][0] -= masses[j] * ax
            acc[i][1] -= masses[j] * ay
            acc[i][2] -= masses[j] * az

            acc[j][0] += masses[i] * ax
            acc[j][1] += masses[i] * ay
            acc[j][2] += masses[i] * az

    return acc


def compute_gravitational_potential(
    positions: List[List[float]],
    masses: List[float],
    G: float = 1.0,
    softening: float = 0.0
) -> float:
    r"""
    Compute total gravitational potential energy V of an N-body system.

    Governing Equation:
    \begin{equation}
        V = -\sum_{1 \le i < j \le N} \frac{G m_i m_j}{\sqrt{\|\mathbf{q}_i - \mathbf{q}_j\|^2 + \epsilon^2}}
    \end{equation}
    """
    n = len(masses)
    V = 0.0
    soft_sq = softening * softening
    for i in range(n):
        qi = positions[i]
        for j in range(i + 1, n):
            qj = positions[j]
            dx = qi[0] - qj[0]
            dy = qi[1] - qj[1]
            dz = qi[2] - qj[2]
            r = math.sqrt(dx * dx + dy * dy + dz * dz + soft_sq)
            if r > 0.0:
                V -= (G * masses[i] * masses[j]) / r
    return V


def compute_kinetic_energy(velocities: List[List[float]], masses: List[float]) -> float:
    r"""Compute total kinetic energy T = 0.5 * \sum m_i \|\mathbf{v}_i\|^2."""
    T = 0.0
    for i in range(len(masses)):
        v_sq = sum(vk * vk for vk in velocities[i])
        T += 0.5 * masses[i] * v_sq
    return T


def compute_linear_momentum(velocities: List[List[float]], masses: List[float]) -> Tuple[float, float, float]:
    r"""Compute total linear momentum \mathbf{P} = \sum m_i \mathbf{v}_i."""
    Px, Py, Pz = 0.0, 0.0, 0.0
    for i in range(len(masses)):
        m = masses[i]
        Px += m * velocities[i][0]
        Py += m * velocities[i][1]
        Pz += m * velocities[i][2]
    return Px, Py, Pz


def compute_angular_momentum(
    positions: List[List[float]],
    velocities: List[List[float]],
    masses: List[float]
) -> Tuple[float, float, float]:
    r"""Compute total angular momentum \mathbf{L} = \sum m_i (\mathbf{q}_i \times \mathbf{v}_i)."""
    Lx, Ly, Lz = 0.0, 0.0, 0.0
    for i in range(len(masses)):
        m = masses[i]
        rx, ry, rz = positions[i]
        vx, vy, vz = velocities[i]
        Lx += m * (ry * vz - rz * vy)
        Ly += m * (rz * vx - rx * vz)
        Lz += m * (rx * vy - ry * vx)
    return Lx, Ly, Lz


# =============================================================================
# Symplectic Integrator & System Coordinator
# =============================================================================

class SymplecticNBodySystem:
    def __init__(self, masses: List[float], positions: List[List[float]], velocities: List[List[float]], G: float = 1.0):
        self.n = len(masses)
        self.masses = [float(m) for m in masses]
        # Copy positions and velocities (3D vectors)
        self.q = [[float(x) for x in pos] for pos in positions]
        self.v = [[float(x) for x in vel] for vel in velocities]
        self.G = float(G)

        # Baseline invariants
        self.initial_energy = self.compute_total_energy()
        self.initial_p = self.compute_linear_momentum()
        self.initial_L = self.compute_angular_momentum()

    def compute_accelerations(self, q_state: List[List[float]], softening: float = 0.0) -> List[List[float]]:
        r"""Compute gravitational accelerations via modular physics function."""
        return compute_gravitational_accelerations(q_state, self.masses, G=self.G, softening=softening)

    def step_leapfrog(self, dt: float) -> None:
        r"""Symplectic Drift-Kick-Drift step (2nd order)."""
        half_dt = 0.5 * dt

        # Drift 1: q^{n+1/2} = q^n + (dt/2) * v^n
        for i in range(self.n):
            for k in range(3):
                self.q[i][k] += half_dt * self.v[i][k]

        # Kick: v^{n+1} = v^n + dt * a(q^{n+1/2})
        acc = self.compute_accelerations(self.q)
        for i in range(self.n):
            for k in range(3):
                self.v[i][k] += dt * acc[i][k]

        # Drift 2: q^{n+1} = q^{n+1/2} + (dt/2) * v^{n+1}
        for i in range(self.n):
            for k in range(3):
                self.q[i][k] += half_dt * self.v[i][k]

    def compute_total_energy(self) -> float:
        r"""Compute E = T + V via modular physics functions."""
        T = compute_kinetic_energy(self.v, self.masses)
        V = compute_gravitational_potential(self.q, self.masses, G=self.G)
        return T + V

    def compute_linear_momentum(self) -> Tuple[float, float, float]:
        r"""Compute total P = \sum m_i v_i via modular physics function."""
        return compute_linear_momentum(self.v, self.masses)

    def compute_angular_momentum(self) -> Tuple[float, float, float]:
        r"""Compute total L = \sum m_i (r_i x v_i) via modular physics function."""
        return compute_angular_momentum(self.q, self.v, self.masses)

    def audit_invariants(self) -> Dict[str, float]:
        r"""Audit relative drift of all physical invariants."""
        current_E = self.compute_total_energy()
        delta_E = abs(current_E - self.initial_energy) / abs(self.initial_energy)

        Px, Py, Pz = self.compute_linear_momentum()
        init_Px, init_Py, init_Pz = self.initial_p
        drift_P = math.sqrt((Px - init_Px)**2 + (Py - init_Py)**2 + (Pz - init_Pz)**2)

        Lx, Ly, Lz = self.compute_angular_momentum()
        init_Lx, init_Ly, init_Lz = self.initial_L
        init_L_mag = math.sqrt(init_Lx**2 + init_Ly**2 + init_Lz**2)
        drift_L = math.sqrt((Lx - init_Lx)**2 + (Ly - init_Ly)**2 + (Lz - init_Lz)**2) / max(init_L_mag, 1e-12)

        return {
            "energy_drift": delta_E,
            "linear_momentum_drift": drift_P,
            "angular_momentum_drift": drift_L,
        }


if __name__ == "__main__":
    # Canonical 2-body Kepler benchmark: Sun-Earth system
    # In canonical units: G = 1, M_sun = 1.0, M_earth = 3e-6, r = 1.0, v = 1.0 (circular orbit, period = 2*pi)
    masses = [1.0, 3e-6]
    positions = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    velocities = [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]]

    # Adjust Sun to center of mass frame
    velocities[0][1] = - (masses[1] * velocities[1][1]) / masses[0]

    sim = SymplecticNBodySystem(masses, positions, velocities, G=1.0)
    dt = 0.01
    num_steps = 10000  # ~ 16 complete orbits

    for _ in range(num_steps):
        sim.step_leapfrog(dt)

    audit = sim.audit_invariants()
    print("Symplectic N-Body Orbit Verification:")
    print(f"  Integration Steps: {num_steps} (dt = {dt})")
    print(f"  Relative Energy Drift: {audit['energy_drift']:.3e}")
    print(f"  Linear Momentum Drift: {audit['linear_momentum_drift']:.3e}")
    print(f"  Angular Momentum Drift: {audit['angular_momentum_drift']:.3e}")

    assert audit["energy_drift"] < 1e-4, "Symplectic integrator energy drift exceeded threshold!"
    assert audit["angular_momentum_drift"] < 1e-12, "Angular momentum not conserved!"
    print("  [PASS] Symplectic conservation laws preserved without secular growth.")
