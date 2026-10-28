"""Tests for scripts/check_against_reference.py.

Run (from the plugin root):  python3 -B -m unittest discover -s tests -v

Three groups:
 1. The reference values themselves are re-derived here by independent means (mpmath, scipy, closed forms, the
    defining equation) and compared with the checker's tables, so the checker is never validated against itself.
 2. Correct solvers must pass; the error each one actually has is asserted within the bounds measured below.
 3. Wrong solvers (sign error, low order, float32, wrong constant, wrong state, NaN, crash, hang) must fail, and
    unusable arguments must exit 2.

Reference values and sources:
 - Kepler's equation M = E - e sin E: unique root for 0 <= e < 1 (Danby 1988, ch. 6); re-solved with mpmath at 30 digits.
 - Lane-Emden n=0: xi_1 = sqrt(6); n=1: xi_1 = pi (closed forms). n=1.5: 3.65375, 2.71406; n=3: 6.89685, 2.01824
   (Chandrasekhar 1939, tabulated to 6 digits, so agreement is checked to 5e-6 / value); re-integrated with scipy DOP853.
 - Sod shock tube (Toro 2009, Table 4.1 test 1): p* = 0.30313, u* = 0.92745 (5 digits, checked to 1e-5), and the star
   pressure must satisfy f_L(p*) + f_R(p*) + (u_R - u_L) = 0 (Toro eq. 4.5), re-implemented here.
 - Robertson: re-integrated with Radau and BDF at rtol 1e-12; mass invariant y1 + y2 + y3 = 1.
Tolerances in the solver tests are stated per test; none was loosened to make a test pass.
"""

import contextlib
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_against_reference.py"
sys.path.insert(0, str(ROOT / "scripts"))

import check_against_reference as car  # noqa: E402
import verification_evidence as ve  # noqa: E402

try:
    import scipy  # noqa: F401
    from scipy.integrate import solve_ivp
    HAVE_SCIPY = True
except ImportError:
    HAVE_SCIPY = False
try:
    import mpmath
    HAVE_MPMATH = True
except ImportError:
    HAVE_MPMATH = False


# ----------------------------------------------------------------------------------------------------------------
# Solvers under test (written to files and run through the real CLI)
# ----------------------------------------------------------------------------------------------------------------

KEPLER_GOOD = '''
import math
def solve(M, e):
    M = M % (2 * math.pi)
    E = M if e < 0.8 else math.pi
    for _ in range(200):
        step = (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
        E -= step
        if abs(step) < 1e-15:
            break
    return E
'''
KEPLER_SHIFTED = KEPLER_GOOD.replace("    return E", "    return E - 2 * math.pi")     # a valid answer shifted by -2 pi
KEPLER_SIGN = '''
import math
def solve(M, e):                      # solves M = E + e sin E: the wrong sign
    M = M % (2 * math.pi)
    E = M
    for _ in range(200):
        E -= (E + e * math.sin(E) - M) / (1 + e * math.cos(E))
    return E
'''
KEPLER_FIRST_ORDER = "import math\ndef solve(M, e):\n    return M % (2*math.pi) + e * math.sin(M)\n"
KEPLER_FEW_ITERATIONS = KEPLER_GOOD.replace("range(200)", "range(3)")
KEPLER_FLOAT32 = KEPLER_GOOD.replace("    return E", "    import struct\n    return struct.unpack('f', struct.pack('f', E))[0]")
KEPLER_NAN = "def solve(M, e):\n    return float('nan')\n"
KEPLER_RAISES = "def solve(M, e):\n    raise RuntimeError('did not converge')\n"
KEPLER_STRING = "def solve(M, e):\n    return 'one point five'\n"
KEPLER_BOOL = "def solve(M, e):\n    return True\n"
KEPLER_HANGS = "import time\ndef solve(M, e):\n    time.sleep(30)\n    return 0.0\n"

LANE_RK4 = '''
import math
def _integrate(n, dxi, method):
    x = 1e-4
    th = 1 - x**2/6 + n*x**4/120 - n*(8*n-5)*x**6/15120
    u = -x/3 + n*x**3/30 - n*(8*n-5)*x**5/2520
    f = lambda x, th, u: (u, -max(th, 0.0)**n - 2.0/x*u)
    while True:
        if method == "rk4":
            k1 = f(x, th, u); k2 = f(x+dxi/2, th+dxi/2*k1[0], u+dxi/2*k1[1])
            k3 = f(x+dxi/2, th+dxi/2*k2[0], u+dxi/2*k2[1]); k4 = f(x+dxi, th+dxi*k3[0], u+dxi*k3[1])
            th2 = th + dxi/6*(k1[0]+2*k2[0]+2*k3[0]+k4[0]); u2 = u + dxi/6*(k1[1]+2*k2[1]+2*k3[1]+k4[1])
        else:                                                      # explicit Euler
            d = f(x, th, u); th2 = th + dxi*d[0]; u2 = u + dxi*d[1]
        if th2 <= 0.0:
            frac = -th / (th2 - th)
            return x + frac*dxi, u + frac*(u2 - u)
        x, th, u = x + dxi, th2, u2
def solve(n):
    xi1, u1 = _integrate(n, __DXI__, __METHOD__)
    return {"xi_1": xi1, "omega_n": __OMEGA__}
'''


def lane_source(dxi, method, omega="-xi1**2 * u1"):
    return LANE_RK4.replace("__DXI__", repr(dxi)).replace("__METHOD__", repr(method)).replace("__OMEGA__", omega)


LANE_GOOD = lane_source(1e-3, "rk4")
LANE_EULER = lane_source(1e-2, "euler")
LANE_OMEGA_UNSQUARED = lane_source(1e-3, "rk4", omega="-xi1 * u1")
LANE_MISSING_KEY = "def solve(n):\n    return {'xi_1': 3.0}\n"

SOD_LAX_FRIEDRICHS = '''
GAMMA = 1.4
def solve(x, t):
    N = 400
    dx = 1.0 / N
    xc = [(i + 0.5) * dx for i in range(N)]
    U = [[1.0, 0.0, 1.0 / (GAMMA - 1)] if c < 0.5 else [0.125, 0.0, 0.1 / (GAMMA - 1)] for c in xc]
    def flux(u):
        rho, m, E = u; v = m / rho; p = (GAMMA - 1) * (E - 0.5 * rho * v * v)
        return [m, m * v + p, v * (E + p)]
    time = 0.0
    while time < t - 1e-14:
        speeds = []
        for rho, m, E in U:
            v = m / rho; p = (GAMMA - 1) * (E - 0.5 * rho * v * v); speeds.append(abs(v) + (GAMMA * p / rho) ** 0.5)
        dt = min(0.4 * dx / max(speeds), t - time)
        F = [flux(u) for u in U]
        new = [U[0][:]]
        for i in range(1, N - 1):
            new.append([0.5 * (U[i-1][k] + U[i+1][k]) - dt / (2 * dx) * (F[i+1][k] - F[i-1][k]) for k in range(3)])
        new.append(U[-1][:])
        U, time = new, time + dt
    rho = [u[0] for u in U]; vel = [u[1] / u[0] for u in U]
    pres = [(GAMMA - 1) * (u[2] - 0.5 * u[0] * (u[1] / u[0]) ** 2) for u in U]
    return {"x": xc, "density": rho, "velocity": vel, "pressure": pres}
'''
SOD_EXACT_COPY = '''
import sys
sys.path.insert(0, %r)
from exact_riemann import exact_riemann_solver
def solve(x, t):
    n = len(x)
    s = exact_riemann_solver(t_target=t, num_points=n)
    return {"x": s["x"], "density": s["density"], "velocity": s["velocity"], "pressure": s["pressure"]}
''' % str(ROOT / "benchmarks" / "cfd")
SOD_MIRRORED = SOD_EXACT_COPY.replace('"density": s["density"], "velocity": s["velocity"], "pressure": s["pressure"]',
                                      '"density": s["density"][::-1], "velocity": s["velocity"], "pressure": s["pressure"][::-1]')
SOD_SHORT = "def solve(x, t):\n    return {'density': [1.0], 'velocity': [0.0], 'pressure': [1.0]}\n"
SOD_NOT_DICT = "def solve(x, t):\n    return [1, 2, 3]\n"

