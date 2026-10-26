"""Tests for scripts/convergence.py (exact solutions and the order-of-convergence estimate).

Run (from the plugin root):  python3 -B -m unittest discover -s tests -v

 1. The exact solutions are verified independently: the ODE ones against scipy's DOP853 at rtol 1e-13, the BVP ones by
    differentiating the exact solution twice with mpmath at 30 digits and checking -u'' = f and u(0) = u(1) = 0.
 2. The estimate is exercised on synthetic error sequences (known order, boundary cases of the margin, the roundoff floor).
 3. Real methods of known order (Euler 1, midpoint 2, Heun 2, RK4 4; second-order central differences) must be measured
    within 0.15 of their order; a classic bug (the time argument not advanced between RK4 stages) must collapse the order
    on the time-dependent problem and only there.
"""

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import convergence as cv  # noqa: E402

try:
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
# Reference methods (independent implementations, used as "user solvers")
# ----------------------------------------------------------------------------------------------------------------

def _add(y, k, h):
    return [a + h * b for a, b in zip(y, k)]


def euler(f, y0, t0, t1, n):
    h, y, t = (t1 - t0) / n, list(y0), t0
    for _ in range(n):
        y, t = _add(y, f(t, y), h), t + h
    return y


def midpoint(f, y0, t0, t1, n):
    h, y, t = (t1 - t0) / n, list(y0), t0
    for _ in range(n):
        k1 = f(t, y)
        y, t = _add(y, f(t + h / 2, _add(y, k1, h / 2)), h), t + h
    return y


def heun(f, y0, t0, t1, n):
    h, y, t = (t1 - t0) / n, list(y0), t0
    for _ in range(n):
        k1 = f(t, y)
        k2 = f(t + h, _add(y, k1, h))
        y, t = [a + h / 2 * (p + q) for a, p, q in zip(y, k1, k2)], t + h
    return y


def rk4(f, y0, t0, t1, n, advance_time=True):
    h, y, t = (t1 - t0) / n, list(y0), t0
    for _ in range(n):
        half = h / 2 if advance_time else 0.0                      # the bug: every stage evaluated at the old time
        full = h if advance_time else 0.0
        k1 = f(t, y)
        k2 = f(t + half, _add(y, k1, h / 2))
        k3 = f(t + half, _add(y, k2, h / 2))
        k4 = f(t + full, _add(y, k3, h))
        y, t = [a + h / 6 * (p + 2 * q + 2 * r + s) for a, p, q, r, s in zip(y, k1, k2, k3, k4)], t + h
    return y


def rk4_stale_time(f, y0, t0, t1, n):
    return rk4(f, y0, t0, t1, n, advance_time=False)


def central_difference(n, f, source_shift=0.0):
    """-u'' = f on (0,1), u(0) = u(1) = 0: second-order central differences, Thomas algorithm.
    source_shift = 0.5 is the bug: the source is evaluated half a cell away from the node (first order)."""
    h = 1.0 / n
    m = n - 1
    diag, rhs = [2.0] * m, [h * h * f((i + 1 + source_shift) * h) for i in range(m)]
    for i in range(1, m):                                          # forward elimination (sub/super diagonals are -1)
        w = -1.0 / diag[i - 1]
        diag[i] += w
        rhs[i] -= w * rhs[i - 1]
    u = [0.0] * m
    u[-1] = rhs[-1] / diag[-1]
    for i in range(m - 2, -1, -1):
        u[i] = (rhs[i] + u[i + 1]) / diag[i]
    return [0.0] + u + [0.0]


def central_difference_shifted_source(n, f):
    return central_difference(n, f, source_shift=0.5)


def ode_orders(method, problem, base=16, count=5):
    answers = [method(*call) for call in cv.ode_calls(problem, base, count)]
    errors = cv.ode_errors(problem, answers)
    return errors, cv.observed_orders(errors)


def bvp_orders(method, problem, base=8, count=5):
    calls = cv.bvp_calls(problem, base, count)
    answers = [method(*call) for call in calls]
    errors = cv.bvp_errors(problem, answers, [c[0] for c in calls])
    return {norm: (e, cv.observed_orders(e)) for norm, e in errors.items()}


