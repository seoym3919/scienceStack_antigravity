"""Tests for the scienceStack scripts and reference benchmarks.

Run (from the plugin root):  python3 -B -m unittest discover -s tests -v

Reference values and sources:
- MMS forcing for u = exp(-t) sin(pi x), L[u] = u_t - alpha u_xx:
      L[u] = (alpha pi^2 - 1) exp(-t) sin(pi x)       (direct differentiation)
- Sod shock tube star region (gamma = 1.4): p* = 0.30313, u* = 0.92745
      (Toro, Riemann Solvers and Numerical Methods for Fluid Dynamics, 3rd ed., Table 4.1, Test 1).
- Lane-Emden n = 1: xi_1 = pi (exact solution sin(xi)/xi); n = 0: xi_1 = sqrt(6).
- Kepler / symplectic N-body: conserved energy, angular momentum (analytic invariants).
"""

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def run(script, *args, cwd=None):
    return subprocess.run([sys.executable, "-B", str(script), *args], capture_output=True, text=True,
                          cwd=cwd, timeout=300)


class AuditorTests(unittest.TestCase):
    AUDIT = SCRIPTS / "audit_numerical_ast.py"

    def audit(self, source, *flags):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "mod.py"
            f.write_text(source)
            res = run(self.AUDIT, str(f), "--json", *flags)
        return res.returncode, json.loads(res.stdout)

    def codes(self, source):
        return {i["code"] for i in self.audit(source)[1]}

    def test_attribute_inv_is_an_error(self):
        rc, issues = self.audit("import numpy as np\nx = np.linalg.inv(A) @ b\n")
        self.assertEqual(rc, 1)
        self.assertIn("BAN_MATRIX_INV", {i["code"] for i in issues})

    def test_from_import_and_alias_forms_are_errors(self):
        self.assertIn("BAN_MATRIX_INV", self.codes("from numpy.linalg import inv\nx = inv(A)\n"))
        self.assertIn("BAN_MATRIX_INV", self.codes("import scipy.linalg as la\nx = la.inv(A)\n"))
        self.assertIn("BAN_MATRIX_INV", self.codes("import torch\nx = torch.inverse(A)\n"))

    def test_solve_is_clean(self):
        rc, issues = self.audit("import numpy as np\nx = np.linalg.solve(A, b)\n")
        self.assertEqual((rc, issues), (0, []))

    def test_unrelated_inv_function_is_not_flagged(self):
        self.assertNotIn("BAN_MATRIX_INV", self.codes("def inv(x):\n    return 1 / x\ny = inv(2.0)\n"))

    def test_cancellation_patterns(self):
        codes = self.codes("import numpy as np\na = np.log(1 + x)\nb = np.exp(x) - 1\nc = 1 - np.cos(x)\n")
        self.assertEqual(codes, {"CANCELLATION_LOG1P", "CANCELLATION_EXPM1", "CANCELLATION_ONE_MINUS_COS"})

    def test_truncated_pi_and_mutable_default(self):
        codes = self.codes("import numpy as np\narea = 3.14159 * r**2\ndef f(x=np.zeros(3)):\n    return x\n")
        self.assertEqual(codes, {"TRUNCATED_PI", "MUTABLE_ARRAY_DEFAULT"})
        self.assertEqual(self.codes("import math\narea = math.pi * r**2\n"), set())

    def test_float32_warning_and_strict_mode(self):
        rc, issues = self.audit("import numpy as np\nx = np.float32(1.0)\n")
        self.assertEqual(rc, 0)                                  # warnings alone do not fail ...
        self.assertEqual([i["code"] for i in issues], ["PRECISION_FLOAT32"])
        rc, _ = self.audit("import numpy as np\nx = np.float32(1.0)\n", "--strict")
        self.assertEqual(rc, 1)                                  # ... unless --strict

    def test_missing_provenance_info(self):
        self.assertIn("MISSING_LATEX_PROVENANCE", self.codes("def solve_kepler(M, e):\n    return M\n"))
        self.assertNotIn("MISSING_LATEX_PROVENANCE",
                         self.codes('def solve_kepler(M, e):\n    """Solve $M = E - e \\sin E$."""\n    return M\n'))


