---
name: astronomy-computing
description: Algorithms and invariants for astronomy, orbital mechanics, symplectic N-body dynamics, and celestial coordinate frames.
---

# Astronomy & Astrophysics Computing Framework

When implementing or auditing astronomical software, follow these specialized principles and algorithmic patterns:

---

## 1. Orbital Mechanics & Kepler's Equation

### Governing Equations
For elliptic two-body Keplerian motion ($0 \le e < 1$):
\begin{equation}
    M = E - e \sin E
\end{equation}
where $M = n(t - t_0)$ is mean anomaly, $E$ is eccentric anomaly, and $e$ is eccentricity.

For hyperbolic orbits ($e > 1$):
\begin{equation}
    M = e \sinh F - F
\end{equation}

### Numerical Implementation Guidelines
- **Starter Guess**: Never use $E_0 = M$ for high eccentricity ($e > 0.8$). Use Danby or Prussing conditioned initial guesses to prevent overshoot.
- **Cubic Halley Iteration**: Accelerate Newton-Raphson using second derivatives:
  \begin{equation}
      \Delta_1 = -\frac{f(E)}{f'(E)}, \quad \Delta_{\text{Halley}} = -\frac{f(E)}{f'(E) + \frac{1}{2} \Delta_1 f''(E)}
  \end{equation}
  where $f'(E) = 1 - e \cos E$ and $f''(E) = e \sin E$. Converges to machine precision in 2--4 iterations.
- **True Anomaly Conversion**:
  Avoid quadrant ambiguity and numerical cancellation using the half-angle tangent relation:
  \begin{equation}
      \tan\frac{\nu}{2} = \sqrt{\frac{1+e}{1-e}} \tan\frac{E}{2}
  \end{equation}
- **Vis-Viva Invariant Verification**:
  Every orbital state $(\mathbf{r}, \mathbf{v})$ must satisfy:
  \begin{equation}
      \mathcal{E} = \frac{v^2}{2} - \frac{\mu}{r} = -\frac{\mu}{2a}
  \end{equation}
  and specific angular momentum conservation $\mathbf{h} = \mathbf{r} \times \mathbf{v} = \text{const}$.

Reference implementation: `benchmarks/astronomy/kepler_solver.py`.

---

## 2. Symplectic N-Body Dynamics

### Standard Explicit Integrators Are Forbidden
- **Runge-Kutta / Forward Euler Failures**: Standard explicit Runge-Kutta integrators do not preserve symplectic phase space area. In long-term orbit integration, they introduce artificial secular energy drift ($dE/dt \neq 0$), causing planets to spiral outward or inward.
- **Mandated Symplectic Integrators**:
  - 2nd-order: Leapfrog / Drift-Kick-Drift (Verlet).
  - 4th-order: Yoshida or Forest-Ruth symplectic splitting.
  - Planetary systems: Wisdom-Holman mapping (separating Keplerian motion from planetary perturbations).

### Invariant Audit Thresholds
Track all invariants over simulation time:
1. **Total Energy**: $E(t) = \sum_i \frac{1}{2} m_i v_i^2 - \sum_{i < j} \frac{G m_i m_j}{r_{ij}}$. Symplectic drift must oscillate with zero secular growth:
   \begin{equation}
       \frac{|E(t) - E(0)|}{|E(0)|} < \tau \quad (\tau \le 10^{-4} \text{ over } 10^4 \text{ orbits})
   \end{equation}
2. **Total Angular Momentum**: $\mathbf{L} = \sum_i m_i (\mathbf{r}_i \times \mathbf{v}_i) \equiv \text{const}$ (to machine precision $\sim 10^{-14}$).
3. **Total Linear Momentum**: $\mathbf{P} = \sum_i m_i \mathbf{v}_i \equiv \text{const}$ (Center-of-mass frame).

Reference implementation: `benchmarks/astronomy/symplectic_nbody.py`.

---

## 3. Stellar Structure & Polytropes (Lane-Emden)

### Governing Differential Equation
\begin{equation}
    \frac{1}{\xi^2} \frac{d}{d\xi}\left( \xi^2 \frac{d\theta}{d\xi} \right) + \theta^n = 0
\end{equation}

### Coordinate Singularity Removal
At the center ($\xi = 0$), the geometric term $2/\xi \cdot \theta'$ creates a $0/0$ coordinate singularity.
- **Mandatory Near-Center Series**: Never evaluate directly at $\xi = 0$. Start integration at $\xi_0 \approx 10^{-4}$ using the analytic Taylor expansion:
  \begin{equation}
      \theta(\xi) \approx 1 - \frac{\xi^2}{6} + \frac{n \xi^4}{120} - \frac{n(8n - 5)\xi^6}{15120}
  \end{equation}
  \begin{equation}
      \frac{d\theta}{d\xi} \approx -\frac{\xi}{3} + \frac{n \xi^3}{30} - \frac{n(8n - 5)\xi^5}{2520}
  \end{equation}
- **Surface Boundary**: Integrate until $\theta(\xi_1) = 0$. Use Hermite/linear interpolation to locate surface radius $\xi_1$ and mass factor $\omega_n = -\xi_1^2 \theta'(\xi_1)$.
- Validate against canonical benchmarks:
  - $n = 0$: $\xi_1 = \sqrt{6}$, $\omega_0 = 2\sqrt{6}$.
  - $n = 1$: $\xi_1 = \pi$, $\omega_1 = \pi$.
  - $n = 1.5$: $\xi_1 \approx 3.65375$, $\omega_{1.5} \approx 2.71406$ (convective star / white dwarf).
  - $n = 3.0$: $\xi_1 \approx 6.89685$, $\omega_3 \approx 2.01824$ (Eddington / relativistic dwarf).

Reference implementation: `benchmarks/astronomy/lane_emden_solver.py`.

---

## 4. Celestial Coordinate Systems & Orthonormality

When transforming coordinates between Equatorial (J2000 ICRS), Ecliptic, and Galactic frames:
- Coordinate frames must be represented as orthonormal rotation matrices $\mathbf{R} \in \mathrm{SO}(3)$.
- Assert $\mathbf{R}^T \mathbf{R} = \mathbf{I}$ and $\det \mathbf{R} = 1$ to machine precision ($< 10^{-14}$).
- Direction cosine vectors $\mathbf{r} = [\cos\delta \cos\alpha, \cos\delta \sin\alpha, \sin\delta]^T$ must be converted to spherical coordinates using `math.atan2(y, x)` and `math.atan2(z, math.hypot(x, y))` to prevent pole singularities.

Reference implementation: `benchmarks/astronomy/coordinate_transforms.py`.
