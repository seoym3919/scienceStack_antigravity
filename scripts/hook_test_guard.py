#!/usr/bin/env python3
r"""
hook_test_guard.py - PreToolUse hook: ask before Claude weakens a test, a reference, or a verification record.

Acts only in an opted-in git project (see hook_common.py) and only on Write, Edit, MultiEdit and Bash. It never denies:
every finding becomes an "ask" (a "deny" in auto and bypassPermissions modes, see decide), so the person sees exactly what is about to change and decides.

What it asks about (the file is taken as it WOULD be after the edit, nothing is written by the hook):

  test files (test_*.py, *_test.py, conftest.py)
      the same comparison test_ratchet.py makes, between the file now and the file after the edit: a looser tolerance,
      a tolerance that can no longer be evaluated, a removed tolerance check or test, fewer assertions, a new skip/xfail,
      fewer parametrize cases. Findings already accepted in test-ratchet-approvals.json are not asked about again.
      A file that is new, or that does not parse after the edit (a step in a larger refactor), is allowed.
  reference-checks.json
      the same ratchet reference_manifest.py applies against a baseline, with the file on disk as the baseline: a check
      removed, a tolerance raised, a requirement lowered, a check pointed at something else, or an approved_relaxation
      added or changed (an approval is a decision for the person).
  test-ratchet-approvals.json
      any change: an approval is a decision for the person.
  golden files named in reference-checks.json (compare.ref)
      any change: editing the reference is how a failing comparison is made to pass.
  .verification/
      any write: the evidence log is written by the tools; a hand-written line is not evidence.
  Bash
      a command that redirects into, tees, sed -i's, mv's/cp's onto, rm's or open(..., "w")'s one of the files above.
      The shell cannot be checked for weakening, so it asks; the ratchet and CI remain the gate. Reading or running a
      test (pytest tests/test_x.py > log.txt) does not match.

Known limits: edits made by other programs or through indirection (a script that writes the file, `python -c` building the
path at run time) are invisible; the person's own terminal is of course not hooked.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hook_common as hc  # noqa: E402

MANIFEST = "reference-checks.json"
APPROVALS = "test-ratchet-approvals.json"
VERIFICATION_DIR = ".verification"

PROTECTED_NAME = (r"[\w./~-]*(?:test_[\w.-]*\.py|[\w.-]*_test\.py|conftest\.py|reference-checks\.json|"
                  r"test-ratchet-approvals\.json|\.verification(?:/[\w./-]*)?)")
_P = PROTECTED_NAME
_Q = r"""['"]?"""
SHELL_WRITES = (
    ("redirects into", re.compile(r">>?\s*" + _Q + _P + r"\b")),
    ("pipes into tee", re.compile(r"\btee\b[^|;&\n]*?" + _Q + _P + r"\b")),
    ("edits in place (sed/perl -i)", re.compile(r"\b(?:sed|perl)\s+-[A-Za-z]*i[^|;&\n]*?" + _Q + _P + r"\b")),
    ("moves or copies onto", re.compile(r"\b(?:mv|cp|install)\b[^|;&\n]*\s" + _Q + _P + _Q + r"\s*(?:$|[;&|)])")),
    ("removes", re.compile(r"\brm\b[^|;&\n]*?" + _Q + _P + r"\b")),
    ("opens for writing", re.compile(r"open\(\s*" + _Q + _P + _Q + r"\s*,\s*['\"][wax+]")),
    ("writes with pathlib", re.compile(r"Path\(\s*" + _Q + _P + _Q + r"\s*\)\s*\.\s*(?:write_text|write_bytes|unlink)")),
)


def _tr():
    import test_ratchet
    return test_ratchet


def _rm():
    import reference_manifest
    return reference_manifest


def _benchmarks():
    import check_against_reference
    return check_against_reference.BENCHMARKS


def apply_edit(tool: str, tool_input: Dict[str, Any], current: Optional[str]) -> Optional[str]:
    """The file text after the tool call, or None when it cannot be known (Claude Code will reject such a call itself)."""
    if tool == "Write":
        content = tool_input.get("content")
        return content if isinstance(content, str) else None
    if current is None:
        return None
    if tool == "Edit":
        edits = [tool_input]
    elif tool == "MultiEdit":
        edits = tool_input.get("edits")
        if not isinstance(edits, list):
            return None
    else:
        return None
    text = current
    for edit in edits:
        old, new = edit.get("old_string"), edit.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str) or old not in text:
            return None
        if edit.get("replace_all"):
            text = text.replace(old, new)
        elif text.count(old) == 1:
            text = text.replace(old, new, 1)
        else:
            return None                                    # not unique: Claude Code refuses it
    return text


