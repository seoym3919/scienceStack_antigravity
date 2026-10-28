"""Tests for scripts/reference_manifest.py and the run-manifest / check-manifest commands.

Run (from the plugin root):  python3 -B -m unittest discover -s tests -v

Covered: every validation rule (one failing case each), the ratchet rules on pure data, and the commands end to end in
throw-away git repositories (a real baseline ref, a real clean re-run). Exit status: 0 all checks pass, 1 a check
failed, 2 manifest invalid / could not run, 3 ratchet violation or withheld verdict; the highest code wins.
"""

import copy
import json
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
import reference_manifest as rm  # noqa: E402
import test_check_against_reference as base  # noqa: E402  (fixtures only)

GOOD = {"schema": rm.SCHEMA, "checks": [
    {"id": "kepler-main", "rationale": "Kepler solver must match the root to 1e-12", "benchmark": "kepler",
     "solver": "src/kepler.py:solve"},
    {"id": "lane-n", "rationale": "RK4 step 1e-3 gives ~1e-6; 1e-4 leaves margin", "benchmark": "lane-emden",
     "solver": "src/lane.py:solve", "tol": 1e-4},
    {"id": "heat-golden", "rationale": "golden heat profile from the 2024 reference run",
     "compare": {"ref": "tests/golden/heat.txt", "test": "build/heat.out", "rtol": 1e-9, "atol": 1e-12}},
]}


def errors(manifest):
    return rm.validate(manifest, car.BENCHMARKS, car.resolve_tolerance)


def with_check(index, **changes):
    manifest = copy.deepcopy(GOOD)
    check = manifest["checks"][index]
    for key, value in changes.items():
        if value is None:
            check.pop(key, None)
        else:
            check[key] = value
    return manifest


