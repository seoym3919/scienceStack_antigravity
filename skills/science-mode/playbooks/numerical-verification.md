# Numerical Verification Playbook

Use this playbook to verify that a discrete simulation algorithm or numerical solver converges correctly to theoretical solutions and maintains physical invariants without numerical drift.

---

## 1. Establish the Analytical Baseline
- Select a problem regime with an exact analytical solution $u_{\text{exact}}(x, t)$ or configure a Method of Manufactured Solutions (MMS) source term.
- Define the error norm to measure:
  - $L_2$ norm: $\|e\|_2 = \sqrt{\frac{1}{N} \sum_i (u_i - u_{\text{exact}, i})^2}$
  - $L_\infty$ norm (maximum error): $\|e\|_\infty = \max_i |u_i - u_{\text{exact}, i}|$
  - Relative error: $\|e\| / \|u_{\text{exact}}\|$

## 2. Convergence Order Analysis (Grid Refinement Study)
- Run the solver over at least 3 successive grid refinements:
  - Resolution 1: $h_1 = h$
  - Resolution 2: $h_2 = h / 2$
  - Resolution 3: $h_3 = h / 4$
- Compute the observed numerical convergence rate:
  $$p_{\text{observed}} = \frac{\log(E(h_1) / E(h_2))}{\log(h_1 / h_2)}$$
- Compare $p_{\text{observed}}$ against the theoretical formal order $p_{\text{theory}}$:
  - 2nd-order scheme (e.g. leapfrog, central difference): $p \approx 2.0 \pm 0.1$.
  - 4th-order scheme (e.g. RK4): $p \approx 4.0 \pm 0.2$.
- If $p_{\text{observed}} < p_{\text{theory}}$, root-cause the order degradation (commonly caused by lower-order boundary stencils, non-smooth initial conditions, or flux mismatches).

## 3. Invariant & Conservation Drift Monitoring
- Measure system invariants over extended integration times (e.g., $10^3$ to $10^5$ steps):
  - Total Energy $E(t)$
  - Total Momentum $\mathbf{P}(t)$
  - Total Mass / Norm $\int |\psi|^2 dV$
- Distinguish between bounded oscillations vs secular drift:
  - Symplectic integrators exhibit bounded energy oscillations of order $\mathcal{O}(\Delta t^2)$ with zero secular growth.
  - Non-conservative / dissipative schemes show monotonic decay or growth $\to$ fix or document as artificial numerical dissipation.

## 4. Stability Region & CFL Verification
- Vary the timestep $\Delta t$ across the theoretical stability boundary:
  - Run below the CFL limit: verify stable convergence.
  - Test near the boundary: verify behavior does not exhibit unphysical oscillations or stiffness blowup.
  - Ensure adaptive step-size controllers correctly reject timesteps that exceed local error tolerances.

## 5. Perturbation & Sensitivity Analysis
- Add small perturbations $\epsilon \sim 10^{-6}$ to initial conditions or parameters:
  - For well-posed non-chaotic systems, the output perturbation must remain bounded ($\Delta y \sim \mathcal{O}(\epsilon)$).
  - Check matrix condition numbers and verify that small floating-point variations do not cause catastrophic solution changes.
