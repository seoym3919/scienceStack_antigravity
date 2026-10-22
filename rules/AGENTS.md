# scienceStack Antigravity Runtime Directives

When scienceStack is active in an Antigravity workspace or session:

1. **Tool Invocation Directives**:
   - Translate all `Task` subagent requests to `invoke_subagent`.
   - Set `TypeName` to `"science-master"` for code delegates, `"comment-master"` for comment cleanup, `"theory-reviewer"` for theoretical audit, `"research"` for read-only exploration, or `"self"` for general tasks.
   - Set `Workspace: "branch"` whenever a skill requests `environment: "cloud"` or an isolated git worktree; use `Workspace: "inherit"` for local shared tasks.
   - For interactive inquiries (originally `AskQuestion`), use the `ask_question` tool.
   - For file exploration, use `run_command` (`rg`, `find`) and `read_file`.

2. **Model Selection & Routing**:
   - Model configurations are defined in `~/.gemini/config/rules/pstack-models.md` or `.agents/rules/pstack-models.md`.
   - If no custom rule is present, apply Antigravity defaults:
     - Code tasks (`feature`, `refactoring`, `bug-fix`, `perf-issue`, `hillclimb`, `swarm workers`): `gemini-3.8-flash-high` (or `Model: "flash"`).
     - Judgment, architecture, prose, and reviews (`hardest tasks`, `judgment and prose`, `architect`, `interrogate`): `claude-opus-4-6-thinking` (or `Model: "pro"`).
     - Standard parent inheritance (`auto` or `inherit-parent`): `Model: "inherit"`.

3. **Subagent Lifecycle**:
   - Subagents run asynchronously in the background. Do NOT poll or sleep; rely on the system's reactive message delivery.
   - Communicate with running subagents via `send_message({ Recipient: <conversationId>, Message: ... })`.

4. **Transcripts & Artifacts**:
   - When inspecting prior session transcripts (e.g. in `reflect` or `eval`), read from `<appDataDir>/brain/<conversation-id>/.system_generated/logs/transcript.jsonl`.
   - When recording decision trails (e.g. in `show-me-your-work`), create structured Markdown artifacts in `<appDataDir>/brain/<conversation-id>/`.

5. **Scientific Coding & Theoretical Accuracy Directives**:
   - **Equation Provenance**: Every mathematical formula must state its continuous equation in LaTeX in docstrings, cite the textbook or paper equation number, and explicitly document coordinate systems and sign conventions.
   - **Dimensional Consistency**: Validate that dimensions match on both sides of every equation ($[LHS] = [RHS]$) and that transcendental function arguments ($\exp, \ln, \sin$) are strictly dimensionless.
   - **Numerical Stability**: Eliminate catastrophic cancellation ($a - b$ for $a \approx b$); guard against division by zero; use `scipy.special.logsumexp`, `expm1`, and `log1p` for small/large values; never use explicit matrix inversion (`inv(A) @ b`); use `solve(A, b)`.
   - **Analytical & Conservation Verification**: Validate code against exact closed-form analytical solutions or the Method of Manufactured Solutions (MMS) with explicit tolerances (`rtol`, `atol`). Assert conservation of physical invariants (energy, mass, probability) over simulation time.
   - **Golden Datasets & Industry Benchmarks**: Whenever possible, validate numerical code against canonical industry benchmarks (e.g. Sod shock tube, Taylor-Green vortex, Lid-driven cavity, Cook's membrane, Robertson kinetics) or golden reference datasets stored in `tests/golden/` with explicit relative $L_2$ error thresholds.
   - **Theory Reviewer**: For scientific changes or equation implementations, spawn a theoretical audit subagent (`TypeName: "theory-reviewer"` or `"self"` with `Model: "pro"` / `claude-opus-4-6-thinking`) to verify equations, signs, and normalization constants before merging.

6. **Astronomy & Celestial Mechanics Directives**:
   - **Symplectic Integration**: In orbit and N-body dynamics, standard explicit Runge-Kutta integrators are strictly prohibited for long-term integration due to artificial secular energy drift ($dE/dt \neq 0$). Use symplectic Leapfrog / Drift-Kick-Drift or Yoshida 4th-order splitting, asserting energy and angular momentum conservation ($|\Delta E(t) / E(0)| < \tau$). Reference: `benchmarks/astronomy/symplectic_nbody.py`.
   - **Kepler's Equation & Vis-Viva Invariants**: Solve $M = E - e \sin E$ using Danby/Prussing conditioned starters with cubic Halley iteration. Always verify the vis-viva invariant $v^2/2 - \mu/r = -\mu/(2a)$ and specific angular momentum vector $\mathbf{h} = \mathbf{r} \times \mathbf{v}$. Reference: `benchmarks/astronomy/kepler_solver.py`.
   - **Stellar Structure & Polytropes**: In solving Lane-Emden or stellar structure equations, coordinate singularities at the stellar center ($\xi = 0$) must be removed via analytic series expansions ($\theta(\xi) \approx 1 - \xi^2/6 + \dots$). Reference: `benchmarks/astronomy/lane_emden_solver.py`.
   - **Celestial Coordinate Frames**: Coordinate transformations between Equatorial (J2000 ICRS), Ecliptic, and Galactic frames must strictly employ orthonormal rotation matrices $\mathbf{R} \in \mathrm{SO}(3)$ satisfying $\mathbf{R}^T \mathbf{R} = \mathbf{I}$ and $\det \mathbf{R} = 1$ to machine precision. Reference: `benchmarks/astronomy/coordinate_transforms.py`.

7. **Automated Verification & Tooling**:
   - Run `python3 scripts/audit_numerical_ast.py <file>` to verify AST compliance (matrix inversion bans, cancellation hazards, float32 traps).
   - Use `python3 scripts/mms_generator.py` for Method of Manufactured Solutions derivations and test generation.
   - Use `python3 scripts/derive_jacobian.py` for symbolic Jacobian matrix synthesis.
