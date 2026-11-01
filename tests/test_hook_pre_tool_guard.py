"""Tests for scripts/hook_pre_tool_guard.py (Claude Code PreToolUse payload format).

Run: python3 -m unittest discover -s tests -v   (from the plugin root)
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "hook_pre_tool_guard.py"
sys.path.insert(0, str(SCRIPT.parent))
import hook_pre_tool_guard as guard  # noqa: E402


def run_hook(payload):
    """Run the hook as Claude Code does: JSON on stdin, decision JSON on stdout."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)], input=payload, capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout


class CheckTests(unittest.TestCase):
    def test_write_with_inv_denied(self):
        p = {"tool_name": "Write", "tool_input": {"file_path": "a.py", "content": "x = np.linalg.inv(A) @ b"}}
        self.assertIn("matrix inversion", guard.check(p))

    def test_edit_with_inv_denied(self):
        p = {"tool_name": "Edit", "tool_input": {"file_path": "a.py", "old_string": "x", "new_string": "scipy.linalg.inv(A)"}}
        self.assertIsNotNone(guard.check(p))

    def test_numpy_long_name_denied(self):
        p = {"tool_name": "Write", "tool_input": {"file_path": "a.py", "content": "numpy.linalg.inv(A)"}}
        self.assertIsNotNone(guard.check(p))

    def test_multiedit_denied_when_any_edit_has_inv(self):
        edits = [{"new_string": "ok"}, {"new_string": "np.linalg.inv(M)"}]
        p = {"tool_name": "MultiEdit", "tool_input": {"file_path": "a.f90", "edits": edits}}
        self.assertIsNotNone(guard.check(p))

    def test_solve_allowed(self):
        p = {"tool_name": "Write", "tool_input": {"file_path": "a.py", "content": "np.linalg.solve(A, b)"}}
        self.assertIsNone(guard.check(p))

    def test_pinv_allowed(self):
        p = {"tool_name": "Write", "tool_input": {"file_path": "a.py", "content": "np.linalg.pinv(A)"}}
        self.assertIsNone(guard.check(p))

    def test_old_string_is_not_scanned(self):
        # Removing an inversion must not be blocked.
        p = {"tool_name": "Edit", "tool_input": {"file_path": "a.py", "old_string": "np.linalg.inv(A)", "new_string": "solve(A, b)"}}
        self.assertIsNone(guard.check(p))

    def test_non_scientific_extension_allowed(self):
        p = {"tool_name": "Write", "tool_input": {"file_path": "notes.md", "content": "np.linalg.inv(A)"}}
        self.assertIsNone(guard.check(p))

    def test_other_tools_ignored(self):
        p = {"tool_name": "Bash", "tool_input": {"command": "echo np.linalg.inv(A)"}}
        self.assertIsNone(guard.check(p))


def write(content, path="a.py"):
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}}


class ImportAwareTests(unittest.TestCase):
    """Cases the old substring match got wrong."""

    def test_from_import_inv_denied(self):
        self.assertIsNotNone(guard.check(write("from numpy.linalg import inv\nx = inv(A) @ b")))

    def test_from_import_with_alias_denied(self):
        self.assertIsNotNone(guard.check(write("from scipy.linalg import inv as minv\nminv(A)")))

    def test_module_alias_denied(self):
        self.assertIsNotNone(guard.check(write("import scipy.linalg as la\nla.inv(A)")))

    def test_from_scipy_import_linalg_denied(self):
        self.assertIsNotNone(guard.check(write("from scipy import linalg\nlinalg.inv(A)")))

    def test_torch_inverse_and_linalg_inv_denied(self):
        self.assertIsNotNone(guard.check(write("import torch\ntorch.inverse(A)")))
        self.assertIsNotNone(guard.check(write("import torch\ntorch.linalg.inv(A)")))

    def test_whitespace_before_paren_denied(self):
        self.assertIsNotNone(guard.check(write("import numpy as np\nx = np.linalg.inv (A)")))

    def test_unresolved_alias_still_denied(self):
        self.assertIsNotNone(guard.check(write("y = jnp.linalg.inv(A)")))

    def test_comment_and_docstring_allowed(self):
        src = 'def f(A, b):\n    """Do not use np.linalg.inv(A)."""\n    # never np.linalg.inv(A)\n    return np.linalg.solve(A, b)\n'
        self.assertIsNone(guard.check(write(src)))

    def test_string_literal_allowed(self):
        self.assertIsNone(guard.check(write('msg = "avoid np.linalg.inv(A)"')))

    def test_unrelated_inv_function_allowed(self):
        # a local function named inv that is not imported from a linear-algebra module
        self.assertIsNone(guard.check(write("def inv(x):\n    return 1.0 / x\ny = inv(2.0)")))

    def test_pinv_and_solve_allowed(self):
        self.assertIsNone(guard.check(write("import numpy as np\nnp.linalg.pinv(A); np.linalg.solve(A, b)")))

    def test_indented_snippet_edit_denied(self):
        p = {"tool_name": "Edit", "tool_input": {"file_path": "a.py", "old_string": "pass",
             "new_string": "    if ok:\n        x = np.linalg.inv(A)"}}
        self.assertIsNotNone(guard.check(p))

    def test_unparseable_snippet_uses_fallback(self):
        p = {"tool_name": "Edit", "tool_input": {"file_path": "a.py", "old_string": "x",
             "new_string": "    + np.linalg.inv(A) @ b)"}}
        self.assertIsNotNone(guard.check(p))
        p["tool_input"]["new_string"] = "    + b)  # np.linalg.inv(A) is banned"
        self.assertIsNone(guard.check(p))

    def test_edit_resolves_imports_from_file_on_disk(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "solver.py")
            with open(path, "w") as fh:
                fh.write("from numpy.linalg import inv\n")
            p = {"tool_name": "Edit", "tool_input": {"file_path": path, "old_string": "x", "new_string": "y = inv(A)"}}
            self.assertIsNotNone(guard.check(p))
            # a relative path is resolved against the payload cwd
            p["tool_input"]["file_path"] = "solver.py"
            p["cwd"] = d
            self.assertIsNotNone(guard.check(p))


