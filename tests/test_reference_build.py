"""Tests for scripts/reference_build.py and its use by run-manifest (compare checks with ref_from / test_from).

Run (from the plugin root):  python3 -B -m unittest discover -s tests -v

Most tests use a Python script as the "legacy program" (steps are plain argument lists, so any program works). The last class
uses the real gfortran and gcc when they are installed (skipped otherwise): a legacy Fortran program is compiled and run,
and a translation is compared with its output.
"""

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_against_reference.py"
sys.path.insert(0, str(ROOT / "scripts"))

import check_against_reference as car  # noqa: E402
import reference_build as rb  # noqa: E402
import reference_manifest as rm  # noqa: E402
import verification_evidence as ve  # noqa: E402

PY = sys.executable


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


LEGACY = textwrap.dedent('''
    import sys
    n = int(open(sys.argv[1]).read())
    y, h = 1.0, 0.1
    for _ in range(n):
        y = y + h * (-2.0 * y)
        print(repr(y))
''')
TRANSLATION = textwrap.dedent('''
    import sys
    n = int(open(sys.argv[1]).read())
    y, h = 1.0, 0.1
    for _ in range(n):
        y = y + h * (-2.0 * y)
        print(repr(y))
''')
TRANSLATION_BUG = TRANSLATION.replace("-2.0 * y", "-2.0000001 * y")


class Repo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name).resolve() / "proj"
        for sub in ("legacy", "src", "inputs", "golden"):
            (self.repo / sub).mkdir(parents=True)
        (self.repo / "legacy" / "decay.py").write_text(LEGACY)
        (self.repo / "src" / "decay.py").write_text(TRANSLATION)
        (self.repo / "inputs" / "n.txt").write_text("5\n")
        self.manifest = self.repo / "reference-checks.json"
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "T")
        self.git("config", "user.email", "t@example.invalid")
        out = subprocess.run([PY, str(self.repo / "legacy" / "decay.py"), str(self.repo / "inputs" / "n.txt")],
                             capture_output=True, text=True, check=True).stdout
        (self.repo / "golden" / "decay.out").write_text(out)
        self.write(self.good_manifest())
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "baseline")

    def tearDown(self):
        self._tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True)

    def pins(self, *rels):
        return {rel: sha(self.repo / rel) for rel in rels}

    def ref_from(self, **over):
        spec = {"steps": [[PY, "legacy/decay.py", "inputs/n.txt"]], "output": "stdout",
                "pinned": self.pins("legacy/decay.py", "inputs/n.txt"), "reproduce_rtol": 1e-14, "reproduce_atol": 0,
                "record_versions": [[PY, "--version"]]}
        spec.update(over)
        return spec

    def test_from(self, **over):
        spec = {"steps": [[PY, "src/decay.py", "inputs/n.txt"]], "output": "stdout", "pinned": self.pins("src/decay.py", "inputs/n.txt")}
        spec.update(over)
        return spec

    def good_manifest(self, **compare):
        inner = {"ref": "golden/decay.out", "rtol": 1e-13, "atol": 0, "ref_from": self.ref_from(), "test_from": self.test_from()}
        inner.update(compare)
        return {"schema": rm.SCHEMA, "checks": [{"id": "decay", "rationale": "the Python port must reproduce the legacy program",
                                                  "compare": inner}]}

    def write(self, manifest):
        self.manifest.write_text(json.dumps(manifest, indent=2))

    def edit(self, change):
        manifest = json.loads(self.manifest.read_text())
        change(manifest["checks"][0]["compare"])
        self.write(manifest)

    def cli(self, *args, timeout=300):
        env = {k: v for k, v in os.environ.items() if k != "VERIFICATION_EVIDENCE_DIR"}
        return subprocess.run([PY, "-B", str(SCRIPT), *args], cwd=self.repo, capture_output=True, text=True, timeout=timeout, env=env)

    def run_manifest(self, *extra):
        done = self.cli("run-manifest", "--json", "summary.json", *extra)
        path = self.repo / "summary.json"
        summary = json.loads(path.read_text()) if path.exists() else None
        return done, summary

    def records(self):
        log = self.repo / ".verification" / "log.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


