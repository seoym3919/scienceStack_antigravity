#!/usr/bin/env python3
r"""
scienceStack Claude Code PreToolUse Lifecycle Hook.

Blocks three numerical hazards in scientific code before it is written:
 1. Explicit matrix inversion: numpy.linalg.inv, scipy.linalg.inv, scipy.sparse.linalg.inv,
    jax.numpy.linalg.inv, jax.scipy.linalg.inv, cupy.linalg.inv, torch.linalg.inv, torch.inverse
 2. Truncated pi literals (3.14159 / 3.1416): use math.pi / np.pi / M_PI
 3. Mutable NumPy array default arguments (def f(x=np.zeros(3))): evaluated once at import time

Detection is import-aware for Python (aliases such as ``import numpy as np`` or
``import scipy.linalg as la`` and ``from numpy.linalg import inv`` are resolved), so comments,
docstrings and strings that merely mention ``inv(`` are not flagged. For an Edit, the file already
on disk supplies the imports. Where Python cannot be parsed (a partial snippet, Cython, other
languages), a conservative pattern match on comment-stripped text is used instead.

Guarded tools: Write, Edit, MultiEdit (scientific source files), and Bash (best effort: only when the
command both writes to a scientific source file and contains an inversion call).

Input  (stdin):  Claude Code PreToolUse JSON, e.g.
    {"tool_name": "Write", "tool_input": {"file_path": "...", "content": "..."}}
    {"tool_name": "Edit",  "tool_input": {"file_path": "...", "new_string": "..."}}
    {"tool_name": "MultiEdit", "tool_input": {"file_path": "...", "edits": [{"new_string": "..."}]}}
    {"tool_name": "Bash", "tool_input": {"command": "..."}}
Output (stdout): a `hookSpecificOutput` deny decision, or nothing to defer to the normal permission flow.
Fail closed: invalid input or an internal error prints an "ask" decision that shows the error, so a broken guard
cannot silently let a hazard through (empty input means no payload and prints nothing). hooks.json also sets
"onFailure": "block" on the file-edit entry for crashes before this code runs.
"""

import ast
import json
import os
import re
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hook_common import run_pre_tool_hook  # noqa: E402
from inversion_detect import (  # noqa: E402
    FORBIDDEN_CALLS, import_aliases, is_inversion_call, is_truncated_pi, mutable_array_default,
)

SCIENTIFIC_EXTENSIONS = (".py", ".pyx", ".cpp", ".cu", ".f90", ".jl", ".rs")
GUARDED_FILE_TOOLS = ("Write", "Edit", "MultiEdit")

# Fallback for text that cannot be parsed as Python.
_FALLBACK_RE = re.compile(r"\blinalg\s*\.\s*inv\s*\(|\btorch\s*\.\s*inverse\s*\(")
_BASH_WRITE_RE = re.compile(
    r"(>>?\s*\S+\.(?:py|pyx|cpp|cu|f90|jl|rs)\b|\btee\b|\bsed\s+-[a-zA-Z]*i|<<)"
)
_BASH_SCI_FILE_RE = re.compile(r"\.(?:py|pyx|cpp|cu|f90|jl|rs)\b")

PI_REASON = (
    "[scienceStack Safety Gate] Truncated pi literal (3.14159 / 3.1416) detected. "
    "Low-precision constants limit numerical accuracy to ~1e-6 and break L2 < 1e-12 parity. "
    "Use machine-precision 'np.pi', 'math.pi', or 'M_PI' (3.141592653589793)."
)
MUTABLE_REASON = (
    "[scienceStack Safety Gate] Mutable NumPy array default argument detected in function signature. "
    "Default arrays are evaluated once at import time and mutate across calls. "
    "Use 'x: np.ndarray | None = None' and initialize inside the function body."
)
_PI_RE = re.compile(r"(?<![0-9.])3\.141(?:59|6)(?![0-9])")
_MUTABLE_RE = re.compile(r"def\s+\w+\s*\([^)]*=\s*(?:np|numpy)\.(?:zeros|ones|empty|array|full)\s*\(")
SELF_REFERENCING = ("hook_pre_tool_guard", "audit_numerical_ast", "inversion_detect")   # name the patterns on purpose