def golden_files(root: Path) -> List[str]:
    """Repo-relative golden (reference) files named by the manifest, in posix form."""
    try:
        manifest = json.loads((root / MANIFEST).read_text())
        checks = manifest.get("checks", [])
    except (OSError, ValueError, AttributeError):
        return []
    names = []
    for check in checks:
        if isinstance(check, dict) and isinstance(check.get("compare"), dict):
            ref = check["compare"].get("ref")
            if isinstance(ref, str):
                names.append(ref)
    return names


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(errors="replace") if path.is_file() else None
    except OSError:
        return None


def manifest_findings(current: Optional[str], proposed: str) -> List[str]:
    try:
        new = json.loads(proposed)
    except ValueError as exc:
        return [f"the proposed {MANIFEST} is not valid JSON ({exc.msg}); it cannot be checked"]
    try:
        old = json.loads(current) if current is not None else None
    except ValueError:
        old = None
    findings: List[str] = []
    if isinstance(new, dict) and isinstance(old, dict):
        result = _rm().ratchet(new, old, _benchmarks())
        findings += [f"check '{v['id']}': {v['problem']}" for v in result["violations"]]
        before = {c.get("id"): (c.get("approved_relaxation") or "").strip() for c in old.get("checks", []) if isinstance(c, dict)}
        for check in new.get("checks", []):
            if isinstance(check, dict):
                reason = (check.get("approved_relaxation") or "").strip()
                if reason and before.get(check.get("id")) != reason:
                    findings.append(f"check '{check.get('id')}': adds or changes an approved_relaxation (\"{reason[:80]}\"); "
                                    "an approval is a decision for you")
    return findings


def approvals_findings(current: Optional[str], proposed: str) -> List[str]:
    def entries(text: Optional[str]) -> Dict[str, str]:
        try:
            data = json.loads(text) if text is not None else {}
            return {f"{a.get('test')} [{a.get('kind')}]": str(a.get("reason", "")) for a in data.get("approvals", [])}
        except (ValueError, AttributeError, TypeError):
            return {}
    before, after = entries(current), entries(proposed)
    findings = [f"approves {key}: {reason[:80]}" for key, reason in after.items() if before.get(key) != reason]
    findings += [f"removes the approval for {key}" for key in before if key not in after]
    return findings or ["changes the approvals file"]


def test_file_findings(root: Path, rel: str, current: Optional[str], proposed: str) -> List[str]:
    if current is None:
        return []
    tr = _tr()
    try:
        old_scopes = tr.extract(rel, current)
        new_scopes = tr.extract(rel, proposed)
    except SyntaxError:
        return []                                            # an unparseable step is not a weakening; the ratchet sees the end state
    try:
        approvals = tr.load_approvals(root / APPROVALS)
    except tr.UsageError:
        approvals = []
    findings = []
    for item in tr.compare_scopes(old_scopes, new_scopes):
        accepted = any(a["test"] == item["test"] and a["kind"] in (item["kind"], "any") for a in approvals)
        if not accepted:
            where = item["test"].split("::", 1)[1] if "::" in item["test"] else item["test"]
            findings.append(f"{where}: {item['kind']} - {item['detail']}")
    return findings


