---
name: check-against-reference
description: Run the user's solver on a canonical problem (Kepler's equation, Lane-Emden, Sod shock tube, Robertson kinetics), measure its order of convergence on ODE and BVP problems with exact solutions, check that it is reproducible, or compare its output with golden data. Gives a pass/fail verdict from a script with stated tolerances, keeps an evidence log, and re-runs a committed manifest of checks in CI. Use when validating or claiming a solver is correct.
argument-hint: "<kepler|lane-emden|sod|robertson> --solver FILE.py:func [--tol X] [--repeat 2]  |  convergence-ode|convergence-bvp --order P  |  compare --ref F --test F --rtol R --atol A  |  run-manifest  |  evidence fresh --subject FILE"
---

# /sciencestack:check-against-reference

The script decides. Claude must not judge a solver "validated" by eyeballing numbers: run the check, report its
exit status and errors, and state the tolerance that was used and why.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_against_reference.py" list                       # contracts, references, rules
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_against_reference.py" run kepler --solver mysolver.py:solve
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_against_reference.py" run sod --solver mysolver.py:solve --tol 0.05 --report sod.md --json sod.json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_against_reference.py" compare --ref golden.txt --test mine.txt --rtol 1e-9 --atol 1e-12
```

The user's solver is imported and called in this process (per-call timeout, `--timeout-s`, default 120 s).
Read the solver first; run it only if the user is content for it to run.

## Benchmarks (v1)

| Name | Your function | Reference | Tolerance |
|---|---|---|---|
| `kepler` | `solve(M, e) -> E` (radians, \|M\| <= 100, 0 <= e < 1; a shift by 2 pi is accepted) | bisection on Kepler's equation, and the equation's own residual | default 1e-12 absolute |
| `lane-emden` | `solve(n) -> {"xi_1", "omega_n"}` for n = 0, 1, 1.5, 3 | closed forms (n = 0, 1); integration agreeing with Chandrasekhar's table (n = 1.5, 3) | **`--tol` required**, relative |
| `sod` | `solve(x, t) -> {"density", "velocity", "pressure"[, "x"]}`, t = 0.2 on [0, 1] | exact Riemann solution (Toro 2009, test 1) | **`--tol` required**, relative L1 per field |
| `robertson` | `solve(t) -> [y1, y2, y3]` from (1, 0, 0), t = 0.4 ... 1e5 | stored values from three implicit integrators, plus the mass invariant y1+y2+y3 = 1 | **`--tol` required**, relative per component |

| `convergence-ode` | `integrate(f, y0, t0, t1, n_steps) -> y(t1)` (`f(t, y)` and `y` are lists) | four problems with exact solutions: decay, oscillator, `y' = y^2`, time-dependent `y' = 2ty` | claim `--order P`; margin default 0.25 (`--tol`), smallest 0.05 |
| `convergence-bvp` | `solve(n, f) -> [u_0 .. u_n]` for `-u'' = f` on (0,1), `u(0)=u(1)=0` | two problems with exact solutions: `sin(pi x)` and `x^3 - x^4` | claim `--order P`; margin as above; max-norm and discrete L2 both judged |

`compare` checks the user's own golden data: `|test - ref| <= atol + rtol * |ref|`, elementwise; both tolerances are
required.

## Order of convergence (`convergence-ode`, `convergence-bvp`)

"Is this a fourth-order method?" is answered by measurement, not by reading the code: the solver is run at N, 2N, 4N, ...
(`--steps` N, default 16 for ODE and 8 for BVP; `--levels`, default 5), and the observed order `log2(e_N / e_2N)` is
compared with the claim.

- You must state `--order` (the order you claim). The check passes only if the **two finest** resolved pairwise orders
  are each at least `order - margin` (margin 0.25 by default, `--tol`); coarse, pre-asymptotic levels are shown but not
  judged, and a higher observed order is fine. The error must fall at every refinement.
- Errors at or below 1e-11 are roundoff, not truncation, and are discarded. With fewer than three levels above that floor
  the check **fails with advice** (a high-order method may need `--steps 4`): it never passes on too little evidence.
- The time-dependent ODE problem exists to catch a stepper that does not advance `t` between stages: such a method looks
  fine on autonomous problems and collapses to first order on this one.
- A larger margin than 0.25 is allowed and marked relaxed. In the evidence the requirement is recorded as the minimum
  observed order (`order_min`) and the number of levels (`levels_min`), so lowering the claim, widening the margin or
  using fewer levels after a failure is withheld like any other loosening.

## Reproducibility (`--repeat`, default 2)

`--repeat` defaults to 2: the solver is called twice (up to 10 times) on every input and the case fails if the answers differ by more than
`--repeat-tol` (relative to 1 + |value|, default 0 = identical). This catches unseeded randomness, state kept between
calls, and a solver that overwrites its input in place. Pass `--repeat 1` only to skip the check. Threaded reductions can legitimately differ in the last bits:
state a `--repeat-tol` (for example 1e-12) rather than dropping the check. Fewer repeats or a larger `--repeat-tol`
after a failure is withheld. In a manifest, omitted `repeat` means 2. `repeat_tol` needs `repeat` of at least 2 (the default counts).
The child process is started with `PYTHONHASHSEED=0`, `OMP_NUM_THREADS=1` and `MKL_NUM_THREADS=1`. `PYTHONHASHSEED` does not reseed the current interpreter.

## Tolerance rules (do not work around them)

- A benchmark whose error is set by the solver's own discretisation has **no default**: the tolerance is the user's
  stated, justified choice. Do not pick one only so that the run passes. If the user has no number, ask what
  accuracy the application needs, or run `--tol` at several values and report the measured errors.
- `kepler` has a default (1e-12) and the convergence benchmarks a default margin (0.25). A larger `--tol` is allowed but the result says **relaxed**; say so when you report it.
- A tolerance finer than the reference can resolve is refused (exit 2). `list` shows the smallest accepted value
  and the reference uncertainty for each benchmark.

## Exit status and what to report

- **0** every case passed. **1** a case failed: wrong value, solver raised, NaN/Inf, wrong shape, timeout.
  **2** nothing was checked (bad arguments, tolerance refused, solver cannot be loaded, evidence not recorded).
  **3** verdict withheld or manifest weakened (see below).
- Report "passes the `<benchmark>` check at tolerance X" only for exit 0, and quote the tolerance, the number of
  cases and the largest error. Passing a benchmark does not validate the solver outside the cases tested.
- Exit 1 or 2 is not a pass. Report which case failed and the reason; do not change the tolerance to make it pass.

## Evidence log (every `run` and `compare` writes one)

Each run appends a line to `./.verification/log.jsonl` (`--evidence-dir` or `$VERIFICATION_EVIDENCE_DIR` to move it,
`--no-evidence` to skip it): the verdict, the tolerance, and the SHA-256 of the solver file (or of the reference and test
files). Lines are hash-chained, so an edited or removed line is detected by `evidence verify`.

- `evidence fresh --subject solver.py` exits 0 only if the latest record for that file is a pass **and the file is
  unchanged since**. Before saying a solver is validated, run it (or run the check again); a stale or missing record is not evidence.
- **Exit 3, verdict withheld:** the tolerance is looser than in the previous *failed* run of the same check (a larger limit, a smaller `*_min`, or a dropped numeric key) and the primary files did not change. Fix the solver. A `--justify` sentence is recorded and does not release the verdict. Release needs `tolerance-approvals.json` (schema `verification-tolerance-approvals/1`) naming the check key, the SHA-256 of the previous failed log line, the old tolerance, the new tolerance, and a reason of at least 10 characters. A manifest `approved_relaxation` writes that entry from the previous failed log line; it is not a `--justify` sentence. If the solver did change, the run is allowed and only flagged. Repeating the command does not release it, and files named with `--subject` cannot release it. A new `--evidence-dir` starts an empty history; a clean re-run in CI is the gate.
- If the log cannot be written, a pass becomes exit 2 (a pass without evidence is not a pass); a failure stays 1.
- Limits: the log is a local file. Anything running as the user can rewrite the whole file, and a truncated tail is not
  detected. Only a clean re-run in CI is an unforgeable gate (next section).

## Manifest and CI

`reference-checks.json` in the project root lists the checks the project must pass (`examples/reference-checks.example.json`):
an id, a **rationale** (why this benchmark, why this tolerance), the benchmark and solver (or a golden `compare`), and a
tolerance. Paths are repo-relative.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_against_reference.py" check-manifest                 # validate only
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_against_reference.py" run-manifest --baseline-ref origin/main
```