class TruncatedPiAndMutableDefaultTests(unittest.TestCase):
    def test_truncated_pi_literals_denied(self):
        for lit in ("3.14159", "3.1416"):
            reason = guard.check(write(f"area = {lit} * r**2"))
            self.assertIn("Truncated pi", reason, lit)

    def test_full_precision_pi_and_unrelated_floats_allowed(self):
        self.assertIsNone(guard.check(write("import math\narea = math.pi * r**2")))
        self.assertIsNone(guard.check(write("x = 3.141592653589793")))
        self.assertIsNone(guard.check(write("x = 13.14159")))                   # different number
        self.assertIsNone(guard.check(write("x = 1  # pi is about 3.14159\n")))   # comment
        self.assertIsNone(guard.check(write('"""pi = 3.1416"""\nx = 1')))        # docstring / string

    def test_pi_in_unparseable_snippet_uses_fallback(self):
        p = {"tool_name": "Edit", "tool_input": {"file_path": "a.py", "old_string": "x",
             "new_string": "    + 3.14159 * r)"}}
        self.assertIn("Truncated pi", guard.check(p))

    def test_mutable_numpy_default_denied(self):
        for src in ("import numpy as np\ndef f(x=np.zeros(3)):\n    return x",
                    "import numpy as np\ndef f(*, w=np.array([1.0])):\n    return w",
                    "import numpy\ndef f(a, b=numpy.ones((2, 2))):\n    return b"):
            self.assertIn("Mutable NumPy", guard.check(write(src)), src)

    def test_safe_defaults_allowed(self):
        self.assertIsNone(guard.check(write("import numpy as np\ndef f(x=None, n=3):\n    return np.zeros(n) if x is None else x")))
        self.assertIsNone(guard.check(write("import numpy as np\ndef f(x):\n    y = np.zeros(3)\n    return y")))

    def test_hazard_scripts_may_name_their_own_patterns(self):
        p = write("pattern = 'np.linalg.inv('\nx = np.linalg.inv(A)", path="scripts/hook_pre_tool_guard.py")
        self.assertIsNone(guard.check(p))

    def test_non_python_files_check_pi_only_via_fallback(self):
        self.assertIn("Truncated pi", guard.check(write("double a = 3.14159 * r * r;", path="k.cpp")))
        self.assertIsNone(guard.check(write("double a = M_PI * r * r;", path="k.cpp")))


