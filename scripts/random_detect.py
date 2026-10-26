#!/usr/bin/env python3
r"""
random_detect.py - find sources of run-to-run nondeterminism in Python solver code.

Used by audit_numerical_ast.py (warnings, so `--strict` turns them into a failing exit status). Standard library only.
Import-aware: `import numpy as np`, `from numpy import random as npr`, `from numpy.random import default_rng`,
`import random as rnd`, ... are all resolved before anything is judged. Nothing is executed.

Findings (all WARNING):

  UNSEEDED_RANDOM_DRAW      a draw from a global random state (numpy.random.rand/normal/..., random.random/gauss/...,
                            torch.rand/randn/...) in a file that never seeds that state. Seeded in another file
                            (conftest, main)? Then this is a false positive; seed where the draws are made.
  UNSEEDED_GENERATOR        numpy.random.default_rng() / RandomState() / Generator(PCG64()) / random.Random() /
                            SeedSequence() with no seed, or seed=None: OS entropy, different on every run.
  NONDETERMINISTIC_SEED     seed(None), seed() with no argument, or a seed derived from the clock, the process id,
                            os.urandom or uuid (time.time(), os.getpid(), ...): different on every run.
  NONDETERMINISTIC_SOURCE   os.urandom, secrets.*, random.SystemRandom, torch.seed(): cannot be seeded at all.

A seed held in a variable (default_rng(seed), rng = default_rng(rng_arg)) is accepted: its value is not knowable here.
Not covered: JAX (explicit keys are deterministic), TensorFlow/Keras global seeds, scikit-learn `random_state=None`
defaults, set/dict iteration order, hash randomisation, thread scheduling.
"""

from __future__ import annotations

import ast
from typing import Dict, List, NamedTuple, Optional, Sequence

from inversion_detect import dotted


class Finding(NamedTuple):
    node: ast.AST
    code: str
    message: str
    suggestion: str


NUMPY_NON_DRAWS = {"seed", "default_rng", "RandomState", "Generator", "SeedSequence", "BitGenerator", "PCG64", "PCG64DXSM",
                   "MT19937", "Philox", "SFC64", "get_state", "set_state", "get_bit_generator", "set_bit_generator",
                   "bit_generator"}
GENERATOR_CONSTRUCTORS = {"numpy.random.default_rng", "numpy.random.RandomState", "numpy.random.SeedSequence",
                    "numpy.random.PCG64", "numpy.random.PCG64DXSM", "numpy.random.MT19937", "numpy.random.Philox",
                    "numpy.random.SFC64", "numpy.random.mtrand.RandomState", "numpy.random.bit_generator.SeedSequence",
                    "random.Random"}
STDLIB_NON_DRAWS = {"seed", "Random", "SystemRandom", "getstate", "setstate"}
TORCH_DRAWS = {"rand", "randn", "randint", "randperm", "normal", "bernoulli", "multinomial", "poisson", "rand_like",
               "randn_like", "randint_like"}
SEEDERS = {"numpy.random.seed", "random.seed", "torch.manual_seed", "torch.random.manual_seed"}
STATE_OF = {"numpy.random.seed": "numpy", "random.seed": "random", "torch.manual_seed": "torch",
            "torch.random.manual_seed": "torch"}
UNSEEDABLE = {"os.urandom", "random.SystemRandom", "torch.seed", "torch.random.seed"}
NONDET_CALLS = {"time.time", "time.time_ns", "time.perf_counter", "time.perf_counter_ns", "time.monotonic",
                "time.monotonic_ns", "time.process_time", "datetime.datetime.now", "datetime.datetime.utcnow",
                "datetime.datetime.today", "os.getpid", "os.urandom", "uuid.uuid1", "uuid.uuid4", "uuid.getnode"}


def resolve(func: ast.AST, aliases: Dict[str, str]) -> Optional[str]:
    """Fully qualified dotted name of a callee ('np.random.rand' -> 'numpy.random.rand'), or None."""
    name = dotted(func)
    if name is None:
        return None
    head, _, rest = name.partition(".")
    base = aliases.get(head)
    if base is None:
        return name
    return f"{base}.{rest}" if rest else base


