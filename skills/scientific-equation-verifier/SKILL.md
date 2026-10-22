---
name: scientific-equation-verifier
description: "Verify that code implementing mathematical and physical equations strictly matches theoretical formulations, sign conventions, index ordering, and normalization constants. Use when implementing new equations, porting formulas from papers, or auditing scientific kernels."
disable-model-invocation: true
---

# Scientific Equation Verifier

Given a mathematical formula, physical law, or algorithm from a paper or textbook, rigorously verify its translation into discrete code.

## Verification Checklist

Execute this 7-point audit before declaring any scientific equation implementation complete:

### 1. LaTeX Formula Specification & Citation
- Write down the exact theoretical continuous equation in standard LaTeX notation.
- Cite the source: Paper / Textbook / RFC, author, year, equation number.
- Explicitly state coordinate systems (Cartesian, spherical, cylindrical, curvilinear) and tensor notation (Einstein summation, covariant/contravariant).

### 2. Sign Conventions & Normalizations
- Check sign conventions:
  - Gradient / Laplacian signs: $\nabla^2 u$ vs $-\nabla^2 u$.
  - Dissipation / Diffusion signs: $+\alpha \nabla^2 u$ (decay) vs $-\alpha \nabla^2 u$ (exponential blowup).
  - Harmonic time factor: $e^{-i \omega t}$ vs $e^{+i \omega t}$.
  - Potential energy force relation: $\mathbf{F} = -\nabla V$ (crucial negative sign!).
- Verify normalization factors:
  - Fourier transforms ($1/\sqrt{2\pi}$ unitary vs $1/N$ discrete FFT).
  - Spherical harmonics normalization.
  - Probability distribution normalization ($\int P(x) dx = 1$).

### 3. Dimensional & Unit Consistency
- Check $[LHS] = [RHS]$.
- Check arguments to transcendental functions are dimensionless: $[\exp(\dots)] = 1$, $[\ln(\dots)] = 1$.
- Ensure variables have documented units (SI, atomic, or dimensionless).

### 4. Index & Tensor Ordering
- If using multidimensional arrays (e.g. NumPy, PyTorch, JAX):
  - Check row-major (C-order) vs column-major (Fortran-order) layout.
  - Verify matrix multiplication order: $A B \neq B A$.
  - Verify tensor contraction indices using `np.einsum` or explicit index comments.
  - Verify spatial dimensions match spatial axes (e.g. `(z, y, x)` vs `(x, y, z)`).

### 5. Asymptotic and Edge Regimes
- Test behavior at extreme parameter values:
  - Zeros: $x = 0$, $t = 0$.
  - Limits: $x \to \infty$, $T \to 0$.
  - Singularities: $r \to 0$ in $1/r^2$ potentials.
  - Branch cuts in complex analysis: $\sqrt{z}$, $\log(z)$, $\arctan2(y, x)$.

### 6. Analytical Unit Test
- Write a unit test comparing code output against an exact analytical benchmark or closed-form solution.
- Use explicit tolerance bounds: `np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-14)`.
- Never use loose tolerances without a mathematical justification based on floating-point truncation.

### 7. Physics Modularity & Decoupling
- Check that pure physics operators (equations of state, forces, collision terms, rate equations) are isolated in standalone, stateless functions or modules (`physics/`).
- Verify that external solvers or other codes can import and call the physics routines directly without depending on simulation loops, time steppers, or file I/O.
