"""Tests for scripts/test_ratchet.py.

Run (from the plugin root):  python3 -B -m unittest discover -s tests -v

Every test builds a throw-away git repository whose first commit is the baseline, edits the working tree, and runs the
real command line. Each weakening the script claims to catch has a case that must give exit status 3, and each change
that is not a weakening (tightening, adding tests, a staged rename) must give 0. The library defaults asserted here are
the ones documented in test_ratchet.py (numpy, math, pytest, unittest documentation).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "test_ratchet.py"

BASE = textwrap.dedent('''
    import math
    import unittest
    import numpy as np
    import pytest

    TOL = 1e-12
    PLACES = 9


    def test_allclose():
        np.testing.assert_allclose(1.0, 1.0, rtol=1e-9, atol=1e-14)


    def test_positional():
        np.testing.assert_allclose(1.0, 1.0, 1e-9, 1e-14)


    def test_bounds():
        err = 0.0
        order = 2.0
        assert abs(err) < TOL
        assert order > 1.9
        assert 1e-10 > err


    def test_isclose_and_approx():
        assert math.isclose(1.0, 1.0, rel_tol=1e-12)
        assert 1.0 == pytest.approx(1.0, rel=1e-9)


    def test_expression():
        np.testing.assert_allclose(1.0, 1.0, rtol=10 ** -9)


    def test_local_constant():
        eps = 1e-11
        assert abs(0.0) < eps


    @pytest.mark.parametrize("n", [1, 2, 3])
    def test_param(n):
        assert n > 0


    class TestUnit(unittest.TestCase):
        EPS = 1e-10

        def test_almost(self):
            self.assertAlmostEqual(1.0, 1.0, places=PLACES)
            self.assertAlmostEqual(1.0, 1.0, delta=1e-9)

        def test_less(self):
            self.assertLess(0.0, self.EPS)
            self.assertGreater(2.0, 1.9)

        def test_decimal(self):
            np.testing.assert_array_almost_equal([1.0], [1.0], decimal=9)
''')


class Repo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "proj"
        (self.root / "tests").mkdir(parents=True)
        (self.root / "src").mkdir()
        self.test_file = self.root / "tests" / "test_physics.py"
        self.test_file.write_text(BASE)
        (self.root / "src" / "solver.py").write_text("TOL = 1e-12\n")
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "T")
        self.git("config", "user.email", "t@example.invalid")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "baseline")

    def tearDown(self):
        self._tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=True)

    def edit(self, old, new, path=None):
        path = path or self.test_file
        text = path.read_text()
        self.assertIn(old, text, "fixture edit did not apply")
        path.write_text(text.replace(old, new, 1))

    def ratchet(self, *extra):
        out = Path(self._tmp.name) / "result.json"
        env = dict(os.environ, VERIFICATION_EVIDENCE_DIR=str(Path(self._tmp.name) / "evidence"))
        done = subprocess.run([sys.executable, "-B", str(SCRIPT), "--baseline-ref", "HEAD", "--json", str(out), *extra],
                              cwd=self.root, capture_output=True, text=True, env=env)
        data = json.loads(out.read_text()) if out.exists() else None
        if out.exists():
            out.unlink()
        return done, data

    def assert_violation(self, kind, test_suffix, *extra):
        done, data = self.ratchet(*extra)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        hits = [v for v in data["violations"] if v["kind"] == kind and v["test"].endswith(test_suffix)]
        self.assertTrue(hits, (kind, test_suffix, data["violations"]))
        return data

    def assert_clean(self, *extra):
        done, data = self.ratchet(*extra)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(data["violations"], [])
        return data


class NoChange(Repo):
    def test_unchanged_tree_is_clean_and_counts_tests(self):
        data = self.assert_clean()
        self.assertEqual((data["tests_before"], data["tests_after"]), (10, 10))

    def test_result_is_deterministic(self):
        self.edit("rtol=1e-9, atol=1e-14", "rtol=1e-6, atol=1e-14")
        first, second = self.ratchet()[1], self.ratchet()[1]
        strip = lambda d: [(v["test"], v["kind"], v["detail"]) for v in d["violations"]]
        self.assertEqual(strip(first), strip(second))


class Loosened(Repo):
    def test_keyword_tolerances(self):
        self.edit("rtol=1e-9, atol=1e-14", "rtol=1e-6, atol=1e-14")
        self.assert_violation("loosened", "::test_allclose")

    def test_atol(self):
        self.edit("rtol=1e-9, atol=1e-14", "rtol=1e-9, atol=1e-8")
        self.assert_violation("loosened", "::test_allclose")

    def test_positional_tolerances(self):
        self.edit("1.0, 1.0, 1e-9, 1e-14)", "1.0, 1.0, 1e-3, 1e-14)")
        self.assert_violation("loosened", "::test_positional")

    def test_removing_the_argument_falls_back_to_a_looser_library_default(self):
        self.edit("rtol=1e-9, atol=1e-14", "atol=1e-14")                    # assert_allclose default rtol is 1e-7
        data = self.assert_violation("loosened", "::test_allclose")
        self.assertTrue(any("1e-07" in v["detail"] for v in data["violations"]))

    def test_math_isclose_default(self):
        self.edit("rel_tol=1e-12)", ")")                                     # default rel_tol 1e-9
        self.assert_violation("loosened", "::test_isclose_and_approx")

    def test_pytest_approx(self):
        self.edit("approx(1.0, rel=1e-9)", "approx(1.0, rel=1e-3)")
        self.assert_violation("loosened", "::test_isclose_and_approx")

    def test_expression_value(self):
        self.edit("rtol=10 ** -9", "rtol=10 ** -6")
        self.assert_violation("loosened", "::test_expression")

    def test_upper_bound_raised(self):
        self.edit("assert 1e-10 > err", "assert 1e-6 > err")                 # literal on the left
        self.assert_violation("loosened", "::test_bounds")

    def test_lower_bound_lowered(self):
        self.edit("assert order > 1.9", "assert order > 1.5")
        self.assert_violation("loosened", "::test_bounds")

    def test_module_constant_flags_the_constant_and_the_tests_using_it(self):
        self.edit("TOL = 1e-12", "TOL = 1e-6")
        data = self.assert_violation("loosened", "::<module>")
        self.assertTrue(any(v["test"].endswith("::test_bounds") for v in data["violations"]))

    def test_local_constant(self):
        self.edit("eps = 1e-11", "eps = 1e-5")
        self.assert_violation("loosened", "::test_local_constant")

    def test_class_constant_and_assert_less(self):
        self.edit("EPS = 1e-10", "EPS = 1e-4")
        data = self.assert_violation("loosened", "::TestUnit")
        self.assertTrue(any(v["test"].endswith("::TestUnit::test_less") for v in data["violations"]))

    def test_assert_greater_lower_bound(self):
        self.edit("self.assertGreater(2.0, 1.9)", "self.assertGreater(2.0, 1.0)")
        self.assert_violation("loosened", "::TestUnit::test_less")

    def test_fewer_places_is_looser(self):
        self.edit("PLACES = 9", "PLACES = 5")
        self.assert_violation("loosened", "::TestUnit::test_almost")

    def test_larger_delta(self):
        self.edit("delta=1e-9", "delta=1e-3")
        self.assert_violation("loosened", "::TestUnit::test_almost")

    def test_fewer_decimals(self):
        self.edit("decimal=9", "decimal=4")
        self.assert_violation("loosened", "::TestUnit::test_decimal")

    def test_tightening_everything_is_clean(self):
        for old, new in (("rtol=1e-9, atol=1e-14", "rtol=1e-12, atol=1e-15"), ("TOL = 1e-12", "TOL = 1e-14"),
                         ("assert order > 1.9", "assert order > 1.95"), ("PLACES = 9", "PLACES = 11"),
                         ("decimal=9", "decimal=10"), ("EPS = 1e-10", "EPS = 1e-12")):
            self.edit(old, new)
        self.assert_clean()


class OtherWeakening(Repo):
    def test_tolerance_hidden_behind_an_unknown_value(self):
        self.edit("rtol=1e-9, atol=1e-14", "rtol=get_tol(), atol=1e-14")
        self.assert_violation("not_literal", "::test_allclose")

    def test_tolerance_check_replaced_by_another_form(self):
        self.edit("np.testing.assert_allclose(1.0, 1.0, rtol=1e-9, atol=1e-14)", "assert np.allclose(1.0, 1.0, rtol=1e-3)")
        self.assert_violation("site_removed", "::test_allclose")

    def test_fewer_assertions(self):
        self.edit("    assert order > 1.9\n", "")
        self.assert_violation("assertions_reduced", "::test_bounds")

    def test_fewer_assertion_calls(self):
        extra = self.root / "tests" / "test_plain.py"
        extra.write_text("import unittest\n\n\nclass P(unittest.TestCase):\n    def test_eq(self):\n"
                         "        self.assertEqual(1, 1)\n        self.assertIn(1, [1])\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "plain")
        self.edit("        self.assertIn(1, [1])\n", "", path=extra)          # no tolerance involved
        self.assert_violation("assertions_reduced", "test_plain.py::P::test_eq")

    def test_removed_test(self):
        self.edit("def test_expression():", "def helper_expression():")
        self.assert_violation("removed", "::test_expression")

    def test_deleted_test_file(self):
        self.test_file.unlink()
        data = self.assert_violation("removed", "::test_allclose")
        self.assertEqual(data["tests_after"], 0)

    def test_fewer_parametrize_cases(self):
        self.edit('[1, 2, 3]', '[1, 2]')
        self.assert_violation("params_reduced", "::test_param")

    def test_parametrize_cases_no_longer_literal(self):
        self.edit('[1, 2, 3]', 'CASES')
        self.assert_violation("not_literal", "::test_param")

    def test_unparseable_file_is_reported_once(self):
        self.test_file.write_text(BASE + "\ndef broken(:\n")
        done, data = self.ratchet()
        self.assertEqual(done.returncode, 3)
        kinds = {v["kind"] for v in data["violations"]}
        self.assertEqual(kinds, {"unparseable"})                         # not also ten "removed" tests


class Skips(Repo):
    def check(self, old, new, suffix):
        self.edit(old, new)
        self.assert_violation("skip_added", suffix)

    def test_pytest_mark_skip(self):
        self.check("def test_allclose():", "@pytest.mark.skip(reason='slow')\ndef test_allclose():", "::test_allclose")

    def test_xfail(self):
        self.check("def test_allclose():", "@pytest.mark.xfail\ndef test_allclose():", "::test_allclose")

    def test_unittest_skip_on_a_class(self):
        self.check("class TestUnit(unittest.TestCase):", "@unittest.skip('later')\nclass TestUnit(unittest.TestCase):",
                   "::TestUnit")

    def test_expected_failure(self):
        self.check("    def test_less(self):", "    @unittest.expectedFailure\n    def test_less(self):", "::TestUnit::test_less")

    def test_skip_test_call(self):
        self.check("    def test_less(self):\n", "    def test_less(self):\n        self.skipTest('flaky')\n",
                   "::TestUnit::test_less")

    def test_pytest_skip_call_and_importorskip(self):
        self.check("    err = 0.0\n", "    pytest.importorskip('scipy')\n    err = 0.0\n", "::test_bounds")

    def test_raise_skiptest(self):
        self.check("    eps = 1e-11\n", "    raise unittest.SkipTest('no')\n    eps = 1e-11\n", "::test_local_constant")

    def test_module_pytestmark(self):
        self.check("TOL = 1e-12\n", "TOL = 1e-12\npytestmark = pytest.mark.skip(reason='all')\n", "::<module>")

    def test_changed_skip_condition(self):
        self.edit("def test_allclose():", "@pytest.mark.skipif(sys.platform == 'win32', reason='x')\ndef test_allclose():")
        self.git("commit", "-qam", "conditional skip")
        self.check("sys.platform == 'win32'", "True", "::test_allclose")

    def test_removing_a_skip_is_clean(self):
        self.edit("def test_allclose():", "@pytest.mark.skip\ndef test_allclose():")
        self.git("commit", "-qam", "skip")
        self.edit("@pytest.mark.skip\ndef test_allclose():", "def test_allclose():")
        self.assert_clean()


class FilesAndApprovals(Repo):
    def test_added_tests_are_listed_and_clean(self):
        self.edit("class TestUnit", "def test_new():\n    assert 1 < 2\n\n\nclass TestUnit")
        data = self.assert_clean()
        self.assertEqual(data["added_tests"], ["tests/test_physics.py::test_new"])

    def test_staged_rename_is_followed(self):
        self.git("mv", "tests/test_physics.py", "tests/test_moved.py")
        self.assert_clean()

    def test_unstaged_rename_looks_like_removal_which_is_a_documented_limit(self):
        shutil.move(str(self.test_file), str(self.root / "tests" / "test_moved.py"))
        self.assert_violation("removed", "::test_allclose")

    def test_non_test_files_are_ignored(self):
        self.edit("TOL = 1e-12", "TOL = 1e-3", path=self.root / "src" / "solver.py")
        self.assert_clean()

    def test_conftest_is_included(self):
        (self.root / "tests" / "conftest.py").write_text("RTOL = 1e-12\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "conftest")
        self.edit("RTOL = 1e-12", "RTOL = 1e-6", path=self.root / "tests" / "conftest.py")
        self.assert_violation("loosened", "conftest.py::<module>")

    def test_include_globs_select_files(self):
        self.edit("rtol=1e-9, atol=1e-14", "rtol=1e-6, atol=1e-14")
        self.assert_clean("--include", "other/*.py")
        self.assert_violation("loosened", "::test_allclose", "--include", "tests/*.py")

    def write_approvals(self, approvals):
        (self.root / "test-ratchet-approvals.json").write_text(json.dumps({"schema": "test-ratchet-approvals/1",
                                                                          "approvals": approvals}))

    def test_an_approval_with_a_reason_accepts_exactly_that_change(self):
        self.edit("rtol=1e-9, atol=1e-14", "rtol=1e-6, atol=1e-14")
        self.write_approvals([{"test": "tests/test_physics.py::test_allclose", "kind": "loosened",
                               "reason": "single-precision GPU path; documented in docs/precision.md"}])
        done, data = self.ratchet()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("APPROVED [loosened] tests/test_physics.py::test_allclose", done.stdout)

    def test_an_approval_for_another_kind_or_test_does_not_apply(self):
        self.edit("rtol=1e-9, atol=1e-14", "rtol=1e-6, atol=1e-14")
        self.write_approvals([{"test": "tests/test_physics.py::test_allclose", "kind": "removed", "reason": "a reason here"},
                              {"test": "tests/test_physics.py::test_bounds", "kind": "any", "reason": "a reason here"}])
        self.assert_violation("loosened", "::test_allclose")

    def test_any_kind_approves_all_kinds_for_that_test(self):
        self.edit("rtol=1e-9, atol=1e-14", "rtol=get_tol(), atol=1e-14")
        self.write_approvals([{"test": "tests/test_physics.py::test_allclose", "kind": "any", "reason": "moved to a helper"}])
        self.assert_clean()

    def test_invalid_approvals_file_exits_two(self):
        for approvals in ([{"test": "x", "kind": "loosened", "reason": "long enough reason"}],
                          [{"test": "a::b", "kind": "nonsense", "reason": "long enough reason"}],
                          [{"test": "a::b", "kind": "loosened", "reason": "short"}],
                          [{"test": "a::b", "kind": "loosened", "reason": "long enough reason", "extra": 1}]):
            self.write_approvals(approvals)
            self.assertEqual(self.ratchet()[0].returncode, 2, approvals)
        (self.root / "test-ratchet-approvals.json").write_text("{not json")
        self.assertEqual(self.ratchet()[0].returncode, 2)


class Usage(Repo):
    def test_bad_ref_and_not_a_repository(self):
        done = subprocess.run([sys.executable, "-B", str(SCRIPT), "--baseline-ref", "no-such-ref"], cwd=self.root,
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertIn("not a commit", done.stderr)
        elsewhere = Path(self._tmp.name) / "plain"
        elsewhere.mkdir()
        done = subprocess.run([sys.executable, "-B", str(SCRIPT), "--baseline-ref", "HEAD"], cwd=elsewhere,
                              capture_output=True, text=True, env=dict(os.environ, GIT_CEILING_DIRECTORIES=self._tmp.name))
        self.assertEqual(done.returncode, 2)

    def test_runs_are_recorded_as_evidence_bound_to_the_tree(self):
        self.ratchet()
        log = Path(self._tmp.name) / "evidence" / "log.jsonl"
        (record,) = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual((record["tool"], record["kind"], record["passed"]), ("test_ratchet", "ratchet", True))
        self.assertEqual(record["subjects"][0]["role"], "tree")
        self.assertIsNone(self.ratchet("--no-evidence")[0].stderr or None)


if __name__ == "__main__":
    unittest.main()