class BashTests(unittest.TestCase):
    def bash(self, cmd):
        return {"tool_name": "Bash", "tool_input": {"command": cmd}}

    def test_heredoc_write_denied(self):
        self.assertIsNotNone(guard.check(self.bash("cat > solver.py <<'EOF'\nx = np.linalg.inv(A)\nEOF")))

    def test_redirect_denied(self):
        self.assertIsNotNone(guard.check(self.bash("echo 'x = np.linalg.inv(A)' >> solver.py")))

    def test_sed_in_place_denied(self):
        self.assertIsNotNone(guard.check(self.bash("sed -i 's/solve(A, b)/np.linalg.inv(A) @ b/' solver.py")))

    def test_grep_and_run_allowed(self):
        self.assertIsNone(guard.check(self.bash("grep -rn 'np.linalg.inv(' src/")))
        self.assertIsNone(guard.check(self.bash("python3 solver.py")))

    def test_write_without_inversion_allowed(self):
        self.assertIsNone(guard.check(self.bash("echo 'x = 1' > solver.py")))


    def test_a_mention_outside_the_written_content_is_not_flagged(self):
        for command in ("grep -rn 'np.linalg.inv(' src/*.py > hits.txt",
                        "printf '%s' '{\"content\": \"x = np.linalg.inv(A)\"}' | python3 tool.py src/x.py",
                        "python3 - <<'E'\nfrom pathlib import Path\nprint(Path('src/x.py').read_text().count('np.linalg.inv('))\nE",
                        "cat a.txt > solver.py; grep -n 'np.linalg.inv(' solver.py"):
            with self.subTest(command=command):
                self.assertIsNone(guard.check(self.bash(command)))

    def test_tee_and_a_heredoc_with_the_file_after_the_marker_are_flagged(self):
        self.assertIsNotNone(guard.check(self.bash("echo 'np.linalg.inv(A)' | tee solver.py")))
        self.assertIsNotNone(guard.check(self.bash("cat <<EOF > solver.py\nx = np.linalg.inv(A)\nEOF")))

    def test_the_marker_applies_in_a_heredoc(self):
        self.assertIsNone(guard.check(self.bash(
            "cat > solver.py <<'EOF'\nC = np.linalg.inv(J.T @ J)  # sciencestack: inverse-is-the-result\nEOF")))


class MarkerTests(unittest.TestCase):
    MARK = "  # sciencestack: inverse-is-the-result"

    def test_the_marked_line_is_allowed(self):
        self.assertIsNone(guard.check(write("import numpy as np\nC = np.linalg.inv(J.T @ J)" + self.MARK + "\n")))

    def test_a_marker_on_another_line_does_not_help(self):
        source = "import numpy as np\nD = 1" + self.MARK + "\nC = np.linalg.inv(J.T @ J)\n"
        self.assertIn("matrix inversion", guard.check(write(source)))

    def test_a_multi_line_call_may_carry_it_on_any_of_its_lines(self):
        self.assertIsNone(guard.check(write("import numpy as np\nC = np.linalg.inv(\n    J.T @ J" + self.MARK + "\n)\n")))

    def test_one_marker_does_not_cover_a_second_inversion(self):
        source = "import numpy as np\nC = np.linalg.inv(A)" + self.MARK + "\nD = np.linalg.inv(B)\n"
        self.assertIsNotNone(guard.check(write(source)))

    def test_an_unparseable_snippet_honours_it(self):
        self.assertIsNone(guard.check(write("    C = np.linalg.inv(A)" + self.MARK + "\n  broken(\n")))

    def test_it_does_not_excuse_another_hazard(self):
        self.assertIn("Truncated pi", guard.check(write("x = 3.14159" + self.MARK + "\n")))

    def test_the_reason_says_how_to_use_it(self):
        self.assertIn("inverse-is-the-result", guard.check(write("x = np.linalg.inv(A)\n")))


class OtherFormsOfInversionTests(unittest.TestCase):
    def test_a_negative_matrix_power_is_an_inversion(self):
        for source in ("import numpy as np\nx = np.linalg.matrix_power(A, -1) @ b\n",
                       "from numpy.linalg import matrix_power as mp\nx = mp(A, -2)\n"):
            with self.subTest(source=source):
                self.assertIn("matrix inversion", guard.check(write(source)))

    def test_a_positive_or_unknown_matrix_power_is_not(self):
        self.assertIsNone(guard.check(write("import numpy as np\nx = np.linalg.matrix_power(A, 3)\n")))
        self.assertIsNone(guard.check(write("import numpy as np\nx = np.linalg.matrix_power(A, k)\n")))

    def test_dot_I_counts_only_for_a_numpy_matrix(self):
        self.assertIn("matrix inversion", guard.check(write("import numpy as np\nA = np.matrix(data)\nx = A.I * b\n")))
        self.assertIsNone(guard.check(write("import numpy as np\nA = np.array(data)\nx = config.I + 1\n")))
        self.assertIsNone(guard.check(write("x = circuit.I * R\n")))

    def test_the_marker_covers_dot_I(self):
        source = "import numpy as np\nA = np.matrix(d)\nC = A.I  # sciencestack: inverse-is-the-result\n"
        self.assertIsNone(guard.check(write(source)))


class TestDataTests(unittest.TestCase):
    def test_pi_is_data_in_a_test(self):
        for path in ("tests/test_parse.py", "test_parse.py", "src/parse_test.py", "pkg/tests/data.py"):
            with self.subTest(path=path):
                self.assertIsNone(guard.check(write("assert parse('3.14159') == 3.14159\n", path=path)))

    def test_pi_is_a_hazard_in_source(self):
        for path in ("src/parse.py", "contest.py", "latest/x.py"):
            with self.subTest(path=path):
                self.assertIn("Truncated pi", guard.check(write("r = 3.14159 * d\n", path=path)))

    def test_an_inversion_in_a_test_is_still_flagged(self):
        self.assertIn("matrix inversion", guard.check(write("x = np.linalg.inv(A)\n", path="tests/test_a.py")))

    def test_the_reason_says_when_the_language_is_not_parsed(self):
        self.assertIn("not parsed", guard.check(write("x = np.linalg.inv(A);\n", path="k.rs")))
        self.assertNotIn("not parsed", guard.check(write("x = np.linalg.inv(A)\n", path="k.py")))