class Validation(Repo):
    def errors(self, change=None, side="ref_from"):
        manifest = self.good_manifest()
        if change:
            change(manifest["checks"][0]["compare"])
        return rm.validate(manifest, car.BENCHMARKS, car.resolve_tolerance)

    def assert_error(self, text, change, **kw):
        found = self.errors(change, **kw)
        self.assertTrue(any(text in e for e in found), (text, found))

    def test_a_complete_manifest_is_valid(self):
        self.assertEqual(self.errors(), [])

    def test_steps(self):
        for bad in ([], "x", [[]], [[""]], [["a", 1]], ["a"], [["a\0b"]]):
            self.assert_error("steps", lambda c, b=bad: c["ref_from"].update(steps=b))
        self.assert_error("argument list", lambda c: c["ref_from"].update(steps=["gfortran -O0 a.f90"]))
        self.assert_error("only {work} and {repo} exist", lambda c: c["ref_from"].update(steps=[["{home}/x"]]))
        self.assertEqual(self.errors(lambda c: c["ref_from"].update(steps=[["{work}/x", "{repo}/y"]])), [])

    def test_output(self):
        for bad in ("stderr", "file:out.txt", "file:{work}/../x", "file:{work}/a/b", "file:{work}/", 5, None):
            self.assert_error("output must be", lambda c, b=bad: c["test_from"].update(output=b))
        self.assertEqual(self.errors(lambda c: c["test_from"].update(output="file:{work}/out.txt")), [])

    def test_pinned(self):
        self.assert_error("pinned is required", lambda c: c["ref_from"].pop("pinned"))
        self.assert_error("pinned is required", lambda c: c["ref_from"].update(pinned={}))
        for path in ("/abs", "../x", "~/x", "a//b", "a\\b", ""):
            self.assert_error("plain repo-relative path", lambda c, p=path: c["ref_from"].update(pinned={p: "0" * 64}))
        for digest in ("abc", "G" * 64, "A" * 64, 5, None, "0" * 63):
            self.assert_error("64-digit SHA-256", lambda c, d=digest: c["ref_from"].update(pinned={"legacy/decay.py": d}))
        self.assert_error("pinned is required", lambda c: c["test_from"].pop("pinned"))

    def test_reference_reproduction_tolerances_are_required_and_non_negative(self):
        for key in ("reproduce_rtol", "reproduce_atol"):
            self.assert_error(key + " is required", lambda c, k=key: c["ref_from"].pop(k))
            for bad in (-1, True, "1e-9", float("nan"), float("inf")):
                self.assert_error(key, lambda c, k=key, b=bad: c["ref_from"].update({k: b}))
        self.assertEqual(self.errors(lambda c: c["ref_from"].update(reproduce_rtol=0, reproduce_atol=0)), [])
        self.assert_error("unknown key 'reproduce_rtol'", lambda c: c["test_from"].update(reproduce_rtol=1e-9))     # reference only

    def test_timeout_and_versions_and_unknown_keys(self):
        for bad in (0, 3601, True, 1.5, "5"):
            self.assert_error("timeout_s", lambda c, b=bad: c["test_from"].update(timeout_s=b))
        self.assertEqual(self.errors(lambda c: c["test_from"].update(timeout_s=3600)), [])
        for bad in ("x", [[]], [["a", 1]], [5]):
            self.assert_error("record_versions", lambda c, b=bad: c["ref_from"].update(record_versions=b))
        self.assert_error("unknown key 'shell'", lambda c: c["ref_from"].update(shell=True))
        self.assert_error("must be an object", lambda c: c.update(ref_from="make"))

    def test_test_and_test_from_are_exclusive_and_one_is_needed(self):
        self.assert_error("not both", lambda c: c.update(test="build/out.txt"))
        self.assert_error("compare.test", lambda c: c.pop("test_from"))                  # neither: the committed test path is needed
        self.assertEqual(self.errors(lambda c: (c.pop("test_from"), c.update(test="build/out.txt"))), [])
        self.assertEqual(self.errors(lambda c: c.pop("ref_from")), [])                   # a plain committed reference is still allowed


class Pinned(Repo):
    def test_matching_missing_and_changed_files(self):
        spec = self.ref_from()
        self.assertEqual(rb.check_pinned(spec, self.repo), [])
        (self.repo / "inputs" / "n.txt").write_text("6\n")
        problems = rb.check_pinned(spec, self.repo)
        self.assertEqual(len(problems), 1)
        self.assertIn("inputs/n.txt: sha256 is", problems[0])
        (self.repo / "legacy" / "decay.py").unlink()
        self.assertTrue(any("legacy/decay.py: pinned but missing" in p for p in rb.check_pinned(spec, self.repo)))

    def test_a_pin_cannot_point_outside_the_repository_or_at_a_symlink(self):
        outside = Path(self._tmp.name) / "outside.txt"
        outside.write_text("secret\n")
        (self.repo / "link.txt").symlink_to(outside)
        spec = {"pinned": {"link.txt": sha(outside), "../outside.txt": sha(outside)}}
        problems = rb.check_pinned(spec, self.repo)
        self.assertEqual(len(problems), 2)
        self.assertTrue(all("pinned but missing" in p for p in problems))

    def test_a_symlink_to_a_file_inside_the_repository_is_refused_too(self):
        """A symlink can be retargeted later without changing the pinned path, so only regular files are pinnable."""
        (self.repo / "legacy" / "alias.py").symlink_to("decay.py")
        problems = rb.check_pinned({"pinned": {"legacy/alias.py": sha(self.repo / "legacy" / "decay.py")}}, self.repo)
        self.assertEqual(len(problems), 1)
        self.assertIn("pinned but missing (or not a regular file", problems[0])

    def test_a_directory_is_not_a_pinnable_file(self):
        self.assertTrue(rb.check_pinned({"pinned": {"legacy": "0" * 64}}, self.repo))