class GeneratorTests(unittest.TestCase):
    def test_mms_source_term_matches_analytic_forcing(self):
        import math
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "fixture.py"
            res = run(SCRIPTS / "mms_generator.py", "--exact", "sin(pi*x)*exp(-t)", "--operator",
                      "diff(u, t) - alpha*diff(u, x, 2)", "--params", "alpha=0.1", "--output", str(out))
            self.assertEqual(res.returncode, 0, res.stderr)
            ns = {}
            exec(compile(out.read_text(), str(out), "exec"), ns)   # noqa: S102 - generated fixture
        alpha = 0.1
        for x, t in ((0.3, 0.2), (0.77, 1.5)):
            expected = (alpha * math.pi ** 2 - 1.0) * math.exp(-t) * math.sin(math.pi * x)
            self.assertAlmostEqual(ns["source_term"](x, t), expected, places=13)
            self.assertAlmostEqual(ns["exact_solution"](x, t), math.exp(-t) * math.sin(math.pi * x), places=14)

    def _jacobian_function(self, variables, equations):
        res = run(SCRIPTS / "derive_jacobian.py", "--vars", variables, "--eqs", equations)
        self.assertEqual(res.returncode, 0, res.stderr)
        code = res.stdout[res.stdout.index("import math"):]
        ns = {}
        exec(compile(code, "<jacobian>", "exec"), ns)          # noqa: S102 - generated by the tool under test
        return res.stdout, ns["compute_jacobian"]

    def test_jacobian_of_known_system(self):
        text, jac = self._jacobian_function("x,y", "x**2 + y, sin(x)*y")
        # d/dx (x^2 + y) = 2x ; d/dy = 1 ; d/dx (y sin x) = y cos x ; d/dy = sin x
        for needle in ("J_0_0 = 2*x", "J_1_0 = y*math.cos(x)", "J_1_1 = math.sin(x)"):
            self.assertIn(needle, text)
        import math
        got = jac([0.7, 1.3])
        self.assertAlmostEqual(got[0][0], 1.4, places=14)
        self.assertAlmostEqual(got[1][0], 1.3 * math.cos(0.7), places=14)

    def test_jacobian_matches_finite_differences_when_a_variable_is_named_y(self):
        # regression: the generated function used `y` for its argument, so a state variable called
        # `y` that is not last (here `y,x`) overwrote the state vector before `x` was read
        import math
        _, jac = self._jacobian_function("y,x", "x*y**2, exp(x) - y")
        f = lambda y, x: [x * y ** 2, math.exp(x) - y]
        y0, x0, h = 0.9, 0.4, 1e-6
        got = jac([y0, x0])
        for j, (dy, dx) in enumerate(((h, 0.0), (0.0, h))):                 # column j = d/d(var_j)
            plus, minus = f(y0 + dy, x0 + dx), f(y0 - dy, x0 - dx)
            for i in range(2):
                self.assertAlmostEqual(got[i][j], (plus[i] - minus[i]) / (2 * h), delta=1e-7)   # O(h^2) error

    def test_generated_mms_fixture_has_no_placeholder_assert(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "fixture.py"
            run(SCRIPTS / "mms_generator.py", "--exact", "x**2*t", "--operator", "diff(u, t)", "--output", str(out))
            text = out.read_text()
            self.assertNotIn("assert True", text)
            self.assertNotIn("import pytest", text)
            self.assertTrue(text.startswith('r"""'))               # LaTeX backslashes need a raw docstring
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                compile(text, str(out), "exec")


class BenchmarkTests(unittest.TestCase):
    def bench(self, rel):
        res = run(ROOT / "benchmarks" / rel)
        self.assertEqual(res.returncode, 0, res.stderr[-400:])
        self.assertIn("[PASS]", res.stdout)
        return res.stdout

    def test_exact_riemann_sod(self):
        out = self.bench("cfd/exact_riemann.py")
        p_star = float(re.search(r"Pressure:\s+([\d.]+)", out).group(1))
        u_star = float(re.search(r"Velocity:\s+([\d.]+)", out).group(1))
        self.assertAlmostEqual(p_star, 0.30313, delta=5e-6)       # Toro (2009), Table 4.1
        self.assertAlmostEqual(u_star, 0.92745, delta=5e-6)

    def test_lane_emden_zeros(self):
        import math
        sys.path.insert(0, str(ROOT / "benchmarks" / "astronomy"))
        import lane_emden_solver as le
        out = self.bench("astronomy/lane_emden_solver.py")
        m = re.search(r"Index n = 1\.0:\s+xi_1 \(surface\): ([\d.]+) vs exact ([\d.]+)", out)
        if m:
            self.assertAlmostEqual(float(m.group(2)), math.pi, places=5)
            self.assertAlmostEqual(float(m.group(1)), math.pi, delta=1e-5)

    def test_kepler_invariants(self):
        out = self.bench("astronomy/kepler_solver.py")
        for label in ("Energy Relative Error", "Angular Momentum Rel Error"):
            self.assertLess(float(re.search(label + r":\s+([\d.e+-]+)", out).group(1)), 1e-12)

    def test_symplectic_nbody_conservation(self):
        out = self.bench("astronomy/symplectic_nbody.py")
        self.assertLess(float(re.search(r"Relative Energy Drift:\s+([\d.e+-]+)", out).group(1)), 1e-8)
        self.assertLess(float(re.search(r"Angular Momentum Drift:\s+([\d.e+-]+)", out).group(1)), 1e-12)

    def test_coordinate_transforms(self):
        out = self.bench("astronomy/coordinate_transforms.py")
        self.assertLess(float(re.search(r"Orthogonality Error:\s+([\d.e+-]+)", out).group(1)), 1e-14)

    def test_robertson_mass_conservation(self):
        out = self.bench("kinetics/robertson_reference.py")
        self.assertLess(float(re.search(r"Mass Drift[^:]*:\s+([\d.e+-]+)", out).group(1)), 1e-12)


class DocumentationTests(unittest.TestCase):
    def test_documented_flags_exist_for_every_script(self):
        docs = list((ROOT / "rules").glob("*.md")) + [ROOT / "README.md"]
        docs += list((ROOT / "skills").glob("*/SKILL.md")) + list((ROOT / "agents").glob("*.md"))
        docs += list((ROOT / "skills" / "science-mode").glob("*/*.md")) + list((ROOT / "references").glob("*.md"))
        cache = {}
        for doc in docs:
            for line in doc.read_text().splitlines():
                for script in set(re.findall(r"scripts/(\w+)\.py", line)):
                    path = SCRIPTS / f"{script}.py"
                    self.assertTrue(path.exists(), f"{doc.name} references missing script {script}.py")
                    if "argparse" not in path.read_text():
                        continue
                    if script not in cache:
                        cache[script] = set(re.findall(r"--[a-z][a-z0-9-]*", run(path, "--help").stdout))
                    for flag in re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", line.split(f"{script}.py", 1)[-1]):
                        self.assertIn(flag, cache[script], f"{doc.name}: {script}.py {flag}")

    def test_no_dangling_skill_or_playbook_references(self):
        """Playbooks may only point at skills/playbooks that ship with this plugin."""
        shipped = {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
        shipped |= {p.stem for p in (ROOT / "skills" / "science-mode" / "playbooks").glob("*.md")}
        for md in list((ROOT / "skills" / "science-mode").rglob("*.md")) + [ROOT / "skills" / "benchmark-checklist" / "SKILL.md"]:
            text = md.read_text()
            for ref in re.findall(r"\*\*([a-z][a-z0-9-]+)\*\* (?:skill|principle skill)", text):
                self.assertIn(ref, shipped, f"{md.name}: unknown skill {ref}")
            self.assertNotRegex(text, r"Opening a PR|grok-|Cursor's", md.name)


class PortabilityTests(unittest.TestCase):
    """The scripts must keep working on Python 3.10 (the oldest CI version)."""

    def test_no_backslash_inside_fstring_expressions(self):
        # A backslash inside the {...} of an f-string is a SyntaxError before Python 3.12.
        import ast
        for path in sorted(SCRIPTS.glob("*.py")):
            src = path.read_text()
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.FormattedValue):
                    segment = ast.get_source_segment(src, node.value) or ""
                    self.assertNotIn("\\", segment, f"{path.name}:{node.lineno}: {segment!r}")


if __name__ == "__main__":
    unittest.main()
