# scienceStack Antigravity Directives

1. **Tool Invocation Directives**:
   - Translate `Task` subagent calls to `invoke_subagent` (`TypeName`: `"science-master"` for code, `"theory-reviewer"` for theoretical audit, `"comment-master"` for cleanup, `"research"` for read-only).
   - Use `Workspace: "branch"` for isolated work; `Workspace: "inherit"` for local shared tasks.
   - Translate `AskQuestion` to `ask_question`. Use `run_command` (`rg`, `find`) and `read_file` for exploration.

2. **Model Selection & Routing**:
   - Code tasks: `Model: "flash"` (`gemini-3.8-flash-high`).
   - Judgment, proofs, and theory audits: `Model: "pro"` (`claude-opus-4-6-thinking`).
   - Worker / routine linting: `Model: "flash_lite"` (`gemini-3.8-flash-medium`).
   - Parent inheritance: `Model: "inherit"`. Overrides in `~/.gemini/config/rules/pstack-models.md`.

3. **Subagents & Transcripts**:
   - Subagents run asynchronously in background. Do not poll or sleep; rely on reactive wakeup.
   - Transcripts: Read `<appDataDir>/brain/<conversation-id>/.system_generated/logs/transcript.jsonl`.
   - Decision trails: Record to `<appDataDir>/brain/<conversation-id>/` artifacts.

4. **Scientific Coding & Astronomy Rules**:
   - **Equation Provenance**: Every formula must have continuous LaTeX in docstrings with paper citations.
   - **Numerical Stability**: Never use explicit matrix inversion (`inv(A) @ b`); use `solve(A, b)`. Prevent cancellation via `log1p`, `expm1`. Guard divisions.
   - **Astronomy & Orbits**: Standard Runge-Kutta is strictly prohibited for long-term orbit integration due to secular energy drift. Use symplectic Leapfrog / Yoshida splitting (`benchmarks/astronomy/symplectic_nbody.py`).
   - **Coordinate Frames**: Transformations between ICRS J2000, Ecliptic, and Galactic must use orthonormal $\mathrm{SO}(3)$ rotation matrices (`benchmarks/astronomy/coordinate_transforms.py`).
   - **Physics Modularity**: Isolate pure physical laws, forces, and equations of state into dedicated, stateless modules (`physics/`), completely decoupled from time steppers, grid meshes, and I/O so external solvers can import them directly.
   - **Automated Verification**: Run `python3 scripts/audit_numerical_ast.py <file>` for AST safety checks. Load `skills/astronomy-computing` or `skills/scientific-equation-verifier` for deep domain guidance.