class Produce(Repo):
    def produce(self, spec):
        return rb.produce(spec, self.repo, car.load_values)

    def test_stdout_numbers_and_the_recorded_information(self):
        values, info = self.produce(self.ref_from())
        self.assertEqual(len(values), 5)
        self.assertAlmostEqual(values[0], 0.8, delta=1e-15)
        self.assertEqual((info["steps"], info["values"]), (1, 5))
        self.assertEqual(info["pinned"], self.ref_from()["pinned"])
        self.assertIn("Python", info["versions"][0])

    def test_a_file_written_into_the_work_directory(self):
        (self.repo / "legacy" / "writer.py").write_text("import sys\nopen(sys.argv[1], 'w').write('1.5 2.5\\n3.5\\n')\n")
        spec = {"steps": [[PY, "legacy/writer.py", "{work}/out.txt"]], "output": "file:{work}/out.txt",
                "pinned": self.pins("legacy/writer.py")}
        self.assertEqual(self.produce(spec)[0], [1.5, 2.5, 3.5])
        missing = dict(spec, output="file:{work}/other.txt")
        with self.assertRaises(rb.BuildFailure) as caught:
            self.produce(missing)
        self.assertIn("did not write", str(caught.exception))

    def test_steps_run_in_order_in_the_repository_and_placeholders_are_substituted(self):
        (self.repo / "legacy" / "stage1.py").write_text("import sys\nopen(sys.argv[1] + '/n.txt', 'w').write('3')\n")
        (self.repo / "legacy" / "stage2.py").write_text(
            "import os, sys\nn = int(open(sys.argv[1] + '/n.txt').read())\nprint(n, os.getcwd() == sys.argv[2])\n")
        spec = {"steps": [[PY, "{repo}/legacy/stage1.py", "{work}"], [PY, "legacy/stage2.py", "{work}", "{repo}"]], "output": "stdout",
                "pinned": self.pins("legacy/stage1.py", "legacy/stage2.py")}
        with self.assertRaises(rb.BuildFailure):                       # stdout holds "3 True": not a list of numbers
            self.produce(spec)
        (self.repo / "legacy" / "stage2.py").write_text(
            "import os, sys\nn = int(open(sys.argv[1] + '/n.txt').read())\nprint(n)\nassert os.getcwd() == sys.argv[2]\n")
        spec["pinned"] = self.pins("legacy/stage1.py", "legacy/stage2.py")
        self.assertEqual(self.produce(spec)[0], [3.0])

    def test_arguments_are_never_interpreted_by_a_shell(self):
        (self.repo / "legacy" / "echo.py").write_text("import sys\nprint(len(sys.argv))\nprint(len(sys.argv[1]))\n")
        marker = self.repo / "injected"
        spec = {"steps": [[PY, "legacy/echo.py", f"1; touch {marker}", "$(touch %s)" % marker, "`touch %s`" % marker]],
                "output": "stdout", "pinned": self.pins("legacy/echo.py")}
        values, _ = self.produce(spec)
        self.assertEqual(values[0], 4.0)                                # four argv entries, each taken literally
        self.assertFalse(marker.exists())

    def test_locale_is_fixed_for_reproducible_number_formats(self):
        (self.repo / "legacy" / "env.py").write_text("import os\nprint(1.0 if os.environ.get('LC_ALL') == 'C' else 0.0)\n")
        spec = {"steps": [[PY, "legacy/env.py"]], "output": "stdout", "pinned": self.pins("legacy/env.py")}
        self.assertEqual(self.produce(spec)[0], [1.0])

    def test_failures_are_build_failures_with_the_tail_of_stderr(self):
        (self.repo / "legacy" / "bad.py").write_text("import sys\nsys.stderr.write('segmentation fault in module X\\n')\nsys.exit(3)\n")
        spec = {"steps": [[PY, "legacy/bad.py"]], "output": "stdout", "pinned": self.pins("legacy/bad.py")}
        with self.assertRaises(rb.BuildFailure) as caught:
            self.produce(spec)
        message = str(caught.exception)
        self.assertIn("step 1 failed (exit 3)", message)
        self.assertIn("segmentation fault in module X", message)

    def test_a_missing_program_is_unavailable_not_a_failure(self):
        spec = {"steps": [["no-such-compiler-anywhere", "x.f90"]], "output": "stdout", "pinned": self.pins("inputs/n.txt")}
        with self.assertRaises(rb.BuildUnavailable) as caught:
            self.produce(spec)
        self.assertIn("program not found: no-such-compiler-anywhere", str(caught.exception))

    def test_a_program_that_cannot_be_executed_is_unavailable(self):
        (self.repo / "legacy" / "notexec.sh").write_text("#!/bin/sh\necho 1\n")
        os.chmod(self.repo / "legacy" / "notexec.sh", 0o644)
        spec = {"steps": [["legacy/notexec.sh"]], "output": "stdout", "pinned": self.pins("legacy/notexec.sh")}
        with self.assertRaises(rb.BuildUnavailable) as caught:
            self.produce(spec)
        self.assertIn("cannot execute", str(caught.exception))

    def test_the_default_timeout_allows_a_step_that_takes_a_while(self):
        (self.repo / "legacy" / "wait.py").write_text("import time\ntime.sleep(2)\nprint(1.0)\n")
        spec = {"steps": [[PY, "legacy/wait.py"]], "output": "stdout", "pinned": self.pins("legacy/wait.py")}   # no timeout_s
        self.assertEqual(self.produce(spec)[0], [1.0])
        self.assertEqual(rb.DEFAULT_TIMEOUT_S, 300)

    def test_a_version_printed_to_stderr_is_recorded(self):
        (self.repo / "legacy" / "version.py").write_text("import sys\nsys.stderr.write('toolchain 4.2 (stderr)\\n')\n")
        spec = self.ref_from(record_versions=[[PY, "legacy/version.py"]])
        _, info = self.produce(spec)
        self.assertEqual(info["versions"], ["toolchain 4.2 (stderr)"])

    def test_a_timeout_kills_the_whole_process_group(self):
        marker = self.repo / "child-survived"
        (self.repo / "legacy" / "slow.py").write_text(
            "import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', "
            f"\"import time; time.sleep(4); open(r'{marker}', 'w').write('x')\"])\ntime.sleep(60)\n")
        spec = {"steps": [[PY, "legacy/slow.py"]], "output": "stdout", "pinned": self.pins("legacy/slow.py"), "timeout_s": 1}
        with self.assertRaises(rb.BuildFailure) as caught:
            self.produce(spec)
        self.assertIn("timed out after 1 s", str(caught.exception))
        import time
        time.sleep(5)
        self.assertFalse(marker.exists())                               # the child was killed with its parent

    def test_no_numbers_and_garbage_are_build_failures(self):
        (self.repo / "legacy" / "empty.py").write_text("pass\n")
        (self.repo / "legacy" / "words.py").write_text("print('result: ok')\n")
        for name, text in (("empty", "no numbers"), ("words", "not a list of numbers")):
            spec = {"steps": [[PY, f"legacy/{name}.py"]], "output": "stdout", "pinned": self.pins(f"legacy/{name}.py")}
            with self.assertRaises(rb.BuildFailure) as caught:
                self.produce(spec)
            self.assertIn(text, str(caught.exception), name)

    def test_the_pins_are_checked_before_anything_runs(self):
        marker = self.repo / "ran"
        (self.repo / "legacy" / "touch.py").write_text(f"open(r'{marker}', 'w').write('x')\nprint(1.0)\n")
        spec = {"steps": [[PY, "legacy/touch.py"]], "output": "stdout", "pinned": {"legacy/touch.py": "0" * 64}}
        with self.assertRaises(rb.BuildFailure) as caught:
            self.produce(spec)
        self.assertIn("pinned files do not match", str(caught.exception))
        self.assertFalse(marker.exists())

    def test_versions_are_recorded_and_an_unavailable_probe_is_noted_not_fatal(self):
        spec = self.ref_from(record_versions=[[PY, "--version"], ["no-such-tool-anywhere", "--version"]])
        _, info = self.produce(spec)
        self.assertIn("Python", info["versions"][0])
        self.assertEqual(info["versions"][1], "no-such-tool-anywhere: not available")