def _is_none(node: Optional[ast.AST]) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _seed_argument(call: ast.Call) -> Optional[ast.AST]:
    """The seed/entropy argument of a constructor or seed() call (first positional, or seed= / entropy=), else None."""
    if call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg in ("seed", "entropy", "x", "a"):
            return keyword.value
    return None


def _nondeterministic_expression(node: ast.AST, aliases: Dict[str, str]) -> Optional[str]:
    """The name of a clock/pid/entropy call inside `node`, if any."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            name = resolve(sub.func, aliases)
            if name in NONDET_CALLS:
                return name
    return None


def _seeding_is_deterministic(call: ast.Call, aliases: Dict[str, str]) -> bool:
    argument = _seed_argument(call)
    if argument is None or _is_none(argument):
        return False
    return _nondeterministic_expression(argument, aliases) is None


def find_nondeterminism(tree: ast.AST, aliases: Dict[str, str]) -> List[Finding]:
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    seeded = set()                                                  # global states with a deterministic seed call
    for call in calls:
        name = resolve(call.func, aliases)
        if name in SEEDERS and _seeding_is_deterministic(call, aliases):
            seeded.add(STATE_OF[name])
    findings: List[Finding] = []

    for call in calls:
        name = resolve(call.func, aliases)
        if name is None:
            continue
        if name in SEEDERS:
            argument = _seed_argument(call)
            if argument is None or _is_none(argument):
                findings.append(Finding(call, "NONDETERMINISTIC_SEED",
                                        f"{name}() with no seed (or None) seeds from OS entropy: results differ on every run.",
                                        "Pass a fixed integer seed."))
            else:
                source = _nondeterministic_expression(argument, aliases)
                if source:
                    findings.append(Finding(call, "NONDETERMINISTIC_SEED",
                                            f"{name} is seeded from {source}(), which changes on every run.",
                                            "Use a fixed integer seed (record it with the results)."))
            continue
        if name in GENERATOR_CONSTRUCTORS:
            argument = _seed_argument(call)
            if argument is None or _is_none(argument):
                findings.append(Finding(call, "UNSEEDED_GENERATOR",
                                        f"{name}() without a seed draws OS entropy: results differ on every run.",
                                        "Pass a fixed seed, e.g. numpy.random.default_rng(12345), or accept a seed/generator argument."))
            else:
                source = _nondeterministic_expression(argument, aliases)
                if source:
                    findings.append(Finding(call, "NONDETERMINISTIC_SEED",
                                            f"{name} is seeded from {source}(), which changes on every run.",
                                            "Use a fixed integer seed (record it with the results)."))
            continue
        if name in UNSEEDABLE or name.startswith("secrets."):
            findings.append(Finding(call, "NONDETERMINISTIC_SOURCE",
                                    f"{name} cannot be seeded: its output differs on every run.",
                                    "Use a seeded generator for simulation code; keep OS entropy for security tokens only."))
            continue
        module, _, function = name.rpartition(".")
        if module == "numpy.random" and function not in NUMPY_NON_DRAWS and "numpy" not in seeded:
            findings.append(Finding(call, "UNSEEDED_RANDOM_DRAW",
                                    f"{name}() draws from numpy's global random state, which this file never seeds.",
                                    "Use rng = numpy.random.default_rng(seed) and rng.<draw>(), or call numpy.random.seed(<int>) here."))
        elif module == "random" and function not in STDLIB_NON_DRAWS and "random" not in seeded:
            findings.append(Finding(call, "UNSEEDED_RANDOM_DRAW",
                                    f"{name}() draws from the global random state, which this file never seeds.",
                                    "Use rng = random.Random(<int>) and rng.<draw>(), or call random.seed(<int>) here."))
        elif module == "torch" and function in TORCH_DRAWS and "torch" not in seeded:
            findings.append(Finding(call, "UNSEEDED_RANDOM_DRAW",
                                    f"{name}() draws from torch's global random state, which this file never seeds.",
                                    "Call torch.manual_seed(<int>) or pass a seeded torch.Generator."))
    return findings