ROBERTSON_RADAU = '''
from scipy.integrate import solve_ivp
def solve(t):
    k1, k2, k3 = 0.04, 1e4, 3e7
    f = lambda s, y: [-k1*y[0] + k2*y[1]*y[2], k1*y[0] - k2*y[1]*y[2] - k3*y[1]**2, k3*y[1]**2]
    J = lambda s, y: [[-k1, k2*y[2], k2*y[1]], [k1, -k2*y[2] - 2*k3*y[1], -k2*y[1]], [0, 2*k3*y[1], 0]]
    return list(solve_ivp(f, (0, t), [1, 0, 0], method="Radau", jac=J, rtol=1e-10, atol=1e-20).y[:, -1])
'''
ROBERTSON_WRONG_RATE = ROBERTSON_RADAU.replace("k3 = 0.04, 1e4, 3e7", "k3 = 0.04, 1e4, 3e6")
ROBERTSON_BACKWARD_EULER = '''
def solve(t):
    k1, k2, k3 = 0.04, 1e4, 3e7
    y = [1.0, 0.0, 0.0]
    h = t / 200.0
    for _ in range(200):                                         # backward Euler, Newton on the 3x3 system
        z = y[:]
        for _ in range(30):
            F = [z[0]-y[0] - h*(-k1*z[0] + k2*z[1]*z[2]), z[1]-y[1] - h*(k1*z[0] - k2*z[1]*z[2] - k3*z[1]**2),
                 z[2]-y[2] - h*(k3*z[1]**2)]
            J = [[1 + h*k1, -h*k2*z[2], -h*k2*z[1]], [-h*k1, 1 + h*(k2*z[2] + 2*k3*z[1]), h*k2*z[1]],
                 [0.0, -2*h*k3*z[1], 1.0]]
            import numpy as np
            dz = np.linalg.solve(np.array(J), -np.array(F)); z = [z[i] + dz[i] for i in range(3)]
            if max(abs(dz)) < 1e-14: break
        y = z
    return y
'''
ROBERTSON_MASS_LEAK = ROBERTSON_RADAU.replace("return list(", "y = list(").replace(
    ".y[:, -1])", ".y[:, -1])\n    y[2] += 1e-5\n    return y")


# ----------------------------------------------------------------------------------------------------------------

class Harness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def solver(self, source, name="solver"):
        path = self.dir / (name + ".py")
        path.write_text(source)
        return "%s:solve" % path

    def run_cli(self, *args, timeout=600):
        env = dict(os.environ, VERIFICATION_EVIDENCE_DIR=str(self.dir / ".verification"))   # never write into the repo
        return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], capture_output=True, text=True, timeout=timeout,
                              env=env)

    def run_bench(self, bench, source, *extra, timeout=600):
        out = self.dir / "result.json"
        done = self.run_cli("run", bench, "--solver", self.solver(source), "--json", str(out), *extra, timeout=timeout)
        data = json.loads(out.read_text()) if out.exists() else None
        out.unlink(missing_ok=True)
        return done, data


class ReferencesAreIndependentlyCorrect(unittest.TestCase):
    @unittest.skipUnless(HAVE_MPMATH, "mpmath not installed")
    def test_kepler_reference_matches_mpmath(self):
        mpmath.mp.dps = 30
        worst = 0.0
        for e in car.KEPLER_E:
            for m in car.KEPLER_M:
                m_wrapped = m % car.TWO_PI
                root = mpmath.findroot(lambda x: x - e * mpmath.sin(x) - m_wrapped, car.kepler_reference(m, e))
                worst = max(worst, abs(float(root) - car.kepler_reference(m, e)))
        self.assertLess(worst, 1e-13)               # the benchmark's stated reference uncertainty (measured 4.5e-14)

    def test_kepler_reference_satisfies_the_equation_exactly(self):
        for e in car.KEPLER_E:
            for m in car.KEPLER_M:
                big_e = car.kepler_reference(m, e)
                self.assertLess(abs(car._fold(big_e - e * math.sin(big_e) - m % car.TWO_PI)), 1e-14, (m, e))
                self.assertTrue(0.0 <= big_e < car.TWO_PI)

    def test_lane_emden_closed_forms_and_tables(self):
        self.assertEqual(car.LANE_EMDEN[0.0][:2], (math.sqrt(6.0), 2.0 * math.sqrt(6.0)))
        self.assertEqual(car.LANE_EMDEN[1.0][:2], (math.pi, math.pi))
        # Chandrasekhar (1939) tabulated, 6 significant digits: agreement within the rounding of the last digit
        for n, (xi, om) in {1.5: (3.65375, 2.71406), 3.0: (6.89685, 2.01824)}.items():
            self.assertAlmostEqual(car.LANE_EMDEN[n][0] / xi, 1.0, delta=5e-6 / xi)
            self.assertAlmostEqual(car.LANE_EMDEN[n][1] / om, 1.0, delta=5e-6 / om)

    @unittest.skipUnless(HAVE_SCIPY, "scipy not installed")
    def test_lane_emden_stored_values_match_reintegration(self):
        def integrate(n, method):
            x0 = 1e-4
            th = 1 - x0**2 / 6 + n * x0**4 / 120 - n * (8 * n - 5) * x0**6 / 15120
            u = -x0 / 3 + n * x0**3 / 30 - n * (8 * n - 5) * x0**5 / 2520
            event = lambda x, y: y[0]
            event.terminal, event.direction = True, -1
            s = solve_ivp(lambda x, y: [y[1], -max(y[0], 0.0) ** n - 2.0 / x * y[1]], (x0, 50), [th, u],
                          method=method, rtol=1e-13, atol=1e-15, events=event)
            xi1, u1 = s.t_events[0][0], s.y_events[0][0][1]
            return xi1, -xi1**2 * u1
        for n in car.LANE_EMDEN:
            for method in ("DOP853", "Radau"):
                xi1, omega = integrate(n, method)
                self.assertAlmostEqual(xi1 / car.LANE_EMDEN[n][0], 1.0, delta=1e-9, msg=(n, method))
                self.assertAlmostEqual(omega / car.LANE_EMDEN[n][1], 1.0, delta=1e-9, msg=(n, method))

    def test_sod_star_state_against_toro_and_defining_equation(self):
        solver = car._exact_riemann()
        s = solver(t_target=0.2, num_points=101)
        self.assertAlmostEqual(s["p_star"], 0.30313, delta=1e-5)          # Toro (2009) Table 4.1, 5 digits
        self.assertAlmostEqual(s["u_star"], 0.92745, delta=1e-5)
        g, c_l, c_r, ps = 1.4, math.sqrt(1.4), math.sqrt(1.4 * 0.1 / 0.125), s["p_star"]
        f_l = 2 * c_l / (g - 1) * (ps ** ((g - 1) / (2 * g)) - 1)         # rarefaction on the left
        f_r = (ps - 0.1) * math.sqrt(2 / ((g + 1) * 0.125) / (ps + (g - 1) / (g + 1) * 0.1))   # shock on the right
        self.assertLess(abs(f_l + f_r), 1e-12)
        self.assertLess(abs(0.5 * (f_r - f_l) - s["u_star"]), 1e-12)

    def test_sod_single_point_sampling_equals_grid_solution(self):
        n = 101
        xs = [i / (n - 1) for i in range(n)]
        grid = car._exact_riemann()(t_target=0.2, num_points=n)
        mine = car._sod_reference_on(xs)
        for key in ("density", "velocity", "pressure"):
            self.assertLess(max(abs(a - b) for a, b in zip(mine[key], grid[key])), 1e-13)

    @unittest.skipUnless(HAVE_SCIPY, "scipy not installed")
    def test_robertson_stored_values_match_reintegration(self):
        k1, k2, k3 = 0.04, 1e4, 3e7
        f = lambda t, y: [-k1*y[0] + k2*y[1]*y[2], k1*y[0] - k2*y[1]*y[2] - k3*y[1]**2, k3*y[1]**2]
        jac = lambda t, y: [[-k1, k2*y[2], k2*y[1]], [k1, -k2*y[2] - 2*k3*y[1], -k2*y[1]], [0, 2*k3*y[1], 0]]
        times = sorted(car.ROBERTSON)
        for method in ("Radau", "BDF"):
            sol = solve_ivp(f, (0, times[-1]), [1, 0, 0], method=method, jac=jac, t_eval=times, rtol=1e-12, atol=1e-22)
            for i, t in enumerate(times):
                for j in range(3):
                    self.assertAlmostEqual(sol.y[j, i] / car.ROBERTSON[t][j], 1.0, delta=1e-9, msg=(method, t, j))
        for t, y in car.ROBERTSON.items():
            self.assertLess(abs(sum(y) - 1.0), 1e-9)                       # linear invariant

    def test_reference_uncertainty_is_above_the_smallest_accepted_tolerance(self):
        for bench in car.BENCHMARKS.values():
            self.assertGreater(bench.min_tol, 0)
            if bench.default_tol is not None:
                self.assertGreaterEqual(bench.default_tol, bench.min_tol)