# ----------------------------------------------------------------------------------------------------------------

class ExactSolutions(unittest.TestCase):
    @unittest.skipUnless(HAVE_SCIPY, "scipy not installed")
    def test_ode_exact_values_match_high_accuracy_integration(self):
        for name, spec in cv.ODE_PROBLEMS.items():
            sol = solve_ivp(lambda t, y: spec["f"](t, list(y)), (spec["t0"], spec["t1"]), spec["y0"], method="DOP853",
                            rtol=1e-13, atol=1e-15)
            for got, exact in zip(sol.y[:, -1], spec["exact"]):
                self.assertAlmostEqual(got, exact, delta=1e-11, msg=name)

    def test_ode_closed_forms(self):
        self.assertEqual(cv.ODE_PROBLEMS["nonlinear"]["exact"], [1.0 / (1.0 - 0.5)])
        self.assertEqual(cv.ODE_PROBLEMS["timedep"]["exact"], [math.exp(1.0 ** 2)])
        self.assertEqual(cv.ODE_PROBLEMS["decay"]["exact"], [math.exp(-2.0)])
        self.assertEqual(cv.ODE_PROBLEMS["oscillator"]["exact"], [math.cos(2.0), -math.sin(2.0)])

    @unittest.skipUnless(HAVE_MPMATH, "mpmath not installed")
    def test_bvp_exact_solutions_satisfy_the_equation_and_the_boundary_conditions(self):
        mpmath.mp.dps = 30
        for name, spec in cv.BVP_PROBLEMS.items():
            exact = spec["exact"]
            self.assertAlmostEqual(exact(0.0), 0.0, delta=1e-15, msg=name)
            self.assertAlmostEqual(exact(1.0), 0.0, delta=1e-15, msg=name)
            for x in (0.1, 0.25, 0.5, 0.77, 0.9):
                u_xx = mpmath.diff(lambda s: exact_mp(name, s), x, 2)
                self.assertAlmostEqual(float(-u_xx), spec["f"](x), delta=1e-12, msg=(name, x))


def exact_mp(name, x):
    """The exact solutions written with mpmath, independently of the lambdas under test."""
    if name == "poisson-sine":
        return mpmath.sin(mpmath.pi * x)
    return x ** 3 - x ** 4


