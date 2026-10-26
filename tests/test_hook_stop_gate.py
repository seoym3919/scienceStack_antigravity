"""Tests for scripts/hook_record_edit.py (PostToolUse) and scripts/hook_stop_gate.py (Stop).

Run (from the plugin root):  python3 -B -m unittest discover -s tests -v

Scenario helper: a git project with evidence records bound to the real hashes of its files; Write/Edit calls are fed to the
recorder as PostToolUse payloads; the Stop payload is fed to the gate. The gate must block at most once per situation, only
in opted-in projects, never inside its own continuation, and must name what is stale.
"""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
RECORDER = ROOT / "scripts" / "hook_record_edit.py"
GATE = ROOT / "scripts" / "hook_stop_gate.py"
sys.path.insert(0, str(ROOT / "scripts"))

import hook_common as hc  # noqa: E402
import hook_stop_gate as gate  # noqa: E402
import verification_evidence as ve  # noqa: E402


class Session(unittest.TestCase):
    session_id = "sess-1"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.state = self.base / "state"
        # in THIS process too: an in-process save_state/load_state must never touch the person's real ~/.cache
        patcher = mock.patch.dict(os.environ, {"SCIENCESTACK_STATE_DIR": str(self.state)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = self.base / "proj"
        for sub in ("src", "tests"):
            (self.root / sub).mkdir(parents=True)
        (self.root / "src" / "solver.py").write_text("K = 1\n")
        (self.root / "tests" / "test_solver.py").write_text("def test_a():\n    assert 1 == 1\n")
        (self.root / "README.md").write_text("docs\n")
        (self.root / ".verification").mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.log = self.root / ".verification" / "log.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.root, capture_output=True, text=True, check=True)

    def env(self, **extra):
        return dict(os.environ, SCIENCESTACK_STATE_DIR=str(self.state), **extra)

    def run_script(self, script, payload=None, raw=None, env=None):
        return subprocess.run([sys.executable, "-B", str(script)], input=raw if raw is not None else json.dumps(payload),
                              capture_output=True, text=True, env=env or self.env())

    # ---- recorder / gate drivers
    def edited(self, rel, tool="Edit", session=None, cwd=None, root=None):
        path = (root or self.root) / rel
        return self.run_script(RECORDER, {"hook_event_name": "PostToolUse", "tool_name": tool, "session_id": session or self.session_id,
                                           "cwd": str(cwd or root or self.root), "tool_input": {"file_path": str(path)},
                                           "tool_response": {}})

    def stop(self, session=None, env=None, **extra):
        done = self.run_script(GATE, {"hook_event_name": "Stop", "session_id": session or self.session_id, "cwd": str(self.root),
                                      "stop_hook_active": False, "last_assistant_message": "done", **extra}, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    # ---- evidence helpers: records bound to the real hashes of the files
    def subject(self, rel, role="primary", root=None):
        return ve.subject(str((root or self.root) / rel), (root or self.root), role)

    def record(self, kind="benchmark", name="kepler", key="k", passed=True, subjects=None, manifest_id=None, log=None, **extra):
        detail = {"manifest_id": manifest_id} if manifest_id else {}
        subjects = subjects if subjects is not None else [self.subject("src/solver.py")]
        return ve.record_run(log or self.log, tool="check_against_reference", plugin="sciencestack", kind=kind, name=name,
                             key=key, passed=passed, tolerance={"tol": 1e-12}, subjects=subjects, detail=detail, **extra)

    def tests_record(self, passed=True, name="unittest"):
        return ve.record_run(self.log, tool="run_tests", plugin="sciencestack", kind="tests", name=name, key="tests:" + name,
                             passed=passed, tolerance={}, subjects=[ve.tree_subject(self.root, self.root)])

    def ratchet_record(self, passed=True):
        return ve.record_run(self.log, tool="test_ratchet", plugin="sciencestack", kind="ratchet", name="test-ratchet",
                             key="ratchet:HEAD", passed=passed, tolerance={}, subjects=[ve.tree_subject(self.root, self.root)])

    def change(self, rel, text):
        (self.root / rel).write_text(text)

    def recorded(self, session=None):
        with mock.patch.dict(os.environ, {"SCIENCESTACK_STATE_DIR": str(self.state)}):
            return hc.load_state(session or self.session_id)


class Recorder(Session):
    def test_edits_in_an_opted_in_project_are_counted_per_file(self):
        for tool in ("Write", "Edit", "MultiEdit", "Edit"):
            done = self.edited("src/solver.py", tool=tool)
            self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)
        self.edited("tests/test_solver.py")
        self.assertEqual(self.recorded()["edited"][str(self.root)], {"src/solver.py": 4, "tests/test_solver.py": 1})

    def test_documentation_caches_evidence_and_other_projects_are_ignored(self):
        (self.root / "src" / "__pycache__").mkdir()
        for rel in ("README.md", "notes.rst", "src/__pycache__/x.pyc", ".verification/log.jsonl", "docs.pdf"):
            self.edited(rel)
        other = self.base / "other"
        other.mkdir()
        (other / "a.py").write_text("x = 1\n")
        self.edited("a.py", root=other)                                    # not a git project at all
        self.assertEqual(self.recorded(), {})

    def test_a_git_project_that_never_used_verification_is_ignored(self):
        plain = self.base / "plain"
        plain.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=plain, check=True)
        (plain / "a.py").write_text("x = 1\n")
        self.edited("a.py", root=plain)
        self.assertEqual(self.recorded(), {})

    def test_other_tools_and_odd_inputs_are_ignored_not_errors(self):
        for payload in ({"tool_name": "Read", "tool_input": {"file_path": str(self.root / "src/solver.py")}},
                        {"tool_name": "Bash", "tool_input": {"command": "x"}}, {"tool_name": "Edit", "tool_input": "x"},
                        {"tool_name": "Edit", "tool_input": {"file_path": 5}}, {"tool_name": "Edit"}):
            done = self.run_script(RECORDER, dict(payload, session_id="s", cwd=str(self.root)))
            self.assertEqual((done.returncode, done.stdout), (0, ""), payload)
        self.assertEqual(self.recorded("s"), {})

    def test_relative_paths_resolve_against_cwd(self):
        done = self.run_script(RECORDER, {"tool_name": "Edit", "session_id": self.session_id, "cwd": str(self.root / "src"),
                                          "tool_input": {"file_path": "solver.py"}})
        self.assertEqual(done.returncode, 0)
        self.assertIn("src/solver.py", self.recorded()["edited"][str(self.root)])

    def test_sessions_are_kept_apart_and_odd_ids_are_hashed(self):
        self.edited("src/solver.py", session="a")
        self.edited("src/solver.py", session="../../escape")
        self.assertTrue((self.state / "a.json").exists())
        self.assertEqual({p.name for p in self.state.iterdir()}, {"a.json", hashlib.sha256(b"../../escape").hexdigest()[:32] + ".json"})

    def test_old_sessions_are_forgotten(self):
        self.edited("src/solver.py", session="old")
        old = self.state / "old.json"
        long_ago = time.time() - 40 * 86400
        os.utime(old, (long_ago, long_ago))
        self.edited("src/solver.py", session="new")
        self.assertFalse(old.exists())
        self.assertTrue((self.state / "new.json").exists())

    def test_the_off_switch_and_empty_input(self):
        done = self.run_script(RECORDER, {"tool_name": "Edit", "session_id": "s", "cwd": str(self.root),
                                          "tool_input": {"file_path": str(self.root / "src/solver.py")}}, env=self.env(SCIENCESTACK_HOOKS="off"))
        self.assertEqual(done.returncode, 0)
        self.assertEqual(self.recorded("s"), {})
        self.assertEqual(self.run_script(RECORDER, raw="").returncode, 0)

    def test_a_failure_to_record_is_reported_not_silent(self):
        for raw in ("not json", "[]"):
            done = self.run_script(RECORDER, raw=raw)
            self.assertEqual(done.returncode, 1)
            self.assertIn("record-edit hook failed", done.stderr)
        (self.state).mkdir(exist_ok=True)
        (self.state / "sess-1.json").mkdir()                              # a directory where the state file should be
        done = self.edited("src/solver.py")
        self.assertEqual(done.returncode, 1)
        self.assertIn("the stop gate may miss edits", done.stderr)


class Gate(Session):
    def test_no_edits_in_this_session_means_nothing_to_report(self):
        self.record()
        self.change("src/solver.py", "K = 2\n")                           # changed, but not recorded as edited by this session
        self.assertIsNone(self.stop())

    def test_an_edited_solver_after_a_passing_check_blocks_and_names_the_check(self):
        self.record(manifest_id=None)
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        decision = self.stop()
        self.assertEqual(decision["decision"], "block")
        reason = decision["reason"]
        for text in ("proj:", "check_against_reference 'kepler'", "src/solver.py edited", "files changed since its last passing run",
                     "re-run the check", "shown once"):
            self.assertIn(text, reason)

    def test_the_hint_names_the_manifest_check_when_there_is_one(self):
        self.record(manifest_id="kepler-main")
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        self.assertIn("run-manifest --only kepler-main", self.stop()["reason"])

    def test_a_fresh_pass_is_not_blocked(self):
        self.edited("src/solver.py")
        self.record()
        self.assertIsNone(self.stop())

    def test_a_failed_or_withheld_last_run_blocks_even_if_the_files_did_not_change_since(self):
        self.record(passed=False)
        self.edited("src/solver.py")
        self.assertIn("its last run failed", self.stop()["reason"])

    def test_a_withheld_verdict_blocks(self):
        self.record(passed=False)
        record, assessment = ve.record_run(self.log, tool="t", plugin="p", kind="benchmark", name="kepler", key="k", passed=True,
                                           tolerance={"tol": 1.0}, subjects=[self.subject("src/solver.py")])   # looser, same files
        self.assertEqual((record["exit_status"], assessment["withheld"]), (3, True))
        self.edited("src/solver.py")
        self.assertIn("withheld (exit status 3)", self.stop()["reason"])

    def test_only_a_primary_subject_counts_as_the_edited_solver(self):
        self.record(subjects=[self.subject("src/solver.py", "extra")])
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        self.assertIsNone(self.stop())

    def test_it_blocks_once_per_situation(self):
        self.record()
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        self.assertEqual(self.stop()["decision"], "block")
        self.assertIsNone(self.stop())                                    # same situation: not raised again
        self.assertIsNone(self.stop())

    def test_never_inside_its_own_continuation_and_nothing_is_remembered_then(self):
        self.record()
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        self.assertIsNone(self.stop(stop_hook_active=True))
        self.assertEqual(self.stop()["decision"], "block")                # the first real stop still gets its one reminder

    def test_a_new_situation_is_raised_again(self):
        self.record()
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        self.assertEqual(self.stop()["decision"], "block")
        self.change("src/solver.py", "K = 3\n")                           # another edit: a different tree
        self.edited("src/solver.py")
        self.assertEqual(self.stop()["decision"], "block")

    def test_pending_background_work_means_the_session_is_not_finished(self):
        self.record()
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        self.assertIsNone(self.stop(background_tasks=[{"id": "t1", "type": "shell", "status": "running"}]))
        self.assertEqual(self.stop(background_tasks=[])["decision"], "block")

    def test_the_off_switch(self):
        self.record()
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        self.assertIsNone(self.stop(env=self.env(SCIENCESTACK_HOOKS="off")))

    def test_a_project_that_stopped_being_opted_in_is_ignored(self):
        self.record()
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        import shutil
        shutil.rmtree(self.root / ".verification")
        self.assertIsNone(self.stop())

    def test_other_kinds_of_verification_are_covered_too(self):
        for kind in ("compare", "roundtrip"):
            self.log.write_text("")
            self.change("src/solver.py", "K = 1\n")
            self.record(kind=kind, name=kind + "-check", key=kind)
            self.change("src/solver.py", "K = 5\n" if kind == "compare" else "K = 6\n")
            self.edited("src/solver.py", session="s-" + kind)
            reason = self.stop(session="s-" + kind)["reason"]
            self.assertIn(kind + "-check", reason)

    def test_a_different_set_of_problems_on_the_same_files_is_a_new_situation(self):
        self.record()
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        self.assertEqual(self.stop()["decision"], "block")
        self.assertIsNone(self.stop())
        # the evidence log is not part of the tree hash, so the tree is unchanged; but one more check is now failing
        self.record(key="k2", name="sod", passed=False, subjects=[self.subject("src/solver.py")])
        second = self.stop()
        self.assertEqual(second["decision"], "block")
        self.assertIn("'sod'", second["reason"])

    def test_a_project_without_the_markers_is_ignored_even_when_a_log_elsewhere_has_findings(self):
        elsewhere = self.base / "ci-evidence"
        self.record(log=elsewhere / "log.jsonl", subjects=[ve.subject(str(self.root / "src" / "solver.py"), elsewhere.parent)])
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        import shutil
        shutil.rmtree(self.root / ".verification")                      # no marker: the project never opted in
        self.assertIsNone(self.stop(env=self.env(VERIFICATION_EVIDENCE_DIR=str(elsewhere))))

    def test_the_evidence_directory_environment_variable_is_honoured(self):
        elsewhere = self.base / "ci-evidence"
        # records written with --evidence-dir elsewhere carry paths relative to that directory's parent
        self.record(log=elsewhere / "log.jsonl", subjects=[ve.subject(str(self.root / "src" / "solver.py"), elsewhere.parent)])
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        self.assertIsNone(self.stop())                                    # the project's own log is empty
        self.assertEqual(self.stop(env=self.env(VERIFICATION_EVIDENCE_DIR=str(elsewhere)))["decision"], "block")


class TestsAndRatchet(Session):
    def test_a_code_edit_after_a_recorded_test_run_blocks(self):
        self.tests_record()
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        reason = self.stop()["reason"]
        self.assertIn("tests 'unittest'", reason)
        self.assertIn("run run_tests.py again before saying they pass", reason)

    def test_documentation_in_an_old_state_file_does_not_demand_a_test_run_either(self):
        """The recorder never records documentation, but the gate must not depend on that."""
        self.tests_record()
        self.change("README.md", "more docs\n")
        with mock.patch.dict(os.environ, {"SCIENCESTACK_STATE_DIR": str(self.state)}):      # never the person's real cache
            hc.save_state(self.session_id, {"edited": {str(self.root): {"README.md": 1, "notes.txt": 1, "docs/manual.pdf": 1}}})
        self.assertEqual(json.loads((self.state / "sess-1.json").read_text())["edited"][str(self.root)]["README.md"], 1)
        self.assertIsNone(self.stop())

    def test_documentation_edits_do_not_demand_a_test_run(self):
        self.tests_record()
        self.change("README.md", "more docs\n")
        self.edited("README.md")
        self.assertIsNone(self.stop())

    def test_a_fresh_passing_test_run_is_fine_and_a_failed_one_is_not(self):
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        self.tests_record(passed=True)
        self.assertIsNone(self.stop())
        self.tests_record(passed=False)
        self.assertIn("its last run failed", self.stop()["reason"])

    def test_projects_that_never_recorded_a_test_run_are_not_nagged_about_tests(self):
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        self.assertIsNone(self.stop())

    def test_edited_test_files_need_a_fresh_ratchet_run_when_the_project_uses_the_ratchet(self):
        self.ratchet_record()
        self.change("tests/test_solver.py", "def test_a():\n    assert 1 == 2 - 1\n")
        self.edited("tests/test_solver.py")
        reason = self.stop()["reason"]
        self.assertIn("without a fresh passing test_ratchet.py run", reason)
        self.assertIn("tests/test_solver.py", reason)

    def test_an_approvals_file_is_enough_to_require_the_ratchet(self):
        (self.root / "test-ratchet-approvals.json").write_text('{"schema": "test-ratchet-approvals/1", "approvals": []}')
        self.change("tests/test_solver.py", "def test_a():\n    assert 1 == 2 - 1\n")
        self.edited("tests/test_solver.py")
        self.assertIn("test_ratchet.py", self.stop()["reason"])

    def test_a_fresh_passing_ratchet_run_clears_it_and_non_ratchet_projects_are_not_nagged(self):
        self.change("tests/test_solver.py", "def test_a():\n    assert 1 == 2 - 1\n")
        self.edited("tests/test_solver.py")
        self.assertIsNone(self.stop())                                    # no ratchet records, no approvals file
        self.ratchet_record()
        self.assertIsNone(self.stop(session="same-edits-new-session"))
        self.edited("tests/test_solver.py", session="s2")
        self.assertIsNone(self.stop(session="s2"))                        # the ratchet record is fresh for this tree

    def test_a_fresh_ratchet_run_against_any_baseline_covers_the_edits(self):
        """Ratchet runs are recorded once per baseline ref; one stale record from another baseline must not block."""
        ve.record_run(self.log, tool="test_ratchet", plugin="sciencestack", kind="ratchet", name="test-ratchet",
                      key="ratchet:origin/main", passed=True, tolerance={}, subjects=[ve.tree_subject(self.root, self.root)])
        self.change("tests/test_solver.py", "def test_a():\n    assert 1 == 2 - 1\n")             # makes that record stale
        self.edited("tests/test_solver.py", session="only-stale")
        self.assertIn("test_ratchet.py", self.stop(session="only-stale")["reason"])                # no fresh pass at all: blocked
        self.edited("tests/test_solver.py")
        self.ratchet_record()                                                                       # a fresh pass against HEAD
        self.assertIsNone(self.stop())                                                              # the stale origin/main one does not matter

    def test_several_findings_are_listed_together(self):
        self.record()
        self.tests_record()
        self.ratchet_record()
        self.change("src/solver.py", "K = 2\n")
        self.change("tests/test_solver.py", "def test_a():\n    assert 1 == 2 - 1\n")
        self.edited("src/solver.py")
        self.edited("tests/test_solver.py")
        reason = self.stop()["reason"]
        self.assertGreaterEqual(reason.count("\n- "), 3)
        self.assertIn("check_against_reference", reason)
        self.assertIn("tests 'unittest'", reason)
        self.assertIn("test_ratchet.py", reason)


class MoreThanOneProject(Session):
    def test_each_project_touched_in_the_session_is_judged(self):
        second = self.base / "second"
        (second / "src").mkdir(parents=True)
        (second / "src" / "solver.py").write_text("K = 1\n")
        (second / ".verification").mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=second, check=True)
        subprocess.run(["git", "add", "-A"], cwd=second, check=True)
        ve.record_run(second / ".verification" / "log.jsonl", tool="t", plugin="p", kind="benchmark", name="sod", key="k",
                      passed=True, tolerance={"tol": 1.0}, subjects=[ve.subject(str(second / "src/solver.py"), second)])
        self.record()
        for repo in (self.root, second):
            (repo / "src" / "solver.py").write_text("K = 9\n")
            self.edited("src/solver.py", root=repo)
        reason = self.stop()["reason"]
        self.assertIn("proj: check_against_reference 'kepler'", reason)
        self.assertIn("second: t 'sod'", reason)