`run-manifest` runs each check in a fresh interpreter. With `--baseline-ref` it compares the manifest with the one on that
git ref and exits 3 if a check was removed (unless `--allow-removed ID`), a tolerance was raised, or a check now compares
against something else, unless that check carries an `approved_relaxation` reason in the manifest (printed as APPROVED
RELAXATION). The highest exit code of all checks and the ratchet wins. `examples/reference-checks.workflow.yml` is a CI
template; copy it to `.github/workflows/` yourself.

## Building both sides instead of trusting files (`ref_from`, `test_from`)

A `compare` check trusts the two files it compares: nothing proves the "Fortran output" came from the Fortran program, or
the "Python output" from the port. In `reference-checks.json` either side can be **produced by running programs**:

```json
{"id": "heat", "rationale": "the Python port must reproduce the legacy Fortran heat code",
 "compare": {"ref": "golden/heat.out", "rtol": 1e-13, "atol": 0,
   "ref_from": {"steps": [["gfortran", "-O0", "-ffp-contract=off", "legacy/heat.f90", "-o", "{work}/heat"], ["{work}/heat", "inputs/heat.nml"]],
                "output": "stdout", "pinned": {"legacy/heat.f90": "<sha256>", "inputs/heat.nml": "<sha256>"},
                "reproduce_rtol": 1e-13, "reproduce_atol": 0, "record_versions": [["gfortran", "--version"]], "timeout_s": 300},
   "test_from": {"steps": [["python3", "src/heat.py", "inputs/heat.nml"]], "output": "stdout",
                 "pinned": {"src/heat.py": "<sha256>", "inputs/heat.nml": "<sha256>"}}}}
```

