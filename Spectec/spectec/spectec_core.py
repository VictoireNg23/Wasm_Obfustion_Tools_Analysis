#!/usr/bin/env python3
# spectec_core.py
"""
Shared SpecTec analysis core, used by analyze_spectec_wasmixer.py,
analyze_spectec_swamped.py, and analyze_spectec_wasmmutate.py.

IMPORTANT -- verify before trusting at scale: this module assumes
SpecTec's CLI accepts a bare .wasm file and signals validity via its
process exit code (0 = valid). Confirm this against your actual build:

    ./spectec/interpreter/wasm a_known_valid.wasm; echo "rc=$?"
    ./spectec/interpreter/wasm a_known_invalid.wasm; echo "rc=$?"

If SpecTec instead expects a .wast harness with explicit assert_return/
assert_trap commands (per §3.5 of the SpecTec paper, which delegates
parsing/invocation to the existing reference interpreter tooling), adapt
run_spectec() below before using any of the three pipeline scripts.
"""

import csv
import subprocess
from pathlib import Path

DEFAULT_TIMEOUT = 120
BATCH_SIZE = 50

EXTRA_FIELDS = [
    "spec_valid_orig",
    "spec_valid_obf",
    "spec_valid_both_bool",
    "spec_error_count_orig",
    "spec_error_count_obf",
    "interpreter_crash_orig",
    "interpreter_crash_obf",
    "spec_rc_orig",
    "spec_rc_obf",
    "spec_output_orig",
    "spec_output_obf",
]

# Diagnostic-only marker words; never used to decide spec_valid_*.
_DIAGNOSTIC_MARKERS = ("error", "violation", "invalid", "exception")

_MAX_OUTPUT_CHARS = 500  # avoid CSV bloat on very chatty failures


def run_spectec(spectec_bin, wasm_path, timeout=DEFAULT_TIMEOUT):
    """
    Returns a dict:
        {
          "valid": bool,
          "rc": int | None,
          "crashed": bool,
          "error_count": int,   # diagnostic only
          "output": str,        # truncated combined stdout+stderr
        }
    """
    if wasm_path is None:
        return {"valid": False, "rc": None, "crashed": True,
                "error_count": 0, "output": "file_not_found"}

    wasm_path = Path(wasm_path)
    if not wasm_path.exists():
        return {"valid": False, "rc": None, "crashed": True,
                "error_count": 0, "output": "file_not_found"}

    try:
        result = subprocess.run(
            [str(spectec_bin), str(wasm_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"valid": False, "rc": None, "crashed": True,
                "error_count": 0, "output": "timeout_expired"}
    except FileNotFoundError as e:
        return {"valid": False, "rc": None, "crashed": True,
                "error_count": 0, "output": f"spectec_binary_not_found:{e}"}
    except Exception as e:
        return {"valid": False, "rc": None, "crashed": True,
                "error_count": 0, "output": f"launch_exception:{e}"}

    combined = (result.stdout + "\n" + result.stderr).strip()
    combined_lower = combined.lower()
    error_count = sum(combined_lower.count(m) for m in _DIAGNOSTIC_MARKERS)

    valid = result.returncode == 0
    # A nonzero exit code that SpecTec uses to report a normal rejection
    # (ill-typed module, trap, etc.) is NOT a crash. Only the launch-level
    # failures above are treated as crashes. Adjust here if your SpecTec
    # build distinguishes "internal tool error" exit codes from
    # "rejected module" exit codes.
    crashed = False

    return {
        "valid": valid,
        "rc": result.returncode,
        "crashed": crashed,
        "error_count": error_count,
        "output": combined.replace("\n", " | ")[:_MAX_OUTPUT_CHARS],
    }


def build_extra_row_fields(res_orig, res_obf):
    """Given two run_spectec() results, build the dict of EXTRA_FIELDS values."""
    return {
        "spec_valid_orig": "yes" if res_orig["valid"] else "no",
        "spec_valid_obf": "yes" if res_obf["valid"] else "no",
        "spec_valid_both_bool": "yes" if (res_orig["valid"] and res_obf["valid"]) else "no",
        "spec_error_count_orig": res_orig["error_count"],
        "spec_error_count_obf": res_obf["error_count"],
        "interpreter_crash_orig": "yes" if res_orig["crashed"] else "no",
        "interpreter_crash_obf": "yes" if res_obf["crashed"] else "no",
        "spec_rc_orig": res_orig["rc"],
        "spec_rc_obf": res_obf["rc"],
        "spec_output_orig": res_orig["output"],
        "spec_output_obf": res_obf["output"],
    }


# ---------------- RESUME ----------------
def csv_has_header(csv_path):
    csv_path = Path(csv_path)
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return False
    with open(csv_path, newline="") as f:
        return f.readline().strip() != ""


def load_existing_keys(csv_path, key_fields):
    """Load a set of tuples built from key_fields for every row already written."""
    csv_path = Path(csv_path)
    done = set()
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return done
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                done.add(tuple(row[k] for k in key_fields))
            except KeyError:
                continue
    return done


def read_input_csv(input_csv):
    with open(Path(input_csv), newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def merged_fieldnames(original_fields):
    return list(original_fields) + [fld for fld in EXTRA_FIELDS if fld not in original_fields]
