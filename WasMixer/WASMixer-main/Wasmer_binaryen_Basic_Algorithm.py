#!/usr/bin/env python3
# run_wasmixer_wasmer_safe.py
"""
Master script: builds tasks and runs wasm_obfuscator.process_one in parallel.
Supports resume: skips tasks already present in CSV.
Uses buffered batch writing to avoid IO contention and data loss.
"""

import argparse, os, sys, csv, itertools, multiprocessing, uuid, subprocess
from pathlib import Path
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.resolve()))
from wasm_metrics_binaryen import process_one

TMP_ROOT = Path("./WasMixer/tmp_wasmer_Basic_Algoritm")
CSV_PATH = Path(".WasMixer/WasMixer_Results/Results_csv/WasMixer_Results_wasmer/Basic_Algoritm.csv")

BATCH_SIZE = 50  

FIELDS = [
    "sample","relpath","obfuscation_transformation","mutant_id","obf_time",
    "size_orig","size_obf","call_ind_orig","call_ind_obf","max_nesting_orig","max_nesting_obf",
    "valid_orig","valid_obf","run_orig","run_obf","run_time_orig","run_time_obf",
    "disassembly_ok_orig","disassembly_ok_obf","wat_similarity","cfg_similarity",
    "func_symbols_orig","func_symbols_obf","type_symbols_orig","type_symbols_obf"
]


def csv_has_header(csv_path):
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return False
    with open(csv_path, newline="") as f:
        first_line = f.readline().strip()
        return first_line.split(",")[0] == "sample"


def load_completed_tasks(csv_path):
    completed = set()
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return completed

    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        return completed

    
    if rows[0][0] == "sample":
        header = rows[0]
        data_rows = rows[1:]
        rel_idx = header.index("relpath")
        combo_idx = header.index("obfuscation_transformation")
    else:
        
        data_rows = rows
        rel_idx = 1
        combo_idx = 2

    for row in data_rows:
        if len(row) > max(rel_idx, combo_idx):
            completed.add((row[rel_idx], row[combo_idx]))
    return completed



def generate_wasmixer_combinations():
    BASE = ["--flatten", "--alias", "--name", "--memory"]
    EXTRA = ["--collatz", "--cf", "--ca"]
    combos = []
    for r in range(1, len(BASE) + 1):
        for c in itertools.combinations(BASE, r):
            combos.append(list(c))
    for e in EXTRA:
        combos.append([e])
    base_copy = combos.copy()
    for c in base_copy:
        for e in EXTRA:
            if e not in c:
                combos.append(c + [e])
    combos.append(["--all"])
    combos.append(["--all", "--safe"])
    uniq = []
    seen = set()
    for c in combos:
        key = tuple(sorted(c))
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq



def build_tasks(dataset, outdir, wasmixer_cli, wabt_bins, timeout, completed_tasks):
    tasks = []
    combos = generate_wasmixer_combinations()
    for root, _, files in os.walk(dataset):
        for file in files:
            full = Path(root) / file
            rel = str(full.relative_to(dataset))
            sample_name = full.stem
            sample_base_out = Path(outdir) / sample_name
            sample_base_out.mkdir(parents=True, exist_ok=True)

            if file.endswith(".c"):
                uid = uuid.uuid4().hex[:8]
                tmp_compile = TMP_ROOT / f"compile_{uid}"
                tmp_compile.mkdir(parents=True, exist_ok=True)
                target = tmp_compile / (sample_name + ".wasm")
                print(f"[C] Compiling {rel} -> tmp")
                try:
                    p = subprocess.run(["emcc", str(full), "-O2", "-s", "STANDALONE_WASM", "-o", str(target)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300)
                    rc = p.returncode
                except Exception:
                    rc = -1
                if rc != 0 or not target.exists():
                    print(f" Compilation failed for {rel}")
                    continue
                wasm_src_for_tasks = str(target)

            elif file.endswith(".wat"):
                uid = uuid.uuid4().hex[:8]
                tmp_conv = TMP_ROOT / f"conv_{uid}"
                tmp_conv.mkdir(parents=True, exist_ok=True)
                target = tmp_conv / (sample_name + ".wasm")
                print(f"[WAT] Converting {rel} -> tmp")
                try:
                    p = subprocess.run([wabt_bins["wat2wasm"], str(full), "-o", str(target)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
                    rc = p.returncode
                except Exception:
                    rc = -1
                if rc != 0 or not target.exists():
                    print(f" wat2wasm failed for {rel}")
                    continue
                wasm_src_for_tasks = str(target)

            elif file.endswith(".wasm"):
                wasm_src_for_tasks = str(full)
            else:
                continue

            for combo in combos:
                combo_label = " ".join(combo)
                key = (rel, combo_label)
                if key in completed_tasks:
                    continue
                tasks.append((rel, wasm_src_for_tasks, str(outdir), str(wasmixer_cli),
                              combo, wabt_bins, timeout, str(TMP_ROOT)))
    return tasks


def worker_wrapper(args):
    try:
        return process_one(*args)
    except Exception as e:
        return {"sample": None, "relpath": args[0] if args else None, "combo": " ".join(args[4]) if args else None,
                "notes": [f"worker_exception:{e}"]}


# --- MAIN ---
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--wasmixer", required=True)
    ap.add_argument("--wabt-bin", default="/usr/bin")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--cores", type=int, default=4)
    args = ap.parse_args()

    dataset = Path(args.dataset)
    outdir = Path(args.outdir)
    wasmixer_cli = Path(args.wasmixer) / "cli" / "main.py"
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

    wabt_bins = {
        "wasm2wat": str(Path(args.wabt_bin)/"wasm2wat"),
        "wat2wasm": str(Path(args.wabt_bin)/"wat2wasm"),
        "validate": str(Path(args.wabt_bin)/"wasm-validate"),
        "wasmer": str(Path.home()/".wasmer/bin/wasmer"),
    }

    print("Loading already completed tasks...")
    completed_tasks = load_completed_tasks(CSV_PATH)
    print(f"Already completed tasks: {len(completed_tasks)}")

    print("Building tasks...")
    tasks = build_tasks(str(dataset), str(outdir), wasmixer_cli, wabt_bins, args.timeout, completed_tasks)
    print(f"Remaining tasks to run: {len(tasks)}")

    if not tasks:
        print("[INFO] No tasks remaining. Exiting.")
        return

    write_header = not csv_has_header(CSV_PATH)
    buffer = []

    with open(CSV_PATH, "a", newline="") as cf:
        writer = csv.DictWriter(cf, fieldnames=FIELDS)
        if write_header:
            writer.writeheader()
            cf.flush()
            os.fsync(cf.fileno())

        with multiprocessing.Pool(processes=args.cores) as pool:
            for res in pool.imap_unordered(worker_wrapper, tasks):
                if not isinstance(res, dict):
                    continue
                row = {field: res.get(field) for field in FIELDS}
                buffer.append(row)

                if len(buffer) >= BATCH_SIZE:
                    writer.writerows(buffer)
                    cf.flush()
                    os.fsync(cf.fileno())
                    buffer.clear()

                print(f"Processed {row['relpath']} [{row['obfuscation_transformation']}] -> obf:{row['valid_obf']} run:{row['run_obf']}")

        
        if buffer:
            writer.writerows(buffer)
            cf.flush()
            os.fsync(cf.fileno())
            buffer.clear()

    print(f"\nAll done. CSV: {CSV_PATH}")


if __name__ == "__main__":
    main()