class FailClosed(Session):
    def test_garbage_input_blocks_once_with_the_error(self):
        done = self.run_script(GATE, raw="not json")
        self.assertEqual(done.returncode, 0)
        decision = json.loads(done.stdout)
        self.assertEqual(decision["decision"], "block")
        self.assertIn("stop gate failed", decision["reason"])
        self.assertIn("do not claim the work is verified", decision["reason"])

    def test_empty_input_prints_nothing(self):
        done = self.run_script(GATE, raw="")
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_an_error_inside_a_continuation_does_not_trap_claude(self):
        payload = {"hook_event_name": "Stop", "session_id": "x", "stop_hook_active": True}
        out = io.StringIO()
        with mock.patch.object(gate, "decide", side_effect=RuntimeError("boom")), \
                mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), mock.patch("sys.stdout", out):
            self.assertEqual(gate.main(), 0)
        self.assertEqual(out.getvalue(), "")
        out = io.StringIO()
        with mock.patch.object(gate, "decide", side_effect=RuntimeError("boom")), \
                mock.patch("sys.stdin", io.StringIO(json.dumps(dict(payload, stop_hook_active=False)))), mock.patch("sys.stdout", out):
            gate.main()
        self.assertIn("RuntimeError: boom", json.loads(out.getvalue())["reason"])

    def test_a_corrupt_state_file_is_replaced_not_fatal(self):
        self.record()
        self.change("src/solver.py", "K = 2\n")
        self.edited("src/solver.py")
        (self.state / "sess-1.json").write_text("{corrupt")
        self.assertIsNone(self.stop())                                    # nothing recorded any more: nothing to report


if __name__ == "__main__":
    unittest.main()
