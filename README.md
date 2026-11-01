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
# - sciencestack (enabled, 0.23.0)
#   Components: 12 skills, 2 agents, 2 rules, 1 hook
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
| **`/check-against-reference`** | Runs your solver on Kepler's equation, Lane-Emden, the Sod shock tube, Robertson kinetics, a Timoshenko cantilever (`beam-timoshenko`), Hilbert systems (`linear-solve-hilbert`) or the Ghia lid-driven cavity (`cavity-ghia`), or compares with your golden data (`compare`, elementwise or by relative norm per field with `--norm l1\|l2\|linf --norm-tol X --blocks N`), and exits non-zero unless it matches the documented reference within the stated tolerance. Measures the observed order of convergence of ODE integrators, 1-D boundary-value solvers and 2-D Poisson solvers against exact solutions (`convergence-ode`, `convergence-bvp`, `poisson-2d`), and of your own solver against your own exact or manufactured solution (`convergence-user --exact mms.py:exact_solution`, with that module written by `mms_generator.py`), and by default calls the solver twice (`--repeat`, default 2) and fails when the answers differ. In `reference-checks.json` a `compare` check can **rebuild** its reference (compile and run the legacy Fortran/C) and produce the port's output (`ref_from`, `test_from`), with the sources and inputs pinned by SHA-256, instead of trusting committed output files. Every run is logged with file hashes (`.verification/log.jsonl`); a tolerance loosened after a failure on unchanged files is withheld (exit 3), with a history per solver file and function, so a renamed or copied solver starts a new one; `run-manifest` re-runs a committed `reference-checks.json` and refuses to let CI weaken it. | `/check-against-reference sod --solver euler.py:solve --tol 0.05` |
| **`/run-tests`** | Runs unittest or pytest, takes the counts from the framework, and records the result bound to a hash of every project file; `fresh` says whether the tests passed on exactly the current files. | `/run-tests unittest --start-dir tests` |
| **`/test-ratchet`** | Parses the test files at a git baseline and now, and exits 3 on any unapproved looser tolerance, removed test or assertion, new skip/xfail or fewer parametrize cases. | `/test-ratchet --baseline-ref origin/main` |
| **`/benchmark-checklist`** | Vets performance and scaling benchmarks (warmup, memory bandwidth limiters, error bars, and $L_2$ parity). | `/benchmark-checklist Profile vectorized vs. scalar solver` |
| **`/setup-sciencestack`** | Configures per-role frontier models (`pro`, `flash`, `inherit`). | `/setup-sciencestack` |

#### Method B: Subagent Delegation Architecture

`scienceStack` delegates implementation and theoretical verification across 2 specialized subagents:
- **[`science-master`](./agents/science-master.md)** (`model: flash` / `inherit`): High-throughput scientific code implementation and MMS test delegate.
- **[`theory-reviewer`](./agents/theory-reviewer.md)** (`model: pro`): Line-by-line mathematical proof, sign convention, tensor index, and conservation law auditor.

#### Method C: Standalone Verification Tools & Lifecycle Safety Hooks

