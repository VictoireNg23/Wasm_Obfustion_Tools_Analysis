#!/usr/bin/env python3
# swamped_metrics_binaryen.py
"""
SWAMPED evaluation pipeline
"""

import os
import sys
import csv
import time
import re
import uuid
import subprocess
from multiprocessing import Pool
from pathlib import Path

from tqdm import tqdm

try:
    from rapidfuzz import fuzz
    def _text_similarity(a, b):
        if not a or not b:
            return None
        return round(fuzz.ratio(a, b), 2)
except ImportError:
    from difflib import SequenceMatcher
    def _text_similarity(a, b):
        if not a or not b:
            return None
        return round(SequenceMatcher(None, a, b).ratio() * 100, 2)

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from wasm_runtime import run_wasm_with_inferred_args
from cfg_similarity import cfg_similarity_structural
from deobfuscation_vulnerability import deobfuscation_vulnerability

# ---------------- CONFIG ----------------
DATASET_BASE = "./Dataset_officiel_wasm/Minos"
OUTPUT_BASE = "./swamped/Results_swamped"
SUB_FOLDERS = ["Minos_benign"]
CSV_OUTPUT = "./swamped/Results_csv/Minos_benign.csv"

WASMTIME = str(Path.home() / ".wasmtime/bin/wasmtime")
WASM2WAT = "wasm2wat"
WASM_VALIDATE = "wasm-validate"

RATIOS = [0.1, 0.5, 1.0]
N_PROC = 20
BATCH_SIZE = 50          # CSV rows buffered before flush to disk
TIMEOUT = 60             # per wasmtime / wabt / binaryen call (seconds)

# Ghidra recovery is the slowest probe (headless JVM startup + analysis).
# Set to False to skip it for a first pass, then re-enable on a subset.
ENABLE_GHIDRA = True
GHIDRA_TIMEOUT = 180

wabt_bins = {
    "wasm2wat": WASM2WAT,
    "validate": WASM_VALIDATE,
    "wasmtime": WASMTIME,
}

# ---------------- SWAMPED IMPORT ----------------
sys.path.append(os.getcwd())
from wasmParser.parser import parseWast, savePertWasm
import strategies.code_perturbation as code_pert
import strategies.structural_perturbation as struct_pert

CODE_STRAT = [
    'nop_insertion', 'stackOP_insertion_memory', 'stackOP_insertion_numeric',
    'stackOP_insertion_bit', 'stackOP_insertion_conversion1',
    'stackOP_insertion_conversion2', 'stackOP_insertion_floating',
    'add_sub_transformation', 'sub_add_transformation', 'shift_transformation',
    'eqz_transformation', 'load_store_transformation', 'direct_to_indirect',
    'xor_MBA_transformation', 'or_MBA_transformation',
    'constant_global_variables', 'constant_value_splitting',
    'opaque_predicate_insertion'
]

STRUCT_STRAT = [
    'import_insertion', 'function_insertion', 'function_body_cloning',
    'export_insertion', 'data_insertion', 'data_encryption',
    'global_insertion', 'function_sig_insertion', 'element_insertion'
]
ALL_STRATEGIES = [("code", s) for s in CODE_STRAT] + [("struct", s) for s in STRUCT_STRAT]

FIELDS = [
    "sample", "relpath", "obfuscation_transformation", "ratio", "mutant_id", "obf_time",
    "size_orig", "size_obf", "call_ind_orig", "call_ind_obf", "max_nesting_orig", "max_nesting_obf",
    "valid_orig", "valid_obf",
    "run_orig", "run_obf", "run_time_orig", "run_time_obf", "run_func_orig", "run_func_obf",
    "disassembly_ok_orig", "disassembly_ok_obf", "wat_similarity", "cfg_similarity",
    "func_symbols_orig", "func_symbols_obf", "type_symbols_orig", "type_symbols_obf",
    "deobf_wabt_orig", "deobf_wabt_obf",
    "deobf_binaryen_orig", "deobf_binaryen_obf",
    "deobf_ghidra_orig", "deobf_ghidra_obf",
    "deobf_ghidra_funcs_orig", "deobf_ghidra_funcs_obf",
    "deobf_score_orig", "deobf_score_obf",
]


# ---------------- UTILS ----------------
def run_cmd(cmd, timeout=TIMEOUT):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except Exception:
        return -1, "", "error"


def wasm2wat_text(path):
    rc, out, _ = run_cmd([WASM2WAT, str(path)])
    return out if rc == 0 else None


def count_call_indirect(wat):
    return len(re.findall(r"\bcall_indirect\b", wat)) if wat else 0