def file_reason(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    tool, tool_input = payload.get("tool_name"), payload.get("tool_input")
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get("file_path"), str):
        return None
    cwd = Path(payload.get("cwd") or os.getcwd())
    path = Path(tool_input["file_path"])
    path = (path if path.is_absolute() else cwd / path).resolve()
    root = hc.project_root(path)
    if not hc.opted_in(root):
        return None
    root = root.resolve()
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return None
    current = _read(path)
    findings: List[str] = []
    label = ""
    if rel == VERIFICATION_DIR or rel.startswith(VERIFICATION_DIR + "/"):
        findings, label = ["the evidence log and its helpers are written by the verification tools; a hand edit is not evidence"], "evidence"
    else:
        proposed = apply_edit(tool, tool_input, current)
        if proposed is None:
            return None
        if proposed == current:
            return None
        if rel == APPROVALS:
            findings, label = approvals_findings(current, proposed), "approvals file"
        elif rel == MANIFEST:
            findings, label = manifest_findings(current, proposed), "reference manifest"
        elif rel in golden_files(root):
            findings, label = ["this is a golden reference file: changing it is how a failing comparison is made to pass"], "golden file"
        elif _tr().is_test_file(rel, []):
            findings, label = test_file_findings(root, rel, current, proposed), "test file"
    if not findings:
        return None
    return {"decision": "ask",
            "reason": f"[scienceStack] This edit to {rel} ({label}) would weaken what verifies the code:\n"
                      f"{hc.shorten(findings)}\nApprove only if you decided this yourself. test_ratchet.py and CI check the "
                      f"final state, and an accepted exception belongs in {APPROVALS} with a reason."}


CD_TARGET = re.compile(r"""\bcd\s+(?:"([^"]+)"|'([^']+)'|([^\s;&|)]+))""")
ABSOLUTE_PATH = re.compile(r"""(?<![\w./~-])(~?/[^\s;&|)<>"']+)""")
MAX_CANDIDATES = 8


def opted_in_roots(command: str, cwd: Path) -> List[Path]:
    """The opted-in projects a shell command can touch: the session's directory, any `cd` target, and the project of every
    absolute (or ~) path it names. The shell does not necessarily start in the project."""
    bases = [cwd]
    for match in CD_TARGET.finditer(command):
        target = Path(os.path.expanduser(next(g for g in match.groups() if g)))
        bases.append(target if target.is_absolute() else cwd / target)
    for match in ABSOLUTE_PATH.finditer(command):
        bases.append(Path(os.path.expanduser(match.group(1))).parent)
    roots: List[Path] = []
    for base in bases[:MAX_CANDIDATES]:
        root = hc.project_root(base)
        if hc.opted_in(root) and root.resolve() not in roots:
            roots.append(root.resolve())
    return roots


def bash_reason(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return None
    roots = opted_in_roots(command, Path(payload.get("cwd") or os.getcwd()))
    if not roots:
        return None
    hits = [label for label, pattern in SHELL_WRITES if pattern.search(command)]
    names = [name for root in roots for name in golden_files(root)]
    if not hits and names:
        golden = "|".join(re.escape(n) for n in names)
        for label, pattern in SHELL_WRITES:
            swapped = re.compile(pattern.pattern.replace(_P, "(?:" + golden + ")"))
            if swapped.search(command):
                hits.append(label + " a golden file")
    if not hits:
        return None
    return {"decision": "ask",
            "reason": "[scienceStack] This shell command appears to modify a protected test, reference or evidence file "
                      f"({', '.join(sorted(set(hits)))}). An edit made through the shell cannot be checked for weakening, "
                      "unlike Edit/Write. Approve only if you meant it; test_ratchet.py and CI check the final state."}


UNATTENDED_MODES = {"auto", "bypassPermissions"}


def decide(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """In default mode a finding is an "ask" for the person. In auto and bypassPermissions modes Claude Code answers an
    "ask" itself (seen live), so it would gate nothing: there the finding is a "deny", and the person acts. A missing or
    unknown permission_mode keeps "ask"."""
    result = _decide(payload)
    if result and result["decision"] == "ask" and payload.get("permission_mode") in UNATTENDED_MODES:
        return {"decision": "deny",
                "reason": result["reason"] + "\n\nBlocked rather than asked because this session runs in "
                          f"{payload['permission_mode']} mode, where nobody is asked. To go ahead: make the change yourself, "
                          f"record an accepted exception with a reason in {APPROVALS}, or have the person set "
                          "SCIENCESTACK_HOOKS=off for Claude Code."}
    return result


def _decide(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    if hc.hooks_disabled():
        return None
    tool = payload.get("tool_name")
    if tool in ("Write", "Edit", "MultiEdit"):
        return file_reason(payload)
    if tool == "Bash":
        return bash_reason(payload)
    return None


def main() -> int:
    return hc.run_pre_tool_hook(decide, "test guard")


if __name__ == "__main__":
    sys.exit(main())
