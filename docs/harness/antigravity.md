# scienceStack in Antigravity

scienceStack skills were originally designed with Cursor, Claude Code, and Agent Plugins conventions, and expanded for rigorous scientific computing in Antigravity. In Google Antigravity, read this adapter reference once per session, then map each Cursor or Claude Code convention using the tables below. `<scienceStack>` refers to the folder that holds `skills/`, `agents/`, `rules/`, and `docs/`.

---

## Tool Mapping

| Original / Cursor | Antigravity Equivalent | Notes |
| :--- | :--- | :--- |
| `Task` | `invoke_subagent` | Subagents in Antigravity run asynchronously in the background. Wakeup is reactive (no manual polling needed). |
| `AskQuestion` / `AskUserQuestion` | `ask_question` | In non-interactive or batch modes, ask in plain text. |
| Open a todolist / `TodoWrite` | Brain Artifacts or `/plan` | Track plan/todo state in an artifact (`<appDataDir>/brain/<conversation-id>/todo.md`) or use `/plan`. |
| Run another pstack skill (`/name` or "the **name** skill") | Read `<pstack>/skills/<name>/SKILL.md` | Antigravity exposes skills via progressive disclosure (name & description). Skills can be invoked via slash commands or on-demand file reading. |
| `Grep`, `Glob`, `Bash` | `run_command` (`rg`, `find`, `grep`) | Antigravity runs shell commands via `run_command`. |
| `Read`, `Write`, `Edit` | `read_file`, `write_file`, `edit_file` | Dedicated high-precision file tools. |

---

## Subagent Field Mapping

When a pstack skill calls for a subagent:

| Original / Cursor Field | Antigravity `invoke_subagent` Field | Details |
| :--- | :--- | :--- |
| `subagent_type: "science-master"` | `TypeName: "science-master"`, `Role: "science-master"` | `science-master` is registered in `agents/science-master.md`. |
| `subagent_type: "comment-master"` (or `comment-sicko`) | `TypeName: "comment-master"`, `Role: "comment-master"` | `comment-master` is registered in `agents/comment-master.md`. |
| `subagent_type: "theory-reviewer"` | `TypeName: "theory-reviewer"`, `Role: "theory-reviewer"` | Audits mathematical equations, sign conventions, and physical conservation laws. |
| `subagent_type: generalPurpose` | `TypeName: "self"` | Inherits parent agent's configuration, prompt, and toolset. |
| `readonly: true` | `TypeName: "research"` or prompt guard | Use `TypeName: "research"` for read-only codebase exploration, or instruct the subagent not to edit files. |
| `readonly: false` | `TypeName: "self"` | Full read/write and tool capabilities. |
| `environment: "cloud"` / worktree | `Workspace: "branch"` | Creates an isolated branch workspace for concurrent tasks. |
| `environment: "local"` | `Workspace: "inherit"` | Shares the parent workspace directly. |
| `cloud_base_branch: <b>` | In brief: "Checkout branch <b> first" | Include branch instructions in the subagent's `Prompt`. |
| `run_in_background: true` | Omit | Antigravity subagents always run in the background automatically. |
| `resume` | `send_message({ Recipient: <conversationId>, Message: "..." })` | Resumes a running or prior subagent using its conversation ID. |
| `file_attachments` | Include absolute file paths in `Prompt` | Include paths in markdown links (`file:///...`). |

---

## Model Selection & Reasoning Budgets

Antigravity uses high-capability Gemini, Claude, and open-source models, as well as abstract model tiers:

| Original Cursor Slug | Antigravity Model Equivalent | Subagent Model Tier (`Model`) |
| :--- | :--- | :--- |
| `claude-opus-5-5-xhigh` / `claude-opus-5-5-max` | `claude-opus-4-6-thinking` | `"pro"` |
| `claude-sonnet-4-5` / `claude-sonnet-4` | `claude-sonnet-4-6` | `"pro"` or `"inherit"` |
| `grok-4.7-xhigh-fast` / `grok-4.7` | `gemini-3.8-flash-high` | `"flash"` |
| `auto` or `inherit-parent` | Current session model | `"inherit"` |
| Routine / fast worker tasks | `gemini-3.8-flash-medium` | `"flash_lite"` |

