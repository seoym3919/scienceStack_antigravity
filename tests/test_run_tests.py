"""Tests for scripts/run_tests.py.

Run (from the plugin root):  python3 -B -m unittest discover -s tests -v

Each test builds a throw-away git project with its own small test suite and runs the real command line. Covered: the
counts come from the framework (a test that prints a fake "OK" does not fool it); failures, errors, import errors,
"no tests", "everything skipped" and unexpected successes fail; the evidence is bound to the whole work tree as it was
BEFORE the run, so editing, adding or deleting any project file makes it stale while caches and ignored files do not.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "run_tests.py"

try:
    import pytest  # noqa: F401
    HAVE_PYTEST = True
except ImportError:
    HAVE_PYTEST = False

PASSING = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertEqual(1, 1)\n\n    def test_two(self):\n        self.assertTrue(True)\n"


class Project(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "proj"
        (self.root / "tests").mkdir(parents=True)
        (self.root / "src").mkdir()
        (self.root / "src" / "model.py").write_text("K = 1\n")
        (self.root / "tests" / "test_model.py").write_text(PASSING)
        (self.root / ".gitignore").write_text("build/\n")
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")

    def tearDown(self):
        self._tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=True)

    def suite(self, source, name="test_model.py"):
        (self.root / "tests" / name).write_text(source)

    def run_tool(self, *args, timeout=300):
        out = Path(self._tmp.name) / "result.json"
        extra = ["--json", str(out)] if args and args[0] != "fresh" else []
        done = subprocess.run([sys.executable, "-B", str(SCRIPT), *args[:1], *extra, *args[1:]], cwd=self.root,
                              capture_output=True, text=True, timeout=timeout)
        data = json.loads(out.read_text()) if out.exists() else None
        if out.exists():
            out.unlink()
        return done, data

    def records(self):
        log = self.root / ".verification" / "log.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def fresh(self):
        return self.run_tool("fresh")[0].returncode


class Unittest(Project):
    def test_passing_suite_is_recorded_with_real_counts_and_is_fresh(self):
        done, data = self.run_tool("unittest")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((data["counts"]["tests"], data["counts"]["failures"], data["counts"]["errors"]), (2, 0, 0))
        (record,) = self.records()
        self.assertEqual((record["tool"], record["kind"], record["passed"], record["exit_status"]), ("run_tests", "tests", True, 0))
        self.assertEqual(record["subjects"][0]["role"], "tree")
        self.assertEqual(self.fresh(), 0)

    def test_a_failing_test_fails_and_is_named(self):
        self.suite(PASSING.replace("self.assertEqual(1, 1)", "self.assertEqual(1, 2)"))
        done, data = self.run_tool("unittest")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(data["counts"]["failures"], 1)
        self.assertTrue(any("test_one" in i for i in data["counts"]["failed_ids"]))
        self.assertEqual(self.fresh(), 1)

    def test_printing_ok_does_not_fool_the_counts(self):
        self.suite(PASSING.replace("self.assertEqual(1, 1)", "print('Ran 9 tests\\\\n\\\\nOK')\n        self.assertEqual(1, 2)"))
        self.assertEqual(self.run_tool("unittest")[0].returncode, 1)

    def test_errors_and_import_errors_fail(self):
        self.suite(PASSING.replace("self.assertEqual(1, 1)", "raise RuntimeError('boom')"))
        self.assertEqual(self.run_tool("unittest")[1]["counts"]["errors"], 1)
        self.suite("import no_such_module_anywhere\n" + PASSING)
        done, data = self.run_tool("unittest")
        self.assertEqual(done.returncode, 1)
        self.assertGreaterEqual(data["counts"]["errors"], 1)

    def test_no_tests_is_a_failure(self):
        self.suite("x = 1\n")
        done, data = self.run_tool("unittest")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(data["reason"], "no tests ran")

    def test_everything_skipped_is_a_failure(self):
        self.suite("import unittest\n\n\n@unittest.skip('later')\nclass T(unittest.TestCase):\n    def test_one(self):\n        pass\n")
        done, data = self.run_tool("unittest")
        self.assertEqual(done.returncode, 1)
        self.assertIn("skipped", data["reason"])

    def test_some_skips_are_fine_and_counted(self):
        self.suite(PASSING.replace("    def test_two(self):", "    @unittest.skip('x')\n    def test_two(self):"))
        done, data = self.run_tool("unittest")
        self.assertEqual(done.returncode, 0)
        self.assertEqual(data["counts"]["skipped"], 1)

    def test_unexpected_success_fails(self):
        self.suite(PASSING.replace("    def test_two(self):", "    @unittest.expectedFailure\n    def test_two(self):"))
        self.assertEqual(self.run_tool("unittest")[0].returncode, 1)

    def test_a_nonzero_runner_exit_fails_even_when_every_test_passed(self):
        self.suite("import atexit, os\natexit.register(lambda: os._exit(3))\n" + PASSING)   # exits 3 after reporting
        done, data = self.run_tool("unittest")
        self.assertEqual(done.returncode, 1)
        self.assertEqual((data["counts"]["failures"], data["counts"]["errors"]), (0, 0))
        self.assertIn("runner exited 3", data["reason"])

    def test_a_stale_bytecode_cache_cannot_run_old_code(self):
        """Regression: a same-sized edit with the same modification time (to the second) matched the cached .pyc, so the
        old PASSING code ran while the evidence claimed the new file had passed (seen on a fast CI machine)."""
        target = self.root / "tests" / "test_model.py"
        self.assertEqual(self.run_tool("unittest")[0].returncode, 0)                 # compiles and caches the passing file
        stamp = target.stat()
        edited = PASSING.replace("self.assertEqual(1, 1)", "self.assertEqual(1, 2)")  # same length: the cache key still matches
        self.assertEqual(len(edited), len(PASSING))
        target.write_text(edited)
        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))                  # force an identical modification time
        done, data = self.run_tool("unittest")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertEqual(data["counts"]["failures"], 1)

    def test_start_dir_and_pattern(self):
        (self.root / "checks").mkdir()
        (self.root / "checks" / "check_a.py").write_text(PASSING)
        done, data = self.run_tool("unittest", "--start-dir", "checks", "--pattern", "check_*.py")
        self.assertEqual((done.returncode, data["counts"]["tests"]), (0, 2))


class Freshness(Project):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.run_tool("unittest")[0].returncode, 0)
        self.assertEqual(self.fresh(), 0)

    def test_editing_any_project_file_makes_it_stale(self):
        (self.root / "src" / "model.py").write_text("K = 2\n")
        self.assertEqual(self.fresh(), 1)

    def test_a_new_untracked_file_makes_it_stale(self):
        (self.root / "src" / "extra.py").write_text("X = 1\n")
        self.assertEqual(self.fresh(), 1)

    def test_deleting_a_tracked_file_makes_it_stale(self):
        (self.root / "src" / "model.py").unlink()
        self.assertEqual(self.fresh(), 1)

    def test_ignored_files_and_caches_do_not(self):
        (self.root / "build").mkdir()
        (self.root / "build" / "out.bin").write_text("x")
        (self.root / "src" / "__pycache__").mkdir()
        (self.root / "src" / "__pycache__" / "model.cpython-313.pyc").write_bytes(b"\0")
        (self.root / ".pytest_cache").mkdir()
        self.assertEqual(self.fresh(), 0)

    def test_reverting_the_edit_makes_it_fresh_again(self):
        (self.root / "src" / "model.py").write_text("K = 2\n")
        self.assertEqual(self.fresh(), 1)
        (self.root / "src" / "model.py").write_text("K = 1\n")
        self.assertEqual(self.fresh(), 0)

    def test_the_module_command_line_agrees(self):
        module = ROOT / "scripts" / "verification_evidence.py"
        same = subprocess.run([sys.executable, str(module), "fresh", "--subject", ".", "--kind", "tests"], cwd=self.root,
                              capture_output=True, text=True)
        self.assertEqual(same.returncode, 0, same.stdout + same.stderr)

    def test_a_passing_ratchet_record_does_not_stand_in_for_a_failed_test_run(self):
        self.git("config", "user.name", "T")
        self.git("config", "user.email", "t@example.invalid")
        self.git("commit", "-qm", "base")
        self.suite(PASSING.replace("self.assertEqual(1, 1)", "self.assertEqual(1, 2)"))
        self.run_tool("unittest")                                              # failed run
        ratchet = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "test_ratchet.py"), "--baseline-ref", "HEAD"],
                                 cwd=self.root, capture_output=True, text=True)
        self.assertEqual(ratchet.returncode, 0, ratchet.stderr)               # a passing record of another kind, same tree
        self.assertEqual(self.records()[-1]["kind"], "ratchet")
        self.assertEqual(self.fresh(), 1)

    def test_a_later_failing_run_is_not_fresh(self):
        self.suite(PASSING.replace("self.assertEqual(1, 1)", "self.assertEqual(1, 2)"))
        self.run_tool("unittest")
        self.suite(PASSING)                                    # back to the passing files, but the latest run failed
        self.assertEqual(self.fresh(), 1)


class Other(Project):
    def test_tests_that_modify_the_tree_are_flagged_and_bound_to_the_files_before(self):
        self.suite(PASSING.replace("self.assertEqual(1, 1)",
                                   "open('src/generated.py', 'w').write('Y = 1')\n        self.assertEqual(1, 1)"))
        done, data = self.run_tool("unittest")
        self.assertEqual(done.returncode, 0)
        self.assertIn("tree_changed_during_run", data["flags"])
        self.assertEqual(self.fresh(), 1)                     # the files now differ from what was tested

    def test_command_runner_knows_only_the_exit_status(self):
        done, data = self.run_tool("command", "--", sys.executable, "-c", "pass")
        self.assertEqual(done.returncode, 0)
        self.assertIn("counts_unavailable", data["flags"])
        self.assertEqual(self.run_tool("command", "--", sys.executable, "-c", "raise SystemExit(1)")[0].returncode, 1)
        self.assertEqual(self.run_tool("command", "--", "no-such-program-anywhere")[0].returncode, 2)
        self.assertEqual(self.run_tool("command")[0].returncode, 2)

    def test_timeout_kills_the_run(self):
        started = time.monotonic()
        done, data = self.run_tool("command", "--timeout-s", "1", "--", sys.executable, "-c", "import time; time.sleep(60)")
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(data["reason"], "timed out")

    def test_not_a_git_repository_exits_two(self):
        plain = Path(self._tmp.name) / "plain"
        plain.mkdir()
        done = subprocess.run([sys.executable, "-B", str(SCRIPT), "unittest", "--cwd", str(plain)], capture_output=True,
                              text=True, env=dict(os.environ, GIT_CEILING_DIRECTORIES=self._tmp.name))
        self.assertEqual(done.returncode, 2)

    def test_no_evidence_and_unwritable_evidence(self):
        self.assertEqual(self.run_tool("unittest", "--no-evidence")[0].returncode, 0)
        self.assertEqual(self.records(), [])
        (self.root / ".verification").write_text("a file\n")
        done = self.run_tool("unittest")[0]
        self.assertEqual(done.returncode, 2)
        self.assertIn("evidence NOT recorded", done.stderr)

    def test_fresh_without_any_run(self):
        self.assertEqual(self.fresh(), 1)

    def test_no_runner_given(self):
        self.assertEqual(self.run_tool()[0].returncode, 2)

    def test_suite_name_is_recorded_and_filters_fresh(self):
        self.run_tool("unittest", "--name", "fast")
        self.assertEqual(self.records()[-1]["name"], "fast")
        self.assertEqual(self.run_tool("fresh", "--name", "fast")[0].returncode, 0)
        self.assertEqual(self.run_tool("fresh", "--name", "slow")[0].returncode, 1)


@unittest.skipUnless(HAVE_PYTEST, "pytest not installed")
class Pytest(Project):
    def test_pytest_counts_come_from_junit(self):
        self.suite("def test_a():\n    assert 1 == 1\n\n\ndef test_b():\n    assert 2 == 2\n")
        done, data = self.run_tool("pytest", "--", "-q", "tests")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((data["counts"]["tests"], data["counts"]["failures"]), (2, 0))
        self.assertFalse((self.root / ".pytest_cache").exists())

    def test_pytest_failure_collection_error_and_no_tests(self):
        self.suite("def test_a():\n    assert 1 == 2\n")
        done, data = self.run_tool("pytest", "--", "-q", "tests")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(data["counts"]["failures"], 1)                       # read from the JUnit report
        self.assertTrue(any("test_a" in i for i in data["counts"]["failed_ids"]))
        self.suite("import no_such_module_anywhere\n\ndef test_a():\n    pass\n")
        self.assertEqual(self.run_tool("pytest", "--", "-q", "tests")[0].returncode, 1)
        self.suite("x = 1\n")
        done, data = self.run_tool("pytest", "--", "-q", "tests")
        self.assertEqual((done.returncode, data["reason"]), (1, "no tests ran"))

    def test_pytest_also_ignores_a_stale_cache(self):
        target = self.root / "tests" / "test_model.py"
        good = "def test_a():\n    assert 1 == 1\n"
        target.write_text(good)
        self.assertEqual(self.run_tool("pytest", "--", "-q", "tests")[0].returncode, 0)
        stamp = target.stat()
        target.write_text("def test_a():\n    assert 1 == 2\n")
        self.assertEqual(len(good), len(target.read_text()))
        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assertEqual(self.run_tool("pytest", "--", "-q", "tests")[0].returncode, 1)

    def test_pytest_that_writes_no_report_is_an_error(self):
        self.suite("def test_a():\n    assert 1 == 1\n")
        done, data = self.run_tool("pytest", "--", "--no-such-pytest-option")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(data["counts"]["errors"], 1)
        self.assertIn("pytest wrote no report", data["counts"]["failed_ids"][0])

    def test_pytest_arguments_are_passed_through(self):
        self.suite("def test_a():\n    assert 1 == 1\n\n\ndef test_b():\n    assert 1 == 2\n")
        done, data = self.run_tool("pytest", "--", "-q", "tests", "-k", "test_a")
        self.assertEqual((done.returncode, data["counts"]["tests"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
