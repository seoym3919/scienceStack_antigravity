# scienceStack (Antigravity Scientific Stack)

**scienceStack** is an Antigravity-native, scientifically rigorous agent workflow plugin adapted from [pstack](https://github.com/cursor/plugins/tree/main/pstack) by [poteto](https://x.com/poteto). It specializes agent orchestration for computational science, engineering, and mathematical computing—ensuring equation provenance, theoretical fidelity, dimensional consistency, and numerical stability.

there's a growing sense that ai writes too much slop code. in scientific computing, slop means ungrounded formulas, silent catastrophic cancellation, flipped signs, broken conservation laws, and dimensional mismatch. throughput without quality and theoretical accuracy is dangerous. if you want to go fast, go deep first. 

**scienceStack is the answer.** these skills turn agents into a rigorous scientific engineering team. the goal is not to maximize loc, in fact it's the opposite: write less, but provably correct, numerically stable scientific code.

**scienceStack gives you fearless parallelism.** when you can go deep on one agent and trust it to verify equations against theory and golden benchmark datasets, you can truly parallelize with confidence. start multiple agents up with `science-mode` and trust that they'll apply rigorous mathematical and engineering principles to their work.

**antigravity gives you the best of all worlds.** multi-model workflows route numerical kernels to fast high-throughput workers and theoretical derivations or architecture audits to high-reasoning models (`pro`).

## install

in antigravity:

```bash
# Global install:
agy plugin install /home/seo3919/AI_skills/scienceStack_antigravity

# Or workspace-local:
# Place scienceStack_antigravity in .agents/plugins/sciencestack
```

The [Antigravity adapter](./docs/harness/antigravity.md) maps all tools (`invoke_subagent`, `ask_question`), model slugs, and rules (`~/.gemini/config/rules/pstack-models.md`).

in cursor:

```bash
/add-plugin sciencestack
```

in claude code:

```bash
/plugin marketplace add cursor/plugins
/plugin install sciencestack@cursor-plugins
```

claude code prefixes plugin commands and agents, so `/science-mode` is `/sciencestack:science-mode`. the [claude code adapter](./docs/harness/claude-code.md) maps every other cursor name.

## get started

two steps:

1. run [`/setup-sciencestack`](./skills/setup-sciencestack/SKILL.md), pick a reasoning budget, and choose which models you want.
2. use [`/science-mode`](./skills/science-mode/SKILL.md) whenever you're doing anything that requires rigor.

new here? the [scienceStack guide](./docs/guide/README.md) walks you through a first real task, from setup and prompting through verification and overnight runs. stuck, or unsure which skill fits? ask [`/science-help`](./skills/science-help/SKILL.md).

that's it. the other skills are situational, and the mode skill uses them for you as needed. out of the box the mode splits work by model strength: code delegates (feature, refactoring, bug fix, perf, hillclimb) go to fast workers (`flash`), while theoretical audits, prose, and judgment go to high-reasoning models (`pro`). the default panel uses both. [`/setup-sciencestack`](./skills/setup-sciencestack/SKILL.md) changes any of it.

## usage

use [`/science-mode`](./skills/science-mode/SKILL.md) at the start of a task. it reads your request, picks from a set of playbooks, and runs the other skills as the steps need them.

pick `/science-mode` from the `/` menu before you type your task, so cursor attaches the skill to the message.

### just use [`/science-mode`](./skills/science-mode/SKILL.md)

this skill is the main shortcut. i use it whenever i need the agent to do rigorous engineering work. it comes with twenty-three playbooks:

```
/science-mode this pr has a subtle bug where the scroll drifts every 750ms even when idle. repro
first, then fix and verify.
```

```
/science-mode i'm going to bed. land the stack even if ci flakes. i want everything merged by
morning.
```

<details>
<summary>the twenty-three playbooks</summary>

| playbook | for |
|---|---|
| [equation implementation](./skills/science-mode/playbooks/equation-implementation.md) | translate a mathematical or physical equation from a paper/textbook to verified code with LaTeX docstrings, dimensional checks, and analytical tests. |
| [numerical verification](./skills/science-mode/playbooks/numerical-verification.md) | verify convergence order $O(h^p)$, grid refinement, and conservation law stability. |
| [investigation](./skills/science-mode/playbooks/investigation.md) | a read-only question. how does x work, why was y built this way, are we sure. |
| [bug fix](./skills/science-mode/playbooks/bug-fix.md) | reproduce a defect, root-cause it, and fix with runtime evidence. |
| [perf](./skills/science-mode/playbooks/perf-issue.md) | trace a measured slowness and improve it against a baseline. |
| [hillclimb](./skills/science-mode/playbooks/hillclimb.md) | sustained, scientific improvement of one metric against a target, looping hypotheses with before/after measurement and one commit per accepted win. |
| [runtime forensics](./skills/science-mode/playbooks/runtime-forensics.md) | diagnose a live symptom (leak, idle-cpu spin, glitch) from instrumentation. |
| [trace forensics](./skills/science-mode/playbooks/trace-forensics.md) | diagnose a captured profiling artifact (cpuprofile, trace, spindump, heap snapshot). |
| [feature](./skills/science-mode/playbooks/feature.md) | new or changed behavior, built from a named data shape. |
| [refactoring](./skills/science-mode/playbooks/refactoring.md) | a behavior-preserving change to structure or shape. |
| [prototype](./skills/science-mode/playbooks/prototype.md) | a throwaway sketch to make a design or behavioral decision cheaply, or to settle an empirical fork by observing it. |
| [visual parity](./skills/science-mode/playbooks/visual-parity.md) | pixel-exact ui equivalence between two implementations. |
| [authoring a skill](./skills/science-mode/playbooks/authoring-a-skill.md) | writing or editing a SKILL.md. |
| [eval](./skills/science-mode/playbooks/eval.md) | test how a skill or prompt change affects agent behavior, blinded. |
| [babysit](./skills/science-mode/playbooks/babysit.md) | drive a pr or a stack to merge-ready: conflicts, review threads, ci. |
| [shipping](./skills/science-mode/playbooks/shipping.md) | independently verify a green stack, then land the contiguous verified run bottom-up through github by default or origin when available. |
| [autonomous run](./skills/science-mode/playbooks/autonomous-run.md) | drive a long task to completion without stopping. |
| [orchestrate](./skills/science-mode/playbooks/orchestrate.md) | a standing project handed to one coordinator chat: multi-day, many stacked prs, fleets of subagents. |
| [autopilot-full](./skills/science-mode/playbooks/autopilot-full.md) | run independent prs to merged with one owner per pr. a swarm verifies each code-ready head, and every later change to the patch gets a fresh check. |
| [autopilot-stack](./skills/science-mode/playbooks/autopilot-stack.md) | build and verify one linear base-branch stack for the operator to review and land. |
| [session pickup](./skills/science-mode/playbooks/session-pickup.md) | resume or take over a prior agent's in-flight work. |
| [pause safely](./skills/science-mode/playbooks/pause-safely.md) | suspend in-flight work cleanly so it can be resumed later. |
| [multi-phase plan](./skills/science-mode/playbooks/multi-phase-plan.md) | work that spans phases or stacked PRs. |
| [worktree cleanup](./skills/science-mode/playbooks/worktree-cleanup.md) | reclaim disk by pruning merged or abandoned worktrees and stale ios simulators, safety-gated. |
| [opening a pr](./skills/science-mode/playbooks/opening-a-pr.md) | open a ready pr from small ordered commits with a conventional commits title and a briefing-style body. invoked at the end of every other playbook. |

</details>



when invoked it:

1. matches your task to a [playbook](./skills/science-mode/playbooks/) and opens a todo list whose first items are its steps, copied in verbatim.
2. routes to the other skills as the steps fire.
3. writes unslopped replies framed for the consumer and the maintainer.

the full rules and playbooks live in [`skills/science-mode/SKILL.md`](./skills/science-mode/SKILL.md).

to keep [`/science-mode`](./skills/science-mode/SKILL.md) on across turns, pick it from the `/` menu and press option+enter (mac) or alt+enter (windows) instead of enter. that makes it a [custom mode](https://cursor.com/docs/skills#using-a-skill-as-a-custom-mode), which cursor offers in the agents window and the cli. it stays in context every turn until you exit the mode. plain enter attaches it to one message only.

[`/science-mode`](./skills/science-mode/SKILL.md) works extremely well with cursor's `/loop` command. you can make cursor work for many hours without sacrificing rigor.

## skills

[`/science-mode`](./skills/science-mode/SKILL.md) runs most of these for you when a step needs them (`how`, `why`, `architect`, `arena`, `swarm`, `interrogate`, `unslop`, `no-comments`, `technical-writing`, `tdd`, and the principles). the table below is for when you want one directly:

```
/how do we cancel runs? do we have an n+1 when we look up every run to cancel?
```

```
/interrogate review this pr.
```

<details>
<summary>all skills</summary>

| skill | use it when |
|---|---|
| [`/science-mode`](./skills/science-mode/SKILL.md) | default entry point for any non-trivial task. |
| [`/science-help`](./skills/science-help/SKILL.md) | you're new to scienceStack, or unsure which skill, playbook, or principle fits. finds out what you're trying to do, answers that part, and hands you a prompt to type. runs only when you type `/science-help` (or `/poteto-help`). |
| [`/in-your-own-words`](./skills/in-your-own-words/SKILL.md) | you want the agent to play back your goal and the problem before it starts. runs only when you type `/in-your-own-words`. |
| [`/sharpen`](./skills/sharpen/SKILL.md) | you want a prompt made deeper, not bigger, before you send it: what a top professional would do that you didn't ask for, the raw material they'd start from, their methods and tools, and an outside check that the result is right. hands back the rewritten prompt and leaves your choices open. doesn't do the task. runs only when you type `/sharpen`. |
| [`/how`](./skills/how/SKILL.md) | you want a walkthrough of how a subsystem works. |
| [`/why`](./skills/why/SKILL.md) | you want to know why something was built this way. discovers available MCPs at run time and queries each evidence category in parallel (source control, issue tracker, long-form docs, real-time chat, infra observability, error tracking, analytics warehouse). |
| [`/recall`](./skills/recall/SKILL.md) | you're starting or resuming work and want your recent context on a topic rebuilt from your own chat history and the shared record, handed back as a tight current-state brief. |
| [`/ketchup`](./skills/ketchup/SKILL.md) | you want what changed in this chat since your last message, in plain words and small visuals, with every item waiting on you listed and decidable from the reply alone, even when that makes the reply long. |
| [`/blast-radius`](./skills/blast-radius/SKILL.md) | you have a small-looking change and want to know what else it could break, with the one fact it's safe because of proven by running code, not asserted. |
| [`/architect`](./skills/architect/SKILL.md) | you're about to write code that crosses a function boundary and want the caller's usage, types, and module shape settled first. |
| [`/arena`](./skills/arena/SKILL.md) | you want N parallel attempts at the same thing, then to grab the best parts of each. |
| [`/swarm`](./skills/swarm/SKILL.md) | you want N parallel workers across different slices or races, then one aggregated report. |
| [`/interrogate`](./skills/interrogate/SKILL.md) | you have a diff and want different models to try to break it, including a strict code-quality lens. |
| [`/automate-me`](./skills/automate-me/SKILL.md) | you want your own `-mode` skill, drafted from how you've actually worked. |
| [`/make-bot-ui`](./skills/make-bot-ui/SKILL.md) | you want a page or dashboard whose buttons wake a Grok Bot over a webhook, including the sender-key handoff and Tailscale. |
| [`/setup-sciencestack`](./skills/setup-sciencestack/SKILL.md) | you want to pick which models scienceStack uses per role. detects your models and writes a config rule. |
| [`/reflect`](./skills/reflect/SKILL.md) | a long task landed and you want the recipe captured as a skill edit. |
| [`/correct`](./skills/correct/SKILL.md) | you keep correcting agents for the same mistakes. mines history for mistake classes, fixes each at the highest level that works (architecture, then types, lint, and ci, then tests, with docs last), and keeps a table pairing each rule with what enforces it. |
| [`/teach`](./skills/teach/SKILL.md) | you want to actually understand a change or subsystem, not just have it summarized. runs how + why and weaves one plain explanation, built up diagram by diagram. |
| [`/tdd`](./skills/tdd/SKILL.md) | you're fixing a bug and there's a cheap local test path. write the failing test first, then the fix. |
| [`/benchmark-checklist`](./skills/benchmark-checklist/SKILL.md) | you ran a benchmark or measured a speedup or regression. vets the number (limiter, tuning, errors, repeat runs, end-to-end relevance) before you report or act on it. |
| [`/no-comments`](./skills/no-comments/SKILL.md) | strip comments before review; spawns Comment Master, fixes accepted findings, offers encodings for claimed constraints. |
| [`/typescript-best-practices`](./skills/typescript-best-practices/SKILL.md) | you're reading or editing typescript. grounds the type-system-discipline principle in syntax. |
| [`/figure-it-out`](./skills/figure-it-out/SKILL.md) | no bundled playbook fits. designs a rigorous, auditable playbook for the task. |
| [`/show-me-your-work`](./skills/show-me-your-work/SKILL.md) | you want a reviewable decision trail. logs decisions to a tsv you can commit. |
| [`/scientific-equation-verifier`](./skills/scientific-equation-verifier/SKILL.md) | verify that code implementing equations strictly matches theoretical formulations, sign conventions, index ordering, and normalization constants. |
| [`/numerical-stability-audit`](./skills/numerical-stability-audit/SKILL.md) | audit scientific code for catastrophic cancellation, condition numbers, division by zero, and stiff ODE instability. |
| [`/golden-dataset-benchmark`](./skills/golden-dataset-benchmark/SKILL.md) | acquire, generate, and verify code against canonical industry benchmark problems (CFD, FEM, MD, quantum, kinetics) and golden reference datasets. |
| [`/astronomy-computing`](./skills/astronomy-computing/SKILL.md) | specialized algorithms and invariants for astronomy, celestial mechanics (Kepler, symplectic N-body), stellar structure (Lane-Emden), and SO(3) coordinate frames. |
| [`/precision-audit`](./skills/precision-audit/SKILL.md) | audit floating-point precision traps (float32 vs float64), condition numbers vs epsilon, and mixed-precision iterative refinement. |
| [`/accelerated-scientific-computing`](./skills/accelerated-scientific-computing/SKILL.md) | memory layouts (row vs column major), SIMD vectorization, and precision guards for C++, Fortran, Julia, and JAX. |
| [`/create-verification-skill`](./skills/create-verification-skill/SKILL.md) | your project has no scripted way to prove app behavior. generates a project-local verify skill with a feature map, for any language or platform. |
| [`/maintain-verification-skill`](./skills/maintain-verification-skill/SKILL.md) | your verify skill's feature map has drifted from the app. source wave + one live pass, at most one PR of proven corrections. |
| [`/create-formal-verification-skill`](./skills/create-formal-verification-skill/SKILL.md) | tests can't reach the case that breaks a race, retry, state machine, parser, or unsafe code. verifies one property with the tool that fits and generates a project-local skill to recheck it on every change. |
| [`/maintain-formal-verification-skill`](./skills/maintain-formal-verification-skill/SKILL.md) | code your formal verification covers has changed since it was last checked. updates the model, harness, or properties to match the code, reruns, and says whether each failure is drift in the verification or a bug in the code. |
| [`/unslop`](./skills/unslop/SKILL.md) | you're cleaning up writing. removes AI tells. |
| [`/bro`](./skills/bro/SKILL.md) | you want the last message restated in plain human language, no jargon. |
| [`/technical-writing`](./skills/technical-writing/SKILL.md) | layered doc standard (Diátaxis + Google developer style + STE + Global English) for docs, RFCs, readmes, PR descriptions, commit messages. |

</details>



### examples

mostly i type [`/science-mode`](./skills/science-mode/SKILL.md) at the start of a task and let it route to a playbook. the other skills fire as the steps need them. a few i reach for directly.


<details>
<summary>all the examples</summary>

```
bug fix:           /science-mode this pr has a subtle bug where the scroll drifts every 750ms even
                   when idle. repro first, then fix and verify.
perf:              /science-mode a big list takes a second or two to load even though we virtualize.
                   run a cpu trace and tell me why.
feature:           /science-mode build a small feature behind a feature flag. verify it really works.
prototype:         /science-mode build two prototypes of the markdown renderer so we can compare.
                   spawn an agent for each.
multi-phase:       /science-mode open source these skills as a plugin. nothing internal leaks, work
                   in a temp dir, show me the dependency graph first.
overnight run:     /science-mode i'm going to bed. land the stack even if ci flakes. i want
                   everything merged by morning.
babysit:           /science-mode check on pr 123. anything outstanding?
visual parity:     /science-mode the row spacing is too tall when this flag is on. the second image
                   is correct. repro and fix until it matches.
figure it out:     /science-mode i'm stepping away. migrate every caller from the synchronous store
                   to the new async one, keeping behavior identical. i want to trust it was done
                   right when i'm back.
how:               /how do we cancel runs? do we have an n+1 when we look up every run to cancel?
why:               /why is this feature flag not on yet?
architect:         design this instrumentation to be high signal with no false positives. /architect
                   this first.
arena:             /arena take my prompt to the arena verbatim. i want to compare their proposals
                   with yours.
swarm:             /swarm check every package under packages/ against its check.sh. one worker per
                   package. one report.
interrogate:       /interrogate review this pr.
tdd:               /tdd implement
unslop:            can we unslop and tighten the new changes?
reflect:           /reflect that took too long. capture what we learned so the next run doesn't
                   repeat it.
correct:           /correct
show-me-your-work: /show-me-your-work keep a decision trail i can review when i'm back.
automate-me:       /automate-me
help:              /science-help which skill should i use to review this branch?
```

</details>

## the `science-master`, Comment Master, and Theory Reviewer subagents

[`/science-mode`](./skills/science-mode/SKILL.md) runs in the chat that receives it. that chat owns the playbook, the todo list, and every subagent spawn.

scienceStack also ships [`subagent_type: "science-master"`](./agents/science-master.md) as the wrapper for delegates spawned during a run. it reads `science-mode` in full, including its inline principles index, before doing any work. substituting `generalPurpose` skips that read and drifts. do not spawn `science-master` to run the playbook itself.

[`/science-mode`](./skills/science-mode/SKILL.md) and [`subagent_type: "science-master"`](./agents/science-master.md) route through the same wrapper.

scienceStack also ships [Comment Master](./agents/comment-master.md), a read-only comment reviewer available as `subagent_type: "comment-master"`. usually invoke it through [`/no-comments`](./skills/no-comments/SKILL.md), not directly.

for scientific and mathematical work, scienceStack ships [Theory Reviewer](./agents/theory-reviewer.md) (`subagent_type: "theory-reviewer"`), which audits code line-by-line against theoretical formulas, sign conventions, index ordering, and physical conservation laws.

## principles

twenty-four short skills, one principle each. `science-mode` indexes them inline and reads that index at task start. the standalone files are there so other skills can reference a principle by name, and so the index can point at the full rule for each.

<details>
<summary>all twenty-four principles</summary>

| principle | group | rule |
|---|---|---|
| [laziness-protocol](./skills/principle-laziness-protocol/SKILL.md) | core | Bias toward deletion and the smallest change that solves the problem. |
| [foundational-thinking](./skills/principle-foundational-thinking/SKILL.md) | core | Apply before writing logic: choosing core types and data structures, sequencing scaffold-vs-feature work, asking what concurrent actors share. Get the data structures right so downstream code becomes obvious. |
| [redesign-from-first-principles](./skills/principle-redesign-from-first-principles/SKILL.md) | core | Redesign as if the requirement had been a foundational assumption from day one, instead of bolting it on. |
| [attack-the-premise](./skills/principle-attack-the-premise/SKILL.md) | core | Apply when two or more fixes that share one premise have failed the same gate. Write the premise down and test it directly before you write another fix that assumes it. |
| [subtract-before-you-add](./skills/principle-subtract-before-you-add/SKILL.md) | core | Remove dead weight, redundant validators, and stub references first, then build on the simpler base. |
| [minimize-reader-load](./skills/principle-minimize-reader-load/SKILL.md) | core | Count layers between question and answer, and hidden state in the reader's head; collapse one-caller wrappers and shrink mutable scope. |
| [outcome-oriented-execution](./skills/principle-outcome-oriented-execution/SKILL.md) | core | Apply during planned rewrites and migrations with explicit phase boundaries. Converge on the target architecture; don't preserve smooth intermediate states with throwaway compatibility code. |
| [experience-first](./skills/principle-experience-first/SKILL.md) | core | Choose user delight over implementation convenience; ship fewer polished features over more rough ones. |
| [exhaust-the-design-space](./skills/principle-exhaust-the-design-space/SKILL.md) | core | Build 2-3 competing prototypes and compare side by side before committing. |
| [build-the-lever](./skills/principle-build-the-lever/SKILL.md) | core | Apply to any non-trivial work, not just bulk work: edits, migrations, analyses, checks. Build the tool that does it or proves it (codemod, script, generator, or a skill your subagents follow) instead of working by hand. The tool is the artifact a reviewer can rerun. |
| [model-the-domain](./skills/principle-model-the-domain/SKILL.md) | architecture | Encode the domain in a structure instead of scattered conditionals. |
| [boundary-discipline](./skills/principle-boundary-discipline/SKILL.md) | architecture | Concentrate guards at system boundaries (CLI, config, network, external APIs); trust internal types and keep business logic in pure functions. |
| [type-system-discipline](./skills/principle-type-system-discipline/SKILL.md) | architecture | Make illegal states unrepresentable, brand semantic primitives, parse external data at boundaries, exhaust variants, derive from authoritative schemas. |
| [make-operations-idempotent](./skills/principle-make-operations-idempotent/SKILL.md) | architecture | Converge to the same end state regardless of partial prior runs. |
| [migrate-callers-then-delete-legacy-apis](./skills/principle-migrate-callers-then-delete-legacy-apis/SKILL.md) | architecture | Migrate callers and delete the old API in the same wave instead of preserving compatibility layers. |
| [separate-before-serializing-shared-state](./skills/principle-separate-before-serializing-shared-state/SKILL.md) | architecture | Eliminate the sharing first; serialize structurally only when one shared writer is a real invariant. |
| [prove-it-works](./skills/principle-prove-it-works/SKILL.md) | verification | Apply after completing a task, before declaring done. Verify against the real artifact (run the feature, read the actual value, inspect the diff), not a proxy, self-report, or 'it compiles.'. |
| [fix-root-causes](./skills/principle-fix-root-causes/SKILL.md) | verification | Trace each symptom back to the first place the system went wrong and fix it there. A guard is a fix only when the state it handles is legitimate. |
| [sequence-verifiable-units](./skills/principle-sequence-verifiable-units/SKILL.md) | verification | Apply to multi-step work (sweeps, migrations, runs of similar edits) and to how you stack commits and PRs. Break work into small units that each end in a verifiable state, check each before the next, and order delivery so the sequence proves itself to a reviewer. |
| [test-behavior-not-implementation](./skills/principle-test-behavior-not-implementation/SKILL.md) | verification | Apply when you write, change, or keep a test. Assert what the code's users can observe, so the test fails when that behavior breaks and keeps passing when only the internals change. |
| [explain-the-number](./skills/principle-explain-the-number/SKILL.md) | verification | Apply before you trust, report, or act on a number you measured: a speedup, a regression, a throughput, a latency, or an eval result. Find what limits it, and rule out that it measured something other than the work you think. |
| [guard-the-context-window](./skills/principle-guard-the-context-window/SKILL.md) | delegation | Route bulk to subagents; keep summaries in the main thread, not raw payloads. |
| [never-block-on-the-human](./skills/principle-never-block-on-the-human/SKILL.md) | delegation | Proceed, present the result, let the human course-correct after the fact; reserve confirmation for irreversible actions. |
| [encode-lessons-in-structure](./skills/principle-encode-lessons-in-structure/SKILL.md) | meta | Encode the rule as a lint, metadata flag, runtime check, or script instead of more text. |

</details>

## not shipped here

a few things `science-mode` references but doesn't bundle:

- `/deslop` and the `deslop` skill ship in the `cursor-team-kit` plugin.
- `control-cli` (for CLIs and TUIs) and `control-ui` (for browser, Electron, web) ship in `cursor-team-kit` too.
- `/create-skill` is a cursor built-in. cursor also ships a built-in `/autopilot` that watches a pr. inside `science-mode`, pr-status requests go to the [babysit playbook](./skills/science-mode/playbooks/babysit.md) instead.

install `cursor-team-kit` alongside pstack if you want the full set.

## why are there no planning skills?

cursor already has a great plan mode which works great with pstack. but personally, i don't believe in planning. the best spec is code. if you do want to make a plan, [`/science-mode`](./skills/science-mode/SKILL.md) covers it, but it's not a default. 

## make it yours

`science-mode` is my style. you may not want exactly that.

type [`/automate-me`](./skills/automate-me/SKILL.md). it mines your recent transcripts, drafts a `<your-name>-mode` skill from how you've actually worked, and routes through pstack underneath. you keep pstack as the base and end up with your own routing skill alongside `science-mode`.

models are configurable too. type [`/setup-sciencestack`](./skills/setup-sciencestack/SKILL.md). it detects the models you have access to and writes a small always-applied rule mapping each role (code, judgment, the review panels) to a model. every skill reads it and falls back to sensible defaults when the rule is absent, so you override only what you want.

when a default changes, a rule written before the change still pins the old default. delete those role lines, or delete the file, then run `/setup-sciencestack` again. a rerun keeps any role whose model differs from the default.

## bundled astronomy & scientific solvers

scienceStack ships zero-network, high-precision reference solvers in [`benchmarks/`](./benchmarks/):

- **Astronomy & Astrophysics** ([`benchmarks/astronomy/`](./benchmarks/astronomy/)):
  - [`kepler_solver.py`](./benchmarks/astronomy/kepler_solver.py): Machine-precision Kepler equation solver (cubic Halley refinement) and Cartesian orbit propagator with vis-viva invariant audit.
  - [`symplectic_nbody.py`](./benchmarks/astronomy/symplectic_nbody.py): Symplectic Leapfrog and Yoshida $N$-body integrators strictly preserving energy ($dE/dt = 0$) and angular momentum without secular growth.
  - [`lane_emden_solver.py`](./benchmarks/astronomy/lane_emden_solver.py): Stellar structure polytrope solver with near-center series expansion removing coordinate singularities, matching analytical limits ($n=0, 1$) and Chandrasekhar benchmarks ($n=1.5, 3.0$).
  - [`coordinate_transforms.py`](./benchmarks/astronomy/coordinate_transforms.py): Direction cosine coordinate transformations (Equatorial J2000, Ecliptic, Galactic) enforcing $\mathrm{SO}(3)$ orthonormality ($\mathbf{R}^T \mathbf{R} = \mathbf{I}$, $\det \mathbf{R} = 1$).
- **Fluid Dynamics & Kinetics**:
  - [`cfd/exact_riemann.py`](./benchmarks/cfd/exact_riemann.py): Exact 1D Euler Riemann solver for Sod shock tube problem.
  - [`kinetics/robertson_reference.py`](./benchmarks/kinetics/robertson_reference.py): Stiff autocatalytic chemical kinetics reference solver with analytic Jacobian and strict mass conservation ($< 10^{-12}$).

## automated verification tooling

scienceStack includes deterministic command-line tools in [`scripts/`](./scripts/):

- [`audit_numerical_ast.py`](./scripts/audit_numerical_ast.py): Python AST scanner detecting matrix inversion anti-patterns (`np.linalg.inv`), catastrophic cancellation hazards, and missing LaTeX equation docstrings.
- [`mms_generator.py`](./scripts/mms_generator.py): SymPy-powered Method of Manufactured Solutions generator that computes analytical source terms and test fixtures.
- [`derive_jacobian.py`](./scripts/derive_jacobian.py): Analytical Jacobian synthesizer that symbolically differentiates ODE/PDE vector fields into error-free Python/NumPy code.
- [`hook_pre_tool_guard.py`](./scripts/hook_pre_tool_guard.py): Antigravity `PreToolUse` lifecycle hook (`hooks.json`) automatically blocking dangerous matrix inversions before code is written.

## license

MIT