class KeplerCli(Harness):
    def test_correct_solver_passes_with_the_default_tolerance(self):
        done, data = self.run_bench("kepler", KEPLER_GOOD)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual((data["tolerance_used"], data["relaxed"]), (1e-12, False))
        self.assertEqual(len(data["cases"]), len(car.KEPLER_E) * len(car.KEPLER_M))
        self.assertLess(max(c["errors"]["residual"] for c in data["cases"]), 1e-13)   # measured, not assumed

    def test_answer_shifted_by_two_pi_is_still_correct(self):
        self.assertEqual(self.run_bench("kepler", KEPLER_SHIFTED)[0].returncode, 0)

    def test_wrong_solvers_fail(self):
        for label, source in {"wrong sign": KEPLER_SIGN, "first order": KEPLER_FIRST_ORDER,
                              "three iterations": KEPLER_FEW_ITERATIONS, "float32 precision": KEPLER_FLOAT32}.items():
            done, data = self.run_bench("kepler", source)
            self.assertEqual(done.returncode, 1, label)
            self.assertFalse(data["passed"], label)

    def test_float32_is_caught_by_residual_not_only_by_reference(self):
        _, data = self.run_bench("kepler", KEPLER_FLOAT32)
        self.assertGreater(max(c["errors"]["residual"] for c in data["cases"]), 1e-9)

    def test_nan_crash_non_number_and_hang_fail_per_case_with_a_reason(self):
        for label, source, text in (("nan", KEPLER_NAN, "not finite"), ("raises", KEPLER_RAISES, "RuntimeError"),
                                    ("string", KEPLER_STRING, "not a number"), ("bool", KEPLER_BOOL, "bool")):
            done, data = self.run_bench("kepler", source)
            self.assertEqual(done.returncode, 1, label)
            self.assertTrue(all(text in c["reason"] for c in data["cases"]), label)
        # The whole run must end in a few seconds: a working timeout stops after the first hung call. Without it this
        # solver would sleep 30 s on each of the 72 cases, so the harness limit below turns that into a failure.
        done, data = self.run_bench("kepler", KEPLER_HANGS, "--timeout-s", "1", timeout=30)
        self.assertEqual(done.returncode, 1)
        self.assertIn("did not return within 1 s", data["cases"][0]["reason"])
        self.assertTrue(all("not run" in c["reason"] for c in data["cases"][1:]))      # no waiting 72 times

    def test_tolerance_relaxation_is_recorded_in_json_and_report(self):
        report = self.dir / "r.md"
        done, data = self.run_bench("kepler", KEPLER_FIRST_ORDER, "--tol", "1", "--report", str(report),
                                    "--no-evidence")
        self.assertTrue(data["relaxed"])
        self.assertEqual((data["tolerance_default"], data["tolerance_used"]), (1e-12, 1.0))
        self.assertIn("Tolerance relaxed", report.read_text())
        self.assertFalse(self.run_bench("kepler", KEPLER_GOOD, "--tol", "1e-12")[1]["relaxed"])   # the default itself
        refused = self.run_cli("run", "kepler", "--solver", self.solver(KEPLER_GOOD), "--tol", "1e-13")
        self.assertEqual(refused.returncode, 2)                      # finer than the reference can certify


KEPLER_NOISY = KEPLER_GOOD.replace("    return E", "    import random\n    return E + random.random() * 1e-14")     # unseeded
KEPLER_COUNTING = KEPLER_GOOD.replace("def solve", "CALLS = [0]\n\n\ndef solve", 1).replace(
    "    return E", "    CALLS[0] += 1\n    return E + CALLS[0] * 1e-15")                                        # hidden state
KEPLER_ALTERNATING = KEPLER_GOOD.replace("def solve", "CALLS = [0]\n\n\ndef solve", 1).replace(
    "    return E", "    CALLS[0] += 1\n    return E + (1e-13 if CALLS[0] % 2 == 0 else 0.0)")       # calls 1 and 3 agree, 2 differs
KEPLER_SHAPE_SHIFT = KEPLER_GOOD.replace("def solve", "CALLS = [0]\n\n\ndef solve", 1).replace(
    "    return E", "    CALLS[0] += 1\n    return E if CALLS[0] % 2 else [E]")
KEPLER_FAILS_SECOND_CALL = KEPLER_GOOD.replace("def solve", "CALLS = [0]\n\n\ndef solve", 1).replace(
    "    return E", "    CALLS[0] += 1\n    if CALLS[0] % 2 == 0:\n        raise RuntimeError('second call fails')\n    return E")


class AnswerDifference(unittest.TestCase):
    d = staticmethod(car.answer_difference)

    def close(self, value, expected):
        """The inputs (3.0 + 4e-9, ...) are not exactly representable, so compare to 1e-6 of the expected value."""
        self.assertAlmostEqual(value / expected, 1.0, delta=1e-6)

    def test_numbers_are_compared_relative_to_one_plus_the_value(self):
        self.assertEqual(self.d(1.5, 1.5), 0.0)
        self.close(self.d(0.0, 1e-9), 1e-9)
        self.close(self.d(1e6, 1e6 + 1e-4), 1e-4 / (1 + 1e6))                          # a large value tolerates more
        self.assertEqual(self.d(1, 1.0), 0.0)

    def test_nested_structures_report_the_worst_leaf(self):
        a = {"x": [1.0, 2.0, {"y": 3.0}], "label": "u"}
        b = {"x": [1.0, 2.0, {"y": 3.0 + 4e-9}], "label": "u"}
        self.close(self.d(a, b), 4e-9 / 4.0)
        self.assertEqual(self.d(a, dict(a)), 0.0)

    def test_structure_keys_lengths_and_types_must_match(self):
        for a, b in (({"x": 1.0}, {"y": 1.0}), ([1.0, 2.0], [1.0]), (1.0, [1.0]), ({"x": 1.0}, [1.0]), ("a", "b"),
                     ("1", 1), (True, 1), (None, 0), (1.0, "1.0"), ((1.0,), 1.0)):
            self.assertEqual(self.d(a, b), math.inf, (a, b))
        self.assertEqual(self.d((1.0, 2.0), [1.0, 2.0]), 0.0)                         # a tuple and a list are the same shape
        self.assertEqual(self.d("a", "a"), 0.0)
        self.assertEqual(self.d(None, None), 0.0)
        self.assertEqual(self.d(True, True), 0.0)

    def test_nan_and_infinity(self):
        nan, inf = float("nan"), float("inf")
        self.assertEqual(self.d(nan, nan), 0.0)
        self.assertEqual(self.d(nan, 1.0), math.inf)
        self.assertEqual(self.d(1.0, nan), math.inf)
        self.assertEqual(self.d(inf, inf), 0.0)
        self.assertEqual(self.d(inf, -inf), math.inf)
        self.assertEqual(self.d(inf, 1.0), math.inf)

    def test_numpy_arrays_and_scalars(self):
        import numpy as np
        self.assertEqual(self.d(np.array([1.0, 2.0]), np.array([1.0, 2.0])), 0.0)
        self.close(self.d(np.array([1.0, 2.0]), np.array([1.0, 2.0 + 3e-9])), 3e-9 / 3.0)
        self.assertEqual(self.d(np.float64(2.0), 2.0), 0.0)
        self.assertEqual(self.d(np.array([1.0]), np.array([1.0, 2.0])), math.inf)

    def test_unknown_objects_compare_by_repr_and_deep_nesting_is_cut_off(self):
        class Thing:
            def __init__(self, v):
                self.v = v

            def __repr__(self):
                return "Thing(%s)" % self.v
        self.assertEqual(self.d(Thing(1), Thing(1)), 0.0)
        self.assertEqual(self.d(Thing(1), Thing(2)), math.inf)
        deep_a = deep_b = 1.0
        for _ in range(60):
            deep_a, deep_b = [deep_a], [deep_b]
        self.assertEqual(self.d(deep_a, deep_b), math.inf)

    def test_empty_containers(self):
        self.assertEqual(self.d([], []), 0.0)
        self.assertEqual(self.d({}, {}), 0.0)


class CallRepeatedAliasing(unittest.TestCase):
    def test_an_answer_that_is_the_object_the_solver_keeps_mutating_is_still_compared(self):
        """Regression: first and second answer were the same list, so the difference was always 0."""
        import argparse
        state = [0.0]

        def solver():
            state[0] += 1.0
            return state                                   # the same list object every call, changed in place
        args = argparse.Namespace(repeat=2, repeat_tol=0.0, timeout_s=0)
        with self.assertRaises(car.CaseFailure) as caught:
            car.call_repeated(solver, (), args)
        self.assertIn("not reproducible", str(caught.exception))

    def test_an_uncopyable_answer_does_not_break_the_check(self):
        import argparse

        class Uncopyable:
            def __deepcopy__(self, memo):
                raise TypeError("no copies")

            def __repr__(self):
                return "Uncopyable()"
        args = argparse.Namespace(repeat=2, repeat_tol=0.0, timeout_s=0)
        answer, spread = car.call_repeated(lambda: Uncopyable(), (), args)
        self.assertEqual(spread, 0.0)                                              # compared by repr: equal, and no exception

    def test_a_single_call_is_not_copied(self):
        import argparse
        marker = object()
        args = argparse.Namespace(repeat=1, repeat_tol=0.0, timeout_s=0)
        answer, spread = car.call_repeated(lambda: marker, (), args)
        self.assertIs(answer, marker)
        self.assertEqual(spread, 0.0)


