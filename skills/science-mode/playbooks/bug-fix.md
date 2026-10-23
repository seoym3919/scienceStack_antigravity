### Bug fix

**You own this task. Plan, review, verify.** Delegate investigation and the fix to subagents (`sciencestack:science-master` for code, `sciencestack:theory-reviewer` for equation/sign/index questions) and stay in the lead.

Be scientific. Every shipped line traces to runtime evidence. A belt-and-suspenders change that "might help" is a hypothesis, not a fix, and it does not ship. When evidence refutes a hypothesis, revert what it motivated. The smallest change the evidence justifies ships, nothing more.

1. Reproduce it yourself, on the surface where it was reported (same script, same inputs, same precision, same seed). Ask the user only with a stated, specific reason you cannot reach that surface, and only after driving it as far as it goes. If it won't reproduce directly, synthesize the trigger, tighten conditions, or instrument until it fires. For numerical or physical defects, reduce it to a minimal case with a known analytical answer.
2. Binary-search the cause. Form candidate hypotheses (sign convention, index order, units, time-step or CFL violation, cancellation, ill-conditioning, a broken invariant), then rule them out until one survives. Read the history (`git log -p`, `git blame`) of the affected code for regressions. Each pass, take the split that cuts the most remaining problem space, get runtime evidence, eliminate. When program state is unclear, add instrumentation or logging and read it as the code runs. Don't guess. For a long or stubborn hunt, drive the passes with the `/loop` skill. Confirm the surviving *mechanism* with runtime evidence before planning the fix.
3. Plan the fix. If it crosses a function boundary, sketch the change and its blast radius first. Delegate implementation to a subagent with a specific scope (files, the failing test, the invariant to hold).
4. Verify on the same surface. The original repro now passes. "Inconclusive" or wrong-surface is not a pass; flag it. Unit tests show branch behavior, not bug absence. Re-run the conservation and convergence checks that the bug could have hidden behind.
5. Stage the commits so the failing repro lands before the fix in git history: failing test first, then the fix on top. Skip the separate test commit only when a test would be expensive, integration-heavy, or unclear, and say so. Do not loosen a tolerance or change a reference result to make a test pass.

**Reply:** what was broken, root cause, fix, how you verified. Paste failing-then-passing repro output verbatim.