REASON = (
    "[scienceStack Safety Gate] Explicit matrix inversion ('inv') detected in proposed code. "
    "Matrix inversion squares the condition number kappa(A) and degrades numerical stability. "
    "Per principle-numerical-stability-first, use 'np.linalg.solve(A, b)' or factorized solvers "
    "(Cholesky/LU/QR) instead of explicit inversion."
)


def _strip_comments(text):
    """Drop '#' comments line by line (good enough for the fallback pattern match)."""
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _parse(text):
    """Parse text as Python, tolerating an indented snippet. Returns None if it cannot be parsed."""
    for candidate in (text, textwrap.dedent(text)):
        try:
            return ast.parse(candidate)
        except (SyntaxError, ValueError):
            continue
    return None


def _has_forbidden_call(tree, aliases):
    return any(is_inversion_call(node, aliases) for node in ast.walk(tree))


def _context_tree(tool_input, cwd):
    """Parse the file already on disk (for imports when checking an Edit). None if unavailable."""
    path = tool_input.get("file_path", "")
    if not path.endswith((".py", ".pyx")):
        return None
    if not os.path.isabs(path) and cwd:
        path = os.path.join(cwd, path)
    try:
        with open(path, encoding="utf-8") as fh:
            return ast.parse(fh.read())
    except (OSError, SyntaxError, ValueError):
        return None


def violation_reason(text, context_tree=None, python_file=True):
    """Reason string if `text` (proposed source) contains a guarded hazard, else None."""
    tree = _parse(text)
    if tree is None:
        stripped = _strip_comments(text)
        if _FALLBACK_RE.search(stripped):
            return REASON
        if _PI_RE.search(stripped):
            return PI_REASON
        if python_file and _MUTABLE_RE.search(stripped):
            return MUTABLE_REASON
        return None
    aliases = import_aliases(context_tree) if context_tree is not None else {}
    aliases.update(import_aliases(tree))
    nodes = list(ast.walk(tree))
    if any(is_inversion_call(n, aliases) for n in nodes):
        return REASON
    if any(is_truncated_pi(n) for n in nodes):
        return PI_REASON
    if python_file and any(mutable_array_default(n, aliases) is not None for n in nodes):
        return MUTABLE_REASON
    return None


def text_has_inversion(text, context_tree=None):
    """Backward-compatible helper: True if `text` performs an explicit matrix inversion."""
    return violation_reason(text, context_tree) == REASON


def proposed_texts(tool_name, tool_input):
    """Return the list of text fragments a file tool call would add."""
    if tool_name == "Write":
        return [tool_input.get("content", "")]
    if tool_name == "Edit":
        return [tool_input.get("new_string", "")]
    if tool_name == "MultiEdit":
        return [e.get("new_string", "") for e in tool_input.get("edits", [])]
    return []


def check(payload):
    """Return a denial reason for a PreToolUse payload, or None to allow."""
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if (_BASH_WRITE_RE.search(command) and _BASH_SCI_FILE_RE.search(command)
                and _FALLBACK_RE.search(command)):
            return REASON
        return None

    if tool_name not in GUARDED_FILE_TOOLS:
        return None
    # Only check scientific and numerical code files
    if not tool_input.get("file_path", "").endswith(SCIENTIFIC_EXTENSIONS):
        return None

    path = tool_input.get("file_path", "")
    if any(name in path for name in SELF_REFERENCING):
        return None
    python_file = path.endswith((".py", ".pyx"))
    context = _context_tree(tool_input, payload.get("cwd", ""))
    for fragment in proposed_texts(tool_name, tool_input):
        reason = violation_reason(fragment, context, python_file)
        if reason:
            return reason
    return None


def decide(payload):
    reason = check(payload)
    return {"decision": "deny", "reason": reason} if reason else None


def main():
    return run_pre_tool_hook(decide, "safety gate")


if __name__ == "__main__":
    main()
