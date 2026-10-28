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
# - sciencestack (enabled, 0.21.1)
#   Components: 12 skills, 2 agents, 1 rule, 4 hooks
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
| **`/numerical-stability-audit`** | Audits solvers for explicit matrix inversion (`inv(A)`), catastrophic cancellation, division by zero, unseeded random states, and stiff ODE hazards. | `/numerical-stability-audit linear_solver.py` |
| **`/precision-audit`** | Audits `float32` vs. `float64` precision drift, condition number amplification $\kappa(A)\epsilon_{\text{mach}}$, and mixed precision. | `/precision-audit solver.py` |
| **`/golden-dataset-benchmark`** | Verifies numerical solvers against Method of Manufactured Solutions (MMS) and canonical reference datasets. | `/golden-dataset-benchmark Run MMS convergence test on navier_stokes.py` |
| **`/check-against-reference`** | Runs your solver on Kepler's equation, Lane-Emden, the Sod shock tube or Robertson kinetics (or compares with your golden data) and exits non-zero unless it matches the documented reference within the stated tolerance. Measures observed order of convergence (`convergence-ode`, `convergence-bvp`), and by default calls the solver twice (`--repeat`, default 2) and fails when the answers differ. In `reference-checks.json` checks can rebuild references from source with pinned SHA-256 hashes. Verified via append-only evidence log (`.verification/log.jsonl`); a tolerance loosened after a failure on unchanged files is withheld (exit 3; requires a `tolerance-approvals.json` entry to release). | `/check-against-reference sod --solver euler.py:solve --tol 0.05` |
| **`/run-tests`** | Runs unittest or pytest, extracts exact framework counts, and records the result bound to the SHA-256 worktree hash; `fresh` verifies whether tests passed on current files. | `/run-tests unittest --start-dir tests` |
| **`/test-ratchet`** | Parses test ASTs at a git baseline and current worktree, exiting 3 on unapproved looser tolerance, removed assertions/tests, new skip/xfail, or reduced parametrization. | `/test-ratchet --baseline-ref origin/main` |
| **`/benchmark-checklist`** | Vets performance and scaling benchmarks (warmup, memory bandwidth limiters, error bars, and $L_2$ parity). | `/benchmark-checklist Profile vectorized vs. scalar solver` |
| **`/setup-sciencestack`** | Configures per-role frontier models (`pro`, `flash`, `inherit`). | `/setup-sciencestack` |

#### Method B: Subagent Delegation Architecture

`scienceStack` delegates implementation and theoretical verification across 2 specialized subagents:
- **[`science-master`](./agents/science-master.md)** (`model: flash` / `inherit`): High-throughput scientific code implementation and MMS test delegate.
- **[`theory-reviewer`](./agents/theory-reviewer.md)** (`model: pro`): Line-by-line mathematical proof, sign convention, tensor index, and conservation law auditor.

#### Method C: Standalone Verification Tools & Lifecycle Safety Hooks

- **Automatic Pre-Write Safety Hook ([`scripts/hook_pre_tool_guard.py`](./scripts/hook_pre_tool_guard.py))**: Intercepts `write_file`, `edit_file`, and tool calls modifying scientific code and blocks (1) explicit matrix inversion (`np.linalg.inv`, `scipy.linalg.inv`, `from numpy.linalg import inv`, `torch.inverse`, resolved via AST import resolution), (2) truncated pi literals (`3.14159`, `3.1416`), and (3) mutable NumPy array default arguments. Comments, docstrings and strings mentioning these are untouched.
- **Verification hooks (opt-in per project)**: In a git repository that uses scienceStack verification (contains `reference-checks.json`, `test-ratchet-approvals.json`, or a `.verification/` directory):
  - **Test guard ([`scripts/hook_test_guard.py`](./scripts/hook_test_guard.py), PreToolUse)**: Prevents silent test weakening (tolerance loosening, test deletion, assertion removal, new skips/xfails) prior to file write/edit unless approved.
  - **Edit recorder ([`scripts/hook_record_edit.py`](./scripts/hook_record_edit.py), PostToolUse)**: Tracks files modified during the active session.
  - **Stop gate ([`scripts/hook_stop_gate.py`](./scripts/hook_stop_gate.py), StopGate)**: Enforces verification discipline before completion—verifying fresh passing reference checks, fresh ratchet passes, and up-to-date test runs.
  - **Fail closed**: Hooks fail closed on invalid states. Set `SCIENCESTACK_HOOKS=off` to temporarily disable them.
- **Standalone CLI Tools**:
```bash
# Run automated AST numerical stability audit on scientific Python files
python3 scripts/audit_numerical_ast.py path/to/solver.py

# Check solver against canonical reference solutions
python3 scripts/check_against_reference.py sod --solver euler.py:solve --tol 0.05

# Run test ratchet check against git baseline
python3 scripts/test_ratchet.py --baseline-ref origin/main

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
| [`perf-issue.md`](./skills/science-mode/playbooks/perf-issue.md) | Profile and eliminate memory-stride, vectorization, or algorithmic bottlenecks while asserting elementwise parity (default rtol $10^{-12}$, atol 0). |
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

## 3. Tests

```bash
pytest tests/   # 594 tests: reference checks, convergence orders, safety hooks, stop gate, ratchet, evidence ledger, AST auditor, MMS/Jacobian generators, reference benchmarks
```

Reference benchmarks (see the docstring of `tests/test_science_tools.py` for sources): Sod shock tube star state (Toro 2009, Table 4.1), Lane-Emden zeros, Kepler/N-body invariants, Robertson mass conservation.

Manual: [`docs/scienceStack_manual.pdf`](./docs/scienceStack_manual.pdf) (LaTeX source alongside).

## 4. License

MIT License. Maintained as part of the Antigravity scientific computing ecosystem alongside `theoryExtractor`, `fortranBridge`, and `cppBridge`.