class Repeat(Harness):
    def test_a_deterministic_solver_passes_with_repeats_and_the_report_says_so(self):
        report = self.dir / "r.md"
        done, data = self.run_bench("kepler", KEPLER_GOOD, "--repeat", "3", "--report", str(report))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(data["repeat"], {"calls": 3, "tolerance": 0.0})
        self.assertTrue(all(c["repeat_max_difference"] == 0.0 for c in data["cases"]))
        self.assertIn("Reproducibility: 3 calls per case, largest difference 0.000e+00", report.read_text())

    def test_without_repeat_nothing_is_checked_and_the_report_says_so(self):
        report = self.dir / "r.md"
        done, data = self.run_bench("kepler", KEPLER_NOISY, "--repeat", "1", "--report", str(report))
        self.assertEqual(done.returncode, 0, done.stdout)                           # the noise is far below the tolerance
        self.assertIn("Reproducibility not checked", report.read_text())
        self.assertNotIn("repeat_max_difference", data["cases"][0])

    def test_unseeded_randomness_is_caught_by_repeat(self):
        done, data = self.run_bench("kepler", KEPLER_NOISY, "--repeat", "2")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertTrue(any("not reproducible" in c.get("reason", "") for c in data["cases"]))

    def test_hidden_state_between_calls_is_caught(self):
        done, data = self.run_bench("kepler", KEPLER_COUNTING, "--repeat", "2")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("not reproducible", data["cases"][0]["reason"])

    def test_repeat_tol_allows_a_stated_difference_but_not_a_larger_one(self):
        self.assertEqual(self.run_bench("kepler", KEPLER_NOISY, "--repeat", "2", "--repeat-tol", "1e-12")[0].returncode, 0)
        self.assertEqual(self.run_bench("kepler", KEPLER_COUNTING, "--repeat", "2", "--repeat-tol", "1e-15", "--no-evidence")[0].returncode, 0)
        done, data = self.run_bench("kepler", KEPLER_COUNTING, "--repeat", "2", "--repeat-tol", "1e-17", "--no-evidence")
        self.assertEqual(done.returncode, 1)
        self.assertIn("allowed 1e-17", data["cases"][0]["reason"])

    def test_every_repeat_is_compared_not_only_the_last(self):
        """Calls 1 and 3 agree and call 2 differs: comparing only the last call with the first would miss it."""
        done, data = self.run_bench("kepler", KEPLER_ALTERNATING, "--repeat", "3")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("not reproducible", data["cases"][0]["reason"])
        self.assertEqual(self.run_bench("kepler", KEPLER_ALTERNATING, "--repeat", "3", "--repeat-tol", "1e-12",
                                        "--no-evidence")[0].returncode, 0)

    def test_a_changed_answer_shape_is_a_difference(self):
        done, data = self.run_bench("kepler", KEPLER_SHAPE_SHIFT, "--repeat", "2")
        self.assertEqual(done.returncode, 1)
        self.assertIn("different structure", data["cases"][0]["reason"])

    def test_a_second_call_that_raises_is_a_failure(self):
        done, data = self.run_bench("kepler", KEPLER_FAILS_SECOND_CALL, "--repeat", "2")
        self.assertEqual(done.returncode, 1)
        self.assertIn("second call fails", data["cases"][0]["reason"])

    def test_dict_answers_are_compared_too(self):
        done, data = self.run_bench("sod", SOD_EXACT_COPY, "--tol", "1e-9", "--points", "11", "--repeat", "2")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(data["cases"][0]["repeat_max_difference"], 0.0)

    def test_the_first_answer_is_the_one_that_is_checked(self):
        done, data = self.run_bench("kepler", KEPLER_GOOD, "--repeat", "2")
        self.assertEqual(len(data["cases"]), len(car.KEPLER_E) * len(car.KEPLER_M))
        self.assertTrue(all(c["passed"] for c in data["cases"]))

    def test_bad_repeat_arguments_exit_two(self):
        for extra in (["--repeat", "0"], ["--repeat", "11"], ["--repeat", "-1"], ["--repeat-tol", "-1e-9"],
                      ["--repeat-tol", "nan"], ["--repeat-tol", "inf"]):
            done = self.run_cli("run", "kepler", "--solver", self.solver(KEPLER_GOOD), *extra)
            self.assertEqual(done.returncode, 2, extra)

    def test_repeat_settings_are_part_of_the_recorded_tolerance(self):
        self.run_bench("kepler", KEPLER_GOOD, "--repeat", "2", "--repeat-tol", "1e-12")
        (record,) = ve.read_log(self.dir / ".verification" / "log.jsonl")[0]
        self.assertEqual((record["tolerance"]["repeat_min"], record["tolerance"]["repeat_tol"]), (2, 1e-12))

    def test_dropping_the_repeat_requirement_after_a_failure_is_withheld(self):
        """The determinism check failed; running the same solver again without it must not simply pass."""
        solver = self.solver(KEPLER_NOISY)
        self.assertEqual(self.run_cli("run", "kepler", "--solver", solver, "--repeat", "2").returncode, 1)
        self.assertEqual(self.run_cli("run", "kepler", "--solver", solver, "--repeat", "1").returncode, 3)
        self.assertEqual(self.run_cli("run", "kepler", "--solver", solver, "--repeat", "2", "--repeat-tol", "1e-12").returncode, 3)
        failed = ve.read_log(self.dir / ".verification" / "log.jsonl")[0]
        previous = next(r for r in reversed(failed) if r.get("exit_status") != 3 and r.get("passed") is False)
        new_tol = dict(previous["tolerance"])
        new_tol["repeat_tol"] = 1e-12
        reason = "approved relaxation: BLAS threads reorder the sum; 1e-12 stated in the spec"
        payload = {"schema": ve.APPROVAL_SCHEMA, "approvals": [{
            "key": previous["key"], "prev": previous["_line"], "old_tolerance": previous["tolerance"],
            "new_tolerance": new_tol, "reason": reason}]}
        (self.dir / ".verification" / "tolerance-approvals.json").write_text(json.dumps(payload))
        released = self.run_cli("run", "kepler", "--solver", solver, "--repeat", "2", "--repeat-tol", "1e-12")
        self.assertEqual(released.returncode, 0, released.stdout + released.stderr)
        self.assertEqual(ve.read_log(self.dir / ".verification" / "log.jsonl")[0][-1]["justification"], reason)


ODE_HEADER = (
    "def _add(y, k, h):\n    return [a + h * b for a, b in zip(y, k)]\n\n\n")
ODE_RK4 = ODE_HEADER + """def integrate(f, y0, t0, t1, n):
    h, y, t = (t1 - t0) / n, list(y0), t0
    for _ in range(n):
        k1 = f(t, y); k2 = f(t + h / 2, _add(y, k1, h / 2)); k3 = f(t + h / 2, _add(y, k2, h / 2)); k4 = f(t + h, _add(y, k3, h))
        y = [a + h / 6 * (p + 2 * q + 2 * r + s) for a, p, q, r, s in zip(y, k1, k2, k3, k4)]
        t += h
    return y
"""
ODE_EULER = ODE_HEADER + """def integrate(f, y0, t0, t1, n):
    h, y, t = (t1 - t0) / n, list(y0), t0
    for _ in range(n):
        y = _add(y, f(t, y), h)
        t += h
    return y
"""
ODE_RK4_STALE_TIME = ODE_RK4.replace("f(t + h / 2,", "f(t,").replace("f(t + h, _add(y, k3, h))", "f(t, _add(y, k3, h))")
ODE_MUTATES_INPUT = """def integrate(f, y0, t0, t1, n):
    h, t = (t1 - t0) / n, t0
    y = y0                                       # no copy: the caller's list is updated in place
    for _ in range(n):
        k = f(t, y)
        for i in range(len(y)):
            y[i] += h * k[i]
        t += h
    return y
"""
ODE_NUMPY = "import numpy as np\n" + ODE_RK4.replace("    return y\n", "    return np.array(y)\n")
ODE_NOISY = ODE_RK4.replace("    return y\n", "    import random\n    return [v + random.random() * 1e-9 for v in y]\n")
ODE_WRONG_SIZE = "def integrate(f, y0, t0, t1, n):\n    return [0.0, 0.0, 0.0]\n"
ODE_NAN = "def integrate(f, y0, t0, t1, n):\n    return [float('nan')] * len(y0)\n"
ODE_RAISES = "def integrate(f, y0, t0, t1, n):\n    raise RuntimeError('step size too small')\n"
ODE_EXACT_AT_ONE_LEVEL = ODE_RK4.replace("def integrate", "def _rk4").replace(
    "    return y\n", "    return y\n\n\ndef integrate(f, y0, t0, t1, n):\n    return _rk4(f, y0, t0, t1, n)\n")

