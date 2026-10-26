#!/usr/bin/env python3
r"""
reference_manifest.py - the committed list of reference checks a project must pass (pure functions, no I/O).

reference-checks.json:

    {"schema": "reference-checks/1",
     "checks": [
       {"id": "kepler-solver", "rationale": "why this benchmark and this tolerance",
        "benchmark": "kepler", "solver": "src/kepler.py:solve", "tol": 1e-12},
       {"id": "heat-golden", "rationale": "...", "compare": {"ref": "tests/golden/heat.txt",
        "test": "build/heat.out", "rtol": 1e-9, "atol": 1e-12}}
     ]}

Rules enforced here:
  * every check has an id and a rationale of at least 10 characters (the tolerance is a recorded, justified choice);
  * exactly one of "benchmark" / "compare"; unknown keys are errors; solver and file paths are repo-relative with
    no "..", no absolute path and no "~", so a clean CI checkout resolves them the same way;
  * a benchmark without a default tolerance must state "tol"; every tolerance must be one the reference can resolve.

The ratchet compares the manifest with the one on a baseline git ref (for example origin/main):
  * a check that is gone, a tolerance that is larger, or a check that now compares against something else is a
    violation unless the check carries a non-empty "approved_relaxation" saying why (it is printed loudly and is
    visible in the diff);
  * a check that is gone is a violation unless it is listed with --allow-removed.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from verification_evidence import looser
import reference_build as rb

SCHEMA = "reference-checks/1"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,59}$")
TOP_KEYS = {"schema", "checks", "description"}
COMMON_KEYS = {"id", "rationale", "approved_relaxation"}
BENCHMARK_KEYS = COMMON_KEYS | {"benchmark", "solver", "tol", "points", "timeout_s", "repeat", "repeat_tol", "order", "steps",
                                "levels"}
CONVERGENCE_KEYS = ("order", "steps", "levels")
COMPARE_KEYS = COMMON_KEYS | {"compare"}
COMPARE_INNER = {"ref", "test", "rtol", "atol", "ref_from", "test_from"}


def _bad_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return True
    parts = value.split("/")
    return value.startswith(("/", "~")) or "\\" in value or ".." in parts or "" in parts


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def validate(manifest: Any, benchmarks: Dict[str, Any],
             resolve_tolerance: Callable[[Any, Optional[float]], Tuple[float, Optional[bool]]]) -> List[str]:
    """Every problem found, as readable strings (empty list = valid). `benchmarks` maps name -> Benchmark."""
    errors: List[str] = []
    if not isinstance(manifest, dict):
        return ["the manifest must be a JSON object"]
    for key in sorted(set(manifest) - TOP_KEYS):
        errors.append(f"unknown top-level key {key!r}")
    if manifest.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}")
    checks = manifest.get("checks")
    if not isinstance(checks, list) or not checks:
        return errors + ["checks must be a non-empty list"]
    seen = set()
    for index, check in enumerate(checks):
        where = f"checks[{index}]"
        if not isinstance(check, dict):
            errors.append(f"{where} must be an object")
            continue
        cid = check.get("id")
        if not isinstance(cid, str) or not ID_RE.match(cid):
            errors.append(f"{where}: id must match {ID_RE.pattern}")
        elif cid in seen:
            errors.append(f"{where}: duplicate id {cid!r}")
        else:
            seen.add(cid)
            where = f"check {cid!r}"
        rationale = check.get("rationale")
        if not isinstance(rationale, str) or len(rationale.strip()) < 10:
            errors.append(f"{where}: rationale (at least 10 characters) is required: why this benchmark, why this tolerance")
        approved = check.get("approved_relaxation")
        if approved is not None and (not isinstance(approved, str) or not approved.strip()):
            errors.append(f"{where}: approved_relaxation must be a non-empty string when present")
        if ("benchmark" in check) == ("compare" in check):
            errors.append(f"{where}: give exactly one of 'benchmark' or 'compare'")
            continue
        if "benchmark" in check:
            for key in sorted(set(check) - BENCHMARK_KEYS):
                errors.append(f"{where}: unknown key {key!r}")
            name = check["benchmark"]
            bench = benchmarks.get(name)
            if bench is None:
                errors.append(f"{where}: unknown benchmark {name!r} (known: {', '.join(sorted(benchmarks))})")
                continue
            target = check.get("solver")
            path, sep, func = (target or "").rpartition(":") if isinstance(target, str) else ("", "", "")
            if not sep or not func.isidentifier() or _bad_path(path):
                errors.append(f"{where}: solver must be 'relative/path.py:function' (no '..', no absolute path)")
            tol = check.get("tol")
            if tol is not None and not _positive(tol):
                errors.append(f"{where}: tol must be a positive finite number")
            else:
                try:
                    resolve_tolerance(bench, None if tol is None else float(tol))
                except Exception as exc:                      # UsageError from the checker: missing or unresolvable
                    errors.append(f"{where}: {exc}")
            if "points" in check and (name != "sod" or not isinstance(check["points"], int) or check["points"] < 3):
                errors.append(f"{where}: points applies to 'sod' only and must be an integer >= 3")
            timeout = check.get("timeout_s")
            convergent = getattr(bench, "kind", "single") == "convergence"
            if convergent:
                order = check.get("order")
                if isinstance(order, bool) or not isinstance(order, (int, float)) or not math.isfinite(order) or not 0 < order <= 12:
                    errors.append(f"{where}: order is required for a convergence benchmark: a number in (0, 12]")
                steps = check.get("steps", 16)
                if isinstance(steps, bool) or not isinstance(steps, int) or steps < 2:
                    errors.append(f"{where}: steps must be an integer >= 2")
                levels = check.get("levels", 5)
                if isinstance(levels, bool) or not isinstance(levels, int) or not 3 <= levels <= 8:
                    errors.append(f"{where}: levels must be an integer between 3 and 8")
            else:
                for key in CONVERGENCE_KEYS:
                    if key in check:
                        errors.append(f"{where}: {key} applies to the convergence benchmarks only")
            repeat = check.get("repeat")
            if "repeat" in check and (isinstance(repeat, bool) or not isinstance(repeat, int) or not 1 <= repeat <= 10):
                errors.append(f"{where}: repeat must be an integer between 1 and 10")
            repeat_tol = check.get("repeat_tol")
            if "repeat_tol" in check and (isinstance(repeat_tol, bool) or not isinstance(repeat_tol, (int, float))
                                          or not math.isfinite(repeat_tol) or repeat_tol < 0):
                errors.append(f"{where}: repeat_tol must be a finite number >= 0")
            elif "repeat_tol" in check and check.get("repeat", 1) == 1:
                errors.append(f"{where}: repeat_tol has no effect without repeat >= 2")
            if "timeout_s" in check and (isinstance(timeout, bool) or not isinstance(timeout, int) or not 0 <= timeout <= 3600):
                errors.append(f"{where}: timeout_s must be an integer between 0 and 3600")
        else:
            for key in sorted(set(check) - COMPARE_KEYS):
                errors.append(f"{where}: unknown key {key!r}")
            inner = check["compare"]
            if not isinstance(inner, dict):
                errors.append(f"{where}: compare must be an object with ref, test, rtol, atol")
                continue
            for key in sorted(set(inner) - COMPARE_INNER):
                errors.append(f"{where}: unknown compare key {key!r}")
            for key in ("ref", "test"):
                if key == "test" and "test_from" in inner:
                    continue
                if _bad_path(inner.get(key)):
                    errors.append(f"{where}: compare.{key} must be a repo-relative path (no '..', no absolute path)")
            if "test_from" in inner and "test" in inner:
                errors.append(f"{where}: give compare.test or compare.test_from, not both (the output is produced, not committed)")
            if "ref_from" in inner:
                errors += rb.validate_side(inner["ref_from"], f"{where}: compare.ref_from", reference=True)
            if "test_from" in inner:
                errors += rb.validate_side(inner["test_from"], f"{where}: compare.test_from", reference=False)
            rtol, atol = inner.get("rtol"), inner.get("atol")
            numbers = [v for v in (rtol, atol) if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if len(numbers) != 2 or not all(math.isfinite(v) and v >= 0 for v in numbers) or not any(v > 0 for v in numbers):
                errors.append(f"{where}: compare.rtol and compare.atol are both required, non-negative, not both zero")
    return errors


def effective_tolerance(check: Dict[str, Any], benchmarks: Dict[str, Any]) -> Dict[str, float]:
    """The tolerance a check really uses: its own number, or the benchmark's default."""
    if "compare" in check:
        inner = check["compare"]
        effective = {"rtol": float(inner["rtol"]), "atol": float(inner["atol"]),
                     # a reference that is rebuilt is a stronger check than one that is trusted: dropping it is a loosening
                     "ref_from_min": 1.0 if "ref_from" in inner else 0.0}
        if "ref_from" in inner:
            effective["reproduce_rtol"] = float(inner["ref_from"].get("reproduce_rtol", 0.0))
            effective["reproduce_atol"] = float(inner["ref_from"].get("reproduce_atol", 0.0))
        return effective
    tol = check.get("tol")
    if tol is None:
        tol = benchmarks[check["benchmark"]].default_tol
    # repeat_min / repeat_tol always count, so dropping a determinism requirement is a loosening like any other. With a
    # single call nothing is compared, which is the loosest possible repeat_tol: infinity.
    repeat = int(check.get("repeat", 1))
    effective = {"tol": float(tol), "repeat_min": float(repeat),
                 "repeat_tol": math.inf if repeat == 1 else float(check.get("repeat_tol", 0.0))}
    if getattr(benchmarks[check["benchmark"]], "kind", "single") == "convergence":
        # The requirement is a minimum observed order; the margin is already inside it, so it is not compared on its own
        # (order 5 with margin 0.5 requires 4.5, which is stricter than order 4 with margin 0.25 requiring 3.75).
        # Keys ending in _min are minimums: lower is looser.
        effective.pop("tol")
        effective["order_min"] = float(check["order"]) - float(tol)
        effective["levels_min"] = float(check.get("levels", 5))
    return effective


