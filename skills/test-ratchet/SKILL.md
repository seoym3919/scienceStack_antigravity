---
name: test-ratchet
description: Check that changes did not weaken the project's tests compared with a git baseline - no looser tolerances, removed tests or assertions, new skips/xfails or fewer parametrize cases - by parsing the test files, not by reading the diff. Use before committing test changes and in CI.
argument-hint: "--baseline-ref origin/main [--include 'tests/*.py']"
---

# /sciencestack:test-ratchet

"Do not relax tolerances or change reference results to make tests pass." This script enforces it mechanically:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/test_ratchet.py" --baseline-ref origin/main      # or HEAD for uncommitted work
```

Both versions of each test file (`test_*.py`, `*_test.py`, `conftest.py`) are parsed with `ast` and compared test by
test. Exit **3** lists every unapproved weakening; exit **0** means none; exit **2** means it could not compare.

| Kind | Example |
|---|---|
| `loosened` | `rtol=1e-9` -> `1e-6`; removing `rtol=` so numpy's default 1e-7 applies; `places=9` -> `5`; `assert err < 1e-10` -> `1e-6`; `assert order > 1.9` -> `1.5`; `TOL = 1e-12` -> `1e-6` |
| `not_literal` | `rtol=1e-9` -> `rtol=get_tol()` (can no longer be checked) |
| `site_removed` | an `assert_allclose(..., rtol=...)` taken out of a test that still exists, or rewritten in another form |
| `assertions_reduced` | a test with fewer `assert` / `assert*` calls |
| `removed` | a deleted test (renames staged with `git mv` are followed) |
| `skip_added` | `@pytest.mark.skip`, `xfail`, `@unittest.skip*`, `expectedFailure`, `self.skipTest()`, `pytest.skip()`, `importorskip()`, `pytestmark`, or a changed `skipif` condition |
| `params_reduced` | `@pytest.mark.parametrize` with fewer literal cases |
| `unparseable` | a test file that no longer parses |

## When a weakening is genuinely right

Do not pick a looser tolerance because a test failed. Find out why it failed. If the person decides the change is
correct (for example a documented precision limit), they record it in `test-ratchet-approvals.json` at the repository root:

```json
{"schema": "test-ratchet-approvals/1", "approvals": [
  {"test": "tests/test_heat.py::TestHeat::test_decay", "kind": "loosened",
   "reason": "float32 GPU path; error floor 3e-7 measured in docs/precision.md"}]}
```

The approval is visible in the diff and is printed as APPROVED on every run. Write an approval only when the user has
stated the reason; never invent one to get past exit 3.

## Limits

Only what is written in the test files is seen: a tolerance imported from another module, an assertion hidden in a
helper, or tests generated at run time are invisible. A rename done with plain `mv` (not staged) looks like a removed
test. Library defaults used for omitted arguments are listed at the top of `test_ratchet.py`.
