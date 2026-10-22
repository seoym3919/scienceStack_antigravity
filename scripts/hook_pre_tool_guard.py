#!/usr/bin/env python3
r"""
scienceStack Antigravity PreToolUse Lifecycle Hook.

Inspects tool calls before execution to block dangerous numerical patterns:
- Explicit matrix inversions (np.linalg.inv, scipy.linalg.inv).
"""

import sys
import json


def main():
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
            path = args.get("Path", "")
            # Only check scientific and numerical code files
            if any(path.endswith(ext) for ext in (".py", ".pyx", ".cpp", ".cu", ".f90", ".jl", ".rs")):
                content = args.get("Content", "") + " " + args.get("Replacement", "")

                # Check for explicit matrix inversion
                if "np.linalg.inv(" in content or "scipy.linalg.inv(" in content or "numpy.linalg.inv(" in content:
                    response = {
                        "decision": "deny",
                        "reason": (
                            "[scienceStack Safety Gate] Explicit matrix inversion ('inv') detected in proposed code. "
                            "Matrix inversion squares the condition number kappa(A) and degrades numerical stability. "
                            "Per principle-numerical-stability-first, use 'np.linalg.solve(A, b)' or factorized solvers "
                            "(Cholesky/LU/QR) instead of explicit inversion."
                        )
                    }
                    print(json.dumps(response))
                    return

        # Default allow
        print(json.dumps({"decision": "allow"}))
    except Exception:
        # Failsafe: never crash the tool loop on hook exception
        print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
