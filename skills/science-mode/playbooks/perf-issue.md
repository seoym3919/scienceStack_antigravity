### Perf issue

**You own the measurement story. Plan, review, verify the numbers.** Tie every fix to a measurement; don't read source instead of measuring.

1. Capture a baseline (wall time, throughput, or a profile) on a realistic workload. Vet the baseline, and each later number, with the **benchmark-checklist** skill.
2. Ground hypotheses in the profile. Don't claim a perf ceiling without running it first.
   Try the performance mantras in order, cheapest first:
   1. Don't do it. Stop work whose result nothing uses rather than cheapening it.
   2. Do it, but don't do it again.
   3. Do it less.
   4. Do it later.
   5. Do it when they're not looking.
   6. Do it concurrently.
   7. Do it cheaper.

   When an earlier mantra meets the target, stop.
3. Plan the fix from the profile. If it crosses a function boundary, sketch the change first. Delegate implementation to a subagent (`sciencestack:science-master`) with a specific scope. Review the diff. Capture a post-fix measurement with the same harness. Verify each attempt before trying the next.
4. Prove the optimization did not change the science: compare the new output with the pre-change output elementwise, $|new - old| \le atol + rtol|old|$, at the tolerance already recorded for the routine (default rtol $10^{-12}$, atol 0), including the sign of zero. Re-check conserved quantities. A speedup that moves the answer is a bug. A relative $L_2$ may be reported; it is not the pass rule.
5. Compare the artifacts (JSON, CSV, or sqlite plus a diff). "Inconclusive" or wrong-surface is not a pass; flag it.
6. Cite the measurement in the commit message or PR description.

For sustained improvement against a metric rather than a one-off fix, use the Hillclimb playbook (`playbooks/hillclimb.md`).

**Reply:** baseline number, post-fix number, delta, parity error, artifact path.
