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

    def test_other_forms_of_inversion_are_errors(self):
        self.assertIn("BAN_MATRIX_INV", self.codes("import numpy as np\nx = np.linalg.matrix_power(A, -1) @ b\n"))
        self.assertIn("BAN_MATRIX_INV", self.codes("import numpy as np\nA = np.matrix(d)\nx = A.I * b\n"))

    def test_look_alikes_of_those_forms_are_not(self):
        self.assertNotIn("BAN_MATRIX_INV", self.codes("import numpy as np\nx = np.linalg.matrix_power(A, 2)\n"))
        self.assertNotIn("BAN_MATRIX_INV", self.codes("x = circuit.I * R\n"))
        self.assertNotIn("BAN_MATRIX_INV", self.codes("import numpy as np\nx = np.linalg.pinv(A) @ b\n"))

    def test_a_marked_inversion_is_listed_but_is_no_error(self):
        source = "import numpy as np\nC = np.linalg.inv(J.T @ J)  # sciencestack: inverse-is-the-result\n"
        rc, issues = self.audit(source)
        self.assertEqual(rc, 0)
        self.assertEqual([(i["level"], i["code"]) for i in issues], [("INFO", "ALLOWED_MATRIX_INV")])

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

    def generate(self, directory, *args):
        out = Path(directory) / "mms.py"
        res = run(SCRIPTS / "mms_generator.py", *args, "--output", str(out))
        return res, out

    def load(self, path):
        ns = {}
        exec(compile(path.read_text(), str(path), "exec"), ns)   # noqa: S102 - generated module
        return ns

    def test_the_generated_module_names_the_command_and_skips_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            res, out = self.generate(d, "--exact", "sin(pi*x)*exp(-t)", "--operator", "diff(u, t) - diff(u, x, 2)")
            self.assertEqual(res.returncode, 0, res.stderr)
            text = out.read_text()
        self.assertIn("run convergence-user", text)
        self.assertIn(f"--exact {out}:exact_solution", text)
        self.assertIn("run convergence-user", res.stdout)
        self.assertNotIn("SkipTest", text)
        self.assertNotIn("def test_", text)

    def test_the_arguments_are_the_coordinates_in_a_stated_order(self):
        import inspect
        cases = ((("--exact", "sin(pi*x)*sin(pi*y)", "--operator", "diff(u, x, 2) + diff(u, y, 2)"), ["x", "y"]),
                 (("--exact", "t*sin(y)*sin(x)", "--operator", "diff(u, t)"), ["x", "y", "t"]),
                 (("--exact", "t*sin(y)*sin(x)", "--operator", "diff(u, t)", "--vars", "t,x,y"), ["t", "x", "y"]))
        for args, expected in cases:
            with self.subTest(args=args), tempfile.TemporaryDirectory() as d:
                res, out = self.generate(d, *args)
                self.assertEqual(res.returncode, 0, res.stderr)
                ns = self.load(out)
                self.assertEqual(list(inspect.signature(ns["exact_solution"]).parameters), expected)
                self.assertEqual(list(inspect.signature(ns["source_term"]).parameters), expected)

    def test_a_missing_parameter_or_an_unknown_coordinate_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            res, out = self.generate(d, "--exact", "sin(x)", "--operator", "alpha*diff(u, x, 2)")
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("alpha", res.stderr)
            self.assertFalse(out.exists())
            res, _ = self.generate(d, "--exact", "sin(x)", "--operator", "diff(u, x)", "--vars", "x,w")
            self.assertNotEqual(res.returncode, 0)

    def test_a_generated_source_term_drives_a_solver_to_its_order(self):
        # End to end: -u'' = f with the generated f; the 3-point Laplacian must measure second order against the module.
        with tempfile.TemporaryDirectory() as d:
            res, out = self.generate(d, "--exact", "sin(pi*x)", "--operator", "-diff(u, x, 2)")
            self.assertEqual(res.returncode, 0, res.stderr)
            solver = Path(d) / "solver.py"
            solver.write_text("import numpy as np\nfrom mms import source_term\ndef solve(n):\n    h = 1.0 / n\n"
                              "    x = [i * h for i in range(n + 1)]\n"
                              "    A = 2.0 * np.eye(n - 1) - np.eye(n - 1, k=1) - np.eye(n - 1, k=-1)\n"
                              "    b = np.array([source_term(v) * h * h for v in x[1:-1]])\n"
                              "    return x, [0.0] + list(np.linalg.solve(A, b)) + [0.0]\n")
            done = run(SCRIPTS / "check_against_reference.py", "run", "convergence-user", "--solver", f"{solver}:solve",
                       "--exact", f"{out}:exact_solution", "--order", "2", "--no-evidence", cwd=d)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

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


