"""Tests for scripts/hook_test_guard.py (PreToolUse: ask before a test, reference or evidence file is weakened).

Run (from the plugin root):  python3 -B -m unittest discover -s tests -v

The hook is run as Claude Code runs it: a JSON payload on stdin, a decision JSON (or nothing) on stdout, in throw-away git
repositories. It must only ever ask (never deny), only in opted-in projects, and fail closed on its own errors.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "hook_test_guard.py"
sys.path.insert(0, str(ROOT / "scripts"))

import hook_common as hc  # noqa: E402
import hook_test_guard as htg  # noqa: E402

TEST_FILE = textwrap.dedent('''
    import unittest
    import numpy as np


    class T(unittest.TestCase):
        def test_close(self):
            np.testing.assert_allclose(1.0, 1.0, rtol=1e-9)
            self.assertLess(0.0, 1e-10)

        def test_other(self):
            self.assertEqual(1, 1)
''')
MANIFEST = {"schema": "reference-checks/1", "checks": [
    {"id": "kepler", "rationale": "Kepler solver must match the root", "benchmark": "kepler", "solver": "src/k.py:solve"},
    {"id": "heat", "rationale": "golden heat profile from the 2024 run",
     "compare": {"ref": "golden/heat.txt", "test": "build/heat.out", "rtol": 1e-9, "atol": 1e-12}}]}


class Project(unittest.TestCase):
    marker = "reference-checks.json"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "proj"
        for sub in ("tests", "src", "golden", "build"):
            (self.root / sub).mkdir(parents=True)
        self.test_path = self.root / "tests" / "test_physics.py"
        self.test_path.write_text(TEST_FILE)
        (self.root / "golden" / "heat.txt").write_text("1.0 2.0\n")
        (self.root / "golden" / "other.txt").write_text("not a reference\n")
        self.git("init", "-q", "-b", "main")
        if self.marker == "reference-checks.json":
            (self.root / "reference-checks.json").write_text(json.dumps(MANIFEST, indent=2))
        elif self.marker == "test-ratchet-approvals.json":
            (self.root / "test-ratchet-approvals.json").write_text(json.dumps({"schema": "test-ratchet-approvals/1", "approvals": []}))
        elif self.marker == ".verification":
            (self.root / ".verification").mkdir()
        self.git("add", "-A")

    def tearDown(self):
        self._tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=True)

    def run_hook(self, payload, env=None, raw=None):
        full = dict(os.environ, **(env or {}))
        done = subprocess.run([sys.executable, "-B", str(SCRIPT)], input=raw if raw is not None else json.dumps(payload),
                              capture_output=True, text=True, env=full)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)["hookSpecificOutput"] if done.stdout.strip() else None

    def payload(self, tool, tool_input, cwd=None):
        return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(cwd or self.root),
                "session_id": "s1"}

    def edit(self, old, new, path=None, **extra):
        return self.payload("Edit", {"file_path": str(path or self.test_path), "old_string": old, "new_string": new, **extra})

    def assert_ask(self, decision, *texts):
        self.assertIsNotNone(decision, "expected an ask")
        self.assertEqual((decision["hookEventName"], decision["permissionDecision"]), ("PreToolUse", "ask"))
        for text in texts:
            self.assertIn(text, decision["permissionDecisionReason"])
        return decision["permissionDecisionReason"]


class OptIn(Project):
    def test_a_project_that_never_used_verification_is_left_alone(self):
        self.marker_removed = True
        for name in ("reference-checks.json",):
            (self.root / name).unlink(missing_ok=True)
        self.assertIsNone(self.run_hook(self.edit("rtol=1e-9", "rtol=1e-3")))

    def test_each_marker_opts_the_project_in(self):
        for marker in ("reference-checks.json", "test-ratchet-approvals.json", ".verification"):
            for name in ("reference-checks.json", "test-ratchet-approvals.json"):
                (self.root / name).unlink(missing_ok=True)
            if (self.root / ".verification").exists():
                (self.root / ".verification").rmdir()
            if marker == ".verification":
                (self.root / marker).mkdir()
            else:
                (self.root / marker).write_text("{}")
            self.assert_ask(self.run_hook(self.edit("rtol=1e-9", "rtol=1e-3")), "loosened")

    def test_a_directory_that_is_not_a_git_project_is_left_alone(self):
        plain = Path(self._tmp.name) / "plain"
        (plain / "tests").mkdir(parents=True)
        (plain / "reference-checks.json").write_text("{}")
        (plain / "tests" / "test_a.py").write_text(TEST_FILE)
        env = {"GIT_CEILING_DIRECTORIES": self._tmp.name}
        self.assertIsNone(self.run_hook(self.edit("rtol=1e-9", "rtol=1e-3", path=plain / "tests" / "test_a.py"), env=env))

    def test_the_escape_hatch_for_the_person_turns_the_hook_off(self):
        self.assertIsNone(self.run_hook(self.edit("rtol=1e-9", "rtol=1e-3"), env={"SCIENCESTACK_HOOKS": "off"}))
        self.assert_ask(self.run_hook(self.edit("rtol=1e-9", "rtol=1e-3"), env={"SCIENCESTACK_HOOKS": "on"}))


class TestFiles(Project):
    def test_a_looser_tolerance_in_an_edit_asks_and_names_the_test_and_kind(self):
        reason = self.assert_ask(self.run_hook(self.edit("rtol=1e-9", "rtol=1e-3")), "tests/test_physics.py", "test file",
                                 "loosened", "T::test_close", "assert_allclose rtol")
        self.assertIn("test_ratchet.py", reason)

    def test_only_ever_ask_never_deny(self):
        for old, new in (("rtol=1e-9", "rtol=1e-3"), ("self.assertEqual(1, 1)", "pass")):
            self.assertEqual(self.run_hook(self.edit(old, new))["permissionDecision"], "ask")

    def test_write_of_the_whole_file(self):
        self.assert_ask(self.run_hook(self.payload("Write", {"file_path": str(self.test_path),
                                                              "content": TEST_FILE.replace("rtol=1e-9", "rtol=1e-3")})), "loosened")

    def test_multiedit_where_only_the_second_edit_weakens(self):
        edits = [{"old_string": "import numpy as np", "new_string": "import numpy as np  # fine"},
                 {"old_string": "self.assertLess(0.0, 1e-10)", "new_string": "self.assertLess(0.0, 1e-4)"}]
        self.assert_ask(self.run_hook(self.payload("MultiEdit", {"file_path": str(self.test_path), "edits": edits})), "loosened")

    def test_each_kind_of_weakening(self):
        cases = {"removed an assertion": ("        self.assertLess(0.0, 1e-10)\n", "", "assertions_reduced"),
                 "skip added": ("    def test_other(self):", "    @unittest.skip('later')\n    def test_other(self):", "skip_added"),
                 "tolerance hidden": ("rtol=1e-9", "rtol=get_tol()", "not_literal"),
                 "test renamed away": ("def test_other(self):", "def other(self):", "removed")}
        for label, (old, new, kind) in cases.items():
            self.assert_ask(self.run_hook(self.edit(old, new)), kind)

    def test_harmless_edits_are_silent(self):
        for old, new in (("rtol=1e-9", "rtol=1e-12"), ("self.assertLess(0.0, 1e-10)", "self.assertLess(0.0, 1e-12)"),
                         ("import numpy as np", "import numpy as np  # comment"),
                         ("    def test_other(self):", "    def test_new(self):\n        self.assertTrue(True)\n\n    def test_other(self):")):
            self.assertIsNone(self.run_hook(self.edit(old, new)), (old, new))
            self.assertIsNotNone(htg.apply_edit("Edit", {"old_string": old, "new_string": new}, TEST_FILE),
                                 "the fixture edit must apply, or this test proves nothing")

    def test_new_files_and_other_files_are_silent(self):
        new_test = self.root / "tests" / "test_new.py"
        self.assertIsNone(self.run_hook(self.payload("Write", {"file_path": str(new_test), "content": TEST_FILE.replace("1e-9", "1e-1")})))
        src = self.root / "src" / "solver.py"
        src.write_text("TOL = 1e-12\n")
        self.assertIsNone(self.run_hook(self.edit("TOL = 1e-12", "TOL = 1e-3", path=src)))

    def test_an_edit_that_cannot_apply_is_left_to_claude_code(self):
        self.assertIsNone(self.run_hook(self.edit("text that is not in the file", "rtol=1e-3")))
        twice = self.root / "tests" / "test_twice.py"
        twice.write_text("def test_a():\n    x = 1e-9\n    y = 1e-9\n")
        self.assertIsNone(self.run_hook(self.edit("1e-9", "1e-3", path=twice)))                       # not unique: refused anyway
        self.assertIsNone(self.run_hook(self.payload("Edit", {"file_path": str(self.root / "tests" / "missing.py"),
                                                              "old_string": "a", "new_string": "b"})))

    def test_replace_all_is_applied_to_every_occurrence(self):
        twice = self.root / "tests" / "test_twice.py"
        twice.write_text("import numpy as np\n\n\ndef test_a():\n    np.testing.assert_allclose(1, 1, rtol=1e-9)\n"
                         "    np.testing.assert_allclose(2, 2, rtol=1e-9)\n")
        self.assert_ask(self.run_hook(self.edit("rtol=1e-9", "rtol=1e-3", path=twice, replace_all=True)), "loosened")

    def test_a_step_that_leaves_the_file_unparseable_is_not_judged(self):
        self.assertIsNone(self.run_hook(self.edit("def test_other(self):", "def test_other(self:")))
        self.test_path.write_text("def broken(:\n")
        self.assertIsNone(self.run_hook(self.edit("def broken(:", "def broken():")))

    def test_findings_accepted_in_the_approvals_file_are_not_asked_about_again(self):
        (self.root / "test-ratchet-approvals.json").write_text(json.dumps({"schema": "test-ratchet-approvals/1", "approvals": [
            {"test": "tests/test_physics.py::T::test_close", "kind": "loosened", "reason": "float32 path; documented in docs/precision.md"}]}))
        self.assertIsNone(self.run_hook(self.edit("rtol=1e-9", "rtol=1e-3")))
        reason = self.assert_ask(self.run_hook(self.edit("self.assertEqual(1, 1)", "pass")), "assertions_reduced")   # another kind
        self.assertNotIn("assert_allclose", reason)

    def test_an_approval_covers_only_its_own_kind_unless_it_says_any(self):
        def approvals(kind):
            (self.root / "test-ratchet-approvals.json").write_text(json.dumps({"schema": "test-ratchet-approvals/1", "approvals": [
                {"test": "tests/test_physics.py::T::test_close", "kind": kind, "reason": "documented in docs/precision.md"}]}))
        approvals("removed")                                           # a different kind: the loosening is still asked about
        self.assert_ask(self.run_hook(self.edit("rtol=1e-9", "rtol=1e-3")), "loosened")
        approvals("any")                                               # any kind for that test
        self.assertIsNone(self.run_hook(self.edit("rtol=1e-9", "rtol=1e-3")))
        self.assertIsNone(self.run_hook(self.edit("rtol=1e-9", "rtol=get_tol()")))
        approvals("loosened")                                          # the matching kind, but a not_literal change is another kind
        self.assert_ask(self.run_hook(self.edit("rtol=1e-9", "rtol=get_tol()")), "not_literal")

    def test_a_broken_approvals_file_does_not_hide_findings(self):
        (self.root / "test-ratchet-approvals.json").write_text("{not json")
        self.assert_ask(self.run_hook(self.edit("rtol=1e-9", "rtol=1e-3")), "loosened")

    def test_relative_paths_and_subdirectory_cwd(self):
        decision = self.run_hook(self.payload("Edit", {"file_path": "tests/test_physics.py", "old_string": "rtol=1e-9",
                                                       "new_string": "rtol=1e-3"}, cwd=self.root))
        self.assert_ask(decision, "tests/test_physics.py")
        decision = self.run_hook(self.payload("Edit", {"file_path": "test_physics.py", "old_string": "rtol=1e-9",
                                                       "new_string": "rtol=1e-3"}, cwd=self.root / "tests"))
        self.assert_ask(decision, "tests/test_physics.py")

    def test_conftest_and_suffix_named_tests(self):
        for name in ("conftest.py", "solver_test.py"):
            path = self.root / "tests" / name
            path.write_text("TOL = 1e-12\n\n\ndef test_a():\n    assert abs(0) < TOL\n")
            self.assert_ask(self.run_hook(self.edit("TOL = 1e-12", "TOL = 1e-3", path=path)), "loosened")

    def test_more_than_eight_findings_are_summarised(self):
        many = "import numpy as np\n\n\n" + "".join(
            "def test_%d():\n    np.testing.assert_allclose(1, 1, rtol=1e-12)\n\n\n" % i for i in range(12))
        path = self.root / "tests" / "test_many.py"
        path.write_text(many)
        decision = self.run_hook(self.payload("Write", {"file_path": str(path), "content": many.replace("rtol=1e-12", "rtol=1e-3")}))
        reason = self.assert_ask(decision, "and 4 more")
        self.assertEqual(reason.count("loosened"), 8)


class Manifest(Project):
    def manifest_edit(self, change):
        manifest = json.loads(json.dumps(MANIFEST))
        change(manifest)
        return self.payload("Write", {"file_path": str(self.root / "reference-checks.json"), "content": json.dumps(manifest, indent=2)})

    def test_removing_a_check_or_raising_a_tolerance_asks(self):
        self.assert_ask(self.run_hook(self.manifest_edit(lambda m: m["checks"].pop(0))), "reference manifest", "check removed")
        self.assert_ask(self.run_hook(self.manifest_edit(lambda m: m["checks"][1]["compare"].update(rtol=1e-3))), "rtol loosened")

    def test_pointing_a_check_at_another_reference_asks(self):
        self.assert_ask(self.run_hook(self.manifest_edit(lambda m: m["checks"][1]["compare"].update(ref="golden/other.txt"))),
                        "now compares against")

    def test_adding_or_changing_an_approved_relaxation_asks_even_when_nothing_else_changes(self):
        reason = self.assert_ask(self.run_hook(self.manifest_edit(lambda m: m["checks"][0].update(approved_relaxation="sensor noise floor"))),
                                 "approved_relaxation", "decision for you")
        self.assertIn("sensor noise floor", reason)

    def test_adding_a_check_or_tightening_is_silent(self):
        self.assertIsNone(self.run_hook(self.manifest_edit(lambda m: m["checks"].append(
            {"id": "new", "rationale": "another solver must match", "benchmark": "kepler", "solver": "src/n.py:solve"}))))
        self.assertIsNone(self.run_hook(self.manifest_edit(lambda m: m["checks"][1]["compare"].update(rtol=1e-12))))

    def test_invalid_json_cannot_be_checked_so_it_asks(self):
        self.assert_ask(self.run_hook(self.payload("Write", {"file_path": str(self.root / "reference-checks.json"),
                                                              "content": "{not json"})), "not valid JSON")

    def test_an_edit_of_the_manifest_is_judged_after_the_edit(self):
        decision = self.run_hook(self.edit('"rtol": 1e-09', '"rtol": 0.001', path=self.root / "reference-checks.json"))
        self.assert_ask(decision, "rtol loosened")

    def test_the_determinism_requirement_cannot_be_dropped_quietly(self):
        strict = json.loads(json.dumps(MANIFEST))
        strict["checks"][0].update(repeat=2)
        (self.root / "reference-checks.json").write_text(json.dumps(strict, indent=2))
        self.assert_ask(self.run_hook(self.manifest_edit(lambda m: m["checks"][0].pop("repeat", None))), "repeat_min loosened")


class OtherProtectedFiles(Project):
    def test_golden_files_named_in_the_manifest_ask_but_other_data_does_not(self):
        golden = self.root / "golden" / "heat.txt"
        self.assert_ask(self.run_hook(self.payload("Write", {"file_path": str(golden), "content": "9.0 9.0\n"})), "golden file")
        self.assert_ask(self.run_hook(self.edit("1.0", "1.5", path=golden)), "golden reference")
        self.assertIsNone(self.run_hook(self.payload("Write", {"file_path": str(self.root / "golden" / "other.txt"), "content": "x\n"})))
        self.assertIsNone(self.run_hook(self.payload("Write", {"file_path": str(golden), "content": "1.0 2.0\n"})))      # unchanged

    def test_the_approvals_file_asks_for_any_change_and_lists_the_entry(self):
        path = self.root / "test-ratchet-approvals.json"
        new = {"schema": "test-ratchet-approvals/1", "approvals": [
            {"test": "tests/test_physics.py::T::test_close", "kind": "loosened", "reason": "stated accuracy need is 1e-3"}]}
        reason = self.assert_ask(self.run_hook(self.payload("Write", {"file_path": str(path), "content": json.dumps(new)})),
                                 "approvals file", "approves tests/test_physics.py::T::test_close [loosened]", "stated accuracy need")
        path.write_text(json.dumps(new))
        self.assert_ask(self.run_hook(self.payload("Write", {"file_path": str(path), "content": json.dumps(
            {"schema": "test-ratchet-approvals/1", "approvals": []})})), "removes the approval")

    def test_the_evidence_directory_asks(self):
        (self.root / ".verification").mkdir(exist_ok=True)
        self.assert_ask(self.run_hook(self.payload("Write", {"file_path": str(self.root / ".verification" / "log.jsonl"),
                                                              "content": "{}\n"})), "evidence", "not evidence")


class Shell(Project):
    def bash(self, command, cwd=None):
        return self.run_hook(self.payload("Bash", {"command": command}, cwd=cwd))

    def test_writes_into_protected_files_ask(self):
        for command in ("echo x > tests/test_physics.py", "echo x >> tests/test_physics.py", "cat a | tee tests/test_physics.py",
                        "sed -i 's/1e-9/1e-3/' tests/test_physics.py", "perl -pi -e 's/a/b/' tests/test_physics.py",
                        "rm tests/test_physics.py", "rm -f tests/conftest.py", "mv /tmp/new.py tests/test_physics.py",
                        "cp /tmp/new.py tests/test_physics.py", "echo {} > reference-checks.json",
                        "cat x | tee -a test-ratchet-approvals.json", "echo x > .verification/log.jsonl",
                        "python3 -c \"open('tests/test_physics.py', 'w').write('x')\"",
                        "python3 -c \"from pathlib import Path; Path('tests/test_physics.py').write_text('x')\"",
                        "echo x > golden/heat.txt", "sed -i 's/1/2/' golden/heat.txt"):
            self.assert_ask(self.bash(command), "shell command", "cannot be checked")

    def test_reading_running_and_unrelated_commands_are_silent(self):
        for command in ("pytest tests/test_physics.py > log.txt", "python3 -m unittest tests/test_physics.py 2> err.txt",
                        "cat tests/test_physics.py", "grep -n rtol tests/test_physics.py > hits.txt",
                        "cp tests/test_physics.py /tmp/backup.py", "mv tests/test_physics.py.bak /tmp/", "git diff tests/test_physics.py",
                        "ls tests > listing.txt", "echo hi > notes.txt", "cat reference-checks.json | python3 -m json.tool",
                        "rm build/heat.out", "echo x > src/solver.py", "git checkout -- tests/test_physics.py"):
            self.assertIsNone(self.bash(command), command)

    def test_a_command_that_cds_into_the_project_or_names_it_by_absolute_path_is_judged_too(self):
        """Found in a live session: the shell does not necessarily start in the project, and the guard only looked at the
        session's directory. Absolute paths and `cd` targets now count."""
        elsewhere = Path(self._tmp.name) / "elsewhere"
        elsewhere.mkdir()
        project = self.root
        for command in (f"cd {project} && sed -i 's/1e-9/1e-3/' tests/test_physics.py",
                        f"cd '{project}'; echo x > tests/test_physics.py",
                        f'cd "{project}/tests" && rm test_physics.py',
                        f"sed -i 's/a/b/' {project}/tests/test_physics.py",
                        f"echo {{}} > {project}/reference-checks.json",
                        f"cat a | tee {project}/golden/heat.txt",
                        f"(cd {project} && sed -i 's/a/b/' tests/test_physics.py)"):
            with self.subTest(command=command):
                self.assert_ask(self.bash(command, cwd=elsewhere), "shell command")
        os.environ["HOME"] = str(self.root.parent)
        try:
            decision = self.run_hook(self.payload("Bash", {"command": "sed -i 's/a/b/' ~/proj/tests/test_physics.py"}, cwd=elsewhere),
                                     env={"HOME": str(self.root.parent)})
        finally:
            os.environ.pop("HOME", None)
        self.assert_ask(decision, "shell command")

    def test_relative_and_tilde_cd_targets_are_followed(self):
        """Only `cd` can reveal these: no absolute path names the project."""
        elsewhere = Path(self._tmp.name) / "elsewhere"
        elsewhere.mkdir()
        rel = os.path.relpath(self.root, elsewhere)
        for command in (f"cd {rel} && sed -i 's/a/b/' tests/test_physics.py",
                        f'cd "{rel}" && sed -i \'s/a/b/\' tests/test_physics.py',
                        f"cd '{rel}' && rm tests/test_physics.py"):
            with self.subTest(command=command):
                self.assert_ask(self.bash(command, cwd=elsewhere), "shell command")
        decision = self.run_hook(self.payload("Bash", {"command": "cd ~/proj && sed -i 's/a/b/' tests/test_physics.py"}, cwd=elsewhere),
                                 env={"HOME": str(self.root.parent)})
        self.assert_ask(decision, "shell command")

    def test_relative_cds_from_inside_the_project_and_unrelated_directories(self):
        self.assert_ask(self.bash("cd tests && sed -i 's/1e-9/1e-3/' test_physics.py"), "shell command")
        elsewhere = Path(self._tmp.name) / "elsewhere"
        (elsewhere / "tests").mkdir(parents=True)
        (elsewhere / "tests" / "test_a.py").write_text("x = 1\n")
        self.assertIsNone(self.bash("sed -i 's/1/2/' tests/test_a.py", cwd=elsewhere))               # not an opted-in project
        self.assertIsNone(self.bash(f"cd {elsewhere} && sed -i 's/1/2/' tests/test_a.py", cwd=elsewhere))
        self.assertIsNone(self.bash("sed -i 's/a/b/' tests/test_physics.py", cwd=elsewhere))         # relative path, shell elsewhere: unknowable
        # Documented false positive: protected NAMES are matched anywhere in the command, so when the session's own project is
        # opted in, a write to a test-looking file in an unrelated directory asks as well.
        self.assert_ask(self.bash(f"cd {elsewhere} && sed -i 's/1/2/' tests/test_a.py", cwd=self.root), "shell command")

    def test_running_things_in_the_project_from_elsewhere_stays_silent(self):
        elsewhere = Path(self._tmp.name) / "elsewhere"
        elsewhere.mkdir()
        for command in (f"cd {self.root} && pytest tests/test_physics.py > log.txt", f"cat {self.root}/tests/test_physics.py",
                        f"cd {self.root} && git diff tests/test_physics.py", f"cp {self.root}/tests/test_physics.py /tmp/backup.py",
                        f"echo hi > {elsewhere}/notes.txt"):
            self.assertIsNone(self.bash(command, cwd=elsewhere), command)

    def test_at_most_a_handful_of_candidate_directories_are_examined(self):
        elsewhere = Path(self._tmp.name) / "elsewhere"
        elsewhere.mkdir()
        many = " ; ".join(f"cd /tmp/nonexistent{i}" for i in range(20))
        self.assertIsNone(self.bash(f"{many}; cd {self.root} && sed -i 's/a/b/' tests/test_physics.py", cwd=elsewhere))

    def test_the_shell_check_also_needs_an_opted_in_project(self):
        (self.root / "reference-checks.json").unlink()
        self.assertIsNone(self.bash("echo x > tests/test_physics.py"))

    def test_bash_payloads_without_a_command_are_ignored(self):
        self.assertIsNone(self.run_hook(self.payload("Bash", {})))
        self.assertIsNone(self.run_hook(self.payload("Bash", {"command": 5})))


