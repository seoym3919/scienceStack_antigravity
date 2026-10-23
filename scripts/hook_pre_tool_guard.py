#!/usr/bin/env python3
r"""
scienceStack Antigravity PreToolUse Lifecycle Hook.

Inspects write_file and edit_file tool calls before execution (at 0 context token cost)
to block three high-severity numerical and scientific porting hazards:
1. Explicit matrix inversions (np.linalg.inv, scipy.linalg.inv) -> use solve(A, b).
2. Low-precision hardcoded pi literals (3.14159, 3.1416) -> use np.pi / math.pi / M_PI.
3. Mutable NumPy array defaults in Python function signatures (def f(x=np.zeros(...))).
"""

import json
import re
import sys

_INV_RE = re.compile(r"\b(?:np|numpy|scipy)\.linalg\.inv\s*\(")
_BAD_PI_RE = re.compile(r"(?<![0-9.])3\.141(?:59|6)(?![0-9])")
_MUTABLE_DEFAULT_RE = re.compile(
    r"def\s+\w+\s*\([^)]*=\s*(?:np|numpy)\.(?:zeros|ones|empty|array|full)\s*\("
)


def _strip_comments(code: str) -> str:
    lines = []
    for line in code.splitlines():
        s = line.strip()
        if s.startswith("#") or s.startswith("//") or s.startswith("!"):
            continue
        lines.append(line)
    return "\n".join(lines)


def main() -> None:
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            print(json.dumps({"decision": "allow"}))
            return

        payload = json.loads(raw_input)
        tool_call = payload.get("toolCall", {})
        tool_name = tool_call.get("name", "")
        args = tool_call.get("args", {})

        if tool_name in ("write_file", "edit_file"):
            path = str(args.get("Path", ""))
            # Skip hook scripts and test files that intentionally reference these patterns
            if "hook_pre_tool_guard" in path or "audit_numerical_ast" in path:
                print(json.dumps({"decision": "allow"}))
                return

            if path.endswith((".py", ".pyx", ".cpp", ".cc", ".c", ".cu", ".f90", ".f", ".jl", ".rs")):
                raw_code = str(args.get("Content", "")) + "\n" + str(args.get("Replacement", ""))
                code = _strip_comments(raw_code)

                # 1. Explicit matrix inversion check
                if _INV_RE.search(code):
                    print(json.dumps({
                        "decision": "deny",
                        "reason": (
                            "[scienceStack Safety Gate] Explicit matrix inversion ('linalg.inv') detected. "
                            "Matrix inversion amplifies roundoff by condition number kappa(A). "
                            "Use 'np.linalg.solve(A, b)' or 'scipy.linalg.solve(A, b)' instead."
                        ),
                    }))
                    return

                # 2. Truncated pi literal check
                if _BAD_PI_RE.search(code):
                    print(json.dumps({
                        "decision": "deny",
                        "reason": (
                            "[scienceStack Safety Gate] Truncated pi literal (3.14159 / 3.1416) detected. "
                            "Low-precision constants limit numerical accuracy to ~1e-6 and break L2 < 1e-12 parity. "
                            "Use machine-precision 'np.pi', 'math.pi', or 'M_PI' (3.141592653589793)."
                        ),
                    }))
                    return

                # 3. Mutable NumPy array default argument in Python
                if path.endswith(".py") and _MUTABLE_DEFAULT_RE.search(code):
                    print(json.dumps({
                        "decision": "deny",
                        "reason": (
                            "[scienceStack Safety Gate] Mutable NumPy array default argument detected in function signature. "
                            "Default arrays are evaluated once at import time and mutate across calls. "
                            "Use 'x: np.ndarray | None = None' and initialize inside the function body."
                        ),
                    }))
                    return

        print(json.dumps({"decision": "allow"}))
    except Exception:
        print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