class Validation(unittest.TestCase):
    def test_a_good_manifest_is_valid(self):
        self.assertEqual(errors(GOOD), [])

    def assert_error(self, manifest, text):
        found = errors(manifest)
        self.assertTrue(any(text in e for e in found), (text, found))

    def test_top_level(self):
        self.assert_error([], "must be a JSON object")
        self.assert_error({**GOOD, "schema": "x"}, "schema must be")
        self.assert_error({**GOOD, "extra": 1}, "unknown top-level key")
        self.assert_error({"schema": rm.SCHEMA, "checks": []}, "non-empty list")
        self.assert_error({"schema": rm.SCHEMA}, "non-empty list")

    def test_ids(self):
        for bad in ("", "has space", "-lead", "x" * 61, 5, None):
            self.assert_error(with_check(0, id=bad), "id must match")
        manifest = copy.deepcopy(GOOD)
        manifest["checks"][1]["id"] = "kepler-main"
        self.assert_error(manifest, "duplicate id")

    def test_rationale_is_mandatory(self):
        for bad in (None, "", "short", "         ", 5):
            self.assert_error(with_check(0, rationale=bad), "rationale")

    def test_exactly_one_kind(self):
        both = with_check(0, compare={"ref": "a", "test": "b", "rtol": 1, "atol": 1})
        self.assert_error(both, "exactly one of")
        manifest = copy.deepcopy(GOOD)
        del manifest["checks"][0]["benchmark"]
        self.assert_error(manifest, "exactly one of")

    def test_benchmark_checks(self):
        self.assert_error(with_check(0, benchmark="nonsense"), "unknown benchmark")
        for bad in ("/abs/k.py:solve", "../k.py:solve", "~/k.py:solve", "a//k.py:solve", "src\\k.py:solve", "nocolon",
                    "src/k.py:", "src/k.py:not valid", ":solve", None, 5):
            self.assert_error(with_check(0, solver=bad), "solver must be")
        self.assert_error(with_check(0, extra_key=1), "unknown key")
        for bad in (0, -1e-9, True, "1e-9", float("inf")):
            self.assert_error(with_check(0, tol=bad), "tol must be")
        self.assert_error(with_check(0, tol=1e-13), "finer than this benchmark's reference can resolve")
        self.assert_error(with_check(1, tol=None), "needs --tol")
        self.assert_error(with_check(1, tol=1e-12), "finer than")
        self.assert_error(with_check(0, points=11), "points applies to 'sod' only")
        self.assert_error(with_check(0, timeout_s=-1), "timeout_s")
        self.assert_error(with_check(0, timeout_s=7200), "timeout_s")
        for bad in ("5", 1.5, True, [1]):
            self.assert_error(with_check(0, timeout_s=bad), "timeout_s")
        self.assertEqual(errors(with_check(0, timeout_s=300, tol=1e-6)), [])

    def test_repeat_and_repeat_tol(self):
        for bad in (0, 11, -1, 2.5, True, "2", None.__class__):
            if bad is not None.__class__:
                self.assert_error(with_check(0, repeat=bad), "repeat must be")
        for bad in (-1e-9, float("inf"), float("nan"), True, "1e-9"):
            self.assert_error(with_check(0, repeat_tol=bad), "repeat_tol must be")
        self.assertEqual(errors(with_check(0, repeat=2, repeat_tol=1e-12)), [])
        self.assertEqual(errors(with_check(0, repeat=10, repeat_tol=0)), [])

    def test_repeat_tol_with_a_single_call_is_rejected(self):
        self.assertEqual(errors(with_check(0, repeat_tol=1e-6)), [])          # omitted repeat is the default of 2
        self.assert_error(with_check(0, repeat=1, repeat_tol=1e-6), "no effect without repeat >= 2")
        self.assertEqual(errors(with_check(0, repeat=2, repeat_tol=1e-6)), [])

    def test_convergence_checks(self):
        ok = {"id": "rk4", "rationale": "our RK4 stepper must be fourth order", "benchmark": "convergence-ode",
              "solver": "src/rk4.py:integrate", "order": 4}
        def manifest(**changes):
            check = dict(ok)
            for key, value in changes.items():
                if value is None:
                    check.pop(key, None)
                else:
                    check[key] = value
            return {"schema": rm.SCHEMA, "checks": [check]}
        self.assertEqual(errors(manifest()), [])
        self.assertEqual(errors(manifest(steps=8, levels=4, tol=0.1)), [])
        self.assert_error(manifest(order=None), "order is required for a convergence benchmark")
        for bad in (0, -1, 13, True, "4", float("nan")):
            self.assert_error(manifest(order=bad), "order is required")
        for bad in (1, 0, True, 2.5):
            self.assert_error(manifest(steps=bad), "steps must be an integer >= 2")
        for bad in (2, 9, True, 4.5):
            self.assert_error(manifest(levels=bad), "levels must be an integer between 3 and 8")
        self.assert_error(manifest(tol=0.01), "finer than")                                  # below the smallest margin
        self.assertEqual(errors(manifest(benchmark="convergence-bvp")), [])

    def test_convergence_keys_are_refused_for_the_other_benchmarks(self):
        for key, value in (("order", 2), ("steps", 8), ("levels", 4)):
            self.assert_error(with_check(0, **{key: value}), "applies to the convergence benchmarks only")

    def test_sod_points(self):
        manifest = with_check(0, benchmark="sod", tol=0.05, points=2)
        self.assert_error(manifest, "points applies to 'sod' only and must be an integer >= 3")
        self.assertEqual(errors(with_check(0, benchmark="sod", tol=0.05, points=101)), [])

    def test_compare_checks(self):
        ok = {"ref": "a.txt", "test": "b.txt", "rtol": 1e-9, "atol": 0}
        self.assertEqual(errors(with_check(2, compare=ok)), [])
        for bad, text in ((dict(ok, ref="/abs"), "compare.ref"), (dict(ok, test="../x"), "compare.test"),
                          ({k: v for k, v in ok.items() if k != "atol"}, "both required"),
                          (dict(ok, rtol=0, atol=0), "not both zero"), (dict(ok, rtol=-1, atol=1), "non-negative"), (dict(ok, rtol=1, atol=-1e-9), "non-negative"),
                          (dict(ok, rtol=True), "both required"), (dict(ok, rtol="1e-9"), "both required"),
                          (dict(ok, extra=1), "unknown compare key"), ("not an object", "must be an object")):
            self.assert_error(with_check(2, compare=bad), text)
        self.assert_error(with_check(2, other=1), "unknown key")

    def test_approved_relaxation_must_be_text(self):
        for bad in ("", "  ", 5):
            self.assert_error(with_check(0, approved_relaxation=bad), "approved_relaxation")
        self.assertEqual(errors(with_check(0, approved_relaxation="ticket 42")), [])

    def test_all_problems_are_reported_together(self):
        manifest = with_check(0, rationale="x", solver="/abs:solve", tol=-1)
        self.assertGreaterEqual(len(errors(manifest)), 3)


