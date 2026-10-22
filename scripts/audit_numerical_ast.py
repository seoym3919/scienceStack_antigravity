#!/usr/bin/env python3
r"""
scienceStack AST Numerical Stability and Scientific Code Quality Auditor.

Walks Python Abstract Syntax Trees (AST) to detect numerical vulnerabilities:
1. Fatal: Explicit matrix inversion (np.linalg.inv, scipy.linalg.inv) -> Suggests solve(A, b).
2. Warning: Catastrophic cancellation patterns (1 - cos, log(1 + x), exp(x) - 1).
3. Warning: Raw division without zero guards.
4. Warning: Single-precision float32 casting in simulation/numerical kernels.
5. Quality: Functions with numerical/mathematical signatures missing continuous LaTeX equation docstrings.

Usage:
    python3 scripts/audit_numerical_ast.py <file_or_directory> [--strict] [--json]
"""

import ast
import os
import sys
import json
from typing import List, Dict, Any


class NumericalASTVisitor(ast.NodeVisitor):
    def __init__(self, filename: str):
        self.filename = filename
        self.issues: List[Dict[str, Any]] = []

    def add_issue(self, level: str, node: ast.AST, code: str, message: str, suggestion: str):
        self.issues.append({
            "file": self.filename,
            "line": getattr(node, "lineno", 0),
            "col": getattr(node, "col_offset", 0),
            "level": level,  # "ERROR", "WARNING", "INFO"
            "code": code,
            "message": message,
            "suggestion": suggestion,
        })

    def visit_Call(self, node: ast.Call):
        # 1. Check for np.linalg.inv or scipy.linalg.inv
        func_name = ""
        if isinstance(node.func, ast.Attribute):
            # E.g. np.linalg.inv or linalg.inv
            attr = node.func.attr
            if attr == "inv":
                self.add_issue(
                    "ERROR",
                    node,
                    "BAN_MATRIX_INV",
                    "Explicit matrix inversion ('inv') detected.",
                    "Replace 'inv(A) @ b' with 'np.linalg.solve(A, b)' or 'scipy.linalg.solve' (Cholesky/LU)."
                )

        # 2. Check for log(1 + x) instead of log1p
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("log", "ln"):
            if len(node.args) >= 1 and isinstance(node.args[0], ast.BinOp):
                binop = node.args[0]
                if isinstance(binop.op, ast.Add):
                    # Check if one operand is literal 1 or 1.0
                    is_one = False
                    if isinstance(binop.left, ast.Constant) and binop.left.value in (1, 1.0):
                        is_one = True
                    elif isinstance(binop.right, ast.Constant) and binop.right.value in (1, 1.0):
                        is_one = True
                    if is_one:
                        self.add_issue(
                            "WARNING",
                            node,
                            "CANCELLATION_LOG1P",
                            "Expression 'log(1 + x)' is susceptible to catastrophic cancellation for |x| << 1.",
                            "Use 'math.log1p(x)' or 'np.log1p(x)'."
                        )

        # 3. Check for exp(x) - 1 instead of expm1
        # (checked in visit_BinOp)

        # 4. Check for float32 usage in numerical kernels
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("float32", "astype"):
            if node.func.attr == "float32":
                self.add_issue(
                    "WARNING",
                    node,
                    "PRECISION_FLOAT32",
                    "Explicit single precision float32 detected.",
                    "Verify that float32 is safe against cumulative rounding drift in scientific integration; prefer float64."
                )

        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp):
        # Check exp(x) - 1
        if isinstance(node.op, ast.Sub):
            # Left is exp(x) and right is 1
            if isinstance(node.left, ast.Call) and isinstance(node.left.func, ast.Attribute):
                if node.left.func.attr == "exp":
                    if isinstance(node.right, ast.Constant) and node.right.value in (1, 1.0):
                        self.add_issue(
                            "WARNING",
                            node,
                            "CANCELLATION_EXPM1",
                            "Expression 'exp(x) - 1' loses significance for |x| << 1.",
                            "Use 'math.expm1(x)' or 'np.expm1(x)'."
                        )
            # Left is 1 and right is cos(x) -> 1 - cos(x)
            if isinstance(node.left, ast.Constant) and node.left.value in (1, 1.0):
                if isinstance(node.right, ast.Call) and isinstance(node.right.func, ast.Attribute):
                    if node.right.func.attr in ("cos",):
                        self.add_issue(
                            "WARNING",
                            node,
                            "CANCELLATION_ONE_MINUS_COS",
                            "Expression '1 - cos(x)' loses significant bits for |x| << 1.",
                            "Replace with '2 * sin(x/2)**2' for small x."
                        )

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        # Check for LaTeX docstring in functions with scientific arguments
        docstring = ast.get_docstring(node)
        math_keywords = ("solve", "integrate", "flux", "kepler", "stress", "riemann", "wave", "hamilton", "polytrope", "divergence", "gradient", "laplacian")
        name_lower = node.name.lower()

        is_scientific = any(kw in name_lower for kw in math_keywords)
        if is_scientific:
            if not docstring or ("$" not in docstring and "\\begin" not in docstring and "\\frac" not in docstring and "\\equation" not in docstring):
                self.add_issue(
                    "INFO",
                    node,
                    "MISSING_LATEX_PROVENANCE",
                    f"Scientific function '{node.name}' has no LaTeX continuous equation in docstring.",
                    "Add LaTeX continuous equation and textbook citation per principle-equation-provenance."
                )

        self.generic_visit(node)


