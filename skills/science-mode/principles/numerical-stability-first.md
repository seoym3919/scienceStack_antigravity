---
name: principle-numerical-stability-first
description: "Guard against catastrophic cancellation, division by near-zero, underflow/overflow, stiff ODE instability, and ill-conditioned matrices. Stability and conditioning take precedence over premature vectorization. Use when writing mathematical kernels or numerical algorithms."
disable-model-invocation: true
---

# Principle: Numerical Stability First

In exact mathematics, $x$ and $\frac{x^2}{x}$ are identical for $x \neq 0$. In IEEE-754 floating-point arithmetic, algebraic equivalences break down due to finite precision, subnormal numbers, catastrophic cancellation, and roundoff accumulation.

A mathematically correct equation implemented naively will fail, produce NaNs, or blow up when inputs approach edge regimes.

## When it applies

- Formulating mathematical equations in code.
- Matrix inversions, linear solves, eigenvalue decompositions.
- Log-likelihoods, probability distributions, exponentials, square roots.
- Stiff differential equations or multi-scale dynamics.

## Rules

1. **Eliminate Catastrophic Cancellation**:
   Subtracting two nearly equal numbers ($a - b$ where $a \approx b$) loses significant bits of precision:
   - Difference of square roots: Replace $\sqrt{x+1} - \sqrt{x}$ with $\frac{1}{\sqrt{x+1} + \sqrt{x}}$.
   - Small $x$ approximations: For $e^x - 1$ when $x \to 0$, use `np.expm1(x)`. For $\ln(1 + x)$ when $x \to 0$, use `np.log1p(x)`.
   - Trigonometric / hyperbolic functions: Use dedicated high-stability kernels (`hypot(x, y)` instead of `sqrt(x**2 + y**2)` to prevent premature overflow).

2. **Log-Space Computation for Probabilities and Scales**:
   Never multiply many small probabilities or exponentials directly (which underflows to 0.0):
   - Store and compute in log-space: $\ln(P_1 \cdot P_2) = \ln P_1 + \ln P_2$.
   - For sums of exponentials $\ln \sum_i e^{x_i}$, always use `logsumexp(x) = c + \ln \sum_i e^{x_i - c}$ where $c = \max_i x_i$.

3. **Check Matrix Condition Numbers Before Solving**:
   - Never compute explicit matrix inverse $A^{-1} b$! Always use `solve(A, b)` with pivoted LU, Cholesky, or QR decomposition.
   - For ill-conditioned systems ($\kappa(A) = \|A\| \|A^{-1}\| \gg 10^{12}$ in double precision), employ regularization (Tikhonov / ridge, truncated SVD) or iterative preconditioning.
   - For symmetric positive-definite matrices, prefer Cholesky decomposition (`np.linalg.cholesky`); if it fails, the matrix is not positive-definite due to numerical noise.

4. **Honor Stability Criteria (CFL & Stiff Solvers)**:
   - For hyperbolic PDEs ($\frac{\partial u}{\partial t} + c \frac{\partial u}{\partial x} = 0$), strictly obey the Courant-Friedrichs-Lewy (CFL) condition: $\Delta t \le C \frac{\Delta x}{c}$. Assert this condition dynamically.
   - For stiff ODEs (systems with widely separated relaxation times), never use explicit Euler or standard explicit Runge-Kutta! Use implicit or semi-implicit A-stable methods (Radau, BDF, Crank-Nicolson).

5. **Guard Division and Singularities**:
   - Add explicit physical regularizers or asymptotic branching when dividing by quantities that can approach zero:
     $$\frac{1}{r} \to \frac{1}{\sqrt{r^2 + \epsilon^2}} \quad \text{or branch for } r < r_{\min}$$
   - When evaluating limits (e.g. $\frac{\sin x}{x}$ as $x \to 0$), use Taylor expansions for $|x| < \epsilon$ to avoid indeterminate $0/0$.
