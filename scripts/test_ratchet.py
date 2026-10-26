#!/usr/bin/env python3
r"""
test_ratchet.py - refuse changes that weaken the project's own tests, compared with a git baseline.

    test_ratchet.py --baseline-ref origin/main [--approvals test-ratchet-approvals.json] [--include GLOB ...] [--json F]

Both versions of every Python test file (test_*.py, *_test.py, conftest.py, or --include globs) are parsed with `ast`
and compared test by test. Nothing is executed and nothing is judged by wording. A change is a VIOLATION when it:

  loosened            raises a tolerance: rtol/atol/rel/abs/delta/nulp keywords or positional arguments of known
                      assertion helpers, the library default that applies when the argument is removed, fewer
                      places/decimal digits, a larger upper bound (assert err < 1e-9) or a smaller lower bound
                      (assert order > 1.9), or a tolerance-named constant (TOL = 1e-12) made larger;
  not_literal         replaces a numeric tolerance with something this script cannot evaluate (cannot be verified);
  site_removed        removes a tolerance check from a test that still exists (or changes its form);
  assertions_reduced  leaves a test with fewer assertions;
  removed             deletes a test (renames staged with `git mv` are followed);
  skip_added          adds skip / skipIf / skipUnless / xfail / expectedFailure, skipTest(), pytest.skip(),
                      importorskip() or a module-level pytestmark skip, or changes an existing skip condition;
  params_reduced      leaves a literal @pytest.mark.parametrize list with fewer cases;
  unparseable         leaves a test file that no longer parses.

New tests, tighter tolerances and more assertions are fine. A violation is accepted only when the approvals file lists
it with a reason, which is visible in the diff:

    {"schema": "test-ratchet-approvals/1", "approvals": [
       {"test": "tests/test_solver.py::TestHeat::test_decay", "kind": "loosened", "reason": "at least ten characters"}]}

"test" is a test id (path::Class::function or path::function), or path::<module> / path::Class for constants and
markers at that level; "kind" is one of the kinds above or "any".

Library defaults used when a tolerance argument is omitted (from each library's documentation):
  numpy.testing.assert_allclose rtol=1e-7 atol=0;  numpy.allclose / numpy.isclose rtol=1e-5 atol=1e-8;
  numpy.testing.assert_almost_equal decimal=7;  numpy.testing.assert_array_almost_equal decimal=6;
  numpy.testing.assert_array_almost_equal_nulp nulp=1;  numpy.testing.assert_array_max_ulp maxulp=1;
  math.isclose rel_tol=1e-9 abs_tol=0;  pytest.approx rel=1e-6 abs=1e-12;  unittest assertAlmostEqual places=7.
  torch.testing.assert_close has dtype-dependent defaults, so an omitted value is not compared.

Limits: only what is written in the test files is seen. A tolerance passed in from a helper in another module, a
helper that hides an assertion, or a test generated at run time are invisible; renames done without `git mv`/`git add`
look like a removed test plus a new one. Exit status: 0 no unapproved violation; 3 unapproved violations;
2 could not compare (not a git repository, bad ref, bad approvals file).
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verification_evidence as ve  # noqa: E402

APPROVALS_SCHEMA = "test-ratchet-approvals/1"
KINDS = ("loosened", "not_literal", "site_removed", "assertions_reduced", "removed", "skip_added", "params_reduced",
         "unparseable")
DEFAULT_PATTERNS = ("test_*.py", "*_test.py", "conftest.py")
SKIP_WORDS = ("skip", "xfail", "expectedfailure", "importorskip")
SKIP_CALLS = {"skipTest", "skip", "xfail", "importorskip"}
TOL_NAME = re.compile(r"(?i)(^|_)(tol|rtol|atol|eps|epsilon|thresh|threshold|tolerance|delta|precision|accuracy|"
                      r"max_?err|err_?max|bound|limit|places|decimal|digits|ulps?|nulp)($|_)")
INVERSE_NAME = re.compile(r"(?i)(places|decimal|digits)")

# callee tail -> {parameter: (positional index or None, default or None, "tol" | "inverse")}
SPECS: Dict[str, Dict[str, Tuple[Optional[int], Optional[float], str]]] = {
    "assert_allclose": {"rtol": (2, 1e-7, "tol"), "atol": (3, 0.0, "tol")},
    "allclose": {"rtol": (2, 1e-5, "tol"), "atol": (3, 1e-8, "tol")},
    "isclose": {"rtol": (2, 1e-5, "tol"), "atol": (3, 1e-8, "tol")},
    "assert_almost_equal": {"decimal": (2, 7, "inverse")},
    "assert_array_almost_equal": {"decimal": (2, 6, "inverse")},
    "assert_array_almost_equal_nulp": {"nulp": (2, 1, "tol")},
    "assert_array_max_ulp": {"maxulp": (2, 1, "tol")},
    "approx": {"rel": (1, 1e-6, "tol"), "abs": (2, 1e-12, "tol")},
    "assert_close": {"rtol": (None, None, "tol"), "atol": (None, None, "tol")},
}
MATH_ISCLOSE = {"rel_tol": (None, 1e-9, "tol"), "abs_tol": (None, 0.0, "tol")}
UPPER = {ast.Lt: "<", ast.LtE: "<="}
LOWER = {ast.Gt: ">", ast.GtE: ">="}
BOUND_CALLS = {"assertLess": "upper", "assertLessEqual": "upper", "assertGreater": "lower", "assertGreaterEqual": "lower"}


class UsageError(Exception):
    """Nothing could be compared (exit status 2)."""


# ----------------------------------------------------------------------------------------------------------------
# Evaluating tolerance expressions
# ----------------------------------------------------------------------------------------------------------------

def const_value(node: Optional[ast.AST], env: Dict[str, Optional[float]]) -> Optional[float]:
    """Numeric value of a literal expression (numbers, + - * / **, unary minus, known names), else None."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = const_value(node.operand, env)
        return None if value is None else (-value if isinstance(node.op, ast.USub) else value)
    if isinstance(node, ast.BinOp):
        left, right = const_value(node.left, env), const_value(node.right, env)
        if left is None or right is None:
            return None
        try:
            if isinstance(node.op, ast.Add):
                result = left + right
            elif isinstance(node.op, ast.Sub):
                result = left - right
            elif isinstance(node.op, ast.Mult):
                result = left * right
            elif isinstance(node.op, ast.Div):
                result = left / right
            elif isinstance(node.op, ast.Pow) and abs(right) <= 400:
                result = left ** right
            else:
                return None
        except (ArithmeticError, ValueError):
            return None
        return result if isinstance(result, float) and math.isfinite(result) else (float(result) if isinstance(result, int) else None)
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in ("self", "cls"):
        return env.get(node.attr)
    return None


