#!/usr/bin/env python3
r"""
run_tests.py - run the project's tests and record what actually happened, bound to the exact files that were tested.

    run_tests.py unittest [--start-dir tests] [--pattern 'test*.py'] [--top-level-dir DIR]
    run_tests.py pytest [-- PYTEST ARGS ...]
    run_tests.py command -- CMD ARGS ...          (any runner; only its exit status is known)
    run_tests.py fresh                            (did the tests pass on exactly the current files?)

The counts come from the test framework itself (unittest's result object, pytest's JUnit XML), not from reading its
console output. A run passes only if the runner exits 0, nothing failed or errored, and at least one test actually ran:
"no tests collected" and "everything skipped" are failures, because nothing was tested.

Every run is appended to the evidence log (./.verification/log.jsonl, see verification_evidence.py) and bound to a
SHA-256 of the whole git work tree, taken BEFORE the tests run. `fresh` (or `verification_evidence.py fresh --subject .
--kind tests`) exits 0 only if the latest test run passed and no tracked or untracked-not-ignored file has changed since.
Caches (__pycache__, .pytest_cache, *.pyc, ...) are not part of the hash, and the run itself starts with an empty
bytecode cache so a stale .pyc can never run old code for a file the evidence says was tested.

Exit status: 0 passed; 1 failed (a failure, an error, nothing ran, timeout); 2 not run (bad arguments, not a git
repository, runner missing, evidence could not be recorded for a pass).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verification_evidence as ve  # noqa: E402

TOOL = "run_tests"
PLUGIN_NAME = "sciencestack"

# Runs in the project's interpreter; writes the counts as JSON. Import errors appear as errors (unittest._FailedTest).
UNITTEST_DRIVER = r"""
import json, sys, unittest
out, start, pattern, top = sys.argv[1], sys.argv[2], sys.argv[3], (sys.argv[4] or None)
suite = unittest.TestLoader().discover(start, pattern=pattern, top_level_dir=top)
result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
ids = lambda pairs: [test.id() for test, _ in pairs][:20]
json.dump({"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
           "skipped": len(result.skipped), "expected_failures": len(result.expectedFailures),
           "unexpected_successes": len(result.unexpectedSuccesses),
           "failed_ids": ids(result.failures) + ids(result.errors)}, open(out, "w"))
"""


class UsageError(Exception):
    """Nothing was run (exit status 2)."""


def run_process(cmd: List[str], cwd: Path, timeout_s: int) -> Dict[str, Any]:
    """Run in its own process group; on timeout kill the whole group.

    The child gets an EMPTY bytecode cache (PYTHONPYCACHEPREFIX): Python validates a cached .pyc by the source file's
    modification time (to the second) and size, so a test file edited within the same second to a same-sized variant
    would otherwise run its OLD code while the evidence says it was the NEW file that passed."""
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="run_tests_pyc_") as pycache:
        env = dict(os.environ, PYTHONPYCACHEPREFIX=pycache)
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        return _run_group(cmd, cwd, timeout_s, env, started)


def _run_group(cmd: List[str], cwd: Path, timeout_s: int, env: Dict[str, str], started: float) -> Dict[str, Any]:
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, start_new_session=True)
    except FileNotFoundError:
        raise UsageError(f"runner not found: {cmd[0]}")
    try:
        code = proc.wait(timeout=timeout_s if timeout_s > 0 else None)
        timed_out = False
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        code, timed_out = None, True
    return {"exit_code": code, "timed_out": timed_out, "seconds": round(time.monotonic() - started, 3)}


def junit_counts(path: Path) -> Dict[str, Any]:
    """Totals from pytest's JUnit XML (one <testsuite>, or several under <testsuites>)."""
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for key in total:
            total[key] += int(suite.get(key, 0) or 0)
    failed = []
    for case in root.iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            failed.append(f"{case.get('classname', '')}::{case.get('name', '')}")
    total["failed_ids"] = failed[:20]
    return total


