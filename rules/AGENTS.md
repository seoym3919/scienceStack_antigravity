# scienceStack Directives

1. **Equation Provenance**: Document continuous LaTeX equations (`.. math::` or `$...$`) with literature citations and physical units in docstrings.
2. **Numerical Stability**: Never invert matrices explicitly (`inv(A) @ b`); use `solve(A, b)`. Prevent catastrophic cancellation via `log1p`/`expm1` and guard denominators. Run `python3 ~/.gemini/config/plugins/sciencestack/scripts/audit_numerical_ast.py <file>` for AST safety checks.
3. **Astronomy & Orbits**: Never use non-symplectic Runge-Kutta (RK4) for long-term orbit integration; use symplectic Leapfrog or Yoshida splitting (`benchmarks/astronomy/symplectic_nbody.py`). Use orthonormal $\mathrm{SO}(3)$ rotation matrices for ICRS J2000 / Ecliptic / Galactic transforms.
4. **Physics Modularity**: Isolate pure physical laws, forces, and equations of state into stateless `physics/` modules decoupled from time steppers, meshes, and I/O.
