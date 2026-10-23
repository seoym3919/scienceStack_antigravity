---
name: setup-sciencestack
description: Configure which models scienceStack uses per role (Gemini 4, Claude Opus 5.5, Claude Sonnet 5.5) and at what reasoning budget.
disable-model-invocation: true
---

# /setup-sciencestack

Configure per-role model assignments in `~/.gemini/config/rules/scstack-models.md`.

## Steps

1. **Detect Available Models**:
   - Run `agy models` to list available models (`gemini-4-argon-high`, `gemini-4-argon-medium`, `claude-opus-5-5-high`, `claude-sonnet-5-5-high`) and subagent tiers (`pro`, `flash`, `flash_lite`, `inherit`).
2. **Confirm Role Mapping**:
   - Use `ask_question` to confirm or customize the role assignments below.
3. **Write `~/.gemini/config/rules/scstack-models.md`**:

```markdown
---
description: scienceStack per-role model configuration
alwaysApply: true
---
# scienceStack model configuration
code_implementation: gemini-4-argon-high
architecture_synthesis: claude-sonnet-5-5-high
theory_reviewer: claude-opus-5-5-high
numerical_auditor: claude-opus-5-5-high
fast_worker: gemini-4-argon-medium
```
