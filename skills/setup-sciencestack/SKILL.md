---
name: setup-sciencestack
description: Configure which models scienceStack uses per role and at what reasoning budget. Detects your available models and writes an always-applied rule that overrides the skill defaults. Use for /setup-sciencestack, /setup-pstack, "configure scienceStack models", "scienceStack budget", or changing scienceStack's model choices.
---

# Setup scienceStack

Write `~/.gemini/config/rules/pstack-models.md` (or `~/.cursor/rules/pstack-models.mdc` in Cursor), an always-applied rule that sets scienceStack's model per role.

## Steps

### 1. Detect available models

Enumerate the model slugs you can pass in this session. In Antigravity, run `agy models` or inspect the available session models (e.g. `gemini-3.8-flash-high`, `claude-opus-4-6-thinking`, `claude-sonnet-4-6`, `gpt-oss-120b-medium`) or subagent model tiers (`pro`, `flash`, `flash_lite`, `inherit`). In Cursor, check the Task subagent model list. If you cannot detect any, ask the user to paste the models they have access to. The aliases `inherit-parent` and `auto` are always valid.

### 2. Load current state

The default role-to-model mapping is the rule shape shown in step 5 below. If `~/.gemini/config/rules/pstack-models.md` (or `~/.cursor/rules/pstack-models.mdc`) already exists, read it and treat its `# budget` line and its role values as the current choices. Otherwise start from those defaults.

### 3. Budget, map, and confirm

**(a) Ask for a budget.** In Antigravity use `ask_question`; in Cursor use `AskQuestion`. Offer these four options with these exact labels, and name the current budget when the rule records one. With no rule, say that `large` matches the skill defaults.

- `unlimited — max reasoning`
- `large — xhigh reasoning`
- `medium — high reasoning`
- `small — medium reasoning`

**(b) Apply it.** Build the working table from the defaults:
- Antigravity defaults: `gemini-3.8-flash-high` for code workers, `claude-opus-4-6-thinking` for judgment/prose/hardest tasks.
- On a re-run keep any role you changed by family, list, or alias (`inherit-parent`, `auto`).

**(c) Show the roles and confirm.** Show every role with its model. Ask whether to accept as-is or change specific roles using `ask_question`. For panel roles (arena runners, architect runners, interrogate reviewers) the value is a list, and one subagent runs per entry.

### 4. Validate

Every real slug written must be in the detected set. `inherit-parent` and `auto` always pass.

### 5. Write the rule

In Antigravity, write `~/.gemini/config/rules/pstack-models.md` (or `.agents/rules/pstack-models.md`); in Cursor, write `~/.cursor/rules/pstack-models.mdc`. Include `alwaysApply: true` in the frontmatter, a `# budget` line, and one line per role. Overwrite the whole file so re-runs stay idempotent.

Antigravity shape:

```markdown
---
description: pstack per-role model choices (overrides skill defaults)
alwaysApply: true
---
# pstack model configuration. One line per role. Delete a line to fall back to the skill default.
# `inherit-parent` or `auto` as a value: the role runs on the parent chat model.
# budget: large (xhigh)
feature, refactoring: gemini-3.8-flash-high
bug-fix: gemini-3.8-flash-high
perf-issue: gemini-3.8-flash-high
hillclimb: gemini-3.8-flash-high
judgment and prose: claude-opus-4-6-thinking
hardest tasks: claude-opus-4-6-thinking
how explorer: gemini-3.8-flash-high
how explainer: claude-opus-4-6-thinking
why investigators: gemini-3.8-flash-high
why synthesizer: claude-opus-4-6-thinking
reflect tooling: gemini-3.8-flash-high
reflect judgment, divergent, synthesizer: claude-opus-4-6-thinking
arena runners: claude-opus-4-6-thinking, gemini-3.8-flash-high
arena cross-judge pool: claude-opus-4-6-thinking, gemini-3.8-flash-high
swarm workers: gemini-3.8-flash-high
architect runners: claude-opus-4-6-thinking, gemini-3.8-flash-high
interrogate reviewers: claude-opus-4-6-thinking, gemini-3.8-flash-high
theory reviewer: claude-opus-4-6-thinking
numerical auditor: gemini-3.8-flash-high
```

### 6. Confirm

Tell the user the rule was written and that it applies to new sessions. Re-running this skill updates it.

### 7. Offer a verification skill (optional)

Check whether the project has a way to drive the real app for proof (a `verify-*` skill, or an existing harness). If not, offer once: "want a project-local verification skill, so agents can drive the app the way a user does and prove changes work? I can generate one with /create-verification-skill." On yes, invoke `/create-verification-skill` (resolves wherever pstack is installed: workspace, user, or plugin). On no, move on without pushing.

### 8. Offer a formal verification skill (optional)

Check whether the project already has a formal verification skill (a project skill that runs a model checker, a proof, or another verifier against the code). If not, offer once: "want a formal verification skill, so agents can prove a key property of your code holds in every case in scope, not only the cases tests reach? I can generate one with /create-formal-verification-skill." On yes, invoke `/create-formal-verification-skill` (resolves wherever pstack is installed: workspace, user, or plugin). On no, move on without pushing.
