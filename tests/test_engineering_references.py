"""Tests for the engineering benchmarks: poisson-2d, beam-timoshenko, linear-solve-hilbert, cavity-ghia and the Sod calibration.

Run (from the plugin root):  python3 -B -m unittest discover -s tests -v

The checker is never validated against itself. Reference values and how each is re-derived here:
- poisson-2d: -(u_xx + u_yy) of u = sin(pi x) sin(pi y), by sympy.
- beam-timoshenko: delta = P L^3 / (3 E I) + P L / (kappa G A) (Timoshenko 1921), by symbolic integration of the Timoshenko
  equations theta' = M(x) / (E I), w' = theta + V / (kappa G A), with M = P (L - x), V = P, clamped at x = 0.
- linear-solve-hilbert: kappa_inf(H_3) = 748 and kappa_inf(H_4) = 28375 are standard values; the integer inverse is multiplied
  by H_n in exact rational arithmetic and must give the identity.
- cavity-ghia: Table I of Ghia, Ghia & Shin (1982) from two copies (see engineering_references.py). Re = 100 is re-derived by a
  second-order stream-function solver (64 x 64, thus the bound). Measured here: rel. L1 3.8e-3 on 64 cells, 1.3e-2 on 32 cells,
  and 5.0e-2 for Re = 50 against the Re = 100 column. Re = 1000 is not re-derived: it would take minutes.
- Sod calibration: numbers printed by benchmarks/cfd/sod_calibration.py, a deterministic scheme, checked to 1e-3 absolute.
"""

import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import convergence as cv  # noqa: E402
import engineering_references as er  # noqa: E402
import reference_manifest as rm  # noqa: E402
import check_against_reference as car  # noqa: E402
import test_check_against_reference as base  # noqa: E402  (fixtures only)

try:
    import sympy
    HAVE_SYMPY = True
except ImportError:
    HAVE_SYMPY = False
try:
    import scipy.sparse as sparse
    import scipy.sparse.linalg as sparse_linalg
    HAVE_SCIPY = True
except ImportError:
    HAVE_SCIPY = False

POISSON = '''
import math
import numpy as np
DIAGONAL = 4.0
SIGN = 1.0
def solve(n):
    h = 1.0 / n
    m = n - 1
    A = np.zeros((m * m, m * m))
    b = np.zeros(m * m)
    for i in range(m):
        for j in range(m):
            k = i * m + j
            A[k, k] = DIAGONAL
            if i > 0: A[k, k - m] = -1.0
            if i < m - 1: A[k, k + m] = -1.0
            if j > 0: A[k, k - 1] = -1.0
            if j < m - 1: A[k, k + 1] = -1.0
            b[k] = SIGN * 2.0 * math.pi ** 2 * math.sin(math.pi * (i + 1) * h) * math.sin(math.pi * (j + 1) * h) * h * h
    u = np.zeros((n + 1, n + 1))
    u[1:-1, 1:-1] = np.linalg.solve(A, b).reshape(m, m)
    return u
'''

BEAM = '''
def solve(L, E, G, I, A, kappa, P):
    return P * L ** 3 / (3.0 * E * I) + P * L / (kappa * G * A)
'''
BEAM_NO_SHEAR = "def solve(L, E, G, I, A, kappa, P):\n    return P * L ** 3 / (3.0 * E * I)\n"
BEAM_UNIFORM_LOAD = "def solve(L, E, G, I, A, kappa, P):\n    return P * L ** 3 / (8.0 * E * I) + P * L / (kappa * G * A)\n"

SOLVE = "import numpy as np\ndef solve(A, b):\n    return np.linalg.solve(np.array(A), np.array(b))\n"
SOLVE_FLOAT32 = ("import numpy as np\ndef solve(A, b):\n"
                 "    return np.linalg.solve(np.array(A, dtype=np.float32), np.array(b, dtype=np.float32)).astype(float)\n")
SOLVE_INVERSE = "import numpy as np\ndef solve(A, b):\n    return np.linalg.inv(np.array(A)) @ np.array(b)\n"
JACOBI = '''
import numpy as np
def solve(A, b):
    A, b = np.array(A), np.array(b)
    x = np.zeros(len(b))
    for _ in range(5):
        x = (b - A @ x + np.diag(A) * x) / np.diag(A)
    return x
'''
GUESS = "def solve(A, b):\n    return [1.0] * len(b)\n"