class SubprocessTests(unittest.TestCase):
    def test_deny_output_format(self):
        payload = json.dumps({"tool_name": "Write", "permission_mode": "auto",
                              "tool_input": {"file_path": "a.py", "content": "np.linalg.inv(A)"}})
        code, out = run_hook(payload)
        self.assertEqual(code, 0)
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(decision["hookEventName"], "PreToolUse")
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("solve", decision["permissionDecisionReason"])

    def decision(self, env=None, **extra):
        payload = {"tool_name": "Write", "tool_input": {"file_path": "a.py", "content": "np.linalg.inv(A)"}, **extra}
        proc = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload), capture_output=True, text=True,
                              env=dict(os.environ, **(env or {})))
        return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] if proc.stdout.strip() else None

    def test_a_person_is_asked_and_nobody_is_denied(self):
        self.assertEqual(self.decision(), "ask")
        self.assertEqual(self.decision(permission_mode="default"), "ask")
        self.assertEqual(self.decision(permission_mode="acceptEdits"), "ask")
        self.assertEqual(self.decision(permission_mode="auto"), "deny")
        self.assertEqual(self.decision(permission_mode="bypassPermissions"), "deny")

    def test_the_off_switch_covers_this_gate_too(self):
        self.assertIsNone(self.decision(env={"SCIENCESTACK_HOOKS": "off"}))
        self.assertIsNone(self.decision(env={"SCIENCESTACK_HOOKS": "off"}, permission_mode="auto"))

    def test_allow_prints_nothing(self):
        payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "a.py", "content": "y = 1"}})
        code, out = run_hook(payload)
        self.assertEqual((code, out), (0, ""))

    def test_empty_input_means_no_payload(self):
        self.assertEqual(run_hook(""), (0, ""))
        self.assertEqual(run_hook("   \n"), (0, ""))

    def test_malformed_input_fails_closed_with_an_ask_that_shows_the_error(self):
        for bad in ("not json", "[]", "42", '"text"'):
            code, out = run_hook(bad)
            self.assertEqual(code, 0, bad)
            decision = json.loads(out)["hookSpecificOutput"]
            self.assertEqual((decision["hookEventName"], decision["permissionDecision"]), ("PreToolUse", "ask"), bad)
            self.assertIn("the hook itself failed", decision["permissionDecisionReason"])

    def test_an_internal_error_fails_closed(self):
        """A tool_input of the wrong type used to crash check() and be swallowed (fail open)."""
        payload = json.dumps({"tool_name": "Write", "tool_input": "not an object"})
        code, out = run_hook(payload)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_antigravity_native_toolcall_format(self):
        deny_payload = json.dumps({
            "toolCall": {
                "name": "write_file",
                "args": {"Path": "solver.py", "Content": "from numpy.linalg import inv\nx = inv(A)"},
            }
        })
        code, out = run_hook(deny_payload)
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["decision"], "force_ask")         # a plain ask would honour a cached "Always Allow"
        self.assertIn("solve", parsed["reason"])
        self.assertNotIn("hookSpecificOutput", parsed)            # protojson rejects unknown fields

        allow_payload = json.dumps({
            "toolCall": {
                "name": "write_file",
                "args": {"Path": "solver.py", "Content": "import numpy as np\nx = np.linalg.solve(A, b)"},
            }
        })
        code2, out2 = run_hook(allow_payload)
        self.assertEqual(code2, 0)
        self.assertEqual(json.loads(out2)["decision"], "allow")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "solver.py"
            path.write_text("from scipy.linalg import " + "in" + "v as invert\nx = 1\n")
            edit_payload = json.dumps({
                "toolCall": {
                    "name": "edit_file",
                    "args": {"Path": str(path), "Target": "x = 1", "Replacement": "x = invert(A)"},
                },
                "workspacePaths": [tmp],
            })
            code3, out3 = run_hook(edit_payload)
            self.assertEqual(code3, 0)
            self.assertEqual(json.loads(out3)["decision"], "force_ask")

        cmd_payload = json.dumps({
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "echo 'x = np.linalg." + "in" + "v(A)' > solver.py"},
            }
        })
        code4, out4 = run_hook(cmd_payload)
        self.assertEqual(code4, 0)
        self.assertEqual(json.loads(out4)["decision"], "force_ask")


if __name__ == "__main__":
    unittest.main()