class Reproduction(unittest.TestCase):
    def test_within_and_outside_the_stated_tolerance(self):
        self.assertTrue(rb.reproduction([1.0, 2.0], [1.0, 2.0], 0.0, 0.0)["reproduces"])
        self.assertTrue(rb.reproduction([1.0 + 1e-13, 2.0], [1.0, 2.0], 1e-12, 0.0)["reproduces"])
        bad = rb.reproduction([1.0 + 1e-9, 2.0], [1.0, 2.0], 1e-12, 0.0)
        self.assertFalse(bad["reproduces"])
        self.assertEqual(bad["worst_index"], 0)
        self.assertIn("value 0 differs", bad["reason"])

    def test_the_relative_tolerance_is_taken_from_the_rebuilt_value(self):
        """|committed - rebuilt| <= atol + rtol |rebuilt|: the rebuilt reference is the truth, the committed one must reproduce it."""
        self.assertFalse(rb.reproduction([100.0], [99.0], 0.01, 0.0)["reproduces"])        # 1 > 0.01 * 99
        self.assertTrue(rb.reproduction([99.0], [100.0], 0.01, 0.0)["reproduces"])         # 1 <= 0.01 * 100

    def test_the_worst_value_is_reported_not_the_first_difference(self):
        result = rb.reproduction([1.0 + 1e-13, 2.0 + 1e-12, 3.0], [1.0, 2.0, 3.0], 1e-11, 0.0)
        self.assertEqual(result["worst_index"], 1)
        self.assertAlmostEqual(result["worst_error_over_allowed"] / (1e-12 / (1e-11 * 2.0)), 1.0, delta=1e-3)   # inputs are not exact

    def test_a_difference_exactly_at_the_allowed_one_reproduces(self):
        result = rb.reproduction([3.0], [2.0], 0.5, 0.0)                                  # |3 - 2| = 1 = 0.5 * 2
        self.assertEqual((result["reproduces"], result["worst_error_over_allowed"]), (True, 1.0))
        self.assertFalse(rb.reproduction([3.0000001], [2.0], 0.5, 0.0)["reproduces"])

    def test_atol_covers_values_near_zero_and_exact_zero_tolerance_means_identical(self):
        self.assertTrue(rb.reproduction([1e-10], [0.0], 1e-12, 1e-9)["reproduces"])
        self.assertFalse(rb.reproduction([1e-10], [0.0], 1e-12, 1e-11)["reproduces"])
        self.assertFalse(rb.reproduction([1.0000001], [1.0], 0.0, 0.0)["reproduces"])

    def test_length_and_non_finite_values(self):
        self.assertIn("2 values", rb.reproduction([1.0, 2.0], [1.0], 1.0, 1.0)["reason"])
        for bad in (float("nan"), float("inf")):
            self.assertFalse(rb.reproduction([bad], [1.0], 1.0, 1.0)["reproduces"])
            self.assertFalse(rb.reproduction([1.0], [bad], 1.0, 1.0)["reproduces"])


