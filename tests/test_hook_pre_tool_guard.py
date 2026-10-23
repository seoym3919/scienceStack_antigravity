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


class SubprocessTests(unittest.TestCase):
    def test_deny_output_format(self):
        payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "a.py", "content": "np.linalg.inv(A)"}})
        code, out = run_hook(payload)
        self.assertEqual(code, 0)
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(decision["hookEventName"], "PreToolUse")
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("solve", decision["permissionDecisionReason"])

    def test_allow_prints_nothing(self):
        payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "a.py", "content": "y = 1"}})
        code, out = run_hook(payload)
        self.assertEqual((code, out), (0, ""))

    def test_empty_and_malformed_input_fail_open(self):
        for bad in ("", "not json", "[]"):
            code, out = run_hook(bad)
            self.assertEqual((code, out), (0, ""), bad)

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
        self.assertEqual(parsed["decision"], "deny")
        self.assertIn("solve", parsed["reason"])

        allow_payload = json.dumps({
            "toolCall": {
                "name": "write_file",
                "args": {"Path": "solver.py", "Content": "import numpy as np\nx = np.linalg.solve(A, b)"},
            }
        })
        code2, out2 = run_hook(allow_payload)
        self.assertEqual(code2, 0)
        self.assertEqual(json.loads(out2)["decision"], "allow")


if __name__ == "__main__":
    unittest.main()