BVP_CENTRAL = """def solve(n, f, shift=0.0):
    h = 1.0 / n
    m = n - 1
    diag, rhs = [2.0] * m, [h * h * f((i + 1 + shift) * h) for i in range(m)]
    for i in range(1, m):
        w = -1.0 / diag[i - 1]
        diag[i] += w
        rhs[i] -= w * rhs[i - 1]
    u = [0.0] * m
    u[-1] = rhs[-1] / diag[-1]
    for i in range(m - 2, -1, -1):
        u[i] = (rhs[i] + u[i + 1]) / diag[i]
    return [0.0] + u + [0.0]
"""
BVP_SHIFTED_SOURCE = BVP_CENTRAL + "\n\ndef solve_shifted(n, f):\n    return solve(n, f, 0.5)\n"
BVP_BAD_BOUNDARY = BVP_CENTRAL.replace("    return [0.0] + u + [0.0]", "    return [0.3] + u + [0.0]")
BVP_SHORT = "def solve(n, f):\n    return [0.0] * n\n"


ODE_SPREAD_BY_LEVEL = ODE_RK4.replace("def integrate", "CALLS = [0]\n\n\ndef integrate", 1).replace(
    "    return y\n", "    CALLS[0] += 1\n    return [v + (0.0 if CALLS[0] % 2 else n * 1e-14) for v in y]\n")   # call 2 differs by n * 1e-14