class RunManifest(Repo):
    def test_a_correct_port_passes_and_the_evidence_is_bound_to_the_pinned_sources(self):
        done, summary = self.run_manifest()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        built = summary["checks"][0]["result"]["built"]
        self.assertEqual(built["reference"]["reproduction"]["reproduces"], True)
        self.assertIn("Python", built["reference"]["versions"][0])
        (record,) = self.records()
        self.assertEqual((record["kind"], record["key"], record["passed"], record["exit_status"]), ("compare", "manifest:decay", True, 0))
        paths = sorted(s["path"] for s in record["subjects"])
        self.assertEqual(paths, ["golden/decay.out", "inputs/n.txt", "legacy/decay.py", "src/decay.py"])
        self.assertTrue(all(s["role"] == "primary" and s["sha256"] for s in record["subjects"]))
        self.assertIn("Python", record["detail"]["built"]["reference"]["versions"][0])       # the build details are in the record
        self.assertEqual(record["detail"]["built"]["test"]["values"], 5)
        self.assertEqual(record["tolerance"], {"atol": 0.0, "ref_from_min": 1, "reproduce_atol": 0.0, "reproduce_rtol": 1e-14, "rtol": 1e-13})

    def test_a_wrong_port_fails_against_the_rebuilt_reference(self):
        (self.repo / "src" / "decay.py").write_text(TRANSLATION_BUG)
        self.edit(lambda c: c.update(test_from=self.test_from()))               # re-pin the changed translation
        done, summary = self.run_manifest()
        self.assertEqual(done.returncode, 1)
        self.assertGreater(summary["checks"][0]["result"]["points_outside_tolerance"], 0)

    def test_changed_legacy_sources_or_inputs_fail_before_anything_runs(self):
        (self.repo / "legacy" / "decay.py").write_text(LEGACY.replace("h = 1.0, 0.1", "h = 1.0, 0.2"))
        done, summary = self.run_manifest()
        self.assertEqual(done.returncode, 1)
        self.assertIn("pinned files do not match the manifest", summary["checks"][0]["result"]["reason"])
        self.assertIn("legacy/decay.py", summary["checks"][0]["result"]["reason"])

    def test_a_hand_edited_committed_reference_is_caught_whatever_the_port_gives(self):
        (self.repo / "golden" / "decay.out").write_text("0.7\n0.6\n0.5\n0.4\n0.3\n")           # forged to make a bad port pass
        done, summary = self.run_manifest()
        self.assertEqual(done.returncode, 1)
        self.assertIn("does not reproduce from its sources", summary["checks"][0]["result"]["reason"])
        self.assertIn("--refresh-reference", summary["checks"][0]["result"]["reason"])
        self.assertIn("if the legacy code or inputs changed on purpose, review the new numbers", summary["checks"][0]["result"]["reason"])

    def test_reproduction_tolerance_is_honoured(self):
        values = (self.repo / "golden" / "decay.out").read_text().split()
        (self.repo / "golden" / "decay.out").write_text("\n".join([repr(float(values[0]) * (1 + 1e-9))] + values[1:]) + "\n")
        self.assertEqual(self.run_manifest()[0].returncode, 1)                           # reproduce_rtol is 1e-14
        self.edit(lambda c: c["ref_from"].update(reproduce_rtol=1e-8))
        self.assertEqual(self.run_manifest()[0].returncode, 3)                           # looser after a failure on unchanged files: withheld
        manifest = json.loads(self.manifest.read_text())
        manifest["checks"][0]["approved_relaxation"] = "the legacy build prints 9 digits; reproduction to 1e-8 is all it can give"
        self.write(manifest)
        self.assertEqual(self.run_manifest()[0].returncode, 0)                           # stated and approved: the rebuilt value is compared

    def test_a_failing_build_step_fails_the_check_with_its_message(self):
        (self.repo / "legacy" / "decay.py").write_text("import sys\nsys.stderr.write('compile error at line 7\\n')\nsys.exit(1)\n")
        self.edit(lambda c: c.update(ref_from=self.ref_from()))
        done, summary = self.run_manifest()
        self.assertEqual(done.returncode, 1)
        self.assertIn("compile error at line 7", summary["checks"][0]["result"]["reason"])

    def test_a_missing_program_is_exit_two_nothing_checked(self):
        self.edit(lambda c: c["ref_from"].update(steps=[["no-such-compiler-anywhere", "x.f90"]]))
        done, summary = self.run_manifest()
        self.assertEqual(done.returncode, 2)
        self.assertIn("program not found", summary["checks"][0]["stderr"])

    def test_only_the_reference_can_be_built_with_a_committed_test_output(self):
        (self.repo / "build").mkdir()
        (self.repo / "build" / "out.txt").write_text((self.repo / "golden" / "decay.out").read_text())
        self.edit(lambda c: (c.pop("test_from"), c.update(test="build/out.txt")))
        done, _ = self.run_manifest()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("build/out.txt", [s["path"] for s in self.records()[-1]["subjects"]])      # the committed output is bound too
        golden = (self.repo / "golden" / "decay.out").read_text()
        (self.repo / "golden" / "decay.out").write_text("0.7\n0.6\n0.5\n0.4\n0.3\n")
        (self.repo / "build" / "out.txt").write_text("0.7\n0.6\n0.5\n0.4\n0.3\n")           # a forged pair that agrees with itself
        forged, summary = self.run_manifest()
        self.assertEqual(forged.returncode, 1)                                                  # only the rebuilt reference is the truth
        self.assertIn("does not reproduce from its sources", summary["checks"][0]["result"]["reason"])
        (self.repo / "golden" / "decay.out").write_text(golden)
        (self.repo / "build" / "out.txt").write_text(golden)
        (self.repo / "build" / "out.txt").write_text("0.1\n0.1\n0.1\n0.1\n0.1\n")
        self.assertEqual(self.run_manifest()[0].returncode, 1)

    def test_only_the_test_side_can_be_built_against_a_committed_reference(self):
        self.edit(lambda c: c.pop("ref_from"))
        done, _ = self.run_manifest()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        (self.repo / "golden" / "decay.out").write_text("0.7\n0.6\n0.5\n0.4\n0.3\n")
        self.assertEqual(self.run_manifest()[0].returncode, 1)                           # no rebuild: the committed file is the truth

    def test_loosening_after_a_failure_is_withheld_with_stable_subjects(self):
        (self.repo / "src" / "decay.py").write_text(TRANSLATION_BUG)
        self.edit(lambda c: c.update(test_from=self.test_from()))
        self.assertEqual(self.run_manifest()[0].returncode, 1)
        self.edit(lambda c: c.update(rtol=1e-3))                                         # looser; sources unchanged
        self.assertEqual(self.run_manifest()[0].returncode, 3)
        self.assertIn("tolerance_loosened_after_failure", self.records()[-1]["flags"])

    def test_dropping_the_rebuilt_reference_after_a_failure_is_flagged_in_the_evidence_and_blocked_by_the_manifest_ratchet(self):
        (self.repo / "src" / "decay.py").write_text(TRANSLATION_BUG)
        self.edit(lambda c: c.update(test_from=self.test_from()))
        self.assertEqual(self.run_manifest()[0].returncode, 1)
        self.git("add", "-A")
        self.git("commit", "-qm", "failing port")
        self.edit(lambda c: c.pop("ref_from"))
        done, _ = self.run_manifest()
        self.assertEqual(done.returncode, 1)                       # the pins of the dropped recipe are no longer subjects: files "changed"
        flags = self.records()[-1]["flags"]
        self.assertIn("tolerance_loosened_after_failure", flags)   # ref_from_min 1 -> 0
        self.assertIn("subjects_changed", flags)
        blocked = self.cli("run-manifest", "--baseline-ref", "HEAD", "--no-evidence")
        self.assertEqual(blocked.returncode, 3, blocked.stdout + blocked.stderr)
        self.assertIn("ref_from_min loosened from 1 to 0", blocked.stderr)

    def test_approved_relaxation_reaches_the_built_check(self):
        (self.repo / "src" / "decay.py").write_text(TRANSLATION_BUG)
        self.edit(lambda c: c.update(test_from=self.test_from()))
        self.assertEqual(self.run_manifest()[0].returncode, 1)
        manifest = json.loads(self.manifest.read_text())
        manifest["checks"][0]["compare"]["rtol"] = 1e-3
        manifest["checks"][0]["approved_relaxation"] = "the port intentionally uses single-step constants (ticket 12)"
        self.write(manifest)
        self.assertEqual(self.run_manifest()[0].returncode, 0)
        self.assertIn("approved relaxation", self.records()[-1]["justification"])

    def test_no_evidence_option(self):
        self.assertEqual(self.run_manifest("--no-evidence")[0].returncode, 0)
        self.assertFalse((self.repo / ".verification").exists())


