---
name: principle-verify-analytical-limits
description: "Validate numerical implementations against known closed-form analytical solutions, asymptotic limits, and manufactured solutions before trusting complex simulations. Use when testing numerical code or verifying mathematical correctness."
disable-model-invocation: true
---

# Principle: Verify Against Analytical Limits

A complex numerical simulation cannot be validated by inspection or by confirming "it ran without crashing".

The foundational test of any scientific code is whether it exactly reproduces known analytical, closed-form solutions in simplified regimes and correct asymptotic power laws in limiting cases.

## When it applies

- Writing unit tests for any numerical solver, PDE/ODE integrator, or mathematical model.
- Validating physical simulations before adding complex geometries, nonlinearities, or couplings.
- Debugging unexpected simulation results or discrepancies with literature.

## Rules

1. **Test Against Analytical Benchmarks**:
   Identify simplified benchmark problems with known exact closed-form solutions:
   - Heat/diffusion equation: Gaussian pulse diffusion ($T(x,t) = \frac{1}{\sqrt{4\pi \alpha t}} \exp(-x^2 / 4\alpha t)$) or separation of variables series.
   - Wave equation: Standing waves or d'Alembert traveling wave solution.
   - Navier-Stokes / Fluid dynamics: Poiseuille flow, Couette flow, Taylor-Green vortex.
   - Quantum mechanics: Harmonic oscillator, hydrogen atom ground state, square well.
   - Orbital dynamics: Kepler two-body problem.

2. **Method of Manufactured Solutions (MMS)**:
   When no closed-form analytical solution exists for a general PDE $\mathcal{L}(u) = 0$:
   - Choose an arbitrary smooth function $u_{\text{exact}}(x, t)$ (e.g. $\cos(k x) \sin(\omega t)$).
   - Analytically compute the source term $f(x, t) = \mathcal{L}(u_{\text{exact}})$.
   - Solve the modified PDE $\mathcal{L}(u) = f(x, t)$ numerically with exact boundary and initial conditions from $u_{\text{exact}}$.
   - Verify that the numerical solution converges to $u_{\text{exact}}$.

3. **Check Asymptotic & Limiting Regimes**:
   Every formula has asymptotic limits where behavior simplifies:
   - Low/high temperature limits ($T \to 0$, $T \to \infty$).
   - Wavevector / frequency limits ($k \to 0$ acoustic/macroscopic limit vs $k \to \infty$).
   - Coupling limits (weak coupling perturbation theory vs strong coupling limit).
   - In relativistic mechanics: $v \ll c$ must recover classical Newtonian mechanics ($E \approx mc^2 + \frac{1}{2}mv^2$).

4. **Verify Asymptotic Order of Convergence**:
   When refining discretization steps ($h = \Delta x$ or $\Delta t$):
   $$\text{Error}(h) = \| u_{\text{numerical}}(h) - u_{\text{exact}} \| \approx C h^p$$
   - Halve the grid spacing: $h_1 = h$, $h_2 = h/2$, $h_3 = h/4$.
   - Calculate the observed numerical order:
     $$p = \frac{\log(\text{Error}(h_1) / \text{Error}(h_2))}{\log(h_1 / h_2)}$$
   - Assert that $p$ matches the theoretical formal order of the scheme (e.g., $p = 2$ for central differences or Runge-Kutta 2; $p = 4$ for RK4). A drop in $p$ reveals bugs in boundary condition order or flux formulation.