class ConvergenceChecks(unittest.TestCase):
    """The per-problem verdict functions, driven with synthetic answers so each quantity can be asserted exactly."""

    def ode_case(self, problem="decay", order=4.0, steps=16, levels=5):
        return {"name": problem, "problem": problem, "order": order, "calls": car.cv.ode_calls(problem, steps, levels)}

    def test_the_observed_order_is_the_worst_of_the_norms(self):
        """A perturbation at one node gives max-norm order 2 but L2 order 2.5 (the L2 norm carries a factor sqrt(h))."""
        exact = car.cv.BVP_PROBLEMS["poisson-sine"]["exact"]
        case = {"name": "poisson-sine", "problem": "poisson-sine", "order": 2.0,
                "calls": car.cv.bvp_calls("poisson-sine", 8, 5)}
        answers = []
        for call in case["calls"]:
            n = call[0]
            u = [exact(i / n) for i in range(n + 1)]
            u[n // 2] += 0.3 * (1.0 / n) ** 2                                    # one node off by 0.3 h^2
            answers.append(u)
        passed, errors, detail = car.convergence_bvp_check(case, answers, 0.25)
        self.assertTrue(passed, detail)
        self.assertAlmostEqual(errors["observed_order"], 2.0, delta=1e-6)         # min(2.0, 2.5), not 2.5
        self.assertIn("max-norm", detail)
        self.assertIn("L2-norm", detail)
        passed, errors, _ = car.convergence_bvp_check(dict(case, order=2.4), answers, 0.25)
        self.assertFalse(passed)                                                    # the max-norm order 2.0 misses 2.15

    def test_the_roundoff_floor_scales_with_the_exact_value_of_the_problem(self):
        """timedep has exact value e = 2.718: its floor is 2.7e-11, so an error of 2e-11 is roundoff, not truncation."""
        case = self.ode_case("timedep", 4.0)
        errors = [2e-11 * (256 / n) ** 4 for n in (16, 32, 64, 128, 256)]            # exact fourth order, finest = 2e-11
        answers = [[math.e + e] for e in errors]
        passed, result, detail = car.convergence_ode_check(case, answers, 0.25)
        self.assertTrue(passed, detail)
        orders_text = detail.split("orders [")[1].split("]")[0]
        self.assertEqual(len(orders_text.split(", ")), 3)                           # the 2e-11 level was discarded
        decay = self.ode_case("decay", 4.0)                                         # exact 0.135: floor stays 1e-11
        answers = [[math.exp(-2.0) + e] for e in errors]
        _, _, detail = car.convergence_ode_check(decay, answers, 0.25)
        self.assertEqual(len(detail.split("orders [")[1].split("]")[0].split(", ")), 4)

    def test_unusable_answers_are_reported_as_the_answer_not_as_a_crash(self):
        with self.assertRaises(car.CaseFailure):
            car.convergence_ode_check(self.ode_case(), [[0.1, 0.2]] * 5, 0.25)
        with self.assertRaises(car.CaseFailure):
            car.convergence_bvp_check({"name": "p", "problem": "poisson-sine", "order": 2.0,
                                       "calls": car.cv.bvp_calls("poisson-sine", 8, 5)}, [[0.0]] * 5, 0.25)


class ConvergenceCli(Harness):
    def conv(self, bench, source, order, *extra, entry="integrate", **kw):
        solver = self.solver(source).replace(":solve", ":" + entry)
        out = self.dir / "result.json"
        done = self.run_cli("run", bench, "--solver", solver, "--order", str(order), "--json", str(out), *extra, **kw)
        data = json.loads(out.read_text()) if out.exists() else None
        out.unlink(missing_ok=True)
        return done, data

    def case(self, data, name):
        return next(c for c in data["cases"] if c["case"] == name)


class ConvergenceOde(ConvergenceCli):
    def test_a_fourth_order_method_passes_its_claim_on_all_four_problems(self):
        report = self.dir / "r.md"
        done, data = self.conv("convergence-ode", ODE_RK4, 4, "--report", str(report))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual([c["case"] for c in data["cases"]], ["decay", "oscillator", "nonlinear", "timedep"])
        for case in data["cases"]:
            self.assertAlmostEqual(case["errors"]["observed_order"], 4.0, delta=0.15, msg=case["case"])
            self.assertEqual(case["errors"]["required_order"], 3.75)
        self.assertEqual(data["convergence"], {"order": 4.0, "levels": 5, "base": 16})
        text = report.read_text()
        self.assertIn("Expected order 4, 5 resolutions starting at 16, required observed order >= 3.75", text)
        self.assertEqual(data["tolerance_used"], 0.25)
        self.assertIs(data["relaxed"], False)

    def test_the_same_method_does_not_pass_a_higher_claim_and_the_reason_is_shown(self):
        report = self.dir / "r.md"
        done, data = self.conv("convergence-ode", ODE_RK4, 5, "--report", str(report))
        self.assertEqual(done.returncode, 1)
        self.assertTrue(all(not c["passed"] for c in data["cases"]))
        self.assertIn("below the required 4.750", report.read_text())

    def test_first_order_euler_passes_one_and_fails_two(self):
        self.assertEqual(self.conv("convergence-ode", ODE_EULER, 1)[0].returncode, 0)
        done, data = self.conv("convergence-ode", ODE_EULER, 2)
        self.assertEqual(done.returncode, 1)
        self.assertAlmostEqual(data["cases"][0]["errors"]["observed_order"], 1.0, delta=0.15)

    def test_a_larger_margin_is_allowed_but_marked_relaxed(self):
        done, data = self.conv("convergence-ode", ODE_EULER, 2, "--tol", "1.1")           # required order 0.9
        self.assertEqual(done.returncode, 0)
        self.assertIs(data["relaxed"], True)
        self.assertEqual(data["tolerance_default"], 0.25)

    def test_the_stale_time_bug_fails_on_the_time_dependent_problem_only(self):
        done, data = self.conv("convergence-ode", ODE_RK4_STALE_TIME, 4)
        self.assertEqual(done.returncode, 1)
        self.assertEqual({c["case"]: c["passed"] for c in data["cases"]},
                         {"decay": True, "oscillator": True, "nonlinear": True, "timedep": False})
        self.assertLess(self.case(data, "timedep")["errors"]["observed_order"], 1.5)

    def test_numpy_arrays_are_accepted(self):
        self.assertEqual(self.conv("convergence-ode", ODE_NUMPY, 4)[0].returncode, 0)

    def test_an_integrator_that_overwrites_its_input_is_caught_by_repeat(self):
        """Without --repeat the first call on each problem is correct; the second call starts from the mutated state."""
        done, data = self.conv("convergence-ode", ODE_MUTATES_INPUT, 1, "--repeat", "1")
        self.assertEqual(done.returncode, 0, done.stdout)
        done, data = self.conv("convergence-ode", ODE_MUTATES_INPUT, 1, "--repeat", "2", "--no-evidence")
        self.assertEqual(done.returncode, 1)
        self.assertIn("not reproducible", data["cases"][0]["reason"])

    def test_unseeded_noise_is_caught_by_repeat_and_otherwise_looks_like_noise_in_the_orders(self):
        done, data = self.conv("convergence-ode", ODE_NOISY, 4, "--repeat", "2")
        self.assertEqual(done.returncode, 1)
        self.assertTrue(any("not reproducible" in c.get("reason", "") for c in data["cases"]))

    def test_the_largest_repeat_difference_over_all_levels_is_reported(self):
        done, data = self.conv("convergence-ode", ODE_SPREAD_BY_LEVEL, 4, "--repeat", "2", "--repeat-tol", "1e-9", "--no-evidence")
        self.assertEqual(done.returncode, 0, done.stdout)
        spreads = [c["repeat_max_difference"] for c in data["cases"]]
        # 256 * 1e-14 at the finest level, divided by 1 + |value| (between 1.1 and 3.7): at least 6e-13. The smallest level
        # (16 * 1e-14) could never exceed 1.6e-13, so reporting the minimum instead of the maximum would fail this.
        self.assertTrue(all(6e-13 < s < 2.6e-12 for s in spreads), spreads)

    def test_deterministic_integrator_passes_with_repeat(self):
        done, data = self.conv("convergence-ode", ODE_RK4, 4, "--repeat", "2")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(data["repeat"], {"calls": 2, "tolerance": 0.0})

    def test_wrong_answers_are_named_per_problem(self):
        for source, text in ((ODE_WRONG_SIZE, "list of 1 number"), (ODE_NAN, "NaN or Inf"), (ODE_RAISES, "step size too small")):
            done, data = self.conv("convergence-ode", source, 2, "--no-evidence")
            self.assertEqual(done.returncode, 1, source)
            self.assertTrue(any(text in c.get("reason", "") for c in data["cases"]), (source, data["cases"][0]))
        done, data = self.conv("convergence-ode", ODE_WRONG_SIZE, 2, "--no-evidence")
        self.assertFalse(data["cases"][0]["reason"].startswith("solver raised"))      # the answer is rejected, nothing crashed

    def test_a_high_order_method_at_a_fine_base_has_too_few_resolved_levels_and_is_told_what_to_do(self):
        done, data = self.conv("convergence-ode", ODE_RK4, 4, "--steps", "128", "--no-evidence")
        self.assertEqual(done.returncode, 1)
        reason = data["cases"][0]["detail"] + data["cases"][0].get("reason", "")
        self.assertIn("above the roundoff floor", reason)
        self.assertIn("--steps 4", reason)
        done, data = self.conv("convergence-ode", ODE_RK4, 4, "--steps", "4", "--no-evidence")       # a coarse base works
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_steps_and_levels_are_honoured(self):
        done, data = self.conv("convergence-ode", ODE_RK4, 4, "--steps", "8", "--levels", "4", "--no-evidence")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(data["convergence"], {"order": 4.0, "levels": 4, "base": 8})

    def test_argument_errors_exit_two(self):
        solver = self.solver(ODE_RK4).replace(":solve", ":integrate")
        for extra in ([], ["--order", "0"], ["--order", "13"], ["--order", "nan"], ["--order", "-2"],
                      ["--order", "4", "--steps", "1"], ["--order", "4", "--levels", "2"], ["--order", "4", "--levels", "9"],
                      ["--order", "4", "--tol", "0.01"], ["--order", "4", "--tol", "0"]):
            done = self.run_cli("run", "convergence-ode", "--solver", solver, *extra)
            self.assertEqual(done.returncode, 2, extra)
        self.assertIn("need --order", self.run_cli("run", "convergence-ode", "--solver", solver).stderr)
        self.assertIn("finer than", self.run_cli("run", "convergence-ode", "--solver", solver, "--order", "4",
                                                 "--tol", "0.01").stderr)

    def test_the_convergence_parameters_are_refused_for_the_other_benchmarks(self):
        solver = self.solver(KEPLER_GOOD)
        for extra in (["--order", "2"], ["--steps", "8"], ["--levels", "4"]):
            done = self.run_cli("run", "kepler", "--solver", solver, *extra)
            self.assertEqual(done.returncode, 2, extra)
            self.assertIn("convergence benchmarks only", done.stderr)

    def test_evidence_records_the_required_order_and_the_number_of_levels(self):
        self.conv("convergence-ode", ODE_RK4, 4, "--steps", "8", "--levels", "4")
        (record,) = ve.read_log(self.dir / ".verification" / "log.jsonl")[0]
        tolerance = record["tolerance"]
        self.assertEqual((tolerance["order_min"], tolerance["levels_min"]), (3.75, 4))
        self.assertNotIn("tol", tolerance)                                  # the margin is inside order_min
        self.conv("convergence-ode", ODE_RK4, 4, "--evidence-dir", str(self.dir / "default-levels"))
        (second,) = ve.read_log(self.dir / "default-levels" / "log.jsonl")[0]
        self.assertEqual(second["tolerance"]["levels_min"], 5)                # --levels omitted: the default of 5

    def test_lowering_the_claimed_order_after_a_failure_is_withheld(self):
        """Claiming 4 for an Euler solver fails; claiming 1 for the same solver must not simply pass."""
        self.assertEqual(self.conv("convergence-ode", ODE_EULER, 4)[0].returncode, 1)
        self.assertEqual(self.conv("convergence-ode", ODE_EULER, 1)[0].returncode, 3)            # order_min 3.75 -> 0.75
        self.assertEqual(self.conv("convergence-ode", ODE_EULER, 1)[0].returncode, 3)            # rerunning does not release it
        log = self.dir / ".verification" / "log.jsonl"
        previous = next(r for r in reversed(ve.read_log(log)[0]) if r.get("exit_status") != 3 and r.get("passed") is False)
        new_tol = dict(previous["tolerance"])
        new_tol["order_min"] = 0.75
        reason = "approved relaxation: the scheme is first order by design"
        (log.parent / "tolerance-approvals.json").write_text(json.dumps({
            "schema": ve.APPROVAL_SCHEMA, "approvals": [{
                "key": previous["key"], "prev": previous["_line"], "old_tolerance": previous["tolerance"],
                "new_tolerance": new_tol, "reason": reason}]}))
        done, _ = self.conv("convergence-ode", ODE_EULER, 1)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_fewer_levels_or_a_wider_margin_after_a_failure_are_withheld(self):
        self.assertEqual(self.conv("convergence-ode", ODE_EULER, 2)[0].returncode, 1)
        self.assertEqual(self.conv("convergence-ode", ODE_EULER, 2, "--levels", "4")[0].returncode, 3)
        self.assertEqual(self.conv("convergence-ode", ODE_EULER, 2, "--tol", "1.1")[0].returncode, 3)

    def test_a_higher_claim_with_a_wider_margin_is_not_a_loosening(self):
        """Order 3 with margin 1.0 requires 2.0, which is stricter than the earlier order 2 with margin 0.25 (1.75)."""
        self.assertEqual(self.conv("convergence-ode", ODE_EULER, 2)[0].returncode, 1)        # fails: requires 1.75
        done, data = self.conv("convergence-ode", ODE_EULER, 3, "--tol", "1.0")              # requires 2.0, euler is 1.0
        self.assertEqual(done.returncode, 1)                                                 # a failure again, not withheld
        self.assertNotIn("withheld", data["evidence"]["flags"])


class ConvergenceBvp(ConvergenceCli):
    def test_second_order_central_differences_pass_in_both_norms(self):
        done, data = self.conv("convergence-bvp", BVP_CENTRAL, 2, entry="solve")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual([c["case"] for c in data["cases"]], ["poisson-sine", "poisson-poly"])
        for case in data["cases"]:
            self.assertAlmostEqual(case["errors"]["observed_order"], 2.0, delta=0.15)
            self.assertIn("max-norm", case["detail"])
            self.assertIn("L2-norm", case["detail"])
        self.assertEqual(data["convergence"], {"order": 2.0, "levels": 5, "base": 8})

    def test_a_source_evaluated_half_a_cell_off_is_first_order_and_fails_the_second_order_claim(self):
        done, data = self.conv("convergence-bvp", BVP_SHIFTED_SOURCE, 2, entry="solve_shifted")
        self.assertEqual(done.returncode, 1)
        self.assertTrue(all(not c["passed"] for c in data["cases"]))
        self.assertEqual(self.conv("convergence-bvp", BVP_SHIFTED_SOURCE, 1, "--no-evidence", entry="solve_shifted")[0].returncode, 0)

    def test_a_wrong_boundary_value_is_an_error_not_ignored(self):
        done, data = self.conv("convergence-bvp", BVP_BAD_BOUNDARY, 2, "--no-evidence", entry="solve")
        self.assertEqual(done.returncode, 1)
        self.assertGreater(data["cases"][0]["errors"]["finest_error_max-norm"], 0.29)

    def test_a_wrong_number_of_nodal_values_is_named(self):
        done, data = self.conv("convergence-bvp", BVP_SHORT, 2, "--no-evidence", entry="solve")
        self.assertEqual(done.returncode, 1)
        self.assertIn("n + 1 = 9 nodal values", data["cases"][0]["reason"])

    def test_steps_default_to_eight_for_the_bvp(self):
        done, data = self.conv("convergence-bvp", BVP_CENTRAL, 2, "--steps", "4", "--levels", "3", "--no-evidence", entry="solve")
        self.assertEqual((done.returncode, data["convergence"]["base"], data["convergence"]["levels"]), (0, 4, 3))


class StaleBytecode(Harness):
    def test_a_same_sized_edit_with_the_same_mtime_runs_the_new_code(self):
        """Regression: Python validates a cached .pyc by mtime (seconds) and size, so the OLD solver ran while the evidence
        was bound to the NEW file's hash."""
        good = KEPLER_GOOD.replace("    return E", "    return E + OFFSET").replace("def solve", "OFFSET = 0.0\n\n\ndef solve", 1)
        bad = good.replace("OFFSET = 0.0", "OFFSET = 9.0")
        self.assertEqual(len(good), len(bad))
        target = Path(self.solver(good).rsplit(":", 1)[0])
        # Run Python the way a user does: with bytecode writing enabled (the harness's -B would hide the problem).
        env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}

        def run():
            return subprocess.run([sys.executable, str(SCRIPT), "run", "kepler", "--solver", "%s:solve" % target,
                                   "--no-evidence"], capture_output=True, text=True, env=env, cwd=self.dir)
        self.assertEqual(run().returncode, 0)
        stamp = target.stat()
        target.write_text(bad)
        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assertEqual(run().returncode, 1)