class RefreshReference(Repo):
    def test_a_deliberate_rewrite_from_the_recipe_then_the_check_passes(self):
        (self.repo / "golden" / "decay.out").write_text("9.0\n9.0\n9.0\n9.0\n9.0\n")
        self.assertEqual(self.run_manifest()[0].returncode, 1)
        done = self.cli("run-manifest", "--refresh-reference", "decay")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("5 values rewritten; largest change vs the previous file", done.stdout)
        self.assertIn("Review `git diff`", done.stdout)
        self.assertIn("built with: Python", done.stdout)
        self.assertEqual(self.run_manifest()[0].returncode, 0)
        self.assertEqual(len((self.repo / "golden" / "decay.out").read_text().split()), 5)

    def test_it_creates_a_missing_reference_and_refuses_unknown_checks_and_checks_without_a_recipe(self):
        (self.repo / "golden" / "decay.out").unlink()
        done = self.cli("run-manifest", "--refresh-reference", "decay")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("(the previous file had 0)", done.stdout)
        self.assertEqual(self.cli("run-manifest", "--refresh-reference", "nope").returncode, 2)
        self.edit(lambda c: c.pop("ref_from"))
        self.assertEqual(self.cli("run-manifest", "--refresh-reference", "decay").returncode, 2)

    def test_it_will_not_rewrite_from_changed_sources_or_a_failing_build(self):
        before = (self.repo / "golden" / "decay.out").read_text()
        (self.repo / "inputs" / "n.txt").write_text("7\n")
        done = self.cli("run-manifest", "--refresh-reference", "decay")
        self.assertEqual(done.returncode, 1)
        self.assertIn("pinned files do not match", done.stderr)
        self.assertEqual((self.repo / "golden" / "decay.out").read_text(), before)