class PermissionModes(Project):
    """Found live: in auto mode Claude Code answers an "ask" itself, so there a finding must be a deny."""

    def weakening(self, mode, tool="Edit"):
        if tool == "Bash":
            payload = self.payload("Bash", {"command": "sed -i 's/1e-9/1e-3/' tests/test_physics.py"})
        else:
            payload = self.edit("rtol=1e-9", "rtol=1e-3")
        if mode is not None:
            payload["permission_mode"] = mode
        return self.run_hook(payload)

    def test_default_and_other_attended_modes_ask(self):
        for mode in ("default", "acceptEdits", "plan"):
            for tool in ("Edit", "Bash"):
                with self.subTest(mode=mode, tool=tool):
                    self.assert_ask(self.weakening(mode, tool))

    def test_a_missing_or_unknown_mode_asks(self):
        for mode in (None, "", "somethingNew", 7):
            with self.subTest(mode=mode):
                self.assert_ask(self.weakening(mode))

    def test_auto_and_bypass_deny_with_the_way_forward(self):
        for mode in ("auto", "bypassPermissions"):
            for tool in ("Edit", "Bash"):
                with self.subTest(mode=mode, tool=tool):
                    decision = self.weakening(mode, tool)
                    self.assertEqual(decision["permissionDecision"], "deny")
                    reason = decision["permissionDecisionReason"]
                    for text in (mode, "test-ratchet-approvals.json", "SCIENCESTACK_HOOKS=off"):
                        self.assertIn(text, reason)

    def test_harmless_edits_stay_silent_in_every_mode(self):
        for mode in ("default", "auto", "bypassPermissions"):
            payload = self.edit("import numpy as np", "import numpy as np  # note")
            payload["permission_mode"] = mode
            with self.subTest(mode=mode):
                self.assertIsNone(self.run_hook(payload))

    def test_the_escape_hatch_still_wins_in_auto_mode(self):
        payload = self.edit("rtol=1e-9", "rtol=1e-3")
        payload["permission_mode"] = "auto"
        self.assertIsNone(self.run_hook(payload, env={"SCIENCESTACK_HOOKS": "off"}))