def looseness(value: Optional[float], how: str) -> Optional[float]:
    """Map a tolerance-like value to a number that grows when the check gets looser."""
    if value is None:
        return None
    if how == "inverse":
        return 10.0 ** (-value)
    if how == "lower":
        return -value
    return value


def callee_tail(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def callee_base(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id
    return ""


def simple_assignments(body: Sequence[ast.stmt], env: Dict[str, Optional[float]]) -> Dict[str, Tuple[ast.AST, int]]:
    """NAME = expr statements directly in `body` (last one wins); `env` is updated with their numeric values."""
    found: Dict[str, Tuple[ast.AST, int]] = {}
    for stmt in body:
        targets: List[ast.expr] = []
        value = None
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets, value = [stmt.target], stmt.value
        for target in targets:
            if isinstance(target, ast.Name):
                found[target.id] = (value, stmt.lineno)
                env[target.id] = const_value(value, env)
    return found


# ----------------------------------------------------------------------------------------------------------------
# Extracting what a test file asserts
# ----------------------------------------------------------------------------------------------------------------

class Scope:
    """One test (or a module/class level holding constants and markers)."""

    def __init__(self, scope_id: str, is_test: bool):
        self.id = scope_id
        self.is_test = is_test
        self.sites: Dict[Tuple[str, int], Tuple[Optional[float], int]] = {}   # (label, occurrence) -> (looseness, line)
        self.assertions = 0
        self.markers: Dict[str, int] = {}                                     # marker text -> line
        self.params: Dict[str, Tuple[Optional[int], int]] = {}               # argnames -> (case count, line)
        self._counts: Dict[str, int] = {}

    def add_site(self, label: str, value: Optional[float], line: int) -> None:
        occurrence = self._counts.get(label, 0)
        self._counts[label] = occurrence + 1
        self.sites[(label, occurrence)] = (value, line)


def is_skip_text(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in SKIP_WORDS)


def collect_markers(decorators: Sequence[ast.expr], scope: Scope, env: Dict[str, Optional[float]]) -> None:
    for dec in decorators:
        text = ast.unparse(dec)
        if is_skip_text(text):
            scope.markers[text] = dec.lineno
        call = dec if isinstance(dec, ast.Call) else None
        if call is not None and callee_tail(call) == "parametrize" and len(call.args) >= 2:
            names = ast.unparse(call.args[0])
            cases = call.args[1]
            count = len(cases.elts) if isinstance(cases, (ast.List, ast.Tuple)) else None
            scope.params[names] = (count, dec.lineno)


def scan_body(nodes: Sequence[ast.AST], scope: Scope, env: Dict[str, Optional[float]]) -> None:
    """Tolerance sites, assertion count and skip calls inside a test body."""
    for root in nodes:
        for node in ast.walk(root):
            if isinstance(node, ast.Assert):
                scope.assertions += 1
                test = node.test
                if isinstance(test, ast.Compare):
                    compare_site(test, scope, env, "assert")
            elif isinstance(node, ast.Raise) and node.exc is not None and "SkipTest" in ast.unparse(node.exc):
                scope.markers["raise " + ast.unparse(node.exc)] = node.lineno
            elif isinstance(node, ast.Call):
                tail = callee_tail(node)
                if tail.lower().startswith("assert") or tail in ("raises", "warns", "deprecated_call"):
                    scope.assertions += 1
                if tail in SKIP_CALLS and callee_base(node) in ("self", "pytest", "unittest"):
                    scope.markers["call " + ast.unparse(node)] = node.lineno
                call_sites(node, tail, scope, env)


def compare_site(test: ast.Compare, scope: Scope, env: Dict[str, Optional[float]], label: str) -> None:
    if len(test.ops) != 1:
        return
    op = type(test.ops[0])
    left, right = test.left, test.comparators[0]
    lv, rv = const_value(left, env), const_value(right, env)
    # The bound is the side written as a literal (1e-9, 10 ** -6); failing that, the right-hand side if it evaluates.
    if const_value(right, {}) is not None:
        lv = None
    elif const_value(left, {}) is not None:
        rv = None
    elif rv is not None:
        lv = None
    if lv is None and rv is None:
        return
    if rv is not None:
        kind = "upper" if op in UPPER else "lower" if op in LOWER else None
        value, symbol = rv, (UPPER.get(op) or LOWER.get(op))
    else:
        kind = "lower" if op in UPPER else "upper" if op in LOWER else None    # 1e-9 > err  is an upper bound
        value, symbol = lv, (UPPER.get(op) or LOWER.get(op))
    if kind is None:
        return
    scope.add_site(f"{label} bound {kind}", looseness(value, "lower" if kind == "lower" else "tol"), test.lineno)


def call_sites(call: ast.Call, tail: str, scope: Scope, env: Dict[str, Optional[float]]) -> None:
    if tail == "assertTrue" and call.args and isinstance(call.args[0], ast.Compare):
        compare_site(call.args[0], scope, env, "assertTrue")
    if tail in BOUND_CALLS and len(call.args) >= 2:
        kind = BOUND_CALLS[tail]
        a, b = const_value(call.args[0], env), const_value(call.args[1], env)
        if b is not None:                                  # the second argument is the limit by convention
            value, direction = b, kind
        elif a is not None:                                # assertLess(1e-9, x): the limit is first, so it is a lower bound
            value, direction = a, "lower" if kind == "upper" else "upper"
        else:
            return
        scope.add_site(f"{tail} bound {direction}", looseness(value, "lower" if direction == "lower" else "tol"), call.lineno)
        return
    if tail == "assertAlmostEqual":
        keywords = {k.arg: k.value for k in call.keywords if k.arg}
        delta = keywords.get("delta") or (call.args[4] if len(call.args) > 4 else None)
        if delta is not None:
            scope.add_site("assertAlmostEqual delta", const_value(delta, env), call.lineno)
        else:
            places = keywords.get("places") or (call.args[2] if len(call.args) > 2 else None)
            value = 7.0 if places is None else const_value(places, env)
            scope.add_site("assertAlmostEqual places", looseness(value, "inverse"), call.lineno)
        return
    spec = MATH_ISCLOSE if (tail == "isclose" and (callee_base(call) == "math" or
                                                   any(k.arg in MATH_ISCLOSE for k in call.keywords))) else SPECS.get(tail)
    if spec is None:
        return
    keywords = {k.arg: k.value for k in call.keywords if k.arg}
    for param, (index, default, how) in spec.items():
        node = keywords.get(param)
        if node is None and index is not None and len(call.args) > index:
            node = call.args[index]
        if node is None:
            if default is None:
                continue                                   # dtype-dependent default: nothing to compare
            value: Optional[float] = float(default)
        else:
            value = const_value(node, env)
        scope.add_site(f"{tail} {param}", looseness(value, how), call.lineno)


def constant_sites(assignments: Dict[str, Tuple[ast.AST, int]], scope: Scope, env: Dict[str, Optional[float]]) -> None:
    for name, (value_node, line) in assignments.items():
        if TOL_NAME.search(name):
            how = "inverse" if INVERSE_NAME.search(name) else "tol"
            scope.add_site(f"constant {name}", looseness(const_value(value_node, env), how), line)


def extract(path: str, source: str) -> Dict[str, Scope]:
    """Every scope of one test file: path::<module>, path::Class, and each test."""
    tree = ast.parse(source, filename=path)
    scopes: Dict[str, Scope] = {}
    module_env: Dict[str, Optional[float]] = {}
    module = Scope(f"{path}::<module>", False)
    module_assign = simple_assignments(tree.body, module_env)
    constant_sites(module_assign, module, module_env)
    if "pytestmark" in module_assign:
        text = ast.unparse(module_assign["pytestmark"][0])
        if is_skip_text(text):
            module.markers["pytestmark = " + text] = module_assign["pytestmark"][1]
    scopes[module.id] = module

    def add_test(func: ast.AST, scope_id: str, env: Dict[str, Optional[float]]) -> None:
        scope = Scope(scope_id, True)
        local_env = dict(env)
        local_assign = simple_assignments(func.body, local_env)
        constant_sites(local_assign, scope, local_env)
        collect_markers(func.decorator_list, scope, local_env)
        scan_body(func.body, scope, local_env)
        scopes[scope_id] = scope

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            add_test(node, f"{path}::{node.name}", module_env)
        elif isinstance(node, ast.ClassDef):
            class_env = dict(module_env)
            class_scope = Scope(f"{path}::{node.name}", False)
            constant_sites(simple_assignments(node.body, class_env), class_scope, class_env)
            collect_markers(node.decorator_list, class_scope, class_env)
            scopes[class_scope.id] = class_scope
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test"):
                    add_test(item, f"{path}::{node.name}::{item.name}", class_env)
    return scopes


# ----------------------------------------------------------------------------------------------------------------
# Comparing two versions
# ----------------------------------------------------------------------------------------------------------------

def compare_scopes(old: Dict[str, Scope], new: Dict[str, Scope]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []

    def add(scope_id: str, kind: str, detail: str, line: Optional[int]) -> None:
        findings.append({"test": scope_id, "kind": kind, "detail": detail, "line": line})

    for scope_id, before in old.items():
        after = new.get(scope_id)
        if after is None:
            if before.is_test:
                add(scope_id, "removed", "test no longer exists", None)
            else:
                for (label, _), (value, line) in before.sites.items():
                    add(scope_id, "site_removed", f"{label} (was {value!r}) no longer defined", None)
            continue
        for key, (old_value, _) in before.sites.items():
            label = key[0]
            if key not in after.sites:
                add(scope_id, "site_removed", f"{label} #{key[1] + 1} is gone", None)
                continue
            new_value, line = after.sites[key]
            if old_value is not None and new_value is None:
                add(scope_id, "not_literal", f"{label}: no longer a value this script can evaluate", line)
            elif old_value is not None and new_value is not None and new_value > old_value:
                add(scope_id, "loosened", f"{label}: {describe(label, old_value)} -> {describe(label, new_value)}", line)
        if after.assertions < before.assertions:
            add(scope_id, "assertions_reduced", f"{before.assertions} -> {after.assertions} assertions", None)
        for marker, line in after.markers.items():
            if marker not in before.markers:
                add(scope_id, "skip_added", marker, line)
        for names, (old_count, _) in before.params.items():
            new_count, line = after.params.get(names, (None, None))
            if names not in after.params:
                add(scope_id, "params_reduced", f"parametrize({names}) removed", None)
            elif old_count is not None and new_count is None:
                add(scope_id, "not_literal", f"parametrize({names}) cases are no longer a literal list", line)
            elif old_count is not None and new_count is not None and new_count < old_count:
                add(scope_id, "params_reduced", f"parametrize({names}): {old_count} -> {new_count} cases", line)
    return findings


def describe(label: str, value: float) -> str:
    if label.endswith("places") or "decimal" in label or INVERSE_NAME.search(label.split()[-1] if label.split() else ""):
        return f"tolerance 10^{math.log10(value):.0f}" if value > 0 else repr(value)
    if " bound lower" in label:
        return f"lower bound {-value:g}"
    return f"{value:g}"


# ----------------------------------------------------------------------------------------------------------------
# Git
# ----------------------------------------------------------------------------------------------------------------

def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=120,
                          env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    if check and done.returncode != 0:
        raise UsageError(f"git {' '.join(args[:2])} failed: {done.stderr.decode(errors='replace').strip()}")
    return done


def is_test_file(path: str, includes: Sequence[str]) -> bool:
    if not path.endswith(".py"):
        return False
    if includes:
        return any(fnmatch.fnmatch(path, pattern) for pattern in includes)
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(name, pattern) for pattern in DEFAULT_PATTERNS)


def renames(root: Path, ref: str) -> Dict[str, str]:
    out = git(root, "diff", "--find-renames", "--name-status", "-z", ref, "--").stdout.decode(errors="surrogateescape")
    fields = out.split("\0")
    mapping, i = {}, 0
    while i < len(fields) and fields[i]:
        status = fields[i]
        if status.startswith(("R", "C")):
            mapping[fields[i + 1]] = fields[i + 2]
            i += 3
        else:
            i += 2
    return mapping


def load_approvals(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise UsageError(f"cannot read {path.name}: {exc}")
    problems = []
    if not isinstance(data, dict) or data.get("schema") != APPROVALS_SCHEMA or not isinstance(data.get("approvals"), list):
        raise UsageError(f"{path.name} must be {{\"schema\": \"{APPROVALS_SCHEMA}\", \"approvals\": [...]}}")
    for index, item in enumerate(data["approvals"]):
        if not isinstance(item, dict) or set(item) - {"test", "kind", "reason"}:
            problems.append(f"approvals[{index}]: only test, kind and reason are allowed")
            continue
        if not isinstance(item.get("test"), str) or "::" not in item["test"]:
            problems.append(f"approvals[{index}]: test must be an id such as path::function")
        if item.get("kind") not in (*KINDS, "any"):
            problems.append(f"approvals[{index}]: kind must be one of {', '.join(KINDS)} or any")
        if not isinstance(item.get("reason"), str) or len(item["reason"].strip()) < 10:
            problems.append(f"approvals[{index}]: reason (at least 10 characters) is required")
    if problems:
        raise UsageError("approvals file is invalid:\n  " + "\n  ".join(problems))
    return data["approvals"]


def ratchet(root: Path, ref: str, includes: Sequence[str], approvals: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    if git(root, "rev-parse", "--verify", f"{ref}^{{commit}}", check=False).returncode != 0:
        raise UsageError(f"--baseline-ref {ref!r} is not a commit in this repository")
    base_files = [p for p in git(root, "ls-tree", "-r", "-z", "--name-only", ref).stdout.decode(errors="surrogateescape").split("\0")
                  if p and is_test_file(p, includes)]
    current = [p for p in git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout
               .decode(errors="surrogateescape").split("\0") if p and is_test_file(p, includes) and (root / p).is_file()]
    moved = renames(root, ref)
    old_scopes: Dict[str, Scope] = {}
    new_scopes: Dict[str, Scope] = {}
    findings: List[Dict[str, Any]] = []
    for path in base_files:
        source = git(root, "show", f"{ref}:{path}").stdout.decode(errors="replace")
        try:
            scopes = extract(moved.get(path, path), source)        # ids use the current name of a renamed file
        except SyntaxError:
            continue                                               # nothing to protect in a file that did not parse
        old_scopes.update(scopes)
    for path in current:
        try:
            new_scopes.update(extract(path, (root / path).read_text(errors="replace")))
        except SyntaxError as exc:
            findings.append({"test": f"{path}::<module>", "kind": "unparseable", "detail": f"line {exc.lineno}: {exc.msg}",
                             "line": exc.lineno})
            unparsed = path
            for scope_id, scope in list(old_scopes.items()):        # do not also report its tests as removed
                if scope_id.startswith(unparsed + "::"):
                    del old_scopes[scope_id]
    findings += compare_scopes(old_scopes, new_scopes)
    for finding in findings:
        reason = next((a["reason"] for a in approvals if a["test"] == finding["test"]
                       and a["kind"] in (finding["kind"], "any")), None)
        finding["approved"] = reason
    added = sorted(s for s, scope in new_scopes.items() if scope.is_test and s not in old_scopes)
    return {"baseline": ref, "files_compared": len(set(base_files) | set(current)),
            "tests_before": sum(1 for s in old_scopes.values() if s.is_test),
            "tests_after": sum(1 for s in new_scopes.values() if s.is_test), "added_tests": added,
            "violations": [f for f in findings if not f["approved"]], "approved": [f for f in findings if f["approved"]]}


# ----------------------------------------------------------------------------------------------------------------
# Command line
# ----------------------------------------------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--baseline-ref", required=True, help="git ref to compare with, e.g. origin/main or HEAD")
    parser.add_argument("--cwd", default=".", help="directory inside the repository (default: current)")
    parser.add_argument("--approvals", help="approvals file (default: <repo>/test-ratchet-approvals.json)")
    parser.add_argument("--include", action="append", help="glob for test files, matched on the repo path (repeatable)")
    parser.add_argument("--json", help="write the result as JSON")
    ve.add_cli_options(parser)
    args = parser.parse_args(argv)
    try:
        start = Path(args.cwd).resolve()
        top = git(start, "rev-parse", "--show-toplevel", check=False)
        if top.returncode != 0:
            raise UsageError(f"{start} is not inside a git repository")
        root = Path(top.stdout.decode().strip())
        approvals = load_approvals(Path(args.approvals) if args.approvals else root / "test-ratchet-approvals.json")
        result = ratchet(root, args.baseline_ref, args.include or [], approvals)
    except UsageError as exc:
        print(f"test_ratchet: {exc} (nothing was compared)", file=sys.stderr)
        return 2

    os.chdir(root)
    passed = not result["violations"]
    evidence = ve.record_cli(args, tool="test_ratchet", plugin="sciencestack", kind="ratchet", name="test-ratchet",
                             key=f"ratchet:{args.baseline_ref}", passed=passed, tolerance={}, subject_paths=[],
                             detail={"baseline": args.baseline_ref, "violations": len(result["violations"]),
                                     "approved": len(result["approved"]), "tests_before": result["tests_before"],
                                     "tests_after": result["tests_after"]}, tree=True)
    result["evidence"] = evidence
    print(f"test_ratchet against {args.baseline_ref}: {result['tests_before']} tests before, {result['tests_after']} now, "
          f"{len(result['added_tests'])} added")
    for item in result["approved"]:
        print(f"APPROVED [{item['kind']}] {item['test']}: {item['detail']} -- {item['approved']}")
    for item in result["violations"]:
        where = f" (line {item['line']})" if item["line"] else ""
        print(f"VIOLATION [{item['kind']}] {item['test']}{where}: {item['detail']}", file=sys.stderr)
    print("no weakening found" if passed else f"{len(result['violations'])} unapproved weakening(s): "
          "fix them, or list each in test-ratchet-approvals.json with a reason")
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))
    status = ve.finish("test_ratchet", passed, evidence)
    return 3 if status == 1 else status


if __name__ == "__main__":
    sys.exit(main())
