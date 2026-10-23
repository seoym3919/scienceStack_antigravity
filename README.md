# scienceStack: Antigravity Scientific Computing & Mathematical Verification Plugin

**scienceStack** is a lightweight, Antigravity-native plugin for computational science, astrophysics, physics modeling, and numerical engineering—enforcing continuous LaTeX equation provenance, dimensional homogeneity, symplectic phase-space conservation, numerical stability, and closed-loop benchmark verification.

---

## 1. Installation & How to Use

### Installation

Install `scienceStack` globally or locally in Google Antigravity:

```bash
# 1. Validate compliance with Agent Plugins 1.0.0 (Strict mode)
agy plugin validate /home/seo3919/AI_skills/scienceStack_antigravity --strict

# 2. Install globally in Antigravity
agy plugin install /home/seo3919/AI_skills/scienceStack_antigravity

# Or workspace-local:
# Place scienceStack_antigravity in .agents/plugins/sciencestack
```

Verify installation status:
```bash
agy plugin list
# - sciencestack (enabled, 0.15.29)
#   Components: 9 skills, 2 agents, 1 rule, 1 hook
```

---

### Quickstart & How to Use

#### Method A: Interactive Slash Commands

| Command | Capability & Action | Example Prompt |
| :--- | :--- | :--- |
| **`/science-mode`** | Master scientific engineering workflow: routes to 6 specialized scientific playbooks and enforces 6 mathematical principles. | `/science-mode Implement a 4th-order Yoshida symplectic N-body orbit integrator` |
| **`/astronomy-computing`** | Algorithms and invariants for orbital mechanics, Kepler solvers, symplectic N-body dynamics, and $\mathrm{SO}(3)$ coordinate frames. | `/astronomy-computing Transform state vectors from ICRS J2000 to Galactic coordinates` |
| **`/accelerated-scientific-computing`** | Memory layouts (row- vs. column-major), SIMD vectorization, and precision guards for C++, Fortran, Julia, and JAX. | `/accelerated-scientific-computing Optimize 3D finite-difference stencil for cache contiguity` |
| **`/scientific-equation-verifier`** | 7-point audit verifying discrete code against continuous LaTeX formulas, sign conventions, index order, and normalizations. | `/scientific-equation-verifier Audit gravitational softening kernel in gravity.py` |
| **`/numerical-stability-audit`** | Audits solvers for explicit matrix inversion (`inv(A)`), catastrophic cancellation, division by zero, and stiff ODE hazards. | `/numerical-stability-audit linear_solver.py` |
| **`/precision-audit`** | Audits `float32` vs. `float64` precision drift, condition number amplification $\kappa(A)\epsilon_{\text{mach}}$, and mixed precision. | `/precision-audit solver.py` |
| **`/golden-dataset-benchmark`** | Verifies numerical solvers against Method of Manufactured Solutions (MMS) and canonical reference datasets. | `/golden-dataset-benchmark Run MMS convergence test on navier_stokes.py` |
| **`/benchmark-checklist`** | Vets performance and scaling benchmarks (warmup, memory bandwidth limiters, error bars, and $L_2$ parity). | `/benchmark-checklist Profile vectorized vs. scalar solver` |
| **`/setup-sciencestack`** | Configures per-role frontier models (`gemini-4-argon-high`, `claude-opus-5-5-high`, `claude-sonnet-5-5-high`). | `/setup-sciencestack` |

#### Method B: Subagent Delegation Architecture

`scienceStack` delegates implementation and theoretical verification across 2 specialized subagents:
- **[`science-master`](./agents/science-master.md)** (`Model: "flash"` — `gemini-4-argon-high` / `claude-sonnet-5-5-high`): High-throughput scientific code implementation and MMS test delegate.
- **[`theory-reviewer`](./agents/theory-reviewer.md)** (`Model: "pro"` — `claude-opus-5-5-high`): Line-by-line mathematical proof, sign convention, tensor index, and conservation law auditor.

#### Method C: Standalone Verification Tools & Lifecycle Safety Hook