class KeplerCriteria(unittest.TestCase):
    """The residual and the distance to the reference root are different tests: for an error d in E they differ by
    the factor f'(E) = 1 - e cos E, which is 1 - e near E = 0 and 1 + e near E = pi. Both must hold."""

    def case(self, m, e):
        return {"M": m, "e": e}

    def test_error_invisible_to_the_residual_but_seen_in_E(self):
        e, m = 0.99, 1e-8                        # E ~ 0: f' ~ 0.01, so an error of 5e-12 gives a residual ~ 5e-14
        root = car.kepler_reference(m, e)
        passed, errors, _ = car.kepler_check(self.case(m, e), root + 5e-12, 1e-12)
        self.assertLess(errors["residual"], 1e-12)
        self.assertGreater(errors["abs_error_vs_reference"], 1e-12)
        self.assertFalse(passed)

    def test_error_small_in_E_but_seen_by_the_residual(self):
        e, m = 0.99, math.pi                     # E = pi: f' = 1 + e = 1.99, so an error of 7e-13 gives a residual 1.4e-12
        root = car.kepler_reference(m, e)
        passed, errors, _ = car.kepler_check(self.case(m, e), root + 7e-13, 1e-12)
        self.assertLess(errors["abs_error_vs_reference"], 1e-12)
        self.assertGreater(errors["residual"], 1e-12)
        self.assertFalse(passed)

    def test_exact_root_and_shifted_root_pass(self):
        for m, e in ((0.5, 0.3), (6.0, 0.9), (-1.0, 0.7), (100.0, 0.0167)):
            root = car.kepler_reference(m, e)
            for answer in (root, root - car.TWO_PI, root + car.TWO_PI):
                self.assertTrue(car.kepler_check(self.case(m, e), answer, 1e-12)[0], (m, e, answer))


class LaneEmdenCli(Harness):
    def test_tolerance_is_required(self):
        done = self.run_cli("run", "lane-emden", "--solver", self.solver(LANE_GOOD))
        self.assertEqual(done.returncode, 2)
        self.assertIn("needs --tol", done.stderr)

    def test_correct_rk4_passes_at_a_stated_tolerance_and_the_error_is_reported(self):
        done, data = self.run_bench("lane-emden", LANE_GOOD, "--tol", "1e-4")
        self.assertEqual(done.returncode, 0, done.stdout)
        worst = max(max(c["errors"].values()) for c in data["cases"])
        self.assertLess(worst, 1e-5)                                         # measured error of this solver
        self.assertIsNone(data["relaxed"])

    def test_same_solver_fails_a_tolerance_it_cannot_meet(self):
        done, _ = self.run_bench("lane-emden", LANE_GOOD, "--tol", "1e-8")
        self.assertEqual(done.returncode, 1)

    def test_wrong_solvers_fail(self):
        for label, source in {"explicit Euler": LANE_EULER, "omega without xi squared": LANE_OMEGA_UNSQUARED,
                              "missing key": LANE_MISSING_KEY}.items():
            done, data = self.run_bench("lane-emden", source, "--tol", "1e-4")
            self.assertEqual(done.returncode, 1, label)
            self.assertFalse(data["passed"], label)
        _, data = self.run_bench("lane-emden", LANE_MISSING_KEY, "--tol", "1e-4")
        self.assertTrue(all("lacks" in c["reason"] and "omega_n" in c["reason"] for c in data["cases"]))

    def test_tolerance_below_what_the_reference_resolves_is_refused(self):
        done = self.run_cli("run", "lane-emden", "--solver", self.solver(LANE_GOOD), "--tol", "1e-12")
        self.assertEqual(done.returncode, 2)
        self.assertIn("finer than this benchmark's reference can resolve", done.stderr)


class SodCli(Harness):
    def test_exact_solution_passes_at_a_very_tight_tolerance(self):
        done, data = self.run_bench("sod", SOD_EXACT_COPY, "--tol", "1e-9", "--points", "101")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertLess(max(data["cases"][0]["errors"].values()), 1e-12)

    def test_lax_friedrichs_error_is_measured_and_judged_against_the_stated_tolerance(self):
        """A first-order scheme has a real discretisation error; the checker must report it, pass it at a tolerance
        that states what is acceptable and fail it at a tighter one (no silent default)."""
        done, data = self.run_bench("sod", SOD_LAX_FRIEDRICHS, "--tol", "0.1")
        self.assertEqual(done.returncode, 0, done.stdout)
        errors = data["cases"][0]["errors"]
        self.assertTrue(all(1e-3 < v < 0.1 for v in errors.values()), errors)   # a real, nonzero numerical error
        self.assertEqual(self.run_bench("sod", SOD_LAX_FRIEDRICHS, "--tol", "1e-3")[0].returncode, 1)

    def test_mirrored_and_malformed_answers_fail(self):
        self.assertEqual(self.run_bench("sod", SOD_MIRRORED, "--tol", "0.1")[0].returncode, 1)
        for source in (SOD_SHORT, SOD_NOT_DICT):
            done, data = self.run_bench("sod", source, "--tol", "0.1")
            self.assertEqual(done.returncode, 1)
            self.assertIn("reason", data["cases"][0])

    def perturbed(self, field_expr):
        return SOD_EXACT_COPY.replace('"density": s["density"], "velocity": s["velocity"], "pressure": s["pressure"]',
                                      field_expr)

    def test_each_field_is_judged_on_its_own(self):
        wrong_density = '"density": [1.5 * v for v in s["density"]], "velocity": s["velocity"], "pressure": s["pressure"]'
        wrong_velocity = '"density": s["density"], "velocity": [1.5 * v for v in s["velocity"]], "pressure": s["pressure"]'
        wrong_pressure = '"density": s["density"], "velocity": s["velocity"], "pressure": [1.5 * v for v in s["pressure"]]'
        for label, expr in (("density", wrong_density), ("velocity", wrong_velocity), ("pressure", wrong_pressure)):
            done, data = self.run_bench("sod", self.perturbed(expr), "--tol", "0.1")
            self.assertEqual(done.returncode, 1, label)
            errors = data["cases"][0]["errors"]
            self.assertGreater(errors["rel_L1_" + label], 0.4, label)
            self.assertTrue(all(v < 1e-9 for k, v in errors.items() if k != "rel_L1_" + label), (label, errors))

    def test_the_error_is_a_relative_L1_norm(self):
        """Scaling the exact density by 1 + d gives int|d rho| / int|rho| = d exactly, whatever the profile."""
        scaled = '"density": [1.01 * v for v in s["density"]], "velocity": s["velocity"], "pressure": s["pressure"]'
        _, data = self.run_bench("sod", self.perturbed(scaled), "--tol", "0.1")
        self.assertAlmostEqual(data["cases"][0]["errors"]["rel_L1_density"], 0.01, delta=1e-9)

    def test_malformed_answers_are_named(self):
        cases = {
            "length": ('"density": s["density"][:-1], "velocity": s["velocity"], "pressure": s["pressure"]', "values for"),
            "domain": ('"density": s["density"], "velocity": s["velocity"], "pressure": s["pressure"]', "Sod domain"),
            "order": ('"density": s["density"], "velocity": s["velocity"], "pressure": s["pressure"]', "increasing"),
        }
        for label, (expr, text) in cases.items():
            source = self.perturbed(expr)
            if label == "domain":
                source = source.replace('"x": s["x"]', '"x": [1.5 * v for v in s["x"]]')
            if label == "order":
                source = source.replace('"x": s["x"]', '"x": s["x"][::-1]')
            done, data = self.run_bench("sod", source, "--tol", "0.1", "--points", "11")
            self.assertEqual(done.returncode, 1, label)
            self.assertIn(text, data["cases"][0]["reason"], label)

    def test_tolerance_is_required(self):
        self.assertEqual(self.run_cli("run", "sod", "--solver", self.solver(SOD_EXACT_COPY)).returncode, 2)

    def test_too_few_points_exit_two(self):
        done = self.run_cli("run", "sod", "--solver", self.solver(SOD_EXACT_COPY), "--tol", "0.1", "--points", "2")
        self.assertEqual(done.returncode, 2)