- **Automatic Pre-Write Safety Hook ([`scripts/hook_pre_tool_guard.py`](./scripts/hook_pre_tool_guard.py))**: Intercepts `write_file`, `edit_file` (and best-effort `run_command` writes into a scientific source file) and **asks** about (1) explicit matrix inversion (`np.linalg.inv`, `scipy.linalg.inv`, `from numpy.linalg import inv`, `torch.inverse`, a negative `matrix_power`, `.I` of a `numpy.matrix`, ... resolved through imports and aliases, not by substring), (2) truncated pi literals (`3.14159`, `3.1416`) outside tests, and (3) mutable NumPy array default arguments. The hook answers `force_ask`, so a cached "Always Allow" does not skip it. Comments, docstrings, strings, and text a shell command merely mentions are not flagged. Where the inverse really is the result, end the line with `# sciencestack: inverse-is-the-result`: the hook lets it through and the auditor lists it as `ALLOWED_MATRIX_INV`. The parsed checks and the AST auditor apply to Python only: for C++, Fortran, Julia and Rust the hook runs a regular expression, and the auditor does nothing.
- **Verification hooks (opt-in per project)**: in a git project that already uses scienceStack verification (it contains `reference-checks.json`, `test-ratchet-approvals.json` or a `.verification/` directory), these hooks act. Everywhere else they do nothing.
  - **Test guard ([`scripts/hook_test_guard.py`](./scripts/hook_test_guard.py), PreToolUse)**: before an `edit_file` or `write_file`, it compares the file as it *would be* after the edit with the file now, using the same comparison as `test_ratchet.py`, and **asks** if a test would be weakened: looser tolerance, removed test or assertion, new skip/xfail, fewer parametrize cases. It also asks before any change to `reference-checks.json` that raises a tolerance, removes a check or adds an `approved_relaxation`, any change to `test-ratchet-approvals.json`, to a golden file named in the manifest, or to `.verification/`, and (best effort) before a shell command that redirects into, `sed -i`'s, moves onto, removes or opens for writing such a file. Findings already approved in `test-ratchet-approvals.json` are not asked about again.
  - **Edit recorder ([`scripts/hook_record_edit.py`](./scripts/hook_record_edit.py), PostToolUse) and stop gate ([`scripts/hook_stop_gate.py`](./scripts/hook_stop_gate.py), Stop)**: the recorder remembers which project files this session changed; when the agent tries to finish, the gate checks the evidence log for those files and **blocks once** if an edited solver or compared output has no fresh passing check, a recorded test run is stale, or edited test files have no fresh `test_ratchet.py` run. The recorder also runs after `run_command`, remembering the newest evidence-log line, and the gate blocks if a line it saw has gone: the hash chain alone cannot see a dropped tail. Deleting `.verification/` from a project with no other marker counts as opting out. It looks at the files, not at what the agent says, never blocks inside its own continuation or while background tasks are running, and raises each distinct situation once.
  - **Fail closed once the script is running**: invalid input asks (or, for the stop gate, blocks once) with the error text. Escape hatches belong to the person: `SCIENCESTACK_HOOKS=off` in Antigravity's environment turns every hook into a no-op.
  - **Limits**: edits made through other programs or indirection are invisible to the hooks; the person's own terminal is not hooked; the stop gate cannot see a claim made without any edit, or a record dropped by the same shell command that wrote it. `git checkout <old> -- tests/x.py` restores a weaker test without the shell guard noticing. The shell rule for the evidence log is deliberately broad: it asks about any command that mentions the log and writes a file, even a different one. `test_ratchet.py` and CI are the checks that do not depend on hooks.
- **Standalone CLI Tools**:
```bash
# Run automated AST numerical stability audit on scientific Python files
python3 scripts/audit_numerical_ast.py path/to/solver.py

# Check solver against canonical reference solutions
python3 scripts/check_against_reference.py run sod --solver euler.py:solve --tol 0.05

# Run test ratchet check against git baseline
python3 scripts/test_ratchet.py --baseline-ref origin/main

# Run symplectic orbit integration & coordinate transform benchmarks
python3 benchmarks/astronomy/symplectic_nbody.py
python3 benchmarks/astronomy/coordinate_transforms.py

# Print what a tolerance means for the Sod benchmark
python3 benchmarks/cfd/sod_calibration.py
```

### Verifying a Solver

Every check is run by `scripts/check_against_reference.py`, which exits 0 only on a pass and records the verdict with the hash of the files it depends on. `list` prints each contract, reference and tolerance rule.