class DocumentedBenchmarkValues(unittest.TestCase):
    """Numbers quoted in the benchmark files' comments and docstrings must match the independently verified values
    (regression: the Robertson comment once said y1 ~ 0.208 at t = 1e5, and the Lane-Emden docstring gave omega_0 as
    2 sqrt(6) / 3 next to the correct decimal 4.898979)."""

    def test_robertson_comment_matches_the_reference_values(self):
        import check_against_reference as car
        text = (ROOT / "benchmarks" / "kinetics" / "robertson_reference.py").read_text()
        match = re.search(r"# y1 = ([\d.e+-]+), y2 = ([\d.e+-]+), y3 = ([\d.e+-]+)", text)
        self.assertIsNotNone(match, "the t = 1e5 reference values are no longer stated")
        for quoted, reference in zip(match.groups(), car.ROBERTSON[100000.0]):
            self.assertAlmostEqual(float(quoted) / reference, 1.0, delta=1e-5)
        self.assertNotIn("0.208", text)

    def test_the_robertson_demo_assertions_agree_with_the_reference_values(self):
        import check_against_reference as car
        y1, y3 = car.ROBERTSON[100000.0][0], car.ROBERTSON[100000.0][2]
        text = (ROOT / "benchmarks" / "kinetics" / "robertson_reference.py").read_text()
        self.assertAlmostEqual(float(re.search(r'res\["y1"\] - ([\d.]+)\)', text).group(1)), y1, delta=1e-6)
        self.assertAlmostEqual(float(re.search(r'res\["y3"\] - ([\d.]+)\)', text).group(1)), y3, delta=1e-6)

    def test_lane_emden_omega0_statement(self):
        import math
        text = (ROOT / "benchmarks" / "astronomy" / "lane_emden_solver.py").read_text()
        match = re.search(r"\\omega_0 = -\\xi_1\^2 \\theta'\(\\xi_1\) = 2\\sqrt\{6\} \\approx ([\d.]+)", text)
        self.assertIsNotNone(match, "omega_0 is no longer stated as 2 sqrt(6)")
        self.assertAlmostEqual(float(match.group(1)), 2.0 * math.sqrt(6.0), delta=1e-6)
        self.assertNotIn(r"\frac{2\sqrt{6}}{3}", text)


class DocumentationTests(unittest.TestCase):
    def test_the_manifest_is_this_plugin_and_not_the_one_it_was_forked_from(self):
        text = (ROOT / "plugin.json").read_text().lower()
        for stale in ("pstack", "cursor", "unslop", "lauren"):
            self.assertNotIn(stale, text)

    def test_every_benchmark_is_documented(self):
        import check_against_reference as car
        readme = (ROOT / "README.md").read_text()
        skill = (ROOT / "skills" / "check-against-reference" / "SKILL.md").read_text()
        for name in car.BENCHMARKS:
            if name != "kepler" and name != "lane-emden" and name != "sod" and name != "robertson":
                self.assertIn(f"`{name}", readme, name)
            self.assertIn(f"`{name}", skill, name)

    def test_the_session_directives_stay_small(self):
        self.assertLess(len((ROOT / "rules" / "directives.md").read_bytes()), 2500)   # injected into every session

    def test_the_readme_does_not_pin_a_test_count_that_will_go_stale(self):
        self.assertIsNone(re.search(r"#\s*\d+ tests", (ROOT / "README.md").read_text()))

    def test_the_versions_agree(self):
        version = json.loads((ROOT / "plugin.json").read_text())["version"]
        self.assertIn(f"Version {version}", (ROOT / "docs" / "scienceStack_manual.tex").read_text())

    def test_documented_flags_exist_for_every_script(self):
        docs = [ROOT / "README.md"]
        if (ROOT / "rules" / "directives.md").exists():
            docs.append(ROOT / "rules" / "directives.md")
        if (ROOT / "rules" / "AGENTS.md").exists():
            docs.append(ROOT / "rules" / "AGENTS.md")
        docs += list((ROOT / "skills").glob("*/SKILL.md")) + list((ROOT / "agents").glob("*.md"))
        docs += list((ROOT / "skills" / "science-mode").glob("*/*.md")) + list((ROOT / "references").glob("*.md"))
        docs += list((ROOT / "agents" / "references").glob("*.md"))
        cache = {}
        for doc in docs:
            for line in doc.read_text().splitlines():
                for script in set(re.findall(r"scripts/(\w+)\.py", line)):
                    path = SCRIPTS / f"{script}.py"
                    self.assertTrue(path.exists(), f"{doc.name} references missing script {script}.py")
                    if "argparse" not in path.read_text():
                        continue
                    if script not in cache:
                        top = run(path, "--help").stdout
                        flags = set(re.findall(r"--[a-z][a-z0-9-]*", top))
                        # a script with subcommands ({list,run,...}) documents its flags in each subcommand's help
                        for group in re.findall(r"\{([a-z][a-z0-9_,-]*)\}", top):
                            for sub in group.split(","):
                                flags |= set(re.findall(r"--[a-z][a-z0-9-]*", run(path, sub, "--help").stdout))
                        cache[script] = flags
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

    def test_no_stale_claude_plugin_roots_or_prefixes_in_antigravity_docs(self):
        docs = [ROOT / "README.md", ROOT / "examples" / "reference-checks.workflow.yml"]
        docs += list((ROOT / "rules").glob("*.md")) + list((ROOT / "skills").rglob("*.md"))
        docs += list((ROOT / "agents").rglob("*.md"))
        for doc in docs:
            text = doc.read_text()
            self.assertNotIn("CLAUDE_PLUGIN_ROOT", text, str(doc.relative_to(ROOT)))
            self.assertNotIn("/sciencestack:", text, str(doc.relative_to(ROOT)))
            self.assertNotIn("sciencestack:science-master", text, str(doc.relative_to(ROOT)))
            self.assertNotIn("sciencestack:theory-reviewer", text, str(doc.relative_to(ROOT)))
            self.assertNotIn("seoym3919/scienceStack_claude", text, str(doc.relative_to(ROOT)))


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