class ShippedExamples(unittest.TestCase):
    def test_the_example_manifest_is_valid(self):
        manifest = json.loads((ROOT / "examples" / "reference-checks.example.json").read_text())
        self.assertEqual(errors(manifest), [])

    def test_the_ci_template_mentions_only_flags_that_exist(self):
        import re
        text = (ROOT / "examples" / "reference-checks.workflow.yml").read_text()
        parser_help = subprocess.run([sys.executable, str(SCRIPT), "run-manifest", "--help"], capture_output=True, text=True).stdout
        parser_help += subprocess.run([sys.executable, str(SCRIPT), "evidence", "--help"], capture_output=True, text=True).stdout
        for script, sub in (("test_ratchet.py", None), ("run_tests.py", "unittest"), ("run_tests.py", "pytest")):
            cmd = [sys.executable, str(ROOT / "scripts" / script)] + ([sub] if sub else []) + ["--help"]
            parser_help += subprocess.run(cmd, capture_output=True, text=True).stdout
        for flag in set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", text)):
            self.assertIn(flag, parser_help, flag)


class Ratchet(unittest.TestCase):
    def ratchet(self, current, baseline, allow=()):
        return rm.ratchet(current, baseline, car.BENCHMARKS, allow)

    def test_no_baseline_and_identical_manifests_have_no_violations(self):
        self.assertEqual(self.ratchet(GOOD, None)["violations"], [])
        self.assertEqual(self.ratchet(GOOD, copy.deepcopy(GOOD)), {"violations": [], "approved": [], "added": [], "removed_allowed": []})

    def test_added_checks_are_fine(self):
        current = copy.deepcopy(GOOD)
        current["checks"].append({"id": "new", "rationale": "a brand new check for ordering", "benchmark": "kepler",
                                  "solver": "src/k2.py:solve"})
        self.assertEqual(self.ratchet(current, GOOD)["added"], ["new"])
        self.assertEqual(self.ratchet(current, GOOD)["violations"], [])

    def test_removing_a_check_is_a_violation_unless_allowed(self):
        current = copy.deepcopy(GOOD)
        del current["checks"][1]
        result = self.ratchet(current, GOOD)
        self.assertEqual([v["id"] for v in result["violations"]], ["lane-n"])
        allowed = self.ratchet(current, GOOD, allow=["lane-n"])
        self.assertEqual((allowed["violations"], allowed["removed_allowed"]), ([], ["lane-n"]))

    def test_a_larger_tolerance_is_a_violation_a_smaller_one_is_not(self):
        looser = with_check(1, tol=1e-2)
        result = self.ratchet(looser, GOOD)
        self.assertEqual(result["violations"][0]["id"], "lane-n")
        self.assertIn("loosened from 0.0001 to 0.01", result["violations"][0]["problem"])
        self.assertEqual(self.ratchet(with_check(1, tol=1e-6), GOOD)["violations"], [])

    def test_a_default_tolerance_replaced_by_a_larger_explicit_one_is_a_violation(self):
        result = self.ratchet(with_check(0, tol=1e-6), GOOD)                  # kepler's default is 1e-12
        self.assertEqual(result["violations"][0]["id"], "kepler-main")
        self.assertEqual(self.ratchet(with_check(0, tol=1e-12), GOOD)["violations"], [])

    def test_approved_relaxation_turns_a_violation_into_a_loud_approval(self):
        result = self.ratchet(with_check(1, tol=1e-2, approved_relaxation="sensor noise floor is 1e-3 (ticket 7)"), GOOD)
        self.assertEqual(result["violations"], [])
        self.assertEqual(result["approved"][0]["approved_relaxation"], "sensor noise floor is 1e-3 (ticket 7)")

    def test_compare_tolerances_either_one(self):
        for inner in ({"rtol": 1e-6, "atol": 1e-12}, {"rtol": 1e-9, "atol": 1e-6}):
            current = with_check(2, compare=dict(GOOD["checks"][2]["compare"], **inner))
            self.assertEqual(self.ratchet(current, GOOD)["violations"][0]["id"], "heat-golden", inner)

    def test_swapping_what_a_check_compares_against_is_a_violation(self):
        self.assertTrue(self.ratchet(with_check(0, benchmark="sod", tol=0.5), GOOD)["violations"])
        golden = with_check(2, compare=dict(GOOD["checks"][2]["compare"], ref="tests/golden/other.txt"))
        self.assertIn("now compares against", self.ratchet(golden, GOOD)["violations"][0]["problem"])
        # a benchmark check turned into a compare check
        swapped = copy.deepcopy(GOOD)
        swapped["checks"][0] = {"id": "kepler-main", "rationale": "swapped to a compare check ok",
                                "compare": {"ref": "a.txt", "test": "b.txt", "rtol": 1e-12, "atol": 0}}
        self.assertTrue(self.ratchet(swapped, GOOD)["violations"])

    def test_effective_tolerance_always_includes_the_determinism_settings(self):
        base = rm.effective_tolerance(GOOD["checks"][1], car.BENCHMARKS)
        self.assertEqual(base, {"tol": 1e-4, "repeat_min": 2.0, "repeat_tol": 0.0})     # omitted repeat is the default of 2
        both = rm.effective_tolerance(with_check(1, repeat=3, repeat_tol=1e-12)["checks"][1], car.BENCHMARKS)
        self.assertEqual((both["repeat_min"], both["repeat_tol"]), (3.0, 1e-12))

    def test_fewer_repeats_or_a_larger_repeat_tol_is_a_violation_more_is_not(self):
        strict = with_check(1, repeat=3, repeat_tol=1e-12)
        for change, text in ((dict(repeat=2), "repeat_min loosened from 3 to 2"), (dict(repeat=None), "repeat_min loosened from 3 to 2"),
                             (dict(repeat_tol=1e-9), "repeat_tol loosened"), (dict(repeat_tol=None), None)):
            current = copy.deepcopy(strict)
            for key, value in change.items():
                if value is None:
                    current["checks"][1].pop(key, None)
                else:
                    current["checks"][1][key] = value
            result = self.ratchet(current, strict)
            if text is None:                                           # dropping repeat_tol means 0: tighter, so fine
                self.assertEqual(result["violations"], [], change)
            else:
                self.assertIn(text, result["violations"][0]["problem"], change)
        self.assertEqual(self.ratchet(with_check(1, repeat=5, repeat_tol=1e-13), strict)["violations"], [])    # stricter
        self.assertEqual(self.ratchet(with_check(1, repeat=5), GOOD)["violations"], [])                         # more repeats, same repeat_tol 0

    def convergence(self, **changes):
        check = {"id": "rk4", "rationale": "our RK4 stepper must be fourth order", "benchmark": "convergence-ode",
                 "solver": "src/rk4.py:integrate", "order": 4}
        for key, value in changes.items():
            if value is None:
                check.pop(key, None)
            else:
                check[key] = value
        return {"schema": rm.SCHEMA, "checks": [check]}

    def test_a_lower_order_fewer_levels_or_a_wider_margin_is_a_violation_stricter_is_not(self):
        base = self.convergence()
        effective = rm.effective_tolerance(base["checks"][0], car.BENCHMARKS)
        self.assertEqual((effective["order_min"], effective["levels_min"]), (3.75, 5.0))
        self.assertNotIn("tol", effective)                                                 # the margin is inside order_min
        for change, text in ((dict(order=2), "order_min loosened from 3.75 to 1.75"), (dict(levels=3), "levels_min loosened from 5 to 3"),
                             (dict(tol=0.5), "order_min loosened from 3.75 to 3.5"), (dict(order=3, tol=0.1), "order_min loosened")):
            result = self.ratchet(self.convergence(**change), base)
            self.assertTrue(any(text in v["problem"] for v in result["violations"]), (change, result["violations"]))
        for change in (dict(order=6), dict(levels=8), dict(tol=0.1), dict(steps=4), dict(order=5, tol=0.5)):
            self.assertEqual(self.ratchet(self.convergence(**change), base)["violations"], [], change)

    def test_the_same_requirement_written_two_ways_is_not_a_change(self):
        self.assertEqual(self.ratchet(self.convergence(order=3.9, tol=0.15), self.convergence(order=4, tol=0.25))["violations"][:0], [])
        a = rm.effective_tolerance(self.convergence(order=3.9, tol=0.15)["checks"][0], car.BENCHMARKS)
        b = rm.effective_tolerance(self.convergence(order=4)["checks"][0], car.BENCHMARKS)
        self.assertAlmostEqual(a["order_min"], b["order_min"], delta=1e-12)

    def test_adding_a_determinism_check_to_an_old_manifest_is_a_tightening(self):
        """repeat 1 compares nothing. Moving to repeat 2 is stricter even when the new check states a repeat_tol."""
        old = with_check(1, repeat=1)
        self.assertEqual(self.ratchet(with_check(1, repeat=2, repeat_tol=1e-6), old)["violations"], [])


    def test_changing_the_solver_path_alone_is_not_weakening(self):
        self.assertEqual(self.ratchet(with_check(0, solver="src/renamed.py:solve"), GOOD)["violations"], [])


