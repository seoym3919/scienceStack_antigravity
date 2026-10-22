# Equation Implementation Playbook

Use this playbook when implementing a mathematical model, physical equation, discrete operator, or paper derivation in code.

---

## 1. Ground the Theory & Provenance
- State the exact continuous mathematical equation in standard LaTeX notation in your working notes or planning artifact.
- Record the exact citation: Paper / Textbook / Standard, Author, Year, Equation number.
- Explicitly list:
  - Coordinate system (Cartesian, polar, spherical, curvilinear).
  - Metric signature and sign conventions (Fourier signs, potential energy vs force signs, dissipation signs).
  - Normalization constants (e.g. $1/\sqrt{2\pi}$, $1/V$).

## 2. Dimensional & Variable Mapping
- Build a tabular map connecting mathematical symbols to code variables:
  - Column 1: Math symbol (e.g. $\psi$, $\kappa$, $\rho$).
  - Column 2: Code identifier (e.g. `psi`, `thermal_conductivity_w_per_mk`, `density_kg_per_m3`).
  - Column 3: Physical dimensions ($[M]^a [L]^b [T]^c$).
  - Column 4: Base unit or dimensionless scaling.
  - Column 5: Valid mathematical domain (e.g. $r > 0$, $T \ge 0$, $\theta \in [0, \pi]$).
- Verify dimensional homogeneity: confirm $[LHS] = [RHS]$ and transcendental arguments are strictly dimensionless ($[\arg] = 1$).

## 3. Discretization & Numerical Formulation
- Choose the discrete representation:
  - Grid / Mesh / Basis: Finite difference, spectral, finite element, particle.
  - Stencil order: 2nd-order central difference, 4th-order Runge-Kutta, etc.
  - Boundary conditions: Dirichlet, Neumann, Robin, periodic, absorbing.
- Check stability conditions:
  - Derive or lookup the CFL / stability bound on $\Delta t$ or $\Delta x$.
  - For stiff terms (diffusion, fast reactions), use implicit or semi-implicit formulations.

## 4. Implementation with Mathematical Docstrings
- Write the implementation with comprehensive LaTeX docstrings (per **principle-equation-provenance**).
- Avoid magic constants: define physical constants ($\hbar$, $k_B$, $c$, $G$) in a dedicated physical constants module with cited CODATA values.
- Enforce numerical stability (per **principle-numerical-stability-first**):
  - Use `logsumexp`, `expm1`, `log1p`, `hypot` where appropriate.
  - Guard division by zero and handle singularities with asymptotic expansions.
  - Use `solve(A, b)` instead of explicit matrix inversion.

## 5. Analytical Benchmark & MMS Testing
- Write automated unit tests verifying the implementation against:
  1. Known analytical closed-form solutions (e.g. plane waves, Gaussian dispersion, harmonic potentials).
  2. Asymptotic limits ($x \to 0$, $x \to \infty$, $T \to 0$).
  3. Method of Manufactured Solutions (MMS) if no closed-form solution exists.
- Assert agreement with strict tolerances: `np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-14)`.

## 6. Symmetries & Conservation Laws
- Verify that physical invariants are preserved:
  - Energy conservation: $\Delta E / E_0 < \epsilon$.
  - Mass / charge conservation.
  - Parity / rotational symmetries ($f(R \mathbf{x}) = R f(\mathbf{x})$).

## 7. Golden Dataset & Industry Benchmark Lock
- For canonical domain problems (CFD, FEM, MD, reaction kinetics, quantum), acquire or generate a golden reference dataset per the **golden-dataset-benchmark** skill (`skills/golden-dataset-benchmark/SKILL.md`).
- Store the reference data in `tests/golden/<problem-slug>/` with `metadata.json` documenting literature citation, parameters, float precision, and SHA256 checksum.
- Add regression tests computing relative $L_2$ error ($\|\mathbf{y} - \mathbf{y}_{\text{gold}}\|_2 / \|\mathbf{y}_{\text{gold}}\|_2$) and maximum pointwise error ($L_\infty$), establishing a strict tolerance gate.
