#!/usr/bin/env python3
# spectec_common.py
"""
Shared logic for the three spectec_analysis_*.py drivers (WasMixer,
WasmMutate, SWAMPED). Each driver is a thin CLI wrapper around this module
-- only the default paths and the enriched CSV's docstring differ between
the three, because all three pipelines' obfuscated-output directory
convention was verified to be IDENTICAL:

    <outdir>/<sample>/<sample>__<mutant_id>/*.wasm

"""

import re
import subprocess
from pathlib import Path

from wasm_runtime import list_func_exports, get_func_param_types, run_cmd

NORMAL_REJECTION_CODES = {1, 2, 3}

EXTRA_FIELDS = [
    "spec_valid_orig",
    "spec_valid_obf",
    "semantic_equivalence_bool",
    "spec_errors_orig",
    "spec_errors_obf",
    "spec_violation_count",
    "interpreter_crash",
]

TEST_INPUTS_BY_TYPE = {
    "i32": ["0", "1", "42", "-1", "2147483647"],
    "i64": ["0", "1", "42", "-1", "9223372036854775807"],
    "f32": ["0.0", "1.0", "3.14", "-1.0", "100.0"],
    "f64": ["0.0", "1.0", "3.14", "-1.0", "100.0"],
}


def sanitize(val):
    if val is None:
        return ""
    return str(val).replace("\n", " | ").replace("\r", "").strip()[:500]


def wasm2wat_text(path, wasm2wat_bin="wasm2wat"):
    rc, out, _ = run_cmd([wasm2wat_bin, str(path)])
    return out if rc == 0 else None


def run_spectec(wasm_path, spectec_bin, timeout=120):
    """Run SpecTec on a single .wasm file. Returns (valid, crashed, rc, output)."""
    spectec_bin = Path(spectec_bin)
    if not spectec_bin.exists():
        return False, True, -2, f"spectec_binary_not_found:{spectec_bin}"

    wasm_path = Path(wasm_path)
    if not wasm_path.exists():
        return False, True, -2, "file_not_found"

    try:
        p = subprocess.run(
            [str(spectec_bin), str(wasm_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, True, -1, "timeout"
    except FileNotFoundError as e:
        return False, True, -2, f"spectec_not_found:{e}"
    except Exception as e:
        return False, True, -3, f"launch_exc:{e}"

    combined = (p.stdout + "\n" + p.stderr).strip()
    valid = (p.returncode == 0)
    crashed = (p.returncode not in ({0} | NORMAL_REJECTION_CODES))
    return valid, crashed, p.returncode, combined


def semantic_equivalence(orig_path, obf_path, wat_text, spectec_bin, timeout=120, n_inputs=5):
    """
    Invoke the main export of both modules with N fixed input vectors via
    SpecTec and compare outputs.
    Returns one of: "yes" | "no" | "partial" | "no_entry" | "err" | "skipped"
    """
    spectec_bin = Path(spectec_bin)
    if not spectec_bin.exists():
        return "skipped"
    if not wat_text:
        return "skipped"

    exports = list_func_exports(wat_text)
    if not exports:
        return "no_entry"

    func_name = next((n for n in ("_start", "main") if n in exports), next(iter(exports)))
    func_id = exports[func_name]
    param_types = get_func_param_types(wat_text, func_id) or []

    test_vectors = []
    for i in range(n_inputs):
        vec = [TEST_INPUTS_BY_TYPE.get(t, ["0"])[i % len(TEST_INPUTS_BY_TYPE.get(t, ["0"]))]
               for t in param_types]
        test_vectors.append(vec)
    if not param_types:
        test_vectors = [[]] * n_inputs

    matches = tested = 0
    for args in test_vectors:
        wast_args = " ".join(f"({t}.const {v})" for t, v in zip(param_types, args))

        def run_wast(wp):
            h = f'(module binary "{wp}")\n(invoke "{func_name}" {wast_args})\n'
            try:
                p = subprocess.run([str(spectec_bin)], input=h,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, timeout=timeout)
                return p.returncode, (p.stdout + p.stderr).strip()
            except Exception as e:
                return -99, str(e)

        rc_o, out_o = run_wast(orig_path)
        rc_b, out_b = run_wast(obf_path)
        if rc_o not in ({0} | NORMAL_REJECTION_CODES) or rc_b not in ({0} | NORMAL_REJECTION_CODES):
            continue
        tested += 1
        if out_o == out_b:
            matches += 1

    if tested == 0:
        return "err"
    if matches == tested:
        return "yes"
    if matches == 0:
        return "no"
    return "partial"


def find_obf_path(obf_dir, sample, mutant_id):
    """
    Reconstruct the obfuscated file's path from the CSV row's own
    `sample` and `mutant_id` columns -- identical directory convention
    across WasMixer, WasmMutate, and SWAMPED (verified against all three
    pipelines' source): `<obf_dir>/<sample>/<sample>__<mutant_id>/*.wasm`.
    Exactly one .wasm is ever written per combo directory (the mutant
    itself; everything else in that directory is a .log/.json artifact),
    so a plain glob is unambiguous.
    """
    combo_dir = Path(obf_dir) / sample / f"{sample}__{mutant_id}"
    if not combo_dir.is_dir():
        return None
    candidates = list(combo_dir.glob("*.wasm"))
    return candidates[0] if candidates else None


def csv_has_header(path):
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return False
    with open(path) as f:
        return f.readline().strip().split(",")[0].strip('"') == "sample"


def load_done(path):
    """
    Resume key is just (relpath_orig, mutant_id) -- mutant_id already
    includes a random hex suffix in all three pipelines, so it's unique
    per row on its own without needing obfuscation_transformation/ratio
    to disambiguate.
    """
    import csv
    done = set()
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return done
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            done.add((row.get("relpath_orig", ""), row.get("mutant_id", "")))
    return done
