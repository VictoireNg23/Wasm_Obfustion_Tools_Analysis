#!/usr/bin/env python3
# run_wasmmutate_binaryen.py
"""
Master script: builds tasks and runs wasm_metrics_binaryen_mutate.process_one
in parallel, for wasm-mutate (wasm_mutator_by_category).
"""

import argparse, os, sys, csv, itertools, multiprocessing, uuid, time, shutil, subprocess
from pathlib import Path
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.resolve()))
from wasm_metrics_binaryen_mutate import process_one

BATCH_SIZE = 50

TRANSFORMATIONS = ["peephole", "add_type", "add_function", "remove_dead_code",
                    "edit_custom_sections", "if_swap", "loop_unroll"]

FIELDS = [
    "sample", "relpath", "obfuscation_transformation", "variant", "mutant_id", "obf_time",
    "size_orig", "size_obf", "call_ind_orig", "call_ind_obf", "max_nesting_orig", "max_nesting_obf",
    "valid_orig", "valid_obf",
    "run_orig", "run_obf", "run_time_orig", "run_time_obf", "run_func_orig", "run_func_obf",
    "disassembly_ok_orig", "disassembly_ok_obf", "wat_similarity", "cfg_similarity",
    "func_symbols_orig", "func_symbols_obf", "type_symbols_orig", "type_symbols_obf",
    "orig_state_hash", "obf_state_hash", "state_match", "behavior_match",
    "deobf_wabt_orig", "deobf_wabt_obf",
    "deobf_binaryen_orig", "deobf_binaryen_obf",
    "deobf_ghidra_orig", "deobf_ghidra_obf",
    "deobf_ghidra_funcs_orig", "deobf_ghidra_funcs_obf",
    "deobf_score_orig", "deobf_score_obf",
]


def csv_has_header(csv_path):
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return False
    with open(csv_path, newline="") as f:
        first_line = f.readline().strip()
        return first_line.split(",")[0] == "sample"


def load_existing_tasks(csv_path):
    """Load already processed (relpath, combo, variant) triples."""
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
        combo_idx = header.index("obfuscation_transformation")
        var_idx = header.index("variant")
    else:
        data_rows = rows
        rel_idx, combo_idx, var_idx = 1, 2, 3

    for row in data_rows:
        if len(row) > max(rel_idx, combo_idx, var_idx):
            done.add((row[rel_idx], row[combo_idx], row[var_idx]))

    return done


def generate_mutate_combinations():
    """All non-empty subsets of TRANSFORMATIONS (matches the original bash script)."""
    combos = []
    n = len(TRANSFORMATIONS)
    for r in range(1, n + 1):
        for c in itertools.combinations(TRANSFORMATIONS, r):
            combos.append(list(c))
    return combos