@unittest.skipUnless(HAVE_SCIPY, "scipy not installed")
class RobertsonCli(Harness):
    def test_correct_stiff_solver_passes_and_errors_are_reported(self):
        done, data = self.run_bench("robertson", ROBERTSON_RADAU, "--tol", "1e-6")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(len(data["cases"]), len(car.ROBERTSON))
        self.assertLess(max(max(c["errors"].values()) for c in data["cases"]), 1e-6)

    def test_wrong_rate_constant_fails(self):
        done, data = self.run_bench("robertson", ROBERTSON_WRONG_RATE, "--tol", "1e-3")
        self.assertEqual(done.returncode, 1)
        self.assertFalse(data["passed"])

    def test_crude_backward_euler_fails_a_tolerance_it_cannot_meet(self):
        self.assertEqual(self.run_bench("robertson", ROBERTSON_BACKWARD_EULER, "--tol", "1e-4")[0].returncode, 1)

    def test_mass_leak_is_caught_by_the_invariant(self):
        done, data = self.run_bench("robertson", ROBERTSON_MASS_LEAK, "--tol", "1e-6")
        self.assertEqual(done.returncode, 1)
        self.assertGreater(max(c["errors"]["mass_drift"] for c in data["cases"]), 9e-6)

    def test_wrong_number_of_components_is_named(self):
        _, data = self.run_bench("robertson", "def solve(t):\n    return [1.0, 0.0]\n", "--tol", "1e-6")
        self.assertTrue(all("expected 3" in c["reason"] for c in data["cases"]))

    def test_tolerance_rules(self):
        self.assertEqual(self.run_cli("run", "robertson", "--solver", self.solver(ROBERTSON_RADAU)).returncode, 2)
        self.assertEqual(self.run_cli("run", "robertson", "--solver", self.solver(ROBERTSON_RADAU),
                                      "--tol", "1e-10").returncode, 2)


class UsageAndCompare(Harness):
    def test_no_command_and_unknown_benchmark_exit_two(self):
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertEqual(self.run_cli("run", "nonsense", "--solver", "x.py:f").returncode, 2)

    def test_unloadable_solvers_exit_two_without_traceback(self):
        crash = self.solver("raise SystemError('at import')\ndef solve(M, e):\n    return 0.0\n", "crash")
        cases = [str(self.dir / "missing.py") + ":solve", "nocolon", self.solver("x = 1\n", "nofunc"),
                 "no_such_module_anywhere:solve", crash]
        for target in cases:
            done = self.run_cli("run", "kepler", "--solver", target)
            self.assertEqual(done.returncode, 2, target)
            self.assertNotIn("Traceback", done.stderr, target)

    def test_bad_tolerances_exit_two(self):
        for tol in ("0", "-1", "nan", "inf"):
            done = self.run_cli("run", "kepler", "--solver", self.solver(KEPLER_GOOD), "--tol", tol)
            self.assertEqual(done.returncode, 2, tol)

    def test_list_describes_every_benchmark_with_its_rules(self):
        done = self.run_cli("list")
        self.assertEqual(done.returncode, 0)
        described = {b["name"]: b for b in json.loads(done.stdout)}
        self.assertEqual(set(described), {"kepler", "lane-emden", "sod", "robertson", "convergence-ode", "convergence-bvp"})
        self.assertIs(described["kepler"]["tolerance_required"], False)
        for name in ("lane-emden", "sod", "robertson"):
            self.assertIs(described[name]["tolerance_required"], True)
            self.assertIsNone(described[name]["default_tolerance"])
            self.assertEqual(described[name]["kind"], "single")
        for name in ("convergence-ode", "convergence-bvp"):                       # a margin with a default, and an order to state
            self.assertEqual((described[name]["kind"], described[name]["default_tolerance"],
                              described[name]["smallest_tolerance_accepted"]), ("convergence", 0.25, 0.05))
            self.assertIn("--order", described[name]["parameters"])
        for entry in described.values():
            self.assertTrue(entry["sources"] and entry["reference_uncertainty"] and entry["solver_contract"])

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text)
        return str(path)

    def compare(self, ref, test, *extra):
        return self.run_cli("compare", "--ref", self.write("ref.txt", ref), "--test", self.write("test.txt", test), *extra,
                            "--no-evidence")             # these tests are about the comparison, not the evidence log

    def test_compare_passes_and_fails_on_the_stated_tolerances(self):
        self.assertEqual(self.compare("1.0 2.0 3.0\n", "1.0 2.0 3.0\n", "--rtol", "1e-12", "--atol", "0").returncode, 0)
        self.assertEqual(self.compare("1.0 2.0 3.0\n", "1.0 2.0 3.001\n", "--rtol", "1e-6", "--atol", "0").returncode, 1)
        self.assertEqual(self.compare("1.0 2.0 3.0\n", "1.0 2.0 3.001\n", "--rtol", "1e-2", "--atol", "0").returncode, 0)

    def test_compare_uses_atol_for_values_near_zero(self):
        self.assertEqual(self.compare("0.0 1.0\n", "1e-10 1.0\n", "--rtol", "1e-12", "--atol", "1e-9").returncode, 0)
        self.assertEqual(self.compare("0.0 1.0\n", "1e-10 1.0\n", "--rtol", "1e-12", "--atol", "1e-11").returncode, 1)
        self.assertEqual(self.compare("0.0\n", "1e-300\n", "--rtol", "1e-3", "--atol", "0").returncode, 1)

    def test_compare_rejects_length_nan_empty_and_bad_numbers(self):
        self.assertEqual(self.compare("1 2 3\n", "1 2\n", "--rtol", "1", "--atol", "1").returncode, 1)
        self.assertEqual(self.compare("1 2 3\n", "1 nan 3\n", "--rtol", "1", "--atol", "1").returncode, 1)
        self.assertEqual(self.compare("1 inf\n", "1 inf\n", "--rtol", "1", "--atol", "1").returncode, 1)
        self.assertEqual(self.compare("# nothing\n", "\n", "--rtol", "1", "--atol", "1").returncode, 1)
        done = self.compare("1 two 3\n", "1 2 3\n", "--rtol", "1", "--atol", "1")
        self.assertEqual(done.returncode, 2)
        self.assertNotIn("Traceback", done.stderr)

    def test_compare_requires_both_tolerances_and_accepts_fortran_exponents(self):
        self.assertEqual(self.compare("1 2\n", "1 2\n", "--rtol", "1e-9").returncode, 2)        # --atol missing
        self.assertEqual(self.compare("1 2\n", "1 2\n", "--rtol", "0", "--atol", "0").returncode, 2)
        self.assertEqual(self.compare("1.0D+00 2.5d-01\n", "1.0 0.25\n", "--rtol", "1e-12", "--atol", "0").returncode, 0)

    def test_compare_missing_file_exits_two(self):
        done = self.run_cli("compare", "--ref", str(self.dir / "no.txt"), "--test", str(self.dir / "no2.txt"),
                            "--rtol", "1", "--atol", "1")
        self.assertEqual(done.returncode, 2)


class InProcess(unittest.TestCase):
    def test_two_solver_files_are_kept_apart(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp, "a.py"), Path(tmp, "b.py")
            a.write_text("def solve(M, e):\n    return 1.0\n")
            b.write_text("def solve(M, e):\n    return 2.0\n")
            self.assertEqual(car.load_callable("%s:solve" % a)(0, 0), 1.0)
            self.assertEqual(car.load_callable("%s:solve" % b)(0, 0), 2.0)
            self.assertEqual(car.load_callable("%s:solve" % a)(0, 0), 1.0)

    def test_two_solver_files_keep_separate_module_identities(self):
        """Under one shared module name the first file's late lookups (typing.get_type_hints, dataclasses) would
        resolve in the second file and fail on code that is correct."""
        first = ("from __future__ import annotations\nimport typing\nfrom dataclasses import dataclass\n"
                 "class Unit:\n    pass\n@dataclass\nclass P:\n    x: Unit\n"
                 "def solve(M, e):\n    typing.get_type_hints(P)\n    return 1.0\n")
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp, "a.py"), Path(tmp, "b.py")
            a.write_text(first)
            b.write_text("def solve(M, e):\n    return 2.0\n")
            solve_a = car.load_callable("%s:solve" % a)
            car.load_callable("%s:solve" % b)             # loaded after a; must not replace a's module
            self.assertEqual(solve_a(0, 0), 1.0)

    def test_timeout_restores_the_previous_alarm_handler(self):
        import signal
        before = signal.getsignal(signal.SIGALRM)
        car.call_with_timeout(lambda: 1, (), 5)
        self.assertEqual(signal.getsignal(signal.SIGALRM), before)

    def test_fold_and_circular_error(self):
        self.assertAlmostEqual(abs(car._fold(3 * math.pi)), math.pi, delta=1e-12)    # +-pi are the same angle
        self.assertAlmostEqual(car._fold(3 * math.pi + 0.1), -math.pi + 0.1, delta=1e-12)
        self.assertAlmostEqual(car._fold(-2 * math.pi - 0.1), -0.1, delta=1e-12)


if __name__ == "__main__":
    unittest.main()