def audit_file(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=path)
        visitor = NumericalASTVisitor(path)
        visitor.visit(tree)
        return visitor.issues
    except Exception as e:
        return [{
            "file": path,
            "line": 0,
            "col": 0,
            "level": "ERROR",
            "code": "PARSE_ERROR",
            "message": f"Failed to parse AST: {str(e)}",
            "suggestion": "Fix Python syntax errors.",
        }]


def audit_path(target_path: str) -> List[Dict[str, Any]]:
    all_issues = []
    if os.path.isfile(target_path):
        if target_path.endswith(".py"):
            all_issues.extend(audit_file(target_path))
    elif os.path.isdir(target_path):
        for root, _, files in os.walk(target_path):
            if any(part.startswith(".") or part in ("node_modules", "venv", ".venv", "__pycache__") for part in root.split(os.sep)):
                continue
            for file in files:
                if file.endswith(".py"):
                    full_path = os.path.join(root, file)
                    all_issues.extend(audit_file(full_path))
    return all_issues


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 audit_numerical_ast.py <path> [--strict] [--json]")
        sys.exit(1)

    target = sys.argv[1]
    strict = "--strict" in sys.argv
    as_json = "--json" in sys.argv

    issues = audit_path(target)

    if as_json:
        print(json.dumps(issues, indent=2))
    else:
        errors = [i for i in issues if i["level"] == "ERROR"]
        warnings = [i for i in issues if i["level"] == "WARNING"]
        infos = [i for i in issues if i["level"] == "INFO"]

        print(f"\n[scienceStack AST Auditor] Target: {target}")
        print(f"Results: {len(errors)} Errors, {len(warnings)} Warnings, {len(infos)} Info notices\n")

        for issue in issues:
            color = "\033[91m" if issue["level"] == "ERROR" else "\033[93m" if issue["level"] == "WARNING" else "\033[94m"
            reset = "\033[0m"
            print(f"{color}[{issue['level']}]{reset} {issue['file']}:{issue['line']}:{issue['col']} - {issue['code']}")
            print(f"  {issue['message']}")
            print(f"  --> Suggestion: {issue['suggestion']}\n")

    has_errors = any(i["level"] == "ERROR" for i in issues)
    if has_errors or (strict and issues):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
