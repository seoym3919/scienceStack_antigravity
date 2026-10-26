---
name: run-tests
description: Run the project's tests and record what actually happened (counts from the framework, bound to a hash of every project file), so "the tests pass" can be checked instead of asserted. Use whenever you run tests or are about to say they pass.
argument-hint: "unittest [--start-dir tests] | pytest [-- ARGS] | command -- CMD | fresh"
---

# /sciencestack:run-tests

Never report a test as passing unless it was run. This script runs the suite, takes the counts from the framework
itself (unittest's result object, pytest's JUnit XML), and appends the result to `./.verification/log.jsonl`, bound to a
SHA-256 of the whole git work tree taken before the run.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run_tests.py" unittest --start-dir tests
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run_tests.py" pytest -- -q tests
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run_tests.py" command -- make check     # exit status only, counts unknown
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run_tests.py" fresh                     # before saying "tests pass"
```

## What counts as passing

- The runner exits 0, nothing failed or errored, no unexpected success, and **at least one test actually ran**.
  "No tests collected" and "every test skipped" are failures: nothing was tested.
- Exit status: **0** passed; **1** failed, nothing ran, or timed out (`--timeout-s`, default 3600); **2** not run (not a
  git repository, runner missing, bad arguments, or a pass whose evidence could not be written).
- `command` mode knows only the exit status; the record says `counts_unavailable`. Prefer `unittest` or `pytest`.

## Before you say the tests pass

Run `run_tests.py fresh`. It exits 0 only if the latest test run passed **and no project file has changed since**
(tracked and untracked-not-ignored files; `__pycache__`, `.pytest_cache`, `*.pyc` and `.verification/` are left out).
Any edit after the run makes it stale: run the tests again. Quote the counts (`ran N, F failed, S skipped`).

If the tests themselves wrote project files during the run, the record is flagged `tree_changed_during_run` and is
stale at once; fix the tests to write into a temporary directory.

## Limits

The log is a local file: anything running as the user can rewrite it. Only a clean CI run is independent. A suite
that tests the wrong thing still passes: pair this with `/sciencestack:test-ratchet` so the tests cannot quietly get weaker.
