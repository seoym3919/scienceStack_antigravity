---
trigger: always_on
description: scienceStack Directives
---
# scienceStack Directives

1. **Equation Provenance**: Document continuous LaTeX equations (`.. math::` or `$...$`) with literature citations and physical units in docstrings.
2. **Numerical Stability**: Never invert matrices explicitly (`inv(A) @ b`); use `solve(A, b)`. Use `log1p`/`expm1` against cancellation; guard denominators; use fixed seeds. `python3 ~/.gemini/config/plugins/sciencestack/scripts/audit_numerical_ast.py <file>` runs AST safety checks.
3. **Astronomy & Orbits**: Never use non-symplectic Runge-Kutta (RK4) for long-term orbit integration; use symplectic Leapfrog or Yoshida splitting (`benchmarks/astronomy/symplectic_nbody.py`). Use orthonormal $\mathrm{SO}(3)$ rotation matrices for ICRS J2000 / Ecliptic / Galactic transforms.
4. **Physics Modularity**: Isolate pure physical laws, forces, and equations of state into stateless `physics/` modules decoupled from time steppers, meshes, and I/O.
5. **Reference Checks**: Validate solvers with `python3 ~/.gemini/config/plugins/sciencestack/scripts/check_against_reference.py` (`list`, `run`, `compare`, `run-manifest` for `reference-checks.json`; `ref_from`/`test_from` rebuild a legacy reference for translations). Say "passes" only for exit 0 and quote the tolerance; report exit 1, 2, 3 as what they are; never choose or loosen a tolerance to make a check pass. Before calling a solver validated, `check_against_reference.py evidence fresh --subject <solver file>` must exit 0. See the `check-against-reference` skill.
6. **Tests**: Run tests with `python3 ~/.gemini/config/plugins/sciencestack/scripts/run_tests.py unittest|pytest` and say they pass only after `run_tests.py fresh` exits 0 (a passing run on exactly the current files); quote the counts.
7. **Test Ratchet**: Before committing changes to tests, `python3 ~/.gemini/config/plugins/sciencestack/scripts/test_ratchet.py --baseline-ref HEAD` (or origin/main) must exit 0: no looser tolerance, removed test or assertion, or new skip unless the user approved it in `test-ratchet-approvals.json`.
8. **Hooks**: In a project using scienceStack verification, an edit that weakens a test, manifest, approvals file, golden file or the evidence log is asked about (denied in auto/bypassPermissions modes), and the stop gate blocks once if edited files lack a fresh passing check. Do not work around either: re-run the check, or say plainly it was not run. `SCIENCESTACK_HOOKS=off` is for the person, not for you.