CAVITY = '''
import sys
sys.path.insert(0, %r)
import engineering_references as er
SCALE = 1.0
def solve(Re):
    column = er.GHIA_COLUMN[Re]
    return {"y": [r[0] for r in er.GHIA_U], "u": [SCALE * r[column] for r in er.GHIA_U]}
''' % str(ROOT / "scripts")


def stream_function_cavity(reynolds, n=64, t_end=40.0, dt=0.003):
    """u on the vertical centreline of the steady cavity: psi-omega form, central differences, Thom's wall vorticity,
    explicit steps to the steady state. An implementation independent of the table it is compared with."""
    h = 1.0 / n
    m = n - 1
    second = sparse.diags([np.ones(m - 1), -2.0 * np.ones(m), np.ones(m - 1)], [-1, 0, 1]) / h ** 2
    identity = sparse.identity(m)
    poisson = sparse_linalg.splu((-(sparse.kron(second, identity) + sparse.kron(identity, second))).tocsc())
    psi = np.zeros((n + 1, n + 1))
    omega = np.zeros((n + 1, n + 1))
    for _ in range(int(t_end / dt)):
        psi[1:-1, 1:-1] = poisson.solve(omega[1:-1, 1:-1].ravel()).reshape(m, m)
        omega[1:-1, 0] = -2.0 * psi[1:-1, 1] / h ** 2
        omega[1:-1, -1] = -2.0 * psi[1:-1, -2] / h ** 2 - 2.0 / h
        omega[0, 1:-1] = -2.0 * psi[1, 1:-1] / h ** 2
        omega[-1, 1:-1] = -2.0 * psi[-2, 1:-1] / h ** 2
        u = (psi[1:-1, 2:] - psi[1:-1, :-2]) / (2.0 * h)
        v = -(psi[2:, 1:-1] - psi[:-2, 1:-1]) / (2.0 * h)
        dwdx = (omega[2:, 1:-1] - omega[:-2, 1:-1]) / (2.0 * h)
        dwdy = (omega[1:-1, 2:] - omega[1:-1, :-2]) / (2.0 * h)
        laplacian = (omega[2:, 1:-1] + omega[:-2, 1:-1] + omega[1:-1, 2:] + omega[1:-1, :-2] - 4.0 * omega[1:-1, 1:-1]) / h ** 2
        omega[1:-1, 1:-1] += dt * (-u * dwdx - v * dwdy + laplacian / reynolds)
    middle = n // 2
    return [j * h for j in range(n + 1)], [0.0] + list((psi[middle, 2:] - psi[middle, :-2]) / (2.0 * h)) + [1.0]


class Poisson2D(base.Harness):
    ARGS = ("--order", "2", "--steps", "4", "--levels", "4")

    def verdict(self, source, *args):
        return self.run_cli("run", "poisson-2d", "--solver", self.solver(source), *args).returncode

    @unittest.skipUnless(HAVE_SYMPY, "needs sympy")
    def test_the_right_hand_side_follows_from_the_solution(self):
        x, y = sympy.symbols("x y")
        u = sympy.sin(sympy.pi * x) * sympy.sin(sympy.pi * y)
        self.assertEqual(sympy.simplify(-sympy.diff(u, x, 2) - sympy.diff(u, y, 2) - 2 * sympy.pi ** 2 * u), 0)
        self.assertEqual(cv.poisson2d_exact(0.0, 0.3), 0.0)
        self.assertAlmostEqual(cv.poisson2d_exact(1.0, 0.3), 0.0, places=15)

    def test_the_five_point_laplacian_is_second_order(self):
        self.assertEqual(self.verdict(POISSON, *self.ARGS), 0)

    def test_a_claim_of_fourth_order_fails(self):
        self.assertEqual(self.verdict(POISSON, "--order", "4", "--steps", "4", "--levels", "4"), 1)

    def test_the_wrong_sign_of_the_source_fails(self):
        self.assertEqual(self.verdict(POISSON.replace("SIGN = 1.0", "SIGN = -1.0"), *self.ARGS), 1)

    def test_a_wrong_stencil_weight_fails(self):
        self.assertEqual(self.verdict(POISSON.replace("DIAGONAL = 4.0", "DIAGONAL = 4.1"), *self.ARGS), 1)

    def test_the_wrong_shape_fails(self):
        self.assertEqual(self.verdict("def solve(n):\n    return [0.0] * (n + 1)\n", *self.ARGS), 1)

    def test_an_order_is_required(self):
        self.assertEqual(self.verdict(POISSON), 2)