class Estimate(unittest.TestCase):
    def sequence(self, order, base=16, count=5, constant=0.3):
        return [constant * (1.0 / n) ** order for n in cv.levels(base, count)]

    def test_known_order_is_recovered(self):
        for order in (1.0, 2.0, 3.0, 4.0):
            orders = cv.observed_orders(self.sequence(order))
            for value in orders:
                self.assertAlmostEqual(value, order, delta=1e-9)

    def test_passes_at_the_expected_order_and_fails_one_below(self):
        self.assertTrue(cv.assess(self.sequence(4.0), 4.0, 0.25)["passed"])
        low = cv.assess(self.sequence(3.0), 4.0, 0.25)
        self.assertFalse(low["passed"])
        self.assertIn("below the required 3.750", low["reason"])

    def test_the_margin_boundary(self):
        seq = self.sequence(3.75)
        self.assertTrue(cv.assess(seq, 4.0, 0.25 + 1e-9)["passed"])                  # observed 3.75 >= 4 - 0.25
        self.assertFalse(cv.assess(seq, 4.0, 0.25 - 1e-6)["passed"])
        self.assertFalse(cv.assess(self.sequence(3.5), 4.0, 0.25)["passed"])

    def test_super_convergence_is_not_a_failure(self):
        verdict = cv.assess(self.sequence(6.0, base=4), 4.0, 0.25)             # base 4: a sixth-order method hits the floor fast
        self.assertTrue(verdict["passed"], verdict)
        self.assertAlmostEqual(verdict["observed"], 6.0, delta=1e-9)

    def test_only_the_two_finest_pairs_are_judged(self):
        pre_asymptotic = [4e-3, 2e-3, 1e-3] + [1e-3 * 0.3 * 0.5 ** (4 * k) for k in range(1, 4)]   # order ~1 then 4
        verdict = cv.assess(pre_asymptotic, 4.0, 0.25)
        self.assertGreater(len(verdict["orders"]), 0)
        self.assertTrue(verdict["passed"], verdict)
        self.assertLess(verdict["orders"][0], 1.5)                                   # the coarse pair is reported but not judged

    def test_a_degrading_order_at_the_fine_end_fails(self):
        degrading = [1e-3, 6.25e-5, 3.9e-6, 3.5e-7, 3.2e-8]                           # 4, 4, 3.5, 3.4
        verdict = cv.assess(degrading, 4.0, 0.25)
        self.assertFalse(verdict["passed"])

    def test_levels_at_the_roundoff_floor_are_discarded_not_judged(self):
        # order 4 until the error reaches 1e-12, where noise would give a meaningless order; discarded, so still 3 levels ok
        errors = [1e-5, 6.25e-7, 3.9e-8, 2.4e-9, 1e-13, 3e-14, 2e-14]
        verdict = cv.assess(errors, 4.0, 0.25)
        self.assertEqual(verdict["resolved"], 4)
        self.assertTrue(verdict["passed"], verdict)

    def test_fewer_than_three_resolved_levels_is_a_failure_with_advice(self):
        verdict = cv.assess([1e-9, 6e-11, 4e-12, 2e-13, 1e-14], 4.0, 0.25)            # only 2 above 1e-11
        self.assertFalse(verdict["passed"])
        self.assertIn("only 2 of 5 levels are above the roundoff floor", verdict["reason"])
        self.assertIn("--steps 4", verdict["reason"])
        self.assertFalse(cv.assess([0.0, 0.0, 0.0], 2.0, 0.25)["passed"])               # an exact answer proves nothing

    def test_the_floor_scales_with_the_magnitude_of_the_exact_value(self):
        errors = [1e-8, 6.25e-10, 3.9e-11]
        self.assertEqual(cv.assess(errors, 4.0, 0.25, scale=1.0)["resolved"], 3)       # floor 1e-11
        self.assertEqual(cv.assess(errors, 4.0, 0.25, scale=1e3)["resolved"], 0)       # floor 1e-8: nothing is resolved
        self.assertEqual(cv.assess(errors, 4.0, 0.25, scale=1e-3)["floor"], 1e-11)     # a small scale does not lower the floor

    def test_non_monotone_error_fails(self):
        verdict = cv.assess([1e-4, 6e-6, 7e-6, 1e-7], 4.0, 0.25)
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["reason"], "the error does not fall with every refinement")

    def test_non_finite_and_negative_errors_fail_for_that_reason(self):
        for bad in ([1e-4, float("nan"), 1e-6], [1e-4, float("inf"), 1e-6], [1e-4, -1e-6, 1e-8]):
            verdict = cv.assess(bad, 2.0, 0.25)
            self.assertFalse(verdict["passed"], bad)
            self.assertIn("not a finite non-negative number", verdict["reason"], bad)

    def test_a_plateau_is_reported_as_no_decrease_not_as_a_low_order(self):
        verdict = cv.assess([1e-4, 1e-5, 1e-5, 1e-7], 2.0, 0.25)
        self.assertEqual(verdict["reason"], "the error does not fall with every refinement")

    def test_noise_that_rebounds_above_the_floor_after_the_floor_was_reached_is_ignored(self):
        # 1e-13 is at the floor: that level and every finer one are discarded, even the bump (4e-8) that is above it again
        verdict = cv.assess([1e-5, 6.25e-7, 3.9e-8, 1e-13, 4e-8], 4.0, 0.25)
        self.assertEqual(verdict["resolved"], 3)
        self.assertTrue(verdict["passed"], verdict)

    def test_both_of_the_two_finest_orders_must_meet_the_requirement(self):
        one_bad_pair = [1e-3, 6.25e-5, 3.9e-6, 4.9e-7, 3.06e-8]                       # orders 4.0, 4.0, 3.0, 4.0
        verdict = cv.assess(one_bad_pair, 4.0, 0.25)
        self.assertEqual([round(o, 1) for o in verdict["orders"]], [4.0, 4.0, 3.0, 4.0])
        self.assertFalse(verdict["passed"])
        self.assertAlmostEqual(verdict["observed"], 3.0, delta=0.05)                    # the worse of the two is reported
        bad_then_good = [1e-3, 6.25e-5, 3.9e-6, 4.9e-7, 4.9e-7 / 2 ** 3.0]               # ... and the order of the pair does not matter
        self.assertFalse(cv.assess(bad_then_good, 4.0, 0.25)["passed"])

    def test_an_observed_order_exactly_at_the_requirement_passes(self):
        halving = [1 / 16, 1 / 32, 1 / 64, 1 / 128]                                     # orders exactly 1.0
        self.assertEqual(cv.observed_orders(halving), [1.0, 1.0, 1.0])
        self.assertTrue(cv.assess(halving, 2.0, 1.0)["passed"])                         # required 1.0: >= passes
        self.assertFalse(cv.assess(halving, 2.0, 0.999)["passed"])

    def test_a_required_order_is_reported(self):
        verdict = cv.assess(self.sequence(2.0), 2.0, 0.25)
        self.assertEqual((verdict["expected"], verdict["required"]), (2.0, 1.75))
        self.assertAlmostEqual(verdict["observed"], 2.0, delta=1e-9)

    def test_levels(self):
        self.assertEqual(cv.levels(16, 5), [16, 32, 64, 128, 256])
        self.assertEqual(cv.levels(4, 3), [4, 8, 16])