- **`pinned`** (required): the SHA-256 of every source and input the numbers come from (`sha256sum legacy/heat.f90`). A
  mismatch fails the check before anything runs, so changing the legacy code or its inputs is a visible edit of the manifest.
- **`steps`**: argument lists run in order in the repository directory, **never through a shell**; `{work}` is a temporary
  directory and `{repo}` the repository directory; `LC_ALL=C`; each step has `timeout_s` (default 300). `output` is `"stdout"`
  (numbers only: whitespace/commas, Fortran `D` exponents allowed) or `"file:{work}/<name>"`.
- **`ref_from`** also needs `reproduce_rtol/atol`: the committed `ref` file must reproduce the rebuilt numbers within them (they
  are separate because compilers and flags do not agree bit for bit). The **rebuilt** reference is what is compared. Use
  `-O0 -ffp-contract=off` or similar when a bitwise-comparable build matters.
- **`test_from`** replaces the `test` path: the output of the port is produced on every run. Give `ref_from`, `test_from`, or both.
- `run-manifest --refresh-reference ID` rewrites the committed reference from its recipe and says how much it changed; the
  result is a diff for a person to review. It never runs by itself.
- The evidence is bound to the pinned files (stable repo-relative paths), so a tolerance loosened after a failure on unchanged
  sources is withheld like any other; compiler version lines (`record_versions`) are kept in the record.
- The ratchet treats **a changed recipe** (steps, output, pins, or reproduce tolerances) as a changed reference: a violation
  unless the check carries an `approved_relaxation`; dropping `ref_from` is a loosening; adding one is not.

**Security: the steps are commands.** Running a manifest runs them with your privileges, like running a build script. Run only a
manifest you trust; in CI do not run it for pull requests from untrusted forks. There is no sandbox; the timeout only stops runaways.
It proves the comparison uses outputs actually produced from the pinned sources and inputs. It does not prove the legacy program
itself is right.

## Not covered

The benchmarks above and golden-data comparison. The convergence benchmarks cover time integrators for ODEs and 1-D
second-order boundary-value problems only: for a PDE solver, a different equation or a multi-dimensional grid, use
`mms_generator.py` to build a manufactured-solution test, or `compare` with golden data. There is no N-body or
coordinate-transform benchmark, and no check of conservation laws on the user's own code beyond the Robertson mass
invariant.