class BeamTimoshenko(base.Harness):
    def verdict(self, source, *args):
        return self.run_cli("run", "beam-timoshenko", "--solver", self.solver(source), *args).returncode

    @unittest.skipUnless(HAVE_SYMPY, "needs sympy")
    def test_the_closed_form_follows_from_the_beam_equations(self):
        L, E, G, I, A, kappa, P, x, s = sympy.symbols("L E G I A kappa P x s", positive=True)
        rotation = sympy.integrate(P * (L - s) / (E * I), (s, 0, x))
        tip = sympy.integrate(rotation + P / (kappa * G * A), (x, 0, L))
        self.assertEqual(sympy.simplify(tip - (P * L ** 3 / (3 * E * I) + P * L / (kappa * G * A))), 0)

    def test_the_cases_cover_the_range_they_claim(self):
        ratios = [(c["P"] * c["L"] / (c["kappa"] * c["G"] * c["A"])) / (c["P"] * c["L"] ** 3 / (3.0 * c["E"] * c["I"]))
                  for c in er.BEAM_CASES]
        self.assertLess(ratios[1], 1e-6)                                  # Euler-Bernoulli limit
        self.assertGreater(ratios[2], 0.1)                                # shear matters
        self.assertAlmostEqual(ratios[1], 7.8e-7, delta=1e-9)             # 0.78 (h / L)^2 for this section and nu = 0.3
        self.assertAlmostEqual(ratios[2], 0.195, places=12)

    def test_the_right_formula_passes(self):
        self.assertEqual(self.verdict(BEAM), 0)

    def test_leaving_out_shear_fails_on_the_deep_beam(self):
        done = self.run_cli("run", "beam-timoshenko", "--solver", self.solver(BEAM_NO_SHEAR))
        self.assertEqual(done.returncode, 1)
        self.assertIn("short and deep", done.stdout)

    def test_the_slender_beam_cannot_tell_shear_at_a_loose_tolerance(self):
        report = self.run_cli("run", "beam-timoshenko", "--solver", self.solver(BEAM_NO_SHEAR, "loose"), "--tol", "1e-5").stdout
        self.assertRegex(report, r"\| `slender, Euler-Bernoulli limit` \| PASS")
        self.assertRegex(report, r"\| `short and deep` \| FAIL")

    def test_the_uniform_load_formula_fails(self):
        self.assertEqual(self.verdict(BEAM_UNIFORM_LOAD), 1)

    def test_a_tolerance_below_the_roundoff_is_refused(self):
        self.assertEqual(self.verdict(BEAM, "--tol", "1e-16"), 2)


class HilbertReference(unittest.TestCase):
    def test_the_condition_numbers_are_the_standard_values(self):
        self.assertEqual(er.hilbert_condition_inf(3), 748.0)
        self.assertEqual(er.hilbert_condition_inf(4), 28375.0)

    def test_the_integer_inverse_is_the_inverse_in_exact_arithmetic(self):
        for n in (3, 7, 12):
            with self.subTest(n=n):
                H = [[Fraction(1, i + j + 1) for j in range(n)] for i in range(n)]
                H_inv = [[er.hilbert_inverse_entry(n, i + 1, j + 1) for j in range(n)] for i in range(n)]
                for i in range(n):
                    for j in range(n):
                        self.assertEqual(sum(H[i][k] * H_inv[k][j] for k in range(n)), 1 if i == j else 0)

    def test_the_solution_is_neither_constant_nor_guessable_from_the_right_hand_side(self):
        truth = er.hilbert_solution(5)
        self.assertEqual(len({abs(v) for v in truth}), 5)
        self.assertEqual({v > 0 for v in truth}, {True, False})


