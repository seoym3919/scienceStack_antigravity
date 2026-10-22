# scienceStack Code Delegate Principles

Compact implementation guide for `science-master` worker subagents.

## Core Directives for Scientific Code

1. **Continuous Equation Provenance**:
   - Every scientific function must state its continuous governing equation in LaTeX in its docstring.
   - Cite textbook or literature equation number, specifying coordinate systems and sign conventions.

2. **Dimensional Discipline**:
   - Verify dimensional homogeneity ($[\text{LHS}] = [\text{RHS}]$).
   - Ensure arguments to transcendental functions ($\exp, \ln, \sin$) are strictly dimensionless.

3. **Numerical Stability First**:
   - **Banned**: Never use explicit matrix inversion (`np.linalg.inv(A) @ b` or `inv(A)`). Always use `np.linalg.solve(A, b)` or appropriate factorizations (Cholesky, LU, QR).
   - **Cancellation**: Avoid catastrophic cancellation ($a - b$ for $a \approx b$). Use `log1p(x)` for $\ln(1+x)$, `expm1(x)` for $e^x - 1$, and $2\sin^2(x/2)$ for $1 - \cos(x)$.
   - **Guards**: Never divide by raw geometric distances without zero guards (use $\sqrt{r^2 + \epsilon^2}$ or `denom + 1e-15`).

4. **Preservation of Invariants**:
   - For Hamiltonian systems and celestial mechanics, explicit Runge-Kutta is forbidden for long-term integration. Use symplectic Leapfrog (Drift-Kick-Drift) or Yoshida integrators.
   - Track and assert physical invariants: energy $E(t)$, linear momentum $\mathbf{P}(t)$, angular momentum $\mathbf{L}(t)$, and mass/probability sums.

5. **Analytical & Golden Verification**:
   - Write automated unit tests verifying the implementation against closed-form analytical benchmarks or the Method of Manufactured Solutions (MMS) with explicit relative tolerances (`rtol`, `atol`).
   - Run `python3 scripts/audit_numerical_ast.py <file>` to verify AST compliance before reporting completion.

6. **Physics-Modular Architecture**:
   - Decouple pure physical laws (equations of state, forces, rate equations, potentials) from numerical time steppers, spatial grids, and simulation loops.
   - Structure physics routines as stateless, callable pure functions in dedicated modules (`physics/`) so other solvers or external codes can import and call them directly.

7. **Execution Discipline**:
   - Work in an isolated branch (`Workspace: "branch"`).
   - Return a clean diff summary with empirical test results to the parent orchestrator.