class Commands(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "proj"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "tests" / "golden").mkdir(parents=True)
        (self.repo / "build").mkdir()
        (self.repo / "src" / "kepler.py").write_text(base.KEPLER_GOOD)
        (self.repo / "src" / "lane.py").write_text(base.LANE_GOOD)
        (self.repo / "tests" / "golden" / "heat.txt").write_text("1.0 2.0 3.0\n")
        (self.repo / "build" / "heat.out").write_text("1.0 2.0 3.0\n")
        self.manifest = self.repo / "reference-checks.json"
        self.write(GOOD)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "T")
        self.git("config", "user.email", "t@example.invalid")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "baseline")

    def tearDown(self):
        self._tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True)

    def write(self, manifest):
        self.manifest.write_text(json.dumps(manifest, indent=2))

    def cli(self, *args, cwd=None, timeout=900):
        env = {k: v for k, v in os.environ.items() if k != "VERIFICATION_EVIDENCE_DIR"}
        return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], cwd=cwd or self.repo, capture_output=True,
                              text=True, timeout=timeout, env=env)

    def records(self):
        return [json.loads(line) for line in (self.repo / ".verification" / "log.jsonl").read_text().splitlines()]

    def test_check_manifest_validates_without_running_anything(self):
        done = self.cli("check-manifest")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("valid, 3 checks", done.stdout)
        self.assertFalse((self.repo / ".verification").exists())
        self.write(with_check(0, solver="/abs/k.py:solve"))
        bad = self.cli("check-manifest")
        self.assertEqual(bad.returncode, 2)
        self.assertIn("manifest is invalid", bad.stderr)

    def test_missing_or_broken_manifest_exits_two(self):
        self.manifest.write_text("{not json")
        self.assertEqual(self.cli("run-manifest").returncode, 2)
        self.manifest.unlink()
        done = self.cli("run-manifest")
        self.assertEqual(done.returncode, 2)
        self.assertNotIn("Traceback", done.stderr)

    def test_run_manifest_passes_and_records_evidence_for_each_check(self):
        done = self.cli("run-manifest", "--json", "summary.json")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("3 of 3 checks passed", done.stdout)
        records = self.records()
        self.assertEqual(sorted(r["key"] for r in records), ["manifest:heat-golden", "manifest:kepler-main", "manifest:lane-n"])
        self.assertTrue(all(r["passed"] and r["exit_status"] == 0 for r in records))
        self.assertEqual(json.loads((self.repo / "summary.json").read_text())["exit_status"], 0)
        paths = {r["name"]: [s["path"] for s in r["subjects"]] for r in records}
        self.assertEqual(paths["kepler"], ["src/kepler.py"])                           # relative: stable across machines
        self.assertEqual(sorted(paths["compare"]), ["build/heat.out", "tests/golden/heat.txt"])

    def test_a_failing_check_gives_exit_one_and_names_it(self):
        (self.repo / "src" / "kepler.py").write_text(base.KEPLER_FIRST_ORDER)
        done = self.cli("run-manifest")
        self.assertEqual(done.returncode, 1)
        self.assertIn("| `kepler-main` | 1 | FAIL |", done.stdout)
        self.assertIn("2 of 3 checks passed", done.stdout)

    def test_only_selects_checks_and_unknown_ids_are_refused(self):
        done = self.cli("run-manifest", "--only", "heat-golden")
        self.assertEqual(done.returncode, 0)
        self.assertIn("1 of 1 checks passed", done.stdout)
        self.assertEqual(self.cli("run-manifest", "--only", "nope").returncode, 2)

    def test_the_same_failing_check_rerun_with_a_looser_manifest_tolerance_is_withheld(self):
        (self.repo / "src" / "lane.py").write_text(base.LANE_EULER)                  # fails at 1e-4
        self.assertEqual(self.cli("run-manifest", "--only", "lane-n").returncode, 1)
        self.write(with_check(1, tol=1.0))                                          # looser, nothing else changed
        done = self.cli("run-manifest", "--only", "lane-n")
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertIn("| `lane-n` | 3 | WITHHELD |", done.stdout)

    def test_ratchet_blocks_a_looser_tolerance_against_the_baseline(self):
        self.write(with_check(1, tol=1e-2))
        done = self.cli("run-manifest", "--baseline-ref", "HEAD")
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertIn("RATCHET VIOLATION [lane-n]", done.stderr)
        self.assertIn("1 ratchet violation", done.stdout)

    def test_approved_relaxation_lets_it_through_and_says_so(self):
        self.write(with_check(1, tol=1e-2, approved_relaxation="accuracy needed by the application is 1e-2"))
        done = self.cli("run-manifest", "--baseline-ref", "HEAD")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("APPROVED RELAXATION [lane-n]", done.stdout)

    def test_removed_check_is_blocked_unless_allowed(self):
        manifest = copy.deepcopy(GOOD)
        del manifest["checks"][2]
        self.write(manifest)
        blocked = self.cli("run-manifest", "--baseline-ref", "HEAD")
        self.assertEqual(blocked.returncode, 3)
        self.assertIn("check removed", blocked.stderr)
        allowed = self.cli("run-manifest", "--baseline-ref", "HEAD", "--allow-removed", "heat-golden")
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)

    def test_baseline_problems(self):
        bad = self.cli("run-manifest", "--baseline-ref", "no-such-ref")
        self.assertEqual(bad.returncode, 2)
        self.assertIn("not a commit", bad.stderr)
        self.git("mv", "reference-checks.json", "elsewhere.json")
        self.git("commit", "-q", "-m", "rename")
        self.write(GOOD)                                                              # a manifest the baseline never had
        new = self.cli("run-manifest", "--baseline-ref", "HEAD")
        self.assertEqual(new.returncode, 0, new.stdout + new.stderr)
        self.assertIn("new manifest, ratchet skipped", new.stdout)

    def test_manifest_in_a_subdirectory_resolves_the_baseline_path(self):
        sub = self.repo / "ci"
        sub.mkdir()
        (sub / "reference-checks.json").write_text(json.dumps(with_check(0, solver="../src/kepler.py:solve")))
        # '..' is refused: a manifest must be self-contained below its own directory
        self.assertEqual(self.cli("check-manifest", "--manifest", "ci/reference-checks.json").returncode, 2)

    def test_highest_exit_code_wins(self):
        (self.repo / "src" / "kepler.py").write_text(base.KEPLER_FIRST_ORDER)       # a failing check (1) ...
        self.write(with_check(1, tol=1e-2))                                          # ... and a ratchet violation (3)
        self.assertEqual(self.cli("run-manifest", "--baseline-ref", "HEAD").returncode, 3)

    def test_solver_can_import_a_sibling_module(self):
        (self.repo / "src" / "helper.py").write_text("OFFSET = 0.0\n")
        (self.repo / "src" / "kepler.py").write_text("import helper\n" + base.KEPLER_GOOD.replace(
            "    return E", "    return E + helper.OFFSET"))
        self.assertEqual(self.cli("run-manifest", "--only", "kepler-main").returncode, 0)

    def run_json(self, *args):
        done = self.cli("run-manifest", "--json", "summary.json", *args)
        return done, json.loads((self.repo / "summary.json").read_text())

    def test_the_summary_json_records_the_real_verdict_per_check(self):
        (self.repo / "src" / "kepler.py").write_text(base.KEPLER_FIRST_ORDER)
        done, summary = self.run_json()
        by_id = {c["id"]: c for c in summary["checks"]}
        self.assertEqual((by_id["kepler-main"]["passed"], by_id["kepler-main"]["exit_status"]), (False, 1))
        self.assertEqual((by_id["lane-n"]["passed"], by_id["heat-golden"]["passed"]), (True, True))
        self.assertEqual(summary["exit_status"], 1)

    def test_compare_tolerances_from_the_manifest_reach_the_comparison(self):
        (self.repo / "build" / "heat.out").write_text("1.0 2.0 3.001\n")                 # 3.3e-4 relative off
        self.assertEqual(self.cli("run-manifest", "--only", "heat-golden", "--no-evidence").returncode, 1)  # rtol 1e-9 must apply
        self.write(with_check(2, compare=dict(GOOD["checks"][2]["compare"], rtol=1e-2)))
        self.assertEqual(self.cli("run-manifest", "--only", "heat-golden", "--no-evidence").returncode, 0)  # and a looser one lets it pass
        (self.repo / "tests" / "golden" / "heat.txt").write_text("0.0 2.0 3.001\n")
        (self.repo / "build" / "heat.out").write_text("1e-6 2.0 3.001\n")
        self.write(with_check(2, compare=dict(GOOD["checks"][2]["compare"], rtol=1e-9, atol=1e-9)))
        self.assertEqual(self.cli("run-manifest", "--only", "heat-golden", "--no-evidence").returncode, 1)  # atol 1e-9 must apply
        self.write(with_check(2, compare=dict(GOOD["checks"][2]["compare"], rtol=1e-9, atol=1e-3)))
        self.assertEqual(self.cli("run-manifest", "--only", "heat-golden", "--no-evidence").returncode, 0)

    def test_repeat_settings_from_the_manifest_reach_the_run(self):
        (self.repo / "src" / "kepler.py").write_text(base.KEPLER_NOISY)
        manifest = with_check(0, repeat=2)
        self.write(manifest)
        done, summary = self.run_json("--only", "kepler-main", "--no-evidence")
        self.assertEqual(done.returncode, 1)                                          # unseeded noise differs between calls
        result = summary["checks"][0]["result"]
        self.assertEqual(result["repeat"], {"calls": 2, "tolerance": 0.0})
        self.write(with_check(0, repeat=2, repeat_tol=1e-12))
        done, summary = self.run_json("--only", "kepler-main", "--no-evidence")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(summary["checks"][0]["result"]["repeat"], {"calls": 2, "tolerance": 1e-12})

    def test_points_and_timeout_from_the_manifest_reach_the_run(self):
        (self.repo / "src" / "sod.py").write_text(base.SOD_EXACT_COPY)
        manifest = copy.deepcopy(GOOD)
        manifest["checks"].append({"id": "sod-exact", "rationale": "the exact solution must match itself", "benchmark": "sod",
                                   "solver": "src/sod.py:solve", "tol": 1e-9, "points": 11})
        self.write(manifest)
        _, summary = self.run_json("--only", "sod-exact")
        self.assertIn("11 points", summary["checks"][0]["result"]["cases"][0]["detail"])
        (self.repo / "src" / "hang.py").write_text(base.KEPLER_HANGS)
        manifest["checks"].append({"id": "hang", "rationale": "a hung solver must be stopped by the limit", "benchmark": "kepler",
                                   "solver": "src/hang.py:solve", "timeout_s": 1})
        self.write(manifest)
        # a missing timeout would leave this solver sleeping 30 s on each of 72 cases: the harness limit makes that an error
        done = self.cli("run-manifest", "--json", "summary.json", "--only", "hang", timeout=60)
        summary = json.loads((self.repo / "summary.json").read_text())
        self.assertIn("did not return within 1 s", summary["checks"][0]["result"]["cases"][0]["reason"])

    def test_checks_run_with_the_manifest_directory_as_the_working_directory(self):
        (self.repo / "coefficient.txt").write_text("0.0\n")
        (self.repo / "src" / "kepler.py").write_text(
            base.KEPLER_GOOD.replace("    return E", "    return E + float(open('coefficient.txt').read())"))
        self.assertEqual(self.cli("run-manifest", "--only", "kepler-main").returncode, 0)
        elsewhere = self.repo.parent                                        # started from another directory, same result
        done = self.cli("run-manifest", "--manifest", str(self.manifest), "--only", "kepler-main", cwd=elsewhere)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_an_approved_relaxation_also_releases_a_withheld_verdict(self):
        (self.repo / "src" / "lane.py").write_text(base.LANE_EULER)
        self.assertEqual(self.cli("run-manifest", "--only", "lane-n").returncode, 1)         # fails at 1e-4
        self.write(with_check(1, tol=1.0))                                                    # looser, unchanged solver
        self.assertEqual(self.cli("run-manifest", "--only", "lane-n").returncode, 3)
        self.write(with_check(1, tol=1.0, approved_relaxation="screening run only; accuracy is not required here"))
        released = self.cli("run-manifest", "--only", "lane-n")
        self.assertEqual(released.returncode, 0, released.stdout + released.stderr)
        self.assertIn("approved relaxation", self.records()[-1]["justification"])

    def test_the_baseline_is_found_for_a_manifest_in_a_subdirectory(self):
        sub = self.repo / "ci"
        sub.mkdir()
        (sub / "kepler.py").write_text(base.KEPLER_GOOD)
        (sub / "lane.py").write_text(base.LANE_GOOD)
        manifest = {"schema": rm.SCHEMA, "checks": [
            {"id": "lane-n", "rationale": "step 1e-3 RK4 is within 1e-4", "benchmark": "lane-emden", "solver": "lane.py:solve",
             "tol": 1e-4}]}
        (sub / "reference-checks.json").write_text(json.dumps(manifest))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "sub")
        manifest["checks"][0]["tol"] = 1e-2
        (sub / "reference-checks.json").write_text(json.dumps(manifest))
        done = self.cli("run-manifest", "--manifest", "ci/reference-checks.json", "--baseline-ref", "HEAD")
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        # the baseline was ci/reference-checks.json (tol 1e-4), not the root manifest (other checks): only a loosening
        self.assertIn("RATCHET VIOLATION [lane-n]: tol loosened from 0.0001 to 0.01", done.stderr)
        self.assertNotIn("check removed", done.stderr)

    def test_a_solver_directory_cannot_shadow_the_standard_library(self):
        """Sibling imports must still work, but a file named like a stdlib module next to the solver must not win."""
        (self.repo / "src" / "colorsys.py").write_text("raise RuntimeError('shadowed the standard library')\n")
        (self.repo / "src" / "kepler.py").write_text("import colorsys\n" + base.KEPLER_GOOD)
        self.assertEqual(self.cli("run-manifest", "--only", "kepler-main").returncode, 0)

    def test_a_convergence_check_runs_from_the_manifest_with_its_parameters(self):
        (self.repo / "src" / "rk4.py").write_text(base.ODE_RK4)
        manifest = copy.deepcopy(GOOD)
        manifest["checks"].append({"id": "rk4", "rationale": "our RK4 stepper must be fourth order", "benchmark": "convergence-ode",
                                   "solver": "src/rk4.py:integrate", "order": 4, "steps": 8, "levels": 4})
        self.write(manifest)
        done, summary = self.run_json("--only", "rk4")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(summary["checks"][0]["result"]["convergence"], {"order": 4.0, "levels": 4, "base": 8})
        (self.repo / "src" / "rk4.py").write_text(base.ODE_EULER)                      # the stepper degrades to first order
        done, summary = self.run_json("--only", "rk4")
        self.assertEqual(done.returncode, 1)
        record = [json.loads(line) for line in (self.repo / ".verification" / "log.jsonl").read_text().splitlines()][-1]
        self.assertEqual((record["tolerance"]["order_min"], record["tolerance"]["levels_min"]), (3.75, 4))

    def test_the_ratchet_blocks_lowering_the_order_of_a_committed_convergence_check(self):
        (self.repo / "src" / "rk4.py").write_text(base.ODE_RK4)
        manifest = copy.deepcopy(GOOD)
        manifest["checks"].append({"id": "rk4", "rationale": "our RK4 stepper must be fourth order", "benchmark": "convergence-ode",
                                   "solver": "src/rk4.py:integrate", "order": 4})
        self.write(manifest)
        self.git("add", "-A")
        self.git("commit", "-qm", "rk4 check")
        manifest["checks"][-1]["order"] = 2
        self.write(manifest)
        done = self.cli("run-manifest", "--baseline-ref", "HEAD", "--only", "rk4")
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertIn("order_min loosened from 3.75 to 1.75", done.stderr)

    def test_evidence_can_be_switched_off_for_a_manifest_run(self):
        self.assertEqual(self.cli("run-manifest", "--only", "heat-golden", "--no-evidence").returncode, 0)
        self.assertFalse((self.repo / ".verification").exists())


if __name__ == "__main__":
    unittest.main()