class LinearSolveHilbert(base.Harness):
    def run_it(self, source, *args):
        return self.run_cli("run", "linear-solve-hilbert", "--solver", self.solver(source), *args)

    def test_a_backward_stable_solve_passes_at_every_size(self):
        done = self.run_it(SOLVE)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("10 of 10 cases passed", done.stdout)

    def test_the_inverse_fails_where_solve_does_not(self):
        # Measured: the residual through the inverse is 3.5e-3 at n = 12 and solve's is 1.4e-16 (numpy, one platform), so the
        # gap is many orders of magnitude and 1e-12 separates them from n = 5 on. Asserted at the largest size only.
        done = self.run_it(SOLVE_INVERSE)
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertRegex(done.stdout, r"\| `n=12` \| FAIL")

    def test_single_precision_fails(self):
        self.assertEqual(self.run_it(SOLVE_FLOAT32).returncode, 1)

    def test_a_few_jacobi_sweeps_fail(self):
        self.assertEqual(self.run_it(JACOBI).returncode, 1)

    def test_a_guessed_constant_vector_fails(self):
        self.assertEqual(self.run_it(GUESS).returncode, 1)

    def test_a_wrong_length_fails(self):
        self.assertEqual(self.run_it("def solve(A, b):\n    return [0.0]\n").returncode, 1)

    def test_a_solver_that_overwrites_its_input_is_not_reproducible(self):
        source = "import numpy as np\ndef solve(A, b):\n    x = np.linalg.solve(np.array(A), np.array(b))\n" \
                 "    A[0][0] = 7.0\n    return x\n"
        self.assertEqual(self.run_it(source).returncode, 1)

    def test_the_forward_error_is_reported_and_not_judged(self):
        done = self.run_it(SOLVE, "--report", str(self.dir / "r.md"), "--json", str(self.dir / "r.json"))
        cases = json.loads((self.dir / "r.json").read_text())["cases"]
        self.assertEqual(list(cases[-1]["errors"]), ["rel_residual"])
        self.assertIn("forward error", cases[-1]["detail"])
        self.assertEqual(done.returncode, 0)

    def test_a_tolerance_below_the_residual_roundoff_is_refused(self):
        self.assertEqual(self.run_it(SOLVE, "--tol", "1e-17").returncode, 2)


class GhiaTable(unittest.TestCase):
    def test_it_is_the_table_of_the_paper_in_shape(self):
        self.assertEqual(len(er.GHIA_U), 17)
        ys = [row[0] for row in er.GHIA_U]
        self.assertEqual(ys, sorted(ys))
        self.assertEqual((ys[0], ys[-1]), (0.0, 1.0))
        self.assertEqual(er.GHIA_U[0][1:], (0.0, 0.0))                    # the fixed wall
        self.assertEqual(er.GHIA_U[-1][1:], (1.0, 1.0))                   # the lid

    def test_the_minimum_moves_toward_the_wall_with_reynolds_number(self):
        # Boundary layers thin as Re grows, so the reverse-flow peak moves down and grows. A swapped column would break this.
        at_100 = min(er.GHIA_U, key=lambda row: row[1])
        at_1000 = min(er.GHIA_U, key=lambda row: row[2])
        self.assertEqual((at_100[0], at_1000[0]), (0.4531, 0.1719))
        self.assertLess(at_1000[2], at_100[1])

    def test_interpolation_is_exact_at_nodes_and_linear_between(self):
        self.assertEqual(er.interpolate([0.0, 1.0, 2.0], [0.0, 2.0, 0.0], 1.0), 2.0)
        self.assertEqual(er.interpolate([0.0, 1.0, 2.0], [0.0, 2.0, 0.0], 1.5), 1.0)

    @unittest.skipUnless(HAVE_SCIPY, "needs scipy")
    def test_a_solver_written_independently_reproduces_the_re_100_column(self):
        y, u = stream_function_cavity(100.0)
        self.assertLess(er.cavity_error(100.0, y, u), 0.006)              # measured 3.8e-3 (see the module docstring)
        coarse = er.cavity_error(100.0, *stream_function_cavity(100.0, n=32))
        self.assertGreater(coarse, er.cavity_error(100.0, y, u))          # and it closes in on the table as the grid refines

    @unittest.skipUnless(HAVE_SCIPY, "needs scipy")
    def test_the_comparison_tells_a_different_reynolds_number(self):
        y, u = stream_function_cavity(50.0)
        self.assertGreater(er.cavity_error(100.0, y, u), 0.02)            # measured 5.0e-2