### The `pstack-models.md` Rule
* In Antigravity, model preferences are configured by running `/setup-pstack`.
* The rule is stored at `~/.gemini/config/rules/pstack-models.md` (global) or `.agents/rules/pstack-models.md` (project).
* Format: Standard Markdown rule with YAML frontmatter `alwaysApply: true`.

---

## Paths & Storage

| Original / Cursor Path | Antigravity Path | Notes |
| :--- | :--- | :--- |
| `.cursor/skills/`, `~/.cursor/skills/` | `.agents/skills/`, `~/.gemini/config/skills/` | Standard Antigravity skill directories. |
| `~/.cursor/plugins/`, `.cursor-plugin/` | `~/.gemini/config/plugins/`, `.agents/plugins/` | Plugin installation directories. |
| `.cursor/rules/*.mdc` | `AGENTS.md`, `GEMINI.md`, or `.agents/rules/*.md` | Native Markdown rules. |
| Transcripts in `~/.cursor/projects/<slug>/agent-transcripts/` | `<appDataDir>/brain/<conversation-id>/.system_generated/logs/transcript.jsonl` | Antigravity JSONL transcript format. Compact log in `transcript.jsonl`, full log in `transcript_full.jsonl`. |
| Decision logs (`show-me-your-work`) | `<appDataDir>/brain/<conversation-id>/*.md` | Antigravity Brain Artifacts with full formatting, alerts, and mermaid diagrams. |

---

## Cursor-Specific Features in Antigravity

| Cursor Feature | Antigravity Handling |
| :--- | :--- |
| `/loop` command | Use `/schedule` or the `schedule` background timer tool. |
| Cursor Automations & Benny | Benny's triage and repro routines map to Antigravity `hooks.json` lifecycle hooks (`PreToolUse`, `PostInvocation`) and `/schedule` cron jobs. |
| Bugbot comments | Treat Bugbot review comments on PRs as standard review threads using `gh pr review-comments` or GitHub API. |
| Built-in PR tool | Use `run_command` with GitHub CLI: `gh pr create`, `gh pr status`, `gh pr merge`. |

---

## Scientific Coding Framework

`scienceStack_antigravity` includes specialized skills and playbooks for rigorous scientific computing:

* **Playbooks**:
  * [`playbooks/equation-implementation.md`](../skills/science-mode/playbooks/equation-implementation.md): Complete lifecycle from LaTeX theory to discrete implementation with units and analytical checks.
  * [`playbooks/numerical-verification.md`](../skills/science-mode/playbooks/numerical-verification.md): Convergence order analysis ($O(h^p)$), grid refinement studies, and invariant drift monitoring.
* **Skills**:
  * [`scientific-equation-verifier`](../skills/scientific-equation-verifier/SKILL.md): 6-point audit for signs, normalizations, dimensions, and analytical unit tests.
  * [`numerical-stability-audit`](../skills/numerical-stability-audit/SKILL.md): Detects catastrophic cancellation, matrix ill-conditioning, division by zero, and stiff instability.
  * [`golden-dataset-benchmark`](../skills/golden-dataset-benchmark/SKILL.md): Catalog of canonical test problems (CFD, FEM, MD, quantum, ODE/PDE) and golden reference data acquisition/verification.
* **Core Principles**:
  * `principle-equation-provenance`: Explicit LaTeX docstrings and paper citations.
  * `principle-dimensional-discipline`: Dimensional consistency and non-dimensionalization.
  * `principle-preserve-conservation-laws`: Preserve energy, mass, momentum, and norm invariants.
  * `principle-numerical-stability-first`: Floating-point hygiene before premature vectorization.
  * `principle-verify-analytical-limits`: Verification against closed-form benchmarks and MMS.
* **Subagents**:
  * `theory-reviewer` (`agents/theory-reviewer.md`): Line-by-line theoretical auditor.

