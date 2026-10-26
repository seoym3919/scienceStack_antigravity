"""Tests for scripts/random_detect.py as used by audit_numerical_ast.py (nondeterminism warnings).

Run (from the plugin root):  python3 -B -m unittest discover -s tests -v

Every rule has a case that must be flagged and a case that must not (a seeded or injected generator, a local function
that merely has the same name as a random function, JAX's explicit keys). The audit never executes the code under test.
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "audit_numerical_ast.py"
sys.path.insert(0, str(ROOT / "scripts"))

import audit_numerical_ast as audit  # noqa: E402

RANDOM_CODES = {"UNSEEDED_RANDOM_DRAW", "UNSEEDED_GENERATOR", "NONDETERMINISTIC_SEED", "NONDETERMINISTIC_SOURCE"}


class Audit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def issues(self, source):
        path = self.dir / "solver.py"
        path.write_text(textwrap.dedent(source))
        return [i for i in audit.audit_file(str(path)) if i["code"] in RANDOM_CODES]

    def codes(self, source):
        return [i["code"] for i in self.issues(source)]

    def assert_flagged(self, source, code, count=1):
        found = self.codes(source)
        self.assertEqual(found, [code] * count, (code, found, source))

    def assert_clean(self, source):
        self.assertEqual(self.codes(source), [], source)


class GlobalDraws(Audit):
    def test_numpy_global_draws(self):
        for call in ("np.random.rand(3)", "np.random.randn(3)", "np.random.random()", "np.random.normal(0, 1)",
                     "np.random.randint(0, 5)", "np.random.choice([1, 2])", "np.random.uniform()",
                     "np.random.random_sample()", "np.random.permutation(5)", "np.random.standard_normal(2)"):
            self.assert_flagged("import numpy as np\nx = %s\n" % call, "UNSEEDED_RANDOM_DRAW")

    def test_shuffle_is_a_draw_too(self):
        self.assert_flagged("import numpy as np\na = [1, 2]\nnp.random.shuffle(a)\n", "UNSEEDED_RANDOM_DRAW")

    def test_import_styles_are_resolved(self):
        for header, call in (("from numpy.random import rand", "rand(2)"), ("from numpy import random as npr", "npr.normal()"),
                             ("import numpy.random as r", "r.uniform()"), ("import numpy", "numpy.random.rand()"),
                             ("from numpy.random import normal as gauss", "gauss()")):
            self.assert_flagged("%s\nx = %s\n" % (header, call), "UNSEEDED_RANDOM_DRAW")

    def test_stdlib_random_draws(self):
        for call in ("random.random()", "random.uniform(0, 1)", "random.randint(0, 3)", "random.choice([1, 2])",
                     "random.gauss(0, 1)", "random.sample(range(5), 2)"):
            self.assert_flagged("import random\nx = %s\n" % call, "UNSEEDED_RANDOM_DRAW")
        self.assert_flagged("import random as rnd\nx = rnd.random()\n", "UNSEEDED_RANDOM_DRAW")
        self.assert_flagged("from random import gauss\nx = gauss(0, 1)\n", "UNSEEDED_RANDOM_DRAW")

    def test_torch_draws(self):
        for call in ("torch.rand(2)", "torch.randn(2)", "torch.randperm(4)", "torch.randint(0, 3, (2,))"):
            self.assert_flagged("import torch\nx = %s\n" % call, "UNSEEDED_RANDOM_DRAW")

    def test_each_draw_is_reported_with_its_line(self):
        found = self.issues("import numpy as np\n\na = np.random.rand()\nb = np.random.rand()\n")
        self.assertEqual([i["line"] for i in found], [3, 4])
        self.assertTrue(all(i["level"] == "WARNING" and i["suggestion"] for i in found))


class Seeded(Audit):
    def test_seeding_the_same_state_silences_its_draws(self):
        self.assert_clean("import numpy as np\nnp.random.seed(0)\nx = np.random.rand()\n")
        self.assert_clean("import random\nrandom.seed(1)\nx = random.random()\n")
        self.assert_clean("import torch\ntorch.manual_seed(0)\nx = torch.rand(2)\n")
        self.assert_clean("import torch\ntorch.random.manual_seed(0)\nx = torch.randn(2)\n")

    def test_a_seed_anywhere_in_the_file_counts(self):
        self.assert_clean("""
            import numpy as np
            def setup():
                np.random.seed(3)
            def run():
                return np.random.rand()
        """)

    def test_a_seed_held_in_a_variable_counts(self):
        self.assert_clean("import numpy as np\nSEED = 5\nnp.random.seed(SEED)\nx = np.random.rand()\n")

    def test_states_are_separate(self):
        self.assert_flagged("import numpy as np\nimport random\nnp.random.seed(0)\nx = random.random()\n", "UNSEEDED_RANDOM_DRAW")
        self.assert_flagged("import numpy as np\nimport random\nrandom.seed(0)\nx = np.random.rand()\n", "UNSEEDED_RANDOM_DRAW")
        self.assert_flagged("import numpy as np\nimport torch\nnp.random.seed(0)\nx = torch.rand(1)\n", "UNSEEDED_RANDOM_DRAW")

    def test_a_nondeterministic_seed_does_not_count_as_seeding(self):
        found = self.codes("import numpy as np, time\nnp.random.seed(int(time.time()))\nx = np.random.rand()\n")
        self.assertEqual(sorted(found), ["NONDETERMINISTIC_SEED", "UNSEEDED_RANDOM_DRAW"])
        found = self.codes("import numpy as np\nnp.random.seed(None)\nx = np.random.rand()\n")
        self.assertEqual(sorted(found), ["NONDETERMINISTIC_SEED", "UNSEEDED_RANDOM_DRAW"])


class Generators(Audit):
    def test_unseeded_constructors(self):
        for call in ("np.random.default_rng()", "np.random.default_rng(None)", "np.random.default_rng(seed=None)",
                     "np.random.RandomState()", "np.random.RandomState(None)", "np.random.SeedSequence()",
                     "np.random.PCG64()", "np.random.Generator(np.random.PCG64())"):
            self.assertIn("UNSEEDED_GENERATOR", self.codes("import numpy as np\nrng = %s\n" % call), call)
        self.assert_flagged("import random\nr = random.Random()\n", "UNSEEDED_GENERATOR")
        self.assert_flagged("import random\nr = random.Random(None)\n", "UNSEEDED_GENERATOR")
        self.assert_flagged("from numpy.random import default_rng\nrng = default_rng()\n", "UNSEEDED_GENERATOR")

    def test_seeded_or_injected_constructors_are_fine(self):
        for call in ("np.random.default_rng(12345)", "np.random.default_rng(seed=0)", "np.random.default_rng(seed)",
                     "np.random.default_rng(rng_arg)", "np.random.RandomState(0)", "np.random.SeedSequence(7)",
                     "np.random.Generator(np.random.PCG64(1))", "np.random.default_rng([1, 2, 3])"):
            self.assert_clean("import numpy as np\nseed = 1\nrng_arg = None\nrng = %s\n" % call)
        self.assert_clean("import random\nr = random.Random(42)\n")

    def test_state_management_functions_are_not_draws(self):
        # no seeding here: only the "not a draw" lists keep these from being reported
        self.assert_clean("import numpy as np\ns = np.random.get_state()\nnp.random.set_state(s)\n")
        self.assert_clean("import random\ns = random.getstate()\nrandom.setstate(s)\n")

    def test_draws_from_a_generator_instance_are_not_global_draws(self):
        self.assert_clean("import numpy as np\nrng = np.random.default_rng(0)\nx = rng.random()\ny = rng.normal()\n")
        self.assert_clean("import numpy as np\nx = np.random.default_rng(0).normal()\n")
        self.assert_clean("import random\nr = random.Random(1)\nx = r.random()\n")


class NondeterministicSeeds(Audit):
    def test_seed_calls_without_a_value(self):
        self.assert_flagged("import numpy as np\nnp.random.seed()\n", "NONDETERMINISTIC_SEED")
        self.assert_flagged("import numpy as np\nnp.random.seed(None)\n", "NONDETERMINISTIC_SEED")
        self.assert_flagged("import random\nrandom.seed()\n", "NONDETERMINISTIC_SEED")
        self.assert_flagged("import torch\ntorch.manual_seed(None)\n", "NONDETERMINISTIC_SEED")

    def test_clock_pid_and_entropy_seeds(self):
        header = "import numpy as np, time, os, uuid, datetime\n"
        for seed in ("time.time()", "int(time.time())", "int(time.time() * 1000) % 2**32", "time.time_ns()",
                     "os.getpid()", "time.perf_counter_ns()", "datetime.datetime.now().microsecond",
                     "uuid.uuid4().int % 2**32"):
            self.assertEqual(self.codes(header + "np.random.seed(%s)\n" % seed), ["NONDETERMINISTIC_SEED"], seed)
        # os.urandom is itself an unseedable source, so it is reported as well (seed call first, by column)
        self.assertEqual(self.codes(header + "np.random.seed(int.from_bytes(os.urandom(4), 'little'))\n"),
                         ["NONDETERMINISTIC_SEED", "NONDETERMINISTIC_SOURCE"])

    def test_clock_seeded_constructors(self):
        self.assert_flagged("import numpy as np, time\nrng = np.random.default_rng(int(time.time()))\n", "NONDETERMINISTIC_SEED")
        self.assert_flagged("import numpy as np, os\nrs = np.random.RandomState(os.getpid())\n", "NONDETERMINISTIC_SEED")
        self.assert_flagged("import random, time\nr = random.Random(time.time())\n", "NONDETERMINISTIC_SEED")

    def test_aliased_clock_is_resolved(self):
        self.assert_flagged("import numpy as np\nfrom time import time as now\nnp.random.seed(int(now()))\n", "NONDETERMINISTIC_SEED")
        self.assert_flagged("import numpy as np\nimport time as t\nrng = np.random.default_rng(int(t.time()))\n", "NONDETERMINISTIC_SEED")

    def test_a_variable_that_merely_has_a_clock_like_name_is_fine(self):
        self.assert_clean("import numpy as np\ntime = 5\nnp.random.seed(time)\n")


class Unseedable(Audit):
    def test_sources_that_cannot_be_seeded(self):
        self.assert_flagged("import os\nb = os.urandom(8)\n", "NONDETERMINISTIC_SOURCE")
        self.assert_flagged("import secrets\nb = secrets.token_hex(8)\n", "NONDETERMINISTIC_SOURCE")
        self.assert_flagged("import secrets\nb = secrets.choice([1, 2])\n", "NONDETERMINISTIC_SOURCE")
        self.assert_flagged("import random\nr = random.SystemRandom()\n", "NONDETERMINISTIC_SOURCE")
        self.assert_flagged("import torch\ns = torch.seed()\n", "NONDETERMINISTIC_SOURCE")


class NotRandom(Audit):
    def test_local_functions_with_random_looking_names(self):
        self.assert_clean("def rand():\n    return 4\n\ndef normal():\n    return 0.0\n\nx = rand() + normal()\n")

    def test_attribute_chains_that_are_not_modules(self):
        self.assert_clean("class A:\n    def f(self):\n        return self.random.rand()\n")

    def test_jax_explicit_keys_are_deterministic(self):
        self.assert_clean("import jax\nkey = jax.random.PRNGKey(0)\nx = jax.random.normal(key, (3,))\n")

    def test_mentions_in_strings_and_comments(self):
        self.assert_clean('# np.random.rand() is a global draw\nS = "np.random.rand()"\nD = """random.random()"""\n')

    def test_module_level_names_that_shadow_an_import_alias(self):
        self.assert_clean("import numpy as np\nnp = object()\n")                      # no call, nothing to flag

    def test_parse_errors_still_report_the_parse_error_only(self):
        path = self.dir / "broken.py"
        path.write_text("def (:\n")
        self.assertEqual([i["code"] for i in audit.audit_file(str(path))], ["PARSE_ERROR"])


class CommandLine(Audit):
    def run_cli(self, source, *extra):
        path = self.dir / "solver.py"
        path.write_text(textwrap.dedent(source))
        return subprocess.run([sys.executable, "-B", str(SCRIPT), str(path), *extra], capture_output=True, text=True)

    def test_warnings_do_not_fail_but_strict_does(self):
        source = "import numpy as np\nx = np.random.rand()\n"
        self.assertEqual(self.run_cli(source).returncode, 0)
        done = self.run_cli(source, "--strict")
        self.assertEqual(done.returncode, 1)
        self.assertIn("UNSEEDED_RANDOM_DRAW", done.stdout)

    def test_seeded_code_passes_strict(self):
        done = self.run_cli("import numpy as np\nrng = np.random.default_rng(0)\nx = rng.random()\n", "--strict")
        self.assertEqual((done.returncode, "UNSEEDED" in done.stdout), (0, False))

    def test_json_output_carries_the_code_line_and_suggestion(self):
        done = self.run_cli("import numpy as np\n\nrng = np.random.default_rng()\n", "--json")
        data = json.loads(done.stdout)
        self.assertEqual([(d["code"], d["line"], d["level"]) for d in data], [("UNSEEDED_GENERATOR", 3, "WARNING")])
        self.assertIn("seed", data[0]["suggestion"])

    def test_the_plugins_own_benchmarks_are_deterministic(self):
        done = subprocess.run([sys.executable, "-B", str(SCRIPT), str(ROOT / "benchmarks"), "--json"], capture_output=True, text=True)
        flagged = [d for d in json.loads(done.stdout) if d["code"] in RANDOM_CODES]
        self.assertEqual(flagged, [])


if __name__ == "__main__":
    unittest.main()