def _identity(check: Dict[str, Any]) -> Tuple[str, str, str]:
    """What a check compares against: the benchmark name, or the golden file and the recipe that rebuilds it."""
    if "compare" in check:
        recipe = check["compare"].get("ref_from")
        return "compare", str(check["compare"].get("ref")), json.dumps(recipe, sort_keys=True) if recipe is not None else ""
    return "benchmark", str(check.get("benchmark")), ""


def ratchet(current: Dict[str, Any], baseline: Optional[Dict[str, Any]], benchmarks: Dict[str, Any],
            allow_removed: Sequence[str] = ()) -> Dict[str, Any]:
    """Compare the manifest with the baseline's. `violations` empty means nothing was weakened without approval."""
    result: Dict[str, Any] = {"violations": [], "approved": [], "added": [], "removed_allowed": []}
    if baseline is None:
        return result
    now = {c["id"]: c for c in current.get("checks", []) if isinstance(c, dict) and "id" in c}
    before = {c["id"]: c for c in baseline.get("checks", []) if isinstance(c, dict) and "id" in c}
    result["added"] = sorted(set(now) - set(before))
    for cid in sorted(before):
        if cid not in now:
            if cid in allow_removed:
                result["removed_allowed"].append(cid)
            else:
                result["violations"].append({"id": cid, "problem": "check removed", "detail": "use --allow-removed to delete it on purpose"})
            continue
        new, old = now[cid], before[cid]
        problems: List[str] = []
        if _identity(new)[:2] != _identity(old)[:2]:
            problems.append(f"now compares against {_identity(new)[1]!r} ({_identity(new)[0]}), was {_identity(old)[1]!r}")
        elif _identity(old)[2] and _identity(new)[2] != _identity(old)[2]:
            # a recipe that existed was changed or removed; adding one where there was none is a tightening
            problems.append("the reference is built differently (ref_from: steps, output, pinned sources or inputs changed)")
        try:
            tol_new, tol_old = effective_tolerance(new, benchmarks), effective_tolerance(old, benchmarks)
        except (KeyError, TypeError, ValueError):
            tol_new, tol_old = {}, {}
        for key in tol_new:
            if key in tol_old and looser(key, tol_new[key], tol_old[key]):
                problems.append(f"{key} loosened from {tol_old[key]:g} to {tol_new[key]:g}")
        if not problems:
            continue
        reason = (new.get("approved_relaxation") or "").strip()
        entry = {"id": cid, "problem": "; ".join(problems)}
        if reason:
            result["approved"].append(dict(entry, approved_relaxation=reason))
        else:
            result["violations"].append(dict(entry, detail="add an approved_relaxation with the reason, or revert"))
    return result