class FailClosed(Project):
    def test_bad_input_asks_with_the_error(self):
        for raw in ("not json", "[]", "42"):
            decision = self.run_hook(None, raw=raw)
            self.assert_ask(decision, "the hook itself failed")

    def test_empty_input_prints_nothing(self):
        self.assertIsNone(self.run_hook(None, raw=""))

    def test_an_exception_inside_the_hook_becomes_an_ask(self):
        out = io.StringIO()
        with mock.patch.object(htg, "file_reason", side_effect=RuntimeError("boom")), \
                mock.patch("sys.stdin", io.StringIO(json.dumps(self.edit("a", "b")))), mock.patch("sys.stdout", out):
            self.assertEqual(hc.run_pre_tool_hook(htg.decide, "test guard"), 0)
        decision = json.loads(out.getvalue())["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "ask")
        self.assertIn("RuntimeError: boom", decision["permissionDecisionReason"])

    def test_unrelated_tools_and_odd_tool_inputs_are_silent_not_errors(self):
        self.assertIsNone(self.run_hook(self.payload("Read", {"file_path": str(self.test_path)})))
        self.assertIsNone(self.run_hook(self.payload("Write", "not an object")))
        self.assertIsNone(self.run_hook(self.payload("Edit", {"file_path": 5})))
        self.assertIsNone(self.run_hook(self.payload("MultiEdit", {"file_path": str(self.test_path), "edits": "x"})))


class ApplyEdit(unittest.TestCase):
    def test_edit_semantics(self):
        self.assertEqual(htg.apply_edit("Write", {"content": "new"}, "old"), "new")
        self.assertEqual(htg.apply_edit("Write", {"content": "new"}, None), "new")
        self.assertIsNone(htg.apply_edit("Write", {"content": 5}, "old"))
        self.assertEqual(htg.apply_edit("Edit", {"old_string": "a", "new_string": "b"}, "xay"), "xby")
        self.assertIsNone(htg.apply_edit("Edit", {"old_string": "a", "new_string": "b"}, "aa"))              # not unique
        self.assertEqual(htg.apply_edit("Edit", {"old_string": "a", "new_string": "b", "replace_all": True}, "aa"), "bb")
        self.assertIsNone(htg.apply_edit("Edit", {"old_string": "z", "new_string": "b"}, "aa"))
        self.assertIsNone(htg.apply_edit("Edit", {"old_string": "a", "new_string": "b"}, None))
        self.assertEqual(htg.apply_edit("MultiEdit", {"edits": [{"old_string": "a", "new_string": "b"},
                                                               {"old_string": "b", "new_string": "c"}]}, "a"), "c")      # sequential
        self.assertIsNone(htg.apply_edit("MultiEdit", {"edits": [{"old_string": "a", "new_string": "b"},
                                                                {"old_string": "q", "new_string": "c"}]}, "a"))
        self.assertIsNone(htg.apply_edit("Read", {}, "a"))
        self.assertIsNone(htg.apply_edit("Edit", {"old_string": 1, "new_string": "b"}, "a"))


if __name__ == "__main__":
    unittest.main()