class CavityGhia(base.Harness):
    def verdict(self, source, *args):
        return self.run_cli("run", "cavity-ghia", "--solver", self.solver(source), *args).returncode

    def test_the_table_itself_passes(self):
        self.assertEqual(self.verdict(CAVITY, "--tol", "1e-3"), 0)

    def test_an_error_of_two_percent_fails_at_one_and_passes_at_three(self):
        wrong = CAVITY.replace("SCALE = 1.0", "SCALE = 1.02")
        self.assertEqual(self.verdict(wrong, "--tol", "0.01", "--no-evidence"), 1)
        self.assertEqual(self.verdict(wrong, "--tol", "0.03", "--no-evidence"), 0)

    def test_swapped_columns_fail(self):
        swapped = CAVITY.replace("column = er.GHIA_COLUMN[Re]", "column = 3 - er.GHIA_COLUMN[Re]")
        self.assertEqual(self.verdict(swapped, "--tol", "0.05"), 1)

    def test_a_tolerance_is_required_and_cannot_beat_the_table(self):
        self.assertEqual(self.verdict(CAVITY), 2)
        self.assertEqual(self.verdict(CAVITY, "--tol", "1e-4"), 2)

    def test_answers_that_cannot_be_judged_fail(self):
        for body in ("return 1.0", "return {'y': [0.0, 1.0]}", "return {'y': [0.0, 0.5], 'u': [0.0, 1.0]}",
                     "return {'y': [1.0, 0.0], 'u': [1.0, 0.0]}", "return {'y': [0.0, 1.0], 'u': [0.0, float('nan')]}"):
            with self.subTest(body=body):
                self.assertEqual(self.verdict(f"def solve(Re):\n    {body}\n", "--tol", "0.5", "--no-evidence"), 1)


class Manifest(unittest.TestCase):
    def validate(self, check):
        return rm.validate({"schema": rm.SCHEMA, "checks": [check]}, car.BENCHMARKS, car.resolve_tolerance)

    def test_the_new_benchmarks_are_valid_checks(self):
        common = {"id": "a", "rationale": "a check with a stated reason", "solver": "s.py:solve"}
        self.assertEqual(self.validate(dict(common, benchmark="beam-timoshenko")), [])
        self.assertEqual(self.validate(dict(common, benchmark="linear-solve-hilbert")), [])
        self.assertEqual(self.validate(dict(common, benchmark="cavity-ghia", tol=0.01)), [])
        self.assertEqual(self.validate(dict(common, benchmark="poisson-2d", order=2)), [])

    def test_their_requirements_are_enforced(self):
        common = {"id": "a", "rationale": "a check with a stated reason", "solver": "s.py:solve"}
        self.assertTrue(self.validate(dict(common, benchmark="cavity-ghia")))
        self.assertTrue(self.validate(dict(common, benchmark="poisson-2d")))


class SodCalibration(unittest.TestCase):
    # Printed by `python3 benchmarks/cfd/sod_calibration.py`: density, velocity, pressure. Also in the check-against-reference skill.
    TABLE = {"exact, diaphragm moved by 0.01": (1.55e-2, 4.19e-2, 1.73e-2),
             "first-order HLL, 100 cells": (2.98e-2, 5.72e-2, 2.61e-2)}

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("sod_calibration", ROOT / "benchmarks" / "cfd" / "sod_calibration.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_the_table_regenerates(self):
        rows = dict(self.module.table([100]))
        self.assertEqual(set(rows), set(self.TABLE))
        for name, expected in self.TABLE.items():
            got = rows[name]
            for key, value in zip(("rel_L1_density", "rel_L1_velocity", "rel_L1_pressure"), expected):
                with self.subTest(name=name, key=key):
                    self.assertAlmostEqual(got[key], value, delta=1e-3)

    def test_the_first_order_scheme_converges(self):
        coarse = self.module.errors(self.module.godunov_hll(100, self.module.POINTS))
        fine = self.module.errors(self.module.godunov_hll(400, self.module.POINTS))
        for key in coarse:
            self.assertLess(fine[key], coarse[key])

    def test_the_script_runs(self):
        done = subprocess.run([sys.executable, "-B", str(ROOT / "benchmarks" / "cfd" / "sod_calibration.py"), "100"],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("first-order HLL, 100 cells", done.stdout)


if __name__ == "__main__":
    unittest.main()