def build_tasks(dataset, outdir, mutator_bin, wabt_bins, timeout, nb_mutants,
                 node_puppet, test_inputs, tmp_root, done_tasks):
    tasks = []
    for root, _, files in os.walk(dataset):
        for file in files:
            full = Path(root) / file
            rel = str(full.relative_to(dataset))
            sample_name = full.stem
            sample_base_out = Path(outdir) / sample_name
            sample_base_out.mkdir(parents=True, exist_ok=True)

            if file.endswith(".c"):
                uid = uuid.uuid4().hex[:8]
                tmp_compile = tmp_root / f"compile_{uid}"
                tmp_compile.mkdir(parents=True, exist_ok=True)
                target = tmp_compile / (sample_name + ".wasm")
                print(f"[C] Compiling {rel} -> tmp")
                try:
                    p = subprocess.run(
                        ["emcc", str(full), "-O2", "-s", "STANDALONE_WASM", "-o", str(target)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300,
                    )
                    rc = p.returncode
                except Exception as e:
                    print(f" emcc exception for {rel}: {e}")
                    rc = -1
                if rc != 0 or not target.exists():
                    print(f" Compilation failed for {rel}")
                    continue
                wasm_src_for_tasks = str(target)

            elif file.endswith(".wat"):
                uid = uuid.uuid4().hex[:8]
                tmp_conv = tmp_root / f"conv_{uid}"
                tmp_conv.mkdir(parents=True, exist_ok=True)
                target = tmp_conv / (sample_name + ".wasm")
                print(f"[WAT] Converting {rel} -> tmp")
                try:
                    p = subprocess.run(
                        [wabt_bins["wat2wasm"], str(full), "-o", str(target)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120,
                    )
                    rc = p.returncode
                except Exception as e:
                    print(f" wat2wasm exception for {rel}: {e}")
                    rc = -1
                if rc != 0 or not target.exists():
                    print(f" wat2wasm failed for {rel}")
                    continue
                wasm_src_for_tasks = str(target)

            elif file.endswith(".wasm"):
                wasm_src_for_tasks = str(full)
            else:
                continue

            combos = generate_mutate_combinations()
            for combo in combos:
                combo_str = "_".join(combo)
                for variant_idx in range(1, nb_mutants + 1):
                    key = (rel, combo_str, str(variant_idx))
                    if key in done_tasks:
                        continue
                    tasks.append(
                        (
                            rel, wasm_src_for_tasks, str(outdir), str(mutator_bin),
                            combo, variant_idx, wabt_bins, timeout, str(tmp_root),
                            str(node_puppet), test_inputs,
                        )
                    )
    return tasks


def worker_wrapper(args):
    try:
        return process_one(*args)
    except Exception as e:
        print(f"[ERROR] Worker exception for {args[0] if args else None}: {e}")
        return {
            "sample": None,
            "relpath": args[0] if args else None,
            "combo": "_".join(args[4]) if args else None,
            "variant": args[5] if len(args) > 5 else None,
            "notes": [f"worker_exception:{e}"],
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--mutator", required=True, help="Path to wasm_mutator_by_category binary")
    ap.add_argument("--node-puppet", required=True, help="Path to run_browser_test.js")
    ap.add_argument("--csv", required=True, help="Path to output CSV")
    ap.add_argument("--tmp-root", required=True)
    ap.add_argument("--wabt-bin", default="/usr/bin")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--cores", type=int, default=4)
    ap.add_argument("--nb-mutants", type=int, default=3)
    ap.add_argument("--test-inputs", default="[[1,2],[5,7],[10,20]]")
    args = ap.parse_args()

    dataset = Path(args.dataset)
    outdir = Path(args.outdir)
    mutator_bin = Path(args.mutator)
    node_puppet = Path(args.node_puppet)
    csv_path = Path(args.csv)
    tmp_root = Path(args.tmp_root)

    if not mutator_bin.exists():
        print(f"[FATAL] mutator binary not found: {mutator_bin}")
        sys.exit(1)
    if not node_puppet.exists():
        print(f"[FATAL] node puppet script not found: {node_puppet}")
        sys.exit(1)

    tmp_root.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    wabt_bins = {
        "wasm2wat": str(Path(args.wabt_bin) / "wasm2wat"),
        "wat2wasm": str(Path(args.wabt_bin) / "wat2wasm"),
        "validate": str(Path(args.wabt_bin) / "wasm-validate"),
        "wasmtime": str(Path.home() / ".wasmtime/bin/wasmtime"),
    }

    print("Loading already processed tasks...")
    done_tasks = load_existing_tasks(csv_path)
    print(f"Already completed tasks: {len(done_tasks)}")

    print("Building remaining tasks...")
    tasks = build_tasks(
        str(dataset), str(outdir), mutator_bin, wabt_bins, args.timeout,
        args.nb_mutants, node_puppet, args.test_inputs, tmp_root, done_tasks,
    )
    print(f"Remaining tasks to process: {len(tasks)}")

    if not tasks:
        print("[INFO] No remaining tasks to process. Exiting.")
        return

    write_header = not csv_has_header(csv_path)
    buffer = []

    with open(csv_path, "a", newline="") as cf:
        writer = csv.DictWriter(cf, fieldnames=FIELDS)
        if write_header:
            writer.writeheader()
            cf.flush()
            os.fsync(cf.fileno())

        with multiprocessing.Pool(processes=args.cores) as pool:
            for res in pool.imap_unordered(worker_wrapper, tasks):
                if not isinstance(res, dict):
                    continue

                row = {
                    "sample": res.get("sample"),
                    "relpath": res.get("relpath"),
                    "obfuscation_transformation": res.get("combo"),
                    "variant": res.get("variant"),
                    "mutant_id": res.get("mutant_id"),
                    "obf_time": res.get("obf_time_s"),
                    "size_orig": res.get("size_orig"),
                    "size_obf": res.get("size_obf"),
                    "call_ind_orig": res.get("call_ind_orig"),
                    "call_ind_obf": res.get("call_ind_obf"),
                    "max_nesting_orig": res.get("max_nesting_orig"),
                    "max_nesting_obf": res.get("max_nesting_obf"),
                    "valid_orig": res.get("valid_orig"),
                    "valid_obf": res.get("valid_obf"),
                    "run_orig": res.get("run_orig"),
                    "run_obf": res.get("run_obf"),
                    "run_time_orig": res.get("run_time_orig"),
                    "run_time_obf": res.get("run_time_obf"),
                    "run_func_orig": res.get("run_func_orig"),
                    "run_func_obf": res.get("run_func_obf"),
                    "disassembly_ok_orig": res.get("disassembly_ok_orig"),
                    "disassembly_ok_obf": res.get("disassembly_ok_obf"),
                    "wat_similarity": res.get("wat_similarity"),
                    "cfg_similarity": res.get("cfg_similarity"),
                    "func_symbols_orig": res.get("func_symbols_orig"),
                    "func_symbols_obf": res.get("func_symbols_obf"),
                    "type_symbols_orig": res.get("type_symbols_orig"),
                    "type_symbols_obf": res.get("type_symbols_obf"),
                    "orig_state_hash": res.get("orig_state_hash"),
                    "obf_state_hash": res.get("obf_state_hash"),
                    "state_match": res.get("state_match"),
                    "behavior_match": res.get("behavior_match"),
                    "deobf_wabt_orig": res.get("deobf_wabt_orig"),
                    "deobf_wabt_obf": res.get("deobf_wabt_obf"),
                    "deobf_binaryen_orig": res.get("deobf_binaryen_orig"),
                    "deobf_binaryen_obf": res.get("deobf_binaryen_obf"),
                    "deobf_ghidra_orig": res.get("deobf_ghidra_orig"),
                    "deobf_ghidra_obf": res.get("deobf_ghidra_obf"),
                    "deobf_ghidra_funcs_orig": res.get("deobf_ghidra_funcs_orig"),
                    "deobf_ghidra_funcs_obf": res.get("deobf_ghidra_funcs_obf"),
                    "deobf_score_orig": res.get("deobf_score_orig"),
                    "deobf_score_obf": res.get("deobf_score_obf"),
                }

                buffer.append(row)

                if len(buffer) >= BATCH_SIZE:
                    writer.writerows(buffer)
                    cf.flush()
                    os.fsync(cf.fileno())
                    buffer.clear()

                print(
                    f"Processed {row['relpath']} [{row['obfuscation_transformation']} "
                    f"v{row['variant']}] -> obf:{row['valid_obf']} run:{row['run_obf']} "
                    f"deobf_score_obf:{row['deobf_score_obf']}"
                )

        if buffer:
            writer.writerows(buffer)
            cf.flush()
            os.fsync(cf.fileno())
            buffer.clear()

    print(f"\nAll done. CSV: {csv_path}")


if __name__ == "__main__":
    main()
