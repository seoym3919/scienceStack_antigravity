#!/usr/bin/env python3
r"""
reference_build.py - produce a comparison's two sides by running programs, instead of trusting committed output files.

A manifest `compare` check may carry `ref_from` and/or `test_from`:

    "compare": {"ref": "golden/heat.out", "test": "build/heat_py.out", "rtol": 1e-12, "atol": 0,
      "ref_from": {"steps": [["gfortran", "-O0", "legacy/heat.f90", "-o", "{work}/heat"], ["{work}/heat", "inputs/heat.nml"]],
                   "output": "stdout",
                   "pinned": {"legacy/heat.f90": "<sha256>", "inputs/heat.nml": "<sha256>"},
                   "reproduce_rtol": 1e-12, "reproduce_atol": 0, "timeout_s": 300,
                   "record_versions": [["gfortran", "--version"]]},
      "test_from": {"steps": [["python3", "src/heat.py", "inputs/heat.nml"]], "output": "stdout",
                    "pinned": {"src/heat.py": "<sha256>", "inputs/heat.nml": "<sha256>"}}}

What running one side does:
  1. every pinned file must have exactly the pinned SHA-256 (repo-relative, inside the repository): the legacy sources and
     inputs the numbers come from are part of the check, so changing them is a visible, reviewed edit of the manifest;
  2. the steps run in order, each as an argument list (NEVER through a shell) in the repository directory, with a
     temporary work directory substituted for {work} and the repository directory for {repo}, LC_ALL=C, and a timeout;
  3. the numbers are read from the last step's stdout, or from a file written into {work}.
For `ref_from` the committed `ref` file must reproduce the rebuilt numbers within reproduce_rtol/reproduce_atol: they are
stated separately because compilers and flags do not agree bit for bit. The REBUILT reference is what is compared.

SECURITY: the steps are commands. Running a manifest runs them with the caller's privileges, exactly as running a build
script would. Run a manifest only from a source you trust; in CI do not run it on pull requests from untrusted forks.
Nothing here sandboxes the steps; the timeout only stops runaway ones.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SHA256 = re.compile(r"^[0-9a-f]{64}$")
SIDE_KEYS = {"steps", "output", "pinned", "timeout_s", "record_versions"}
REF_KEYS = SIDE_KEYS | {"reproduce_rtol", "reproduce_atol"}
PLACEHOLDER = re.compile(r"\{(\w+)\}")
ALLOWED_PLACEHOLDERS = {"work", "repo"}
OUTPUT_FILE = re.compile(r"^file:\{work\}/[A-Za-z0-9_.-]+$")
DEFAULT_TIMEOUT_S = 300


class BuildFailure(Exception):
    """The side could not be produced, or a pinned file does not match: a verification failure (exit status 1)."""


class BuildUnavailable(Exception):
    """A program could not be started: nothing was checked (exit status 2)."""


def sha256_file(path: Path) -> Optional[str]:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def _safe_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith(("/", "~")):
        return False
    parts = value.split("/")
    return ".." not in parts and "" not in parts


def validate_side(spec: Any, where: str, reference: bool) -> List[str]:
    """Every problem with one `ref_from` / `test_from` block (empty list = valid)."""
    if not isinstance(spec, dict):
        return [f"{where} must be an object"]
    errors: List[str] = []
    for key in sorted(set(spec) - (REF_KEYS if reference else SIDE_KEYS)):
        errors.append(f"{where}: unknown key {key!r}")
    steps = spec.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append(f"{where}: steps must be a non-empty list of argument lists")
    else:
        for index, step in enumerate(steps):
            if not isinstance(step, list) or not step or not all(isinstance(a, str) and a and "\0" not in a for a in step):
                errors.append(f"{where}: steps[{index}] must be a non-empty list of non-empty strings (an argument list, not a shell line)")
                continue
            for argument in step:
                for name in PLACEHOLDER.findall(argument):
                    if name not in ALLOWED_PLACEHOLDERS:
                        errors.append(f"{where}: steps[{index}] uses {{{name}}}; only {{work}} and {{repo}} exist")
    output = spec.get("output")
    if output != "stdout" and not (isinstance(output, str) and OUTPUT_FILE.match(output)):
        errors.append(f"{where}: output must be \"stdout\" or \"file:{{work}}/<name>\"")
    pinned = spec.get("pinned")
    if not isinstance(pinned, dict) or not pinned:
        errors.append(f"{where}: pinned is required: the SHA-256 of every source and input the numbers are produced from")
    else:
        for path, digest in pinned.items():
            if not _safe_relative(path):
                errors.append(f"{where}: pinned path {path!r} must be a plain repo-relative path")
            if not isinstance(digest, str) or not SHA256.match(digest):
                errors.append(f"{where}: pinned[{path!r}] must be a lowercase 64-digit SHA-256")
    if "timeout_s" in spec:
        timeout = spec["timeout_s"]
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3600:
            errors.append(f"{where}: timeout_s must be an integer between 1 and 3600")
    if "record_versions" in spec:
        versions = spec["record_versions"]
        if not isinstance(versions, list) or not all(isinstance(c, list) and c and all(isinstance(a, str) and a for a in c) for c in versions):
            errors.append(f"{where}: record_versions must be a list of argument lists")
    if reference:
        for key in ("reproduce_rtol", "reproduce_atol"):
            value = spec.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                errors.append(f"{where}: {key} is required: how closely the committed reference must reproduce (>= 0)")
    return errors


def check_pinned(spec: Dict[str, Any], repo: Path) -> List[str]:
    """Mismatches between the pinned hashes and the files in the repository (empty list = all match)."""
    problems = []
    root = repo.resolve()
    for rel, expected in sorted(spec["pinned"].items()):
        path = (repo / rel)
        try:
            inside = path.resolve().is_relative_to(root)
        except OSError:
            inside = False
        actual = sha256_file(path) if inside and path.is_file() and not path.is_symlink() else None
        if actual is None:
            problems.append(f"{rel}: pinned but missing (or not a regular file inside the repository)")
        elif actual != expected:
            problems.append(f"{rel}: sha256 is {actual[:12]}..., pinned {expected[:12]}...")
    return problems


def _substitute(argument: str, work: Path, repo: Path) -> str:
    return argument.replace("{work}", str(work)).replace("{repo}", str(repo))


def _run_step(step: Sequence[str], repo: Path, work: Path, timeout_s: int) -> subprocess.CompletedProcess:
    command = [_substitute(a, work, repo) for a in step]
    env = dict(os.environ, LC_ALL="C", PYTHONDONTWRITEBYTECODE="1")
    try:
        proc = subprocess.Popen(command, cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                start_new_session=True)
    except FileNotFoundError:
        raise BuildUnavailable(f"program not found: {command[0]} (is it installed?)")
    except PermissionError:
        raise BuildUnavailable(f"cannot execute: {command[0]}")
    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise BuildFailure(f"step timed out after {timeout_s} s: {' '.join(command)[:200]}")
    return subprocess.CompletedProcess(command, proc.returncode, out, err)


def first_line(command: Sequence[str], repo: Path) -> str:
    try:
        done = subprocess.run(list(command), cwd=repo, capture_output=True, text=True, timeout=30,
                              env=dict(os.environ, LC_ALL="C"))
    except (OSError, subprocess.SubprocessError):
        return f"{command[0]}: not available"
    text = (done.stdout or done.stderr).strip()
    return text.splitlines()[0][:200] if text else f"{command[0]}: no output"


def produce(spec: Dict[str, Any], repo: Path, load_values) -> Tuple[List[float], Dict[str, Any]]:
    """Run one side: check the pins, run the steps, read the numbers. `load_values(path)` parses a numbers file.

    Raises BuildFailure (pinned file mismatch, a step failed or timed out, no numbers) or BuildUnavailable (a program
    cannot be started)."""
    problems = check_pinned(spec, repo)
    if problems:
        raise BuildFailure("pinned files do not match the manifest (the sources or inputs changed; update the pins "
                           "deliberately): " + "; ".join(problems))
    timeout_s = spec.get("timeout_s", DEFAULT_TIMEOUT_S)
    info: Dict[str, Any] = {"steps": len(spec["steps"]), "pinned": dict(spec["pinned"])}
    if spec.get("record_versions"):
        info["versions"] = [first_line(command, repo) for command in spec["record_versions"]]
    with tempfile.TemporaryDirectory(prefix="refbuild_") as tmp:
        work = Path(tmp)
        last = None
        for index, step in enumerate(spec["steps"]):
            last = _run_step(step, repo, work, timeout_s)
            if last.returncode != 0:
                tail = (last.stderr or last.stdout).strip()[-300:]
                raise BuildFailure(f"step {index + 1} failed (exit {last.returncode}): {' '.join(last.args)[:200]}"
                                   + (f"\n{tail}" if tail else ""))
        if spec["output"] == "stdout":
            target = work / "stdout.txt"
            target.write_text(last.stdout)
        else:
            target = work / spec["output"].split("/", 1)[1]
            if not target.is_file():
                raise BuildFailure(f"the steps did not write {spec['output']}")
        try:
            values = load_values(str(target))
        except Exception as exc:                                    # an unparseable output is a failed side, not a crash
            raise BuildFailure(f"the output is not a list of numbers: {exc}")
    if not values:
        raise BuildFailure("the steps produced no numbers")
    info["values"] = len(values)
    return values, info


def reproduction(committed: Sequence[float], rebuilt: Sequence[float], rtol: float, atol: float) -> Dict[str, Any]:
    """Does the committed reference reproduce the rebuilt one? |committed - rebuilt| <= atol + rtol |rebuilt|."""
    if len(committed) != len(rebuilt):
        return {"reproduces": False, "reason": f"the committed reference has {len(committed)} values, the rebuilt one {len(rebuilt)}"}
    worst, worst_index = 0.0, 0
    for index, (c, r) in enumerate(zip(committed, rebuilt)):
        if not (math.isfinite(c) and math.isfinite(r)):
            return {"reproduces": False, "reason": f"value {index} is not finite"}
        allowed = atol + rtol * abs(r)
        excess = abs(c - r) / allowed if allowed > 0 else (0.0 if c == r else math.inf)
        if excess > worst:
            worst, worst_index = excess, index
    return {"reproduces": worst <= 1.0, "worst_error_over_allowed": worst, "worst_index": worst_index,
            "reason": None if worst <= 1.0 else f"value {worst_index} differs by {worst:.3g} times the allowed difference"}
