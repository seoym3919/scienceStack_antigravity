#!/usr/bin/env python3
r"""
hook_common.py - what every scienceStack hook script shares. Standard library only.

Claude Code hook protocol (checked against the documentation, Claude Code 2.1.310):
  PreToolUse   stdin {"hook_event_name", "tool_name", "tool_input", "cwd", "session_id", ...};
               stdout {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask"|"deny"|"allow",
               "permissionDecisionReason": ...}}. Several matching hooks run in parallel; deny beats ask beats allow.
  PostToolUse  stdin additionally "tool_response"; it cannot block (the tool already ran).
  Stop         stdin {"stop_hook_active", "last_assistant_message", "background_tasks", ...};
               stdout {"decision": "block", "reason": ...} keeps Claude working. Claude Code stops blocking after 8
               consecutive continuations. It does not run when the user interrupts.
  A hook that crashes, times out or prints invalid output does NOT block the action unless the hook entry sets
  "onFailure": "block" (Claude Code 2.1.295 or later; it has no effect on Stop).

Fail closed: a script error is turned into an "ask" prompt that shows the error, so a broken hook can never silently let
an edit through. (hooks.json also sets "onFailure": "block" on the file-edit entries to cover crashes before this code
runs.) Escape hatch for the person, not for an agent: SCIENCESTACK_HOOKS=off in the environment of Claude Code turns the
new test/reference hooks into no-ops, and `claude plugin disable sciencestack` turns off everything.

Opt-in: the test/reference protection and the stop gate act only in a git project that has already started using
scienceStack verification, i.e. it contains reference-checks.json, test-ratchet-approvals.json or a .verification/
directory. Everywhere else they do nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

MARKERS = ("reference-checks.json", "test-ratchet-approvals.json", ".verification")
MAX_FINDINGS_SHOWN = 8


def hooks_disabled() -> bool:
    return os.environ.get("SCIENCESTACK_HOOKS", "").strip().lower() == "off"


def project_root(start: Path) -> Optional[Path]:
    """The git top level containing `start` (a file or directory), or None."""
    directory = start if start.is_dir() else start.parent
    while not directory.exists() and directory != directory.parent:
        directory = directory.parent
    try:
        done = subprocess.run(["git", "-C", str(directory), "rev-parse", "--show-toplevel"], capture_output=True,
                              text=True, timeout=10, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else None


def opted_in(root: Optional[Path]) -> bool:
    return root is not None and any((root / marker).exists() for marker in MARKERS)


def pre_tool_output(decision: str, reason: str) -> Dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                   "permissionDecisionReason": reason}}


def shorten(findings: list, limit: int = MAX_FINDINGS_SHOWN) -> str:
    shown = [f"- {text}" for text in findings[:limit]]
    if len(findings) > limit:
        shown.append(f"- ... and {len(findings) - limit} more")
    return "\n".join(shown)


def run_pre_tool_hook(decide: Callable[[Dict[str, Any]], Optional[Dict[str, str]]], name: str) -> int:
    """Read the payload, call decide(payload) -> None | {"decision": "ask"|"deny", "reason": ...}, print the decision.

    Empty stdin means "no payload": print nothing. Anything unexpected (bad JSON, an exception) becomes an ask with the
    error text, never a silent allow."""
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("the hook input is not a JSON object")
        is_antigravity = "toolCall" in payload
        if is_antigravity:
            tc = payload["toolCall"]
            raw_name = tc.get("name", "")
            args = tc.get("args", {}) or {}
            norm_payload = dict(payload)
            if raw_name == "write_file":
                norm_payload.update({"tool_name": "Write", "tool_input": {"file_path": str(args.get("Path", "")), "content": str(args.get("Content", ""))}})
            elif raw_name == "edit_file":
                norm_payload.update({"tool_name": "Edit", "tool_input": {"file_path": str(args.get("Path", "")), "new_string": str(args.get("Replacement", ""))}})
            elif raw_name == "run_command":
                norm_payload.update({"tool_name": "Bash", "tool_input": {"command": str(args.get("CommandLine", ""))}})
            payload = norm_payload
        result = decide(payload)
    except Exception as exc:                                       # fail closed
        result = {"decision": "ask", "reason": f"[scienceStack {name}] the hook itself failed ({type(exc).__name__}: {exc}); "
                                              "nothing could be checked for this tool call. Approve it only if you "
                                              "have looked at it yourself."}
    if result:
        out = {
            "decision": result["decision"],
            "reason": result.get("reason", ""),
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": result["decision"],
                "permissionDecisionReason": result.get("reason", "")
            }
        }
        print(json.dumps(out))
    elif is_antigravity:
        print(json.dumps({"decision": "allow"}))
    return 0


# --------------------------------------------------------------------------------------------------------------
# Per-session memory shared by the recorder and the stop gate
# --------------------------------------------------------------------------------------------------------------

DOC_SUFFIXES = (".md", ".rst", ".txt", ".tex", ".pdf", ".png", ".svg", ".jpg", ".gitignore")
IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".verification", ".git"}


def state_dir() -> Path:
    base = os.environ.get("SCIENCESTACK_STATE_DIR")
    if base:
        return Path(base)
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "sciencestack" / "hooks"


def state_path(session_id: Any) -> Path:
    name = str(session_id or "no-session")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name):
        name = hashlib.sha256(name.encode()).hexdigest()[:32]
    return state_dir() / (name + ".json")


def load_state(session_id: Any) -> Dict[str, Any]:
    try:
        data = json.loads(state_path(session_id).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(session_id: Any, state: Dict[str, Any]) -> None:
    path = state_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    os.replace(tmp, path)
    for old in path.parent.glob("*.json"):                     # forget sessions older than 30 days
        try:
            if old != path and old.stat().st_mtime < path.stat().st_mtime - 30 * 86400:
                old.unlink()
        except OSError:
            pass


def counts_as_edit(rel: str) -> bool:
    """A project file whose change can make verification stale: not documentation, caches or the evidence directory."""
    parts = rel.split("/")
    return not any(part in IGNORED_PARTS for part in parts) and not rel.endswith(DOC_SUFFIXES)
