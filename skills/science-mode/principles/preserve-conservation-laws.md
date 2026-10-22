---
name: principle-preserve-conservation-laws
description: "Mathematical and physical invariants (energy, mass, momentum, probability norm, positivity, symplectic structure) must be preserved by discrete numerical schemes and asserted in tests. Use when implementing solvers, integrators, or state-update algorithms."
disable-model-invocation: true
---

# Principle: Preserve Conservation Laws and Symmetries

In physics and mathematics, Noether's theorem connects continuous symmetries to fundamental conservation laws. 

A numerical method that produces low local truncation error but violates global conservation laws (e.g. artificial energy creation, negative probability densities, mass leakage) will produce non-physical behavior, unphysical secular drift, or numerical blowup over long simulation times.

## When it applies

- Selecting or implementing time integrators (Runge-Kutta, symplectic Verlet/Euler, Crank-Nicolson).
- Discretizing spatial operators (finite difference, finite volume, finite element, spectral).
- Implementing particle simulations, fluid dynamics, quantum wavefunctions, chemical reaction kinetics, or Markov chains.

## Rules

1. **Match the Integrator to the Invariant**:
   - Hamiltonian systems (classical mechanics, orbital dynamics, molecular dynamics): Use **symplectic integrators** (e.g. Velocity Verlet, Yoshida). They preserve phase space volume and bound energy error over arbitrarily long integration times without secular energy drift.
   - Quantum systems: Use unitary propagators (e.g. Crank-Nicolson, split-operator) preserving $\langle \psi | \psi \rangle = 1$.
   - Advection-diffusion / Fluid flow: Use conservative finite volume discretizations where fluxes across cell boundaries cancel exactly.
   - Markov chains / chemical kinetics: Enforce probability conservation $\sum_i P_i = 1$ and non-negativity $P_i \ge 0$ unconditionally.

2. **Instrument Invariant Checks**:
   Compute and log the invariant at every step (or every $N$ steps):
   - Energy drift: $\Delta E(t) = |E(t) - E(0)| / |E(0)|$.
   - Mass/Charge drift: $\Delta Q(t) = |Q(t) - Q(0)| / |Q(0)|$.
   - Divergence of magnetic field / incompressible velocity: $\|\nabla \cdot \mathbf{B}\| \approx 0$ or $\|\nabla \cdot \mathbf{u}\| \approx 0$.
   - Positivity constraint: $\min(\rho) \ge 0$.

3. **Assert Conservation in Unit & Regression Tests**:
   Every simulation test suite must include invariant conservation assertions:
   ```python
   def test_harmonic_oscillator_energy_conservation():
       initial_energy = compute_energy(q0, p0)
       q_final, p_final = integrate_verlet(q0, p0, t_span=(0, 1000.0), dt=0.01)
       final_energy = compute_energy(q_final, p_final)
       
       # Symplectic integrator should bound energy error to O(dt^2) without growth
       assert np.isclose(final_energy, initial_energy, rtol=1e-4)
   ```

4. **Preserve Geometric and Symmetry Invariants**:
   - If a system has rotational, translational, or parity symmetry, test that rotating or reflecting inputs produces identically rotated or reflected outputs ($f(R \mathbf{x}) = R f(\mathbf{x})$).
   - If a matrix must be Hermitian, symmetric, or positive-definite, verify that property after discrete operations (e.g. explicitly symmetrize $(A + A^T)/2$ if numerical roundoff introduces skew).