def max_nesting(wat):
    if not wat:
        return 0
    d = m = 0
    for c in wat:
        if c == "(":
            d += 1
            m = max(m, d)
        elif c == ")":
            d -= 1
    return m


def wasm_dis_text(path):
    rc, out, _ = run_cmd(["wasm-dis", str(path)])
    return out if rc == 0 else None


def count_symbols(text):
    if not text:
        return {"func": None, "type": None}
    return {
        "func": len(re.findall(r"\(func\s+\$", text)),
        "type": len(re.findall(r"\(type\s+\$", text))
    }


def native_run(path, wat_text):
    res = run_wasm_with_inferred_args(WASMTIME, path, wat_text, timeout_s=TIMEOUT)
    return res["status"], res["elapsed_s"], res["func"]


def deobf_vuln(path):
    return deobfuscation_vulnerability(
        path,
        timeout_wabt=TIMEOUT, timeout_binaryen=TIMEOUT, timeout_ghidra=GHIDRA_TIMEOUT,
        ghidra_script_dir=str(Path(__file__).parent.resolve()),
        run_ghidra=ENABLE_GHIDRA,
    )


# ---------------- RESUME ----------------
def csv_has_header(csv_path):
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return False
    with open(csv_path, newline="") as f:
        return f.readline().strip().split(",")[0] == "sample"


