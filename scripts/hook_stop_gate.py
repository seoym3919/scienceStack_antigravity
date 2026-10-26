#!/usr/bin/env python3
r"""
hook_stop_gate.py - Stop hook: before Claude finishes, check that what it edited this session is still verified.

Acts only in opted-in git projects (see hook_common.py) in which hook_record_edit.py recorded edits this session. For each
such project it reads the shared evidence log (./.verification/log.jsonl, or $VERIFICATION_EVIDENCE_DIR) and reports:

  A. a verification (benchmark, compare, roundtrip) whose primary subject - the solver, the compared outputs, the function
     files - was edited this session and whose latest record is not a fresh pass: it failed, was withheld, or the files have
     changed since the run;
  B. a recorded test run (run_tests.py) that is no longer a fresh pass although a code file was edited this session;
  C. test files edited this session, in a project that uses test_ratchet.py (a ratchet record or an approvals file exists),
     without a fresh passing ratchet run since.

It does not read what Claude says: the trigger is the files, so rewording cannot avoid it.

Blocks at most ONCE per distinct situation (the state is remembered per session), never while Claude is already continuing
because of a stop hook (stop_hook_active), and never while background tasks are pending (the session is not finished).
Claude Code itself stops blocking after 8 consecutive continuations. The hook cannot see edits made through the shell
unless a project file is also edited with Edit/Write, and cannot see a claim made without any edit. If the hook itself
fails it blocks once with the error text (a failure must not look like a pass); "onFailure" does not apply to Stop hooks.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hook_common as hc  # noqa: E402
import verification_evidence as ve  # noqa: E402

VERIFICATIONS = ("benchmark", "compare", "roundtrip")


def _latest_by_key(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for record in records:
        if isinstance(record.get("key"), str):
            latest[record["key"]] = record
    return latest


def _stale_subjects(record: Dict[str, Any], base: Path, memo: Dict[str, Any]) -> List[str]:
    stale = []
    for entry in record.get("subjects", []):
        path = entry.get("path", "")
        cache_key = f"{entry.get('role')}:{path}"
        if cache_key not in memo:
            memo[cache_key] = ve._current_digest(entry, base)
        if entry.get("sha256") != memo[cache_key]:
            stale.append(path)
    return stale


def _why_not_fresh(record: Dict[str, Any], base: Path, memo: Dict[str, Any]) -> str:
    if record.get("passed") is not True:
        return "its last run failed"
    if record.get("exit_status") != 0:
        return "its last verdict was withheld (exit status %s)" % record.get("exit_status")
    stale = _stale_subjects(record, base, memo)
    if stale:
        return "files changed since its last passing run (%s)" % ", ".join(stale[:3])
    return ""


def findings_for(root: Path, edited: Dict[str, int]) -> List[str]:
    evidence_dir = ve.evidence_dir(None)
    log = evidence_dir / "log.jsonl" if os.environ.get(ve.ENV_DIR) else root / ".verification" / "log.jsonl"
    records, _ = ve.read_log(log)
    base = log.parent.parent
    edited_abs = {(root / rel).resolve() for rel in edited}
    findings: List[str] = []
    memo: Dict[str, Any] = {}
    latest = _latest_by_key(records)

    for key, record in latest.items():                                         # A
        if record.get("kind") not in VERIFICATIONS:
            continue
        primary = [e for e in record.get("subjects", []) if e.get("role") == "primary"]
        touched = [e["path"] for e in primary
                   if (Path(e["path"]) if Path(e["path"]).is_absolute() else base / e["path"]).resolve() in edited_abs]
        if not touched:
            continue
        why = _why_not_fresh(record, base, memo)
        if why:
            ident = (record.get("detail") or {}).get("manifest_id")
            hint = f"run-manifest --only {ident}" if ident else "re-run the check"
            findings.append(f"{record.get('tool')} '{record.get('name')}' ({', '.join(touched[:2])} edited): {why}; {hint}")

    code_edited = [rel for rel in edited if hc.counts_as_edit(rel)]
    if code_edited:                                                             # B
        for key, record in latest.items():
            if record.get("kind") == "tests":
                why = _why_not_fresh(record, base, memo)
                if why:
                    findings.append(f"tests '{record.get('name')}': {why}; run run_tests.py again before saying they pass")

    test_files = [rel for rel in edited if _is_test_file(rel)]                  # C
    uses_ratchet = any(r.get("kind") == "ratchet" for r in records) or (root / "test-ratchet-approvals.json").exists()
    if test_files and uses_ratchet:
        ratchet = [r for r in latest.values() if r.get("kind") == "ratchet"]
        # covered if ANY recorded ratchet run (one per baseline ref) is a fresh pass on the current files
        if not ratchet or all(_why_not_fresh(r, base, memo) for r in ratchet):
            findings.append(f"test files edited ({', '.join(test_files[:3])}) without a fresh passing test_ratchet.py run; "
                            "run it with --baseline-ref HEAD (or origin/main)")
    return findings


def _is_test_file(rel: str) -> bool:
    import test_ratchet
    return test_ratchet.is_test_file(rel, [])


def decide(payload: Dict[str, Any]) -> Dict[str, Any]:
    """{} to let Claude stop, or {"decision": "block", "reason": ...}."""
    if hc.hooks_disabled() or payload.get("stop_hook_active") or payload.get("background_tasks"):
        return {}
    session = payload.get("session_id")
    state = hc.load_state(session)
    edited_by_root = state.get("edited") or {}
    problems: List[str] = []
    for root_text, edited in sorted(edited_by_root.items()):
        root = Path(root_text)
        if not root.is_dir() or not hc.opted_in(root):
            continue
        for finding in findings_for(root, edited):
            problems.append(f"{root.name}: {finding}")
    if not problems:
        return {}
    digests = []
    for root_text in sorted(edited_by_root):
        try:
            digests.append(ve.worktree_digest(Path(root_text))[1])
        except ve.EvidenceError:
            digests.append("no-tree")
    fingerprint = hashlib.sha256(json.dumps([problems, digests]).encode()).hexdigest()
    blocked = state.setdefault("blocked", [])
    if fingerprint in blocked:
        return {}                                                                # this exact situation was already raised
    blocked.append(fingerprint)
    hc.save_state(session, state)
    return {"decision": "block",
            "reason": "scienceStack: files edited in this session are not covered by a fresh passing verification:\n"
                      + hc.shorten(problems) + "\nRe-run the checks above, or say plainly in your final answer that they were "
                      "not run and why. This reminder is shown once for this situation."}


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    payload: Dict[str, Any] = {}
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("the hook input is not a JSON object")
        result = decide(payload)
    except Exception as exc:
        # A failure must not look like a pass; but never trap Claude in a continuation it cannot get out of.
        if isinstance(payload, dict) and payload.get("stop_hook_active"):
            return 0
        result = {"decision": "block",
                  "reason": f"scienceStack stop gate failed ({type(exc).__name__}: {exc}); verification of this session's "
                            "edits could not be checked. Tell the person that, and do not claim the work is verified."}
    if result:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