def verdict(run: Dict[str, Any], counts: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """passed + the reason when it did not."""
    if run["timed_out"]:
        return {"passed": False, "reason": "timed out"}
    if counts is None:
        return {"passed": run["exit_code"] == 0, "reason": None if run["exit_code"] == 0 else f"exit code {run['exit_code']}",
                "counts_unavailable": True}
    executed = counts["tests"] - counts.get("skipped", 0)
    if counts["failures"] or counts["errors"] or counts.get("unexpected_successes"):
        return {"passed": False, "reason": f"{counts['failures']} failed, {counts['errors']} errors"
                + (f", {counts['unexpected_successes']} unexpected successes" if counts.get("unexpected_successes") else "")}
    if counts["tests"] == 0:
        return {"passed": False, "reason": "no tests ran"}
    if executed <= 0:
        return {"passed": False, "reason": "every test was skipped: nothing was tested"}
    if run["exit_code"] != 0:
        return {"passed": False, "reason": f"runner exited {run['exit_code']} although no test failed"}
    return {"passed": True, "reason": None}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="runner")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--cwd", default=".", help="project directory (default: current)")
    common.add_argument("--python", default=sys.executable, help="interpreter for unittest/pytest (default: this one)")
    common.add_argument("--timeout-s", type=int, default=3600, help="whole run (default 3600; 0 = no limit)")
    common.add_argument("--name", help="name of this suite in the evidence log (default: the runner)")
    common.add_argument("--json", help="write the result as JSON")
    ve.add_cli_options(common)
    unit = sub.add_parser("unittest", parents=[common], help="unittest discovery")
    unit.add_argument("--start-dir", default="tests")
    unit.add_argument("--pattern", default="test*.py")
    unit.add_argument("--top-level-dir", default="")
    py = sub.add_parser("pytest", parents=[common], help="pytest (extra arguments after --)")
    py.add_argument("rest", nargs=argparse.REMAINDER)
    cmd = sub.add_parser("command", parents=[common], help="any command after --; only its exit status is known")
    cmd.add_argument("rest", nargs=argparse.REMAINDER)
    fr = sub.add_parser("fresh", help="exit 0 only if the latest test run passed on exactly the current files")
    fr.add_argument("--cwd", default=".")
    fr.add_argument("--evidence-dir")
    fr.add_argument("--name")
    return parser


