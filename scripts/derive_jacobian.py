#!/usr/bin/env python3
r"""
Symbolic Jacobian and Hessian Matrix Synthesizer.

Differentiates non-linear vector equations analytically using SymPy to eliminate
human arithmetic errors and sign flips in Jacobian evaluations for implicit solvers.

Usage:
    python3 scripts/derive_jacobian.py --vars "y1,y2,y3" \
                                       --eqs "-0.04*y1 + 1e4*y2*y3, 0.04*y1 - 1e4*y2*y3 - 3e7*y2**2, 3e7*y2**2"
"""

import sys
import argparse
import sympy as sp


def derive_jacobian(vars_str: str, eqs_str: str):
    var_names = [v.strip() for v in vars_str.split(",") if v.strip()]
    symbols = [sp.Symbol(name, real=True) for name in var_names]
    local_env = {str(s): s for s in symbols}

    eq_strs = [e.strip() for e in eqs_str.split(",") if e.strip()]
    f_vec = [sp.sympify(e, locals=local_env) for e in eq_strs]

    print("=" * 70)
    print("Symbolic Jacobian Derivation:")
    print("=" * 70)
    print("State Variables:")
    for i, s in enumerate(symbols):
        print(f"  y[{i}] = {s}")

    print("\nNonlinear Vector Field f(y):")
    for i, eq in enumerate(f_vec):
        print(f"  f_{i+1} = {eq}  (LaTeX: ${sp.latex(eq)}$)")

    # Compute Jacobian Matrix J_ij = \partial f_i / \partial y_j
    J = sp.zeros(len(f_vec), len(symbols))
    for i in range(len(f_vec)):
        for j in range(len(symbols)):
            J[i, j] = sp.simplify(sp.diff(f_vec[i], symbols[j]))

    print("\nAnalytical Jacobian Matrix J = [df_i / dy_j]:")
    print(f"  LaTeX:\n\\begin{{bmatrix}}\n{sp.latex(J)}\n\\end{{bmatrix}}\n")

    print("SymPy Matrix Form:")
    sp.pprint(J)

    print("\n" + "=" * 70)
    print("Python / NumPy Implementation:")
    print("=" * 70)
    print("def compute_jacobian(y):")
    for i, name in enumerate(var_names):
        print(f"    {name} = y[{i}]")

    print("\n    # Evaluated entries:")
    for i in range(len(f_vec)):
        for j in range(len(symbols)):
            entry = J[i, j]
            py_code = sp.pycode(entry)
            print(f"    J_{i}_{j} = {py_code}")

    print("\n    return [")
    for i in range(len(f_vec)):
        row_str = ", ".join(f"J_{i}_{j}" for j in range(len(symbols)))
        print(f"        [{row_str}],")
    print("    ]")


def main():
    parser = argparse.ArgumentParser(description="scienceStack Symbolic Jacobian Synthesizer")
    parser.add_argument("--vars", required=True, help="Comma-separated state variable names, e.g. 'y1,y2,y3'")
    parser.add_argument("--eqs", required=True, help="Comma-separated equations, e.g. '-k1*y1 + k2*y2*y3, k1*y1 - ...'")

    args = parser.parse_args()
    derive_jacobian(args.vars, args.eqs)


if __name__ == "__main__":
    main()
