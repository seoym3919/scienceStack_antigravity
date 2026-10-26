#!/usr/bin/env python3
r"""
hook_record_edit.py - PostToolUse hook for Write, Edit and MultiEdit: remember which project files this session changed.

The stop gate (hook_stop_gate.py) needs to know what was edited in THIS session; the evidence log says what was verified
and when, not who changed a file afterwards. This hook only records: it never blocks (a PostToolUse hook cannot) and prints
nothing. It acts only in opted-in git projects (see hook_common.py) and ignores documentation, caches and .verification/.

A failure to record is not silent: the script exits 1 with the error on stderr, which Claude Code shows as a hook error.
State lives in ~/.cache/sciencestack/hooks/<session id>.json ($SCIENCESTACK_STATE_DIR overrides it).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hook_common as hc  # noqa: E402


def record(payload) -> bool:
    tool_input = payload.get("tool_input")
    if payload.get("tool_name") not in ("Write", "Edit", "MultiEdit") or not isinstance(tool_input, dict):
        return False
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str):
        return False
    cwd = Path(payload.get("cwd") or os.getcwd())
    path = Path(file_path)
    path = (path if path.is_absolute() else cwd / path).resolve()
    root = hc.project_root(path)
    if not hc.opted_in(root):
        return False
    try:
        rel = path.relative_to(root.resolve()).as_posix()
    except ValueError:
        return False
    if not hc.counts_as_edit(rel):
        return False
    session = payload.get("session_id")
    state = hc.load_state(session)
    edited = state.setdefault("edited", {}).setdefault(str(root.resolve()), {})
    edited[rel] = edited.get(rel, 0) + 1
    hc.save_state(session, state)
    return True


def main() -> int:
    if hc.hooks_disabled():
        return 0
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("the hook input is not a JSON object")
        record(payload)
    except Exception as exc:
        print(f"scienceStack record-edit hook failed ({type(exc).__name__}: {exc}); the stop gate may miss edits made in "
              "this session.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