def load_existing_tasks(csv_path):
    """Load already processed (relpath, strategy, ratio) triples."""
    done = set()
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return done
    with open(csv_path, newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return done
    if rows[0][0] == "sample":
        header = rows[0]
        data_rows = rows[1:]
        rel_idx = header.index("relpath")
        strat_idx = header.index("obfuscation_transformation")
        ratio_idx = header.index("ratio")
    else:
        data_rows = rows
        rel_idx, strat_idx, ratio_idx = 1, 2, 3
    for row in data_rows:
        if len(row) > max(rel_idx, strat_idx, ratio_idx):
            done.add((row[rel_idx], row[strat_idx], row[ratio_idx]))
    return done


# ---------------- CORE ----------------
def remaining_combos_for_file(done_tasks, relpath):
    remaining = []
    for type_p, strat in ALL_STRATEGIES:
        if not hasattr(code_pert if type_p == "code" else struct_pert, strat):
            continue
        for r in RATIOS:
            if (relpath, strat, str(r)) not in done_tasks:
                remaining.append((type_p, strat, r))
    return remaining


def process_one_file(task):
    wasm_path, category, rel_dir, filename, done_tasks = task
    base = filename.replace(".wasm", "")
    relpath_key = os.path.join(rel_dir, filename)

    combos = remaining_combos_for_file(done_tasks, relpath_key)
    if not combos:
        return []

    rows = []

    # ---- orig metrics computed once, shared across all combos for this file ----
    wat_orig = wasm2wat_text(wasm_path)
    dis_orig = wasm_dis_text(wasm_path)
    size_orig = os.path.getsize(wasm_path)
    call_ind_orig = count_call_indirect(wat_orig)
    nest_orig = max_nesting(wat_orig)
    valid_orig = "ok" if run_cmd([WASM_VALIDATE, wasm_path])[0] == 0 else "invalid"
    run_orig, run_time_orig, run_func_orig = native_run(wasm_path, wat_orig)
    sym_o = count_symbols(dis_orig)

    try:
        dv_orig = deobf_vuln(wasm_path)
    except Exception:
        dv_orig = None

    for type_p, strat, r in combos:
        module = code_pert if type_p == "code" else struct_pert
        func = getattr(module, strat)

        try:
            t0 = time.time()
            sections = parseWast(wat_orig.splitlines())
            func(sections, 1, 1, r)
            out_dir = os.path.join(OUTPUT_BASE, rel_dir, str(r), base, strat)
            os.makedirs(out_dir, exist_ok=True)

            wat_path = os.path.join(out_dir, f"{base}_{strat}.wat")
            savePertWasm(out_dir, f"{base}_{strat}.wat", sections)
            t1 = time.time()

            wasm_path_obf = wat_path.replace(".wat", ".wasm")
            if not os.path.exists(wasm_path_obf):
                continue

            wat_obf = wasm2wat_text(wasm_path_obf)
            dis_obf = wasm_dis_text(wasm_path_obf)

            valid_obf = "ok" if run_cmd([WASM_VALIDATE, wasm_path_obf])[0] == 0 else "invalid"
            run_obf, run_time_obf, run_func_obf = native_run(wasm_path_obf, wat_obf)

            sym_b = count_symbols(dis_obf)

            cfg_sim = None
            try:
                cfg_sim = cfg_similarity_structural(wasm_path, wasm_path_obf, timeout_s=TIMEOUT)
            except Exception:
                pass

            try:
                dv_obf = deobf_vuln(wasm_path_obf)
            except Exception:
                dv_obf = None

            row = {
                "sample": base,
                "relpath": relpath_key,
                "obfuscation_transformation": strat,
                "ratio": r,
                "mutant_id": f"{base}_{strat}_{r}_{uuid.uuid4().hex[:8]}",
                "obf_time": round(t1 - t0, 6),

                "size_orig": size_orig,
                "size_obf": os.path.getsize(wasm_path_obf),

                "call_ind_orig": call_ind_orig,
                "call_ind_obf": count_call_indirect(wat_obf),
                "max_nesting_orig": nest_orig,
                "max_nesting_obf": max_nesting(wat_obf),

                "valid_orig": valid_orig,
                "valid_obf": valid_obf,

                "run_orig": run_orig,
                "run_obf": run_obf,
                "run_time_orig": run_time_orig,
                "run_time_obf": run_time_obf,
                "run_func_orig": run_func_orig,
                "run_func_obf": run_func_obf,

                "disassembly_ok_orig": "yes" if dis_orig else "no",
                "disassembly_ok_obf": "yes" if dis_obf else "no",

                "wat_similarity": _text_similarity(dis_orig, dis_obf),
                "cfg_similarity": cfg_sim,

                "func_symbols_orig": sym_o["func"],
                "func_symbols_obf": sym_b["func"],
                "type_symbols_orig": sym_o["type"],
                "type_symbols_obf": sym_b["type"],

                "deobf_wabt_orig": dv_orig["wabt"]["success"] if dv_orig else None,
                "deobf_wabt_obf": dv_obf["wabt"]["success"] if dv_obf else None,
                "deobf_binaryen_orig": dv_orig["binaryen"]["success"] if dv_orig else None,
                "deobf_binaryen_obf": dv_obf["binaryen"]["success"] if dv_obf else None,
                "deobf_ghidra_orig": (dv_orig["ghidra"]["success"] if dv_orig and dv_orig["ghidra"] else None),
                "deobf_ghidra_obf": (dv_obf["ghidra"]["success"] if dv_obf and dv_obf["ghidra"] else None),
                "deobf_ghidra_funcs_orig": (dv_orig["ghidra"]["func_count"] if dv_orig and dv_orig["ghidra"] else None),
                "deobf_ghidra_funcs_obf": (dv_obf["ghidra"]["func_count"] if dv_obf and dv_obf["ghidra"] else None),
                "deobf_score_orig": dv_orig["score"] if dv_orig else None,
                "deobf_score_obf": dv_obf["score"] if dv_obf else None,
            }

            rows.append(row)

        except Exception as e:
            print(f"[WARN] {relpath_key} | {strat} | r={r} -> {e}")
            continue

    return rows


# ---------------- MAIN ----------------
def main():
    csv_path = Path(CSV_OUTPUT)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    print("Loading already processed tasks...")
    done_tasks = load_existing_tasks(csv_path)
    print(f"Already completed (relpath, strategy, ratio) triples: {len(done_tasks)}")

    file_tasks = []
    for cat in SUB_FOLDERS:
        d = os.path.join(DATASET_BASE, cat)
        for root, dirs, files in os.walk(d):
            rel_dir = os.path.relpath(root, DATASET_BASE)
            for f in files:
                if f.endswith(".wasm"):
                    file_tasks.append((os.path.join(root, f), cat, rel_dir, f, done_tasks))

    print(f"Total source files: {len(file_tasks)}")

    write_header = not csv_has_header(csv_path)
    buffer = []

    with open(csv_path, "a", newline="") as cf:
        writer = csv.DictWriter(cf, fieldnames=FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
            cf.flush()
            os.fsync(cf.fileno())

        with Pool(N_PROC) as p:
            for rows in tqdm(p.imap_unordered(process_one_file, file_tasks), total=len(file_tasks)):
                if not rows:
                    continue
                buffer.extend(rows)

                if len(buffer) >= BATCH_SIZE:
                    writer.writerows(buffer)
                    cf.flush()
                    os.fsync(cf.fileno())
                    buffer.clear()

            if buffer:
                writer.writerows(buffer)
                cf.flush()
                os.fsync(cf.fileno())
                buffer.clear()

    print(" DONE:", csv_path)


if __name__ == "__main__":
    main()