class RatchetOfBuiltChecks(Repo):
    def ratchet(self, change):
        baseline = json.loads(self.manifest.read_text())
        current = copy.deepcopy(baseline)
        change(current["checks"][0]["compare"])
        return rm.ratchet(current, baseline, car.BENCHMARKS)

    def test_changing_how_the_reference_is_built_is_a_violation(self):
        for label, change in (("steps", lambda c: c["ref_from"].update(steps=[[PY, "legacy/decay.py", "inputs/n.txt", "--fast"]])),
                              ("pins", lambda c: c["ref_from"]["pinned"].update({"legacy/decay.py": "1" * 64})),
                              ("output", lambda c: c["ref_from"].update(output="file:{work}/x.txt")),
                              ("extra pin", lambda c: c["ref_from"]["pinned"].update({"inputs/other.txt": "2" * 64}))):
            result = self.ratchet(change)
            self.assertTrue(any("the reference is built differently" in v["problem"] for v in result["violations"]), (label, result))

    def test_removing_the_recipe_or_loosening_the_reproduction_is_a_violation(self):
        result = self.ratchet(lambda c: c.pop("ref_from"))
        self.assertTrue(any("ref_from_min loosened from 1 to 0" in v["problem"] for v in result["violations"]), result)
        result = self.ratchet(lambda c: c["ref_from"].update(reproduce_rtol=1e-9))
        self.assertTrue(any("reproduce_rtol loosened" in v["problem"] for v in result["violations"]), result)
        result = self.ratchet(lambda c: c["ref_from"].update(reproduce_atol=1e-6))
        self.assertTrue(any("reproduce_atol loosened from 0 to 1e-06" in v["problem"] for v in result["violations"]), result)

    def test_changes_to_the_test_side_are_not_violations_and_a_recipe_added_is_a_tightening(self):
        result = self.ratchet(lambda c: c["test_from"].update(steps=[[PY, "src/decay.py", "inputs/n.txt", "--v"]]))
        self.assertEqual(result["violations"], [])
        baseline = self.good_manifest()
        baseline["checks"][0]["compare"].pop("ref_from")
        current = self.good_manifest()
        self.assertEqual(rm.ratchet(current, baseline, car.BENCHMARKS)["violations"], [])

    def test_an_approved_relaxation_accepts_a_new_recipe(self):
        baseline = json.loads(self.manifest.read_text())
        current = copy.deepcopy(baseline)
        current["checks"][0]["compare"]["ref_from"]["pinned"]["legacy/decay.py"] = "3" * 64
        current["checks"][0]["approved_relaxation"] = "legacy program updated to the 2025 release (ticket 9)"
        result = rm.ratchet(current, baseline, car.BENCHMARKS)
        self.assertEqual(result["violations"], [])
        self.assertEqual(len(result["approved"]), 1)

    def test_the_effective_tolerance_of_a_compare_check(self):
        effective = rm.effective_tolerance(self.good_manifest()["checks"][0], car.BENCHMARKS)
        self.assertEqual(effective, {"rtol": 1e-13, "atol": 0.0, "ref_from_min": 1.0, "reproduce_rtol": 1e-14, "reproduce_atol": 0.0})
        plain = self.good_manifest()
        plain["checks"][0]["compare"].pop("ref_from")
        self.assertEqual(rm.effective_tolerance(plain["checks"][0], car.BENCHMARKS), {"rtol": 1e-13, "atol": 0.0, "ref_from_min": 0.0})

    def test_a_manifest_in_git_blocks_the_change_end_to_end(self):
        self.edit(lambda c: c["ref_from"]["pinned"].update({"legacy/decay.py": "4" * 64}))
        done = self.cli("run-manifest", "--baseline-ref", "HEAD", "--no-evidence")
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertIn("the reference is built differently", done.stderr)


FORTRAN = textwrap.dedent('''
    program heat
      implicit none
      integer, parameter :: n = 8, steps = 40
      double precision :: u(n), unew(n), alpha, dt, dx
      integer :: i, s
      alpha = 0.3d0
      dt = 0.001d0
      dx = 0.1d0
      do i = 1, n
        u(i) = dble(i) * dx * (1.0d0 - dble(i) * dx / 0.9d0)
      end do
      do s = 1, steps
        unew = u
        do i = 2, n - 1
          unew(i) = u(i) + alpha * dt / dx**2 * (u(i+1) - 2.0d0 * u(i) + u(i-1))
        end do
        u = unew
      end do
      do i = 1, n
        write (*, '(es25.17e3)') u(i)
      end do
    end program heat
''')
PORT = textwrap.dedent('''
    n, steps = 8, 40
    alpha, dt, dx = 0.3, 0.001, 0.1
    u = [(i + 1) * dx * (1.0 - (i + 1) * dx / 0.9) for i in range(n)]
    for _ in range(steps):
        unew = list(u)
        for i in range(1, n - 1):
            unew[i] = u[i] + alpha * dt / dx ** 2 * (u[i + 1] - 2.0 * u[i] + u[i - 1])
        u = unew
    for value in u:
        print(repr(value))
''')
C_PORT = textwrap.dedent('''
    #include <stdio.h>
    int main(void) {
      enum { n = 8, steps = 40 };
      double u[n], unew[n], alpha = 0.3, dt = 0.001, dx = 0.1;
      for (int i = 0; i < n; i++) u[i] = (i + 1) * dx * (1.0 - (i + 1) * dx / 0.9);
      for (int s = 0; s < steps; s++) {
        for (int i = 0; i < n; i++) unew[i] = u[i];
        for (int i = 1; i < n - 1; i++)
          unew[i] = u[i] + alpha * dt / (dx * dx) * (u[i + 1] - 2.0 * u[i] + u[i - 1]);
        for (int i = 0; i < n; i++) u[i] = unew[i];
      }
      for (int i = 0; i < n; i++) printf("%.17e\\n", u[i]);
      return 0;
    }
''')