def strip_dashes(rest: Sequence[str]) -> List[str]:
    return list(rest[1:]) if rest[:1] == ["--"] else list(rest)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.runner is None:
            parser.print_help(sys.stderr)
            raise UsageError("choose unittest, pytest, command or fresh")
        cwd = Path(args.cwd).resolve()
        if not cwd.is_dir():
            raise UsageError(f"--cwd {cwd} is not a directory")
        if args.runner == "fresh":
            os.chdir(cwd)
            return ve.evidence_command("fresh", args.evidence_dir, subject_path=".", name=args.name, kind="tests")
        if args.timeout_s < 0:
            raise UsageError("--timeout-s must be >= 0")
        os.chdir(cwd)                                  # the evidence log and the tree hash are relative to the project
        try:
            tree_before = ve.worktree_digest(cwd)
        except ve.EvidenceError as exc:
            raise UsageError(str(exc))

        with tempfile.TemporaryDirectory() as tmp:
            counts: Optional[Dict[str, Any]] = None
            if args.runner == "unittest":
                out = Path(tmp) / "counts.json"
                cmd = [args.python, "-c", UNITTEST_DRIVER, str(out), args.start_dir, args.pattern, args.top_level_dir]
                run = run_process(cmd, cwd, args.timeout_s)
                counts = json.loads(out.read_text()) if out.exists() else None
                if counts is None and not run["timed_out"]:
                    counts = {"tests": 0, "failures": 0, "errors": 1, "skipped": 0,
                              "failed_ids": ["the unittest driver did not report (crashed before the end)"]}
            elif args.runner == "pytest":
                xml = Path(tmp) / "junit.xml"
                cmd = [args.python, "-m", "pytest", f"--junitxml={xml}", "-p", "no:cacheprovider", *strip_dashes(args.rest)]
                run = run_process(cmd, cwd, args.timeout_s)
                if xml.exists():
                    counts = junit_counts(xml)
                elif not run["timed_out"]:
                    counts = {"tests": 0, "failures": 0, "errors": 1, "skipped": 0,
                              "failed_ids": [f"pytest wrote no report (exit code {run['exit_code']})"]}
            else:
                cmd = strip_dashes(args.rest)
                if not cmd:
                    raise UsageError("command needs the command to run after --")
                run = run_process(cmd, cwd, args.timeout_s)

        outcome = verdict(run, counts)
        tree_after = ve.worktree_digest(cwd)[1]
        name = args.name or args.runner
        shown = ([args.python, "unittest-discover", args.start_dir, args.pattern] if args.runner == "unittest" else cmd)
        detail = {"runner": args.runner, "command": shown,
                  "exit_code": run["exit_code"], "seconds": run["seconds"], "counts": counts,
                  "reason": outcome["reason"], "files_hashed": tree_before[2],
                  "tree_changed_during_run": tree_after != tree_before[1]}
        flags = []
        if outcome.get("counts_unavailable"):
            flags.append("counts_unavailable")
        if detail["tree_changed_during_run"]:
            flags.append("tree_changed_during_run")
        evidence = None
        if not args.no_evidence:
            evidence = record(args, name, outcome["passed"], detail, tree_before, flags)

        summary = {"passed": outcome["passed"], "reason": outcome["reason"], "counts": counts, "run": run,
                   "flags": flags, "evidence": evidence}
        report(summary, name)
        if args.json:
            Path(args.json).write_text(json.dumps(summary, indent=2))
        return ve.finish("run_tests", outcome["passed"], evidence)
    except UsageError as exc:
        print(f"run_tests: {exc} (nothing was recorded)", file=sys.stderr)
        return 2


def record(args, name: str, passed: bool, detail: Dict[str, Any], tree_before, flags: List[str]) -> Dict[str, Any]:
    """Append the run, bound to the work-tree digest taken BEFORE the run (what was actually tested)."""
    log = ve.log_path(args.evidence_dir)
    base = log.parent.parent
    root, digest, count = tree_before
    try:
        tree = {"path": os.path.relpath(root, base.resolve()), "sha256": digest, "role": "tree", "files": count}
        extras = [ve.subject(p, base, "extra") for p in (args.subject or [])]
        record_, _ = ve.record_run(log, tool=TOOL, plugin=PLUGIN_NAME, kind="tests", name=name, key=f"tests:{name}",
                                   passed=passed, tolerance={}, subjects=[tree, *extras], justification=args.justify,
                                   detail=detail, extra_flags=flags)
    except (ve.EvidenceError, OSError) as exc:
        return {"log": str(log), "error": f"{exc} (use --no-evidence to run without a log)"}
    return {"log": str(log), "flags": record_["flags"], "exit_status": record_["exit_status"], "withheld": False,
            "justification": record_["justification"]}


def report(summary: Dict[str, Any], name: str) -> None:
    counts = summary["counts"]
    lines = [f"run_tests [{name}]: {'PASSED' if summary['passed'] else 'FAILED'}"]
    if counts:
        lines.append(f"  ran {counts['tests']} tests: {counts['failures']} failed, {counts['errors']} errors, "
                     f"{counts.get('skipped', 0)} skipped")
        for test_id in counts.get("failed_ids", []):
            lines.append(f"    - {test_id}")
    else:
        lines.append("  counts unavailable (command runner): only the exit status is known")
    if summary["reason"]:
        lines.append(f"  reason: {summary['reason']}")
    if "tree_changed_during_run" in summary["flags"]:
        lines.append("  note: the tests changed files in the work tree; the evidence is bound to the files as they were before")
    evidence = summary["evidence"]
    if evidence and not evidence.get("error"):
        lines.append(f"  evidence: {evidence['log']} (bound to the work tree; check with `run_tests.py fresh`)")
    print("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
