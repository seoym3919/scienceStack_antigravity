---
name: numerical-stability-audit
description: "Audit scientific and numerical code for floating-point vulnerabilities: catastrophic cancellation, ill-conditioned linear systems, division by near-zero, premature overflow/underflow, and conservation drift. Use when debugging NaNs, infinities, solver divergence, or precision loss."
disable-model-invocation: true
---

# Numerical Stability Audit

Scan and diagnose scientific code for numerical instability, ill-conditioning, and floating-point precision loss.

## Vulnerability Patterns & Mitigations

### 1. Catastrophic Cancellation ($a - b$ when $a \approx b$)
- **Problem**: Subtracting two nearly identical floating-point values cancels out high-order bits, leaving only numerical roundoff noise.
- **Audit**: Search for subtractions between variables of similar magnitude.
- **Fix**:
  - Use algebraic reformulations (e.g. $\sqrt{x+1} - \sqrt{x} \to 1/(\sqrt{x+1} + \sqrt{x})$).
  - Use Taylor series expansions near the cancellation point.
  - Use standard library stable functions: `math.expm1(x)` instead of `exp(x) - 1`; `math.log1p(x)` instead of `log(1 + x)`.

### 2. Division by Near-Zero & Singularities
- **Problem**: In physical potentials (gravity, electrostatics), $1/r^n$ blows up to `Inf` or causes overflow when $r \to 0$.
- **Audit**: Find all division operations `/` and check if denominators can be zero or subnormal.
- **Fix**:
  - Add softening parameters: $1/\sqrt{r^2 + \epsilon^2}$.
  - Branch to analytical limits for $|r| < \epsilon_{\text{cutoff}}$.
  - Assert strictly positive denominators with informative error messages.

### 3. Ill-Conditioned Linear Systems ($A x = b$)
- **Problem**: If the matrix condition number $\kappa(A) \gg 1 / \epsilon_{\text{machine}}$ ($\approx 10^{15}$ for float64, $10^7$ for float32), solutions are pure noise.
- **Audit**:
  - Check for explicit matrix inversions (`inv(A) @ b` $\to$ MUST FIX to `solve(A, b)`).
  - Compute condition number: `np.linalg.cond(A)` in diagnostics.
- **Fix**:
  - Use pivoted LU or QR decompositions.
  - Apply row/column balancing or preconditioning.
  - Apply Tikhonov regularization: $(A^T A + \lambda I) x = A^T b$.

### 4. Exponential Underflow & Overflow
- **Problem**: Evaluating likelihoods, partition functions $Z = \sum e^{-\beta E_i}$, or softmax directly causes `Inf` or `0.0`.
- **Audit**: Search for un-normalized `exp()` calls inside sums or products.
- **Fix**:
  - Compute in log-space: use `scipy.special.logsumexp`.
  - Shift exponents: $e^{x_i - \max(x)}$ before summing.

### 5. Stiff Differential Equations & Timestep Violations
- **Problem**: Explicit time integrators (Forward Euler, explicit RK4) fail and blow up if the timestep $\Delta t > 2 / \lambda_{\max}$ (the largest eigenvalue of the Jacobian).
- **Audit**: Check eigenvalues of the system Jacobian $\mathbf{J} = \frac{\partial \mathbf{f}}{\partial \mathbf{x}}$. If eigenvalues have widely varying magnitudes, the system is stiff.
- **Fix**:
  - Switch to implicit / A-stable integrators (e.g. Radau, BDF, Crank-Nicolson).
  - Implement adaptive timestepping with local truncation error control.
  - Dynamically assert the Courant-Friedrichs-Lewy (CFL) condition: $\Delta t \le C_{\max} \Delta x / v_{\max}$.

### 6. Symmetry & Positive-Definiteness Drift
- **Problem**: Covariance matrices, metric tensors, and density matrices must be symmetric positive-semi-definite ($A = A^T$, $\lambda_i \ge 0$). Roundoff error introduces asymmetry and tiny negative eigenvalues.
- **Audit**: Check symmetry and eigenvalues after repeated operations.
- **Fix**:
  - Re-symmetrize explicitly: $A \leftarrow \frac{1}{2}(A + A^T)$.
  - Clip negative eigenvalues: $A \leftarrow V \max(\Lambda, 0) V^T$.
