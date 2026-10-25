---
name: science-mode
description: Rigorous scientific engineering workflow for theoretical fidelity, equation provenance, dimensional consistency, numerical stability, and closed-loop verification.
disable-model-invocation: true
argument-hint: "<task>"
---

# /science-mode — Native Antigravity Scientific Engineering Workflow

Execute scientific computing, physics modeling, and numerical solver tasks with formal mathematical rigor and minimal token overhead.

## 1. Core Scientific Non-Negotiables

1. **Equation Provenance ([`principles/equation-provenance.md`](principles/equation-provenance.md))**:
   - Document continuous governing equations in standard LaTeX (`.. math::` or `$$...$$`) with canonical literature citations and physical units (`[SI]` / `[CGS]`) in docstrings.
2. **Dimensional Discipline ([`principles/dimensional-discipline.md`](principles/dimensional-discipline.md))**:
   - Verify dimensional homogeneity across all terms before implementation. Non-dimensionalize coupled PDEs/ODEs where appropriate.
3. **Numerical Stability First ([`principles/numerical-stability-first.md`](principles/numerical-stability-first.md))**:
   - Never invert matrices explicitly (`inv(A) @ b`); always use factorized linear solvers (`np.linalg.solve(A, b)` or `scipy.linalg.solve`).
   - Guard against catastrophic cancellation (`log1p`, `expm1`, `hypot`) and division by zero.
   - Run `python3 ~/.gemini/config/plugins/sciencestack/scripts/audit_numerical_ast.py <file>` on modified numerical files.
4. **Conservation Laws & Symplectic Structure ([`principles/preserve-conservation-laws.md`](principles/preserve-conservation-laws.md))**:
   - Never use non-symplectic Runge-Kutta (RK4) for long-term Hamiltonian or orbital mechanics integration; use symplectic Leapfrog/Verlet or Yoshida splitting.
   - Track conserved Noether invariants (energy, momentum, angular momentum, mass/flux) in tests.
5. **Physics Modularity ([`principles/physics-modular-architecture.md`](principles/physics-modular-architecture.md))**:
   - Isolate pure physical laws, forces, and equations of state into stateless `physics/` modules decoupled from time-steppers, grid meshes, and I/O.
6. **Analytical Limits & MMS ([`principles/verify-analytical-limits.md`](principles/verify-analytical-limits.md))**:
   - Verify solvers against closed-form analytical limits ($e \to 0$, linear regime, single-body limit) or the Method of Manufactured Solutions (MMS).

---

## 2. Playbook Selection

Read **only** the single playbook matching the user's task:
- **Implementing a physical law or equation**: [`playbooks/equation-implementation.md`](playbooks/equation-implementation.md)
- **Auditing numerical convergence, stability, or invariants**: [`playbooks/numerical-verification.md`](playbooks/numerical-verification.md)
- **Optimizing solver throughput, vectorization, or memory layout**: [`playbooks/perf-issue.md`](playbooks/perf-issue.md) or [`playbooks/hillclimb.md`](playbooks/hillclimb.md)
- **Diagnosing a numerical or physical bug**: [`playbooks/bug-fix.md`](playbooks/bug-fix.md)
- **Decoupling monolithic simulation code into modular physics**: [`playbooks/refactoring.md`](playbooks/refactoring.md)

Bundled domain skills live at `../<skill>/SKILL.md` (`astronomy-computing`, `accelerated-scientific-computing`, `scientific-equation-verifier`, `numerical-stability-audit`, `precision-audit`, `golden-dataset-benchmark`, `benchmark-checklist`).

---

## 3. Subagent Delegation (Gemini 4, Claude Opus 5.5, Claude Sonnet 5.5)

- **Implementation Delegate (`science-master`)**:
  - `invoke_subagent({ TypeName: "science-master", Model: "flash", Workspace: "inherit", ... })`
  - Uses `gemini-4-argon-high` / `claude-sonnet-5-5-high` for fast kernel implementation, vectorization, and unit test construction.
- **Theoretical & Mathematical Auditor (`theory-reviewer`)**:
  - `invoke_subagent({ TypeName: "theory-reviewer", Model: "pro", Workspace: "inherit", ... })`
  - Uses `claude-opus-5-5-high` to audit governing equations, sign conventions, index ordering, and conservation laws line-by-line.
