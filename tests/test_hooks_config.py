"""Structure of hooks/hooks.json: every script it runs exists, and the fail-closed wiring cannot silently drift.

Run (from the plugin root):  python3 -B -m unittest discover -s tests -v
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS_PATH = ROOT / "hooks" / "hooks.json"
if not HOOKS_PATH.exists():
    HOOKS_PATH = ROOT / "tests" / "fixtures" / "claude_hooks.json"
HOOKS = json.loads(HOOKS_PATH.read_text())["hooks"]


def entries(event):
    return HOOKS[event]


def commands(entry):
    return [h["command"] for h in entry["hooks"]]


def script_of(command):
    match = re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/scripts/(\w+\.py)", command)
    return match.group(1) if match else None


class HooksJson(unittest.TestCase):
    def test_every_script_the_hooks_run_exists_and_ignores_empty_input(self):
        for event, items in HOOKS.items():
            for entry in items:
                for command in commands(entry):
                    name = script_of(command)
                    if name is None:
                        continue                                   # the SessionStart echo
                    path = ROOT / "scripts" / name
                    self.assertTrue(path.exists(), (event, name))
                    done = subprocess.run([sys.executable, "-B", str(path)], input="", capture_output=True, text=True)
                    self.assertEqual((done.returncode, done.stdout), (0, ""), (name, done.stderr))

    def test_the_file_edit_guards_fail_closed_through_claude_code_too(self):
        edit = [e for e in entries("PreToolUse") if e["matcher"] == "Write|Edit|MultiEdit"]
        self.assertEqual(len(edit), 1)
        names = [script_of(c) for c in commands(edit[0])]
        self.assertEqual(names, ["hook_pre_tool_guard.py", "hook_test_guard.py"])
        for hook in edit[0]["hooks"]:
            self.assertEqual(hook["onFailure"], "block", hook["command"])

    def test_the_shell_entry_does_not_block_every_command_when_a_hook_breaks(self):
        shell = [e for e in entries("PreToolUse") if e["matcher"] == "Bash"]
        self.assertEqual(len(shell), 1)
        self.assertEqual([script_of(c) for c in commands(shell[0])], ["hook_pre_tool_guard.py", "hook_test_guard.py"])
        for hook in shell[0]["hooks"]:
            self.assertNotIn("onFailure", hook)                    # the scripts ask on their own errors; see hook_common.py

    def test_the_recorder_and_the_stop_gate_are_wired_to_the_right_events(self):
        post = entries("PostToolUse")
        self.assertEqual([(e["matcher"], [script_of(c) for c in commands(e)]) for e in post],
                         [("Write|Edit|MultiEdit", ["hook_record_edit.py"])])
        stop = entries("Stop")
        self.assertEqual([[script_of(c) for c in commands(e)] for e in stop], [["hook_stop_gate.py"]])
        self.assertNotIn("onFailure", stop[0]["hooks"][0])         # it has no effect on Stop; the script handles its own errors

    def test_timeouts_are_set_and_sane(self):
        for event, items in HOOKS.items():
            for entry in items:
                for hook in entry["hooks"]:
                    self.assertIn("timeout", hook, (event, hook["command"]))
                    self.assertLessEqual(hook["timeout"], 60)

    def test_the_matcher_is_an_exact_tool_name_list(self):
        for event in ("PreToolUse", "PostToolUse"):
            for entry in entries(event):
                self.assertRegex(entry["matcher"], r"^[A-Za-z|]+$")   # letters and '|' only: matched as exact names, not a regex


if __name__ == "__main__":
    unittest.main()