class RealMethods(unittest.TestCase):
    def assert_order(self, method, problem, order, tol=0.15):
        errors, orders = ode_orders(method, problem)
        for value in orders[-2:]:
            self.assertAlmostEqual(value, order, delta=tol, msg=(method.__name__, problem, orders))
        self.assertTrue(cv.assess(errors, order, 0.25)["passed"], (method.__name__, problem, errors))

    def test_every_method_reaches_its_order_on_every_problem(self):
        for method, order in ((euler, 1.0), (midpoint, 2.0), (heun, 2.0), (rk4, 4.0)):
            for problem in cv.ODE_PROBLEMS:
                self.assert_order(method, problem, order)

    def test_a_method_is_not_credited_with_a_higher_order(self):
        for problem in cv.ODE_PROBLEMS:
            errors, _ = ode_orders(euler, problem)
            self.assertFalse(cv.assess(errors, 2.0, 0.25)["passed"], problem)
            errors, _ = ode_orders(midpoint, problem)
            self.assertFalse(cv.assess(errors, 4.0, 0.25)["passed"], problem)

    def test_the_stale_time_bug_collapses_the_order_on_the_time_dependent_problem_only(self):
        _, bad = ode_orders(rk4_stale_time, "timedep")
        self.assertLess(max(bad[-2:]), 1.5, bad)                                        # classic RK4 falls to first order
        for autonomous in ("decay", "oscillator", "nonlinear"):
            self.assert_order(rk4_stale_time, autonomous, 4.0)                          # invisible without t-dependence

    def test_central_differences_are_second_order_in_both_norms_on_both_problems(self):
        for problem in cv.BVP_PROBLEMS:
            for norm, (errors, orders) in bvp_orders(central_difference, problem).items():
                for value in orders[-2:]:
                    self.assertAlmostEqual(value, 2.0, delta=0.15, msg=(problem, norm, orders))
                self.assertTrue(cv.assess(errors, 2.0, 0.25)["passed"], (problem, norm))
                self.assertFalse(cv.assess(errors, 3.0, 0.25)["passed"], (problem, norm))

    def test_a_source_term_evaluated_half_a_cell_off_is_first_order(self):
        for problem in cv.BVP_PROBLEMS:
            for norm, (errors, orders) in bvp_orders(central_difference_shifted_source, problem).items():
                for value in orders[-2:]:
                    self.assertAlmostEqual(value, 1.0, delta=0.15, msg=(problem, norm, orders))
                self.assertFalse(cv.assess(errors, 2.0, 0.25)["passed"], (problem, norm))
                self.assertTrue(cv.assess(errors, 1.0, 0.25)["passed"], (problem, norm))

    def test_a_defect_that_heals_as_the_grid_is_refined_is_judged_by_its_asymptotic_order(self):
        """Documented behaviour, not a bug: orders 1.5, 1.8, 1.9, 2.0 pass at the expected order 2 because only the two
        finest levels are judged. A defect that only matters on coarse grids is not a convergence-order defect."""
        errors = [2.74e-2, 9.79e-3, 2.78e-3, 7.32e-4, 1.87e-4]
        self.assertTrue(cv.assess(errors, 2.0, 0.25)["passed"])