@unittest.skipUnless(shutil.which("gfortran") and shutil.which("gcc"), "gfortran and gcc are not installed")
class RealCompilers(Repo):
    def setUp(self):
        super().setUp()
        (self.repo / "legacy" / "heat.f90").write_text(FORTRAN)
        (self.repo / "src" / "heat.py").write_text(PORT)
        (self.repo / "src" / "heat.c").write_text(C_PORT)
        self.fortran = {"steps": [["gfortran", "-O0", "-ffp-contract=off", "legacy/heat.f90", "-o", "{work}/heat"], ["{work}/heat"]],
                        "output": "stdout", "pinned": self.pins("legacy/heat.f90"), "reproduce_rtol": 1e-13, "reproduce_atol": 0,
                        "record_versions": [["gfortran", "--version"]], "timeout_s": 120}
        out = subprocess.run(["bash", "-c", "gfortran -O0 -ffp-contract=off legacy/heat.f90 -o /tmp/heat_ref_$$ && /tmp/heat_ref_$$; rm -f /tmp/heat_ref_$$"],
                             cwd=self.repo, capture_output=True, text=True, check=True).stdout
        (self.repo / "golden" / "heat.out").write_text(out)
        self.heat = {"id": "heat", "rationale": "the Python and C ports of the legacy Fortran heat code must reproduce it",
                     "compare": {"ref": "golden/heat.out", "rtol": 1e-13, "atol": 0, "ref_from": self.fortran,
                                 "test_from": {"steps": [[PY, "src/heat.py"]], "output": "stdout", "pinned": self.pins("src/heat.py")}}}
        self.write({"schema": rm.SCHEMA, "checks": [self.heat]})

    def run_check(self, test_from):
        self.heat["compare"]["test_from"] = test_from
        self.write({"schema": rm.SCHEMA, "checks": [self.heat]})
        return self.run_manifest()

    def test_the_fortran_program_is_compiled_and_run_and_the_python_port_matches(self):
        done, summary = self.run_manifest()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        built = summary["checks"][0]["result"]["built"]["reference"]
        self.assertEqual(built["values"], 8)
        self.assertIn("GNU Fortran", built["versions"][0])
        self.assertTrue(built["reproduction"]["reproduces"])
        self.assertEqual(self.records()[-1]["detail"]["built"]["reference"]["versions"], built["versions"])

    def test_a_c_port_compiled_with_gcc_matches_too(self):
        c_port = {"steps": [["gcc", "-O0", "-ffp-contract=off", "src/heat.c", "-o", "{work}/heat_c"], ["{work}/heat_c"]],
                  "output": "stdout", "pinned": self.pins("src/heat.c"), "timeout_s": 120}
        done, _ = self.run_check(c_port)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_translation_with_an_off_by_one_index_fails(self):
        """The classic port error: the stencil reads u[i + 1] where the Fortran 1-based loop ends one earlier."""
        (self.repo / "src" / "heat.py").write_text(PORT.replace("range(1, n - 1)", "range(1, n)").replace(
            "u[i + 1] - 2.0", "u[(i + 1) % n] - 2.0"))
        done, summary = self.run_check({"steps": [[PY, "src/heat.py"]], "output": "stdout", "pinned": self.pins("src/heat.py")})
        self.assertEqual(done.returncode, 1)
        self.assertGreater(summary["checks"][0]["result"]["points_outside_tolerance"], 0)

    def test_a_syntax_error_in_the_legacy_source_is_a_build_failure_with_the_compiler_message(self):
        (self.repo / "legacy" / "heat.f90").write_text(FORTRAN.replace("end program heat", "end progrm heat"))
        self.fortran["pinned"] = self.pins("legacy/heat.f90")
        self.write({"schema": rm.SCHEMA, "checks": [self.heat]})
        done, summary = self.run_manifest()
        self.assertEqual(done.returncode, 1)
        self.assertIn("step 1 failed", summary["checks"][0]["result"]["reason"])
        self.assertIn("Error", summary["checks"][0]["result"]["reason"])

    def test_editing_the_fortran_source_without_updating_the_pin_is_caught(self):
        (self.repo / "legacy" / "heat.f90").write_text(FORTRAN.replace("alpha = 0.3d0", "alpha = 0.31d0"))
        done, summary = self.run_manifest()
        self.assertEqual(done.returncode, 1)
        self.assertIn("legacy/heat.f90", summary["checks"][0]["result"]["reason"])


if __name__ == "__main__":
    unittest.main()