| Check | Your function | Reference | Tolerance |
| :--- | :--- | :--- | :--- |
| `kepler` | `solve(M, e) -> E` | bisection on Kepler's equation, and its residual | default 1e-12 absolute |
| `lane-emden` | `solve(n) -> {"xi_1", "omega_n"}` | closed forms (n = 0, 1); high-accuracy integration (n = 1.5, 3) | `--tol` required |
| `sod` | `solve(x, t) -> {"density", "velocity", "pressure"}` | exact Riemann solution (Toro 2009) | `--tol` required, relative L1 per field |
| `robertson` | `solve(t) -> [y1, y2, y3]` | three implicit integrators, and the mass invariant | `--tol` required |
| `beam-timoshenko` | `solve(L, E, G, I, A, kappa, P) -> delta` | closed form with the shear term (Timoshenko 1921) | default 1e-12 relative |
| `linear-solve-hilbert` | `solve(A, b) -> x`, n = 3 ... 12 | residual of a backward-stable solve; forward error and exact condition number reported, not judged | default 1e-12 |
| `cavity-ghia` | `solve(Re) -> {"y", "u"}`, Re = 100, 1000 | Ghia, Ghia & Shin (1982), Table I | `--tol` required, at least 1e-3 |
| `convergence-ode` | `integrate(f, y0, t0, t1, n) -> y(t1)` | four ODEs with exact solutions | claim `--order P` |
| `convergence-bvp` | `solve(n, f) -> [u_0 .. u_n]` | two 1-D Poisson problems | claim `--order P` |
| `poisson-2d` | `solve(n) -> u[i][j]` | exact solution on the unit square | claim `--order P` |
| `convergence-user` | `solve(n) -> (points, values)` | your exact or manufactured solution, `--exact FILE:FUNC` | claim `--order P` |
| `compare` | two files of numbers | your golden data | `--rtol` and `--atol`, or `--norm` and `--norm-tol` |

The tolerances need calibrating against what they can see. A Sod solution with its shock one cell out of place has a relative L1 error of 0.015 to 0.042, so `--tol 0.05` cannot tell it from the exact one. The cavity table is itself a 129 x 129 computation, taken from two independently kept copies compared by program rather than from the paper; Re = 100 is re-derived in the tests by a separate solver, Re = 1000 is not.

To measure the order of a solver on your own equation:

```bash
# Write mms.py with exact_solution and source_term; put source_term into your solver as the forcing
python3 scripts/mms_generator.py --exact "sin(pi*x)*sin(pi*y)" --operator="-diff(u, x, 2) - diff(u, y, 2)" --output mms.py

# Measure the order; solve(n) returns (points, values) on its own grid
python3 scripts/check_against_reference.py run convergence-user --solver solver.py:solve --exact mms.py:exact_solution --order 2
```

An operator that starts with a minus sign needs the `--operator=` form. Elementwise `compare` is the rule for ports; `compare --norm` is for a new scheme against a reference solution. A loosened tolerance after a failure on unchanged files is withheld, and in a manifest it is a ratchet violation. Manifest steps run without a shell, and a step that starts one is refused.

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
python3 -m pytest tests/   # reference checks, convergence orders, safety hooks, stop gate, ratchet, evidence ledger, AST auditor, MMS/Jacobian generators, reference benchmarks
```

`python3 scripts/run_tests.py unittest --start-dir tests` reports the current count and records it. Reference benchmarks (see the docstrings of `tests/test_science_tools.py` and `tests/test_engineering_references.py` for sources): Sod shock tube star state (Toro 2009, Table 4.1), Lane-Emden zeros, Kepler/N-body invariants, Robertson mass conservation, Timoshenko deflection, Hilbert condition numbers, Ghia cavity Table I.

Manual: [`docs/scienceStack_manual.pdf`](./docs/scienceStack_manual.pdf) (LaTeX source alongside).

## 4. License

MIT License. Maintained as part of the Antigravity scientific computing ecosystem alongside `theoryExtractor`, `fortranBridge`, and `cppBridge`.
