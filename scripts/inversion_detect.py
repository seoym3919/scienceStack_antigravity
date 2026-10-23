#!/usr/bin/env python3
r"""
inversion_detect.py - Import-aware detection of explicit matrix inversion in Python source.

Shared by the PreToolUse hook (hook_pre_tool_guard.py) and the AST auditor (audit_numerical_ast.py).
Also hosts the other two import-aware checks both use: truncated pi literals and mutable NumPy array
default arguments.

Resolves ``import numpy as np`` / ``import scipy.linalg as la`` / ``from numpy.linalg import inv`` so
that aliases are caught and unrelated functions that happen to be called ``inv`` are not.
"""

import ast
from typing import Dict, Optional

# Fully qualified callables that perform an explicit inversion.
FORBIDDEN_CALLS = frozenset({
    "numpy.linalg.inv",
    "scipy.linalg.inv",
    "scipy.sparse.linalg.inv",
    "jax.numpy.linalg.inv",
    "jax.scipy.linalg.inv",
    "cupy.linalg.inv",
    "torch.linalg.inv",
    "torch.inverse",
})


def import_aliases(tree: ast.AST) -> Dict[str, str]:
    """Map local names to fully qualified dotted names for every import in the tree."""
    aliases: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    aliases[a.asname] = a.name
                else:
                    top = a.name.split(".")[0]
                    aliases[top] = top
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for a in node.names:
                aliases[a.asname or a.name] = f"{node.module}.{a.name}"
    return aliases


def dotted(node: ast.AST) -> Optional[str]:
    """Return 'a.b.c' for an attribute chain / name, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def is_inversion_call(node: ast.AST, aliases: Dict[str, str]) -> bool:
    """True if `node` is a Call that explicitly inverts a matrix."""
    if not isinstance(node, ast.Call):
        return False
    chain = dotted(node.func)
    if not chain:
        return False
    head, _, rest = chain.partition(".")
    resolved = aliases.get(head, head) + ("." + rest if rest else "")
    if resolved in FORBIDDEN_CALLS:
        return True
    # Unresolved module alias (e.g. 'jnp' with no visible import) -- still catch '...linalg.inv'.
    return chain.endswith("linalg.inv")


# --- truncated pi ---------------------------------------------------------------------------
TRUNCATED_PI = (3.14159, 3.1416)


def is_truncated_pi(node: ast.AST) -> bool:
    """A float literal that is exactly 3.14159 or 3.1416 (truncated pi limits accuracy to ~1e-6)."""
    return (isinstance(node, ast.Constant) and isinstance(node.value, float)
            and node.value in TRUNCATED_PI)


# --- mutable NumPy array defaults -----------------------------------------------------------
_ARRAY_FACTORIES = {"zeros", "ones", "empty", "array", "full"}


def mutable_array_default(node: ast.AST, aliases: Dict[str, str]) -> Optional[ast.AST]:
    """First default argument of a function definition that is a NumPy array constructor call."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
    for d in defaults:
        if isinstance(d, ast.Call):
            chain = dotted(d.func)
            if not chain:
                continue
            head, _, rest = chain.partition(".")
            resolved = aliases.get(head, head) + ("." + rest if rest else "")
            mod, _, fn = resolved.rpartition(".")
            if fn in _ARRAY_FACTORIES and mod in ("numpy", "np"):
                return d
    return None