- **Automatic Pre-Write Safety Hook ([`scripts/hook_pre_tool_guard.py`](./scripts/hook_pre_tool_guard.py))**: Intercepts `write_file` and `edit_file` calls on scientific code files at 0 token cost to block:
  1. Explicit matrix inversion (`np.linalg.inv`, `scipy.linalg.inv`) in favor of factorized linear solves (`solve(A, b)`).
  2. Truncated $\pi$ literals (`3.14159`, `3.1416`) in favor of machine-precision `np.pi`, `math.pi`, or `M_PI`.
  3. Mutable NumPy array defaults in Python function signatures (`def f(x=np.zeros(...)):`).
- **Standalone CLI Tools**:
```bash
# Run automated AST numerical stability audit on scientific Python files
python3 scripts/audit_numerical_ast.py path/to/solver.py

# Run symplectic orbit integration & coordinate transform benchmarks
python3 benchmarks/astronomy/symplectic_nbody.py
python3 benchmarks/astronomy/coordinate_transforms.py
```

---

## 2. Core Scientific Playbooks & Principles

### Scientific Playbooks ([`skills/science-mode/playbooks/`](./skills/science-mode/playbooks/))

| Playbook | Purpose |
| :--- | :--- |
| [`equation-implementation.md`](./skills/science-mode/playbooks/equation-implementation.md) | Translate a continuous mathematical or physical equation from a paper/textbook into verified code with LaTeX docstrings, dimensional checks, and analytical limit tests. |
| [`numerical-verification.md`](./skills/science-mode/playbooks/numerical-verification.md) | Verify asymptotic truncation error order $\mathcal{O}(h^p)$, grid refinement convergence, and conservation law stability. |
| [`perf-issue.md`](./skills/science-mode/playbooks/perf-issue.md) | Profile and eliminate memory-stride, vectorization, or algorithmic bottlenecks while asserting $L_2 < 10^{-12}$ parity. |
| [`hillclimb.md`](./skills/science-mode/playbooks/hillclimb.md) | Iteratively optimize solver throughput or accuracy against a quantitative benchmark target. |
| [`bug-fix.md`](./skills/science-mode/playbooks/bug-fix.md) | Reproduce a numerical or physical defect with a minimal analytical test case, root-cause it, and verify the fix. |
| [`refactoring.md`](./skills/science-mode/playbooks/refactoring.md) | Decouple monolithic legacy simulation loops into pure, stateless `physics/` modules and independent time-steppers. |

### Mathematical & Engineering Principles ([`skills/science-mode/principles/`](./skills/science-mode/principles/))

1. **[`equation-provenance.md`](./skills/science-mode/principles/equation-provenance.md)**: Every equation must carry its continuous LaTeX formulation, literature citation, and physical units in docstrings.
2. **[`dimensional-discipline.md`](./skills/science-mode/principles/dimensional-discipline.md)**: Enforce dimensional consistency across all equations and non-dimensionalize coupled systems via characteristic scales.
3. **[`numerical-stability-first.md`](./skills/science-mode/principles/numerical-stability-first.md)**: Ban explicit matrix inversion (`inv(A) @ b`), guard against catastrophic cancellation (`log1p`, `expm1`), and track condition numbers.
4. **[`preserve-conservation-laws.md`](./skills/science-mode/principles/preserve-conservation-laws.md)**: Use symplectic integrators (Leapfrog, Verlet, Yoshida) for Hamiltonian systems and assert invariant conservation.
5. **[`physics-modular-architecture.md`](./skills/science-mode/principles/physics-modular-architecture.md)**: Isolate pure physical laws (`physics/`) from numerical integrators, meshes, and I/O.
6. **[`verify-analytical-limits.md`](./skills/science-mode/principles/verify-analytical-limits.md)**: Validate solvers against closed-form analytical solutions ($e \to 0$, linear waves, point-mass limits) and MMS benchmarks.

---

## 3. License

MIT License. Maintained as part of the Antigravity scientific computing ecosystem alongside `theoryExtractor`, `fortranBridge`, and `cppBridge`.