class AnswerValidation(unittest.TestCase):
    def test_ode_answers(self):
        self.assertEqual(cv.ode_vector(2.0, 1), [2.0])
        self.assertEqual(cv.ode_vector((1, 2), 2), [1.0, 2.0])
        for bad, size in (([1.0], 2), ([1.0, 2.0], 1), ("ab", 2), (None, 1), ([float("nan")], 1), ([float("inf")], 1),
                          ([True], 1), (["1"], 1), ({"y": 1.0}, 1)):
            with self.assertRaises(cv.ConvergenceFailure, msg=bad):
                cv.ode_vector(bad, size)

    def test_ode_numpy_answers(self):
        import numpy as np
        self.assertEqual(cv.ode_vector(np.array([1.0, 2.0]), 2), [1.0, 2.0])
        self.assertEqual(cv.ode_vector(np.float64(3.0), 1), [3.0])

    def test_ode_error_is_the_max_norm_over_components(self):
        errors = cv.ode_errors("oscillator", [[math.cos(2.0) + 0.5, -math.sin(2.0) - 0.25]])
        self.assertAlmostEqual(errors[0], 0.5, delta=1e-15)

    def test_bvp_answers(self):
        exact = [math.sin(math.pi * i / 4) for i in range(5)]
        errors = cv.bvp_errors("poisson-sine", [exact], [4])
        self.assertEqual((errors["max-norm"], errors["L2-norm"]), ([0.0], [0.0]))
        wrong = list(exact)
        wrong[2] += 0.4
        e = cv.bvp_errors("poisson-sine", [wrong], [4])
        self.assertAlmostEqual(e["max-norm"][0], 0.4, delta=1e-15)
        self.assertAlmostEqual(e["L2-norm"][0], math.sqrt(0.4 ** 2 / 4), delta=1e-15)          # sqrt(h * sum e^2), h = 1/4
        corner = list(exact)
        corner[0] = 0.3                                                          # a wrong boundary value must count
        self.assertAlmostEqual(cv.bvp_errors("poisson-sine", [corner], [4])["max-norm"][0], 0.3, delta=1e-15)
        corner[0], corner[4] = 0.0, -0.2
        self.assertAlmostEqual(cv.bvp_errors("poisson-sine", [corner], [4])["max-norm"][0], 0.2, delta=1e-15)
        for bad in ([0.0] * 4, [0.0] * 6, [0.0, 0.0, float("nan"), 0.0, 0.0], [0.0, True, 0.0, 0.0, 0.0], "abcde", None):
            with self.assertRaises(cv.ConvergenceFailure, msg=bad):
                cv.bvp_errors("poisson-sine", [bad], [4])

    def test_calls_carry_the_problem_data(self):
        calls = cv.ode_calls("decay", 16, 3)
        self.assertEqual([c[4] for c in calls], [16, 32, 64])
        self.assertEqual((calls[0][1], calls[0][2], calls[0][3]), ([1.0], 0.0, 1.0))
        self.assertEqual(calls[0][0](0.0, [3.0]), [-6.0])
        self.assertEqual(calls[0][1] is not cv.ODE_PROBLEMS["decay"]["y0"], True)             # a copy: the solver cannot corrupt it
        bvp = cv.bvp_calls("poisson-poly", 8, 2)
        self.assertEqual([c[0] for c in bvp], [8, 16])
        self.assertEqual(bvp[0][1](0.5), 12 * 0.25 - 3.0)


if __name__ == "__main__":
    unittest.main()
