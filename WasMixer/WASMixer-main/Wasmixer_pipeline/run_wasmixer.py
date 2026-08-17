#!/usr/bin/env python3
# run_wasmixer.py
"""
Master pipeline for the WasMixer NDSS evaluation.

Pipeline
--------
Usage
-----
python run_wasmixer.py \
    --dataset /path/to/dataset \
    --outdir  /path/to/output_binaries \
    --csv     /path/to/results.csv \
    --wasmixer /path/to/WASMixer_repo \
    --browser-runner /path/to/browser_runner.js \
    --wabt-bin /usr/bin \
    --wasmtime-bin ~/.wasmtime/bin/wasmtime \
    --cores 8 \ 
    [--run-ghidra --ghidra-headless /opt/ghidra/support/analyzeHeadless]
"""

import argparse
import csv
import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

from combos import generate_combinations, combo_label, flags_label
from orig_metrics import compute_orig_metrics, save_cache, load_cache
from metrics_worker import process_combo

FIELDS = [
    "sample", "relpath_orig", "obfuscation_transformation", "mutant_id", "obf_time",
    "size_orig", "size_obf", "call_ind_orig", "call_ind_obf",
    "max_nesting_orig", "max_nesting_obf", "valid_orig", "valid_obf",
    "run_orig", "run_obf", "run_time_orig", "run_time_obf",
    "run_func_orig", "run_func_obf", "retval_orig", "retval_obf", "retval_match",
    "state_hash_orig", "state_hash_obf", "state_match",
    "import_trace_hash_orig", "import_trace_hash_obf", "import_trace_match",
    "payload_preserved", "memory_pages_orig", "memory_pages_obf",
    "exports_called_orig", "exports_called_obf",
    "browser_error_orig", "browser_error_obf",
    "disassembly_ok_orig", "disassembly_ok_obf",
    "wat_similarity", "cfg_similarity",
    "func_symbols_orig", "func_symbols_obf", "type_symbols_orig", "type_symbols_obf",
    "deobf_wabt_orig", "deobf_wabt_obf", "deobf_binaryen_orig", "deobf_binaryen_obf",
    "deobf_ghidra_orig", "deobf_ghidra_obf",
    "deobf_ghidra_funcs_orig", "deobf_ghidra_funcs_obf",
    "deobf_score_orig", "deobf_score_obf",
    "notes",
]

BATCH_SIZE = 20  # rows buffered before flush+fsync


# ---------------------------------------------------------------------
# CSV resume helpers
# ---------------------------------------------------------------------

def csv_has_header(csv_path):
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return False
    with open(csv_path, newline="") as f:
        return f.readline().strip().split(",")[0].strip('"') == "sample"


def load_done_combos(csv_path):
    done = set()
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return done
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            done.add((row["relpath_orig"], row["obfuscation_transformation"]))
    return done


# ---------------------------------------------------------------------
# Dataset discovery (recursive) + .c / .wat -> .wasm normalization
# ---------------------------------------------------------------------

def sample_hash(rel):
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16]


def discover_samples(dataset, tmp_root, wabt_bins, emcc_timeout=300):
    """
    Recursively walks `dataset`. For every .wasm/.wat/.c file found (at any
    depth), returns (sample, rel, canonical_wasm_path).
    """
    dataset = Path(dataset)
    compile_root = tmp_root / "compiled_sources"
    compile_root.mkdir(parents=True, exist_ok=True)

    samples = []
    for root, _, files in os.walk(dataset):
        for fname in files:
            full = Path(root) / fname
            rel = str(full.relative_to(dataset))
            sample = full.stem
            h = sample_hash(rel)

            if fname.endswith(".wasm"):
                samples.append((sample, rel, full))

            elif fname.endswith(".c"):
                target = compile_root / f"{h}.wasm"
                if not target.exists():
                    print(f"[C] compiling {rel}")
                    p = subprocess.run(
                        ["emcc", str(full), "-O2", "-s", "STANDALONE_WASM", "-o", str(target)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        timeout=emcc_timeout,
                    )
                    if p.returncode != 0 or not target.exists():
                        print(f"  [FAIL] emcc: {p.stderr.strip()[:300]}")
                        continue
                samples.append((sample, rel, target))

            elif fname.endswith(".wat"):
                target = compile_root / f"{h}.wasm"
                if not target.exists():
                    print(f"[WAT] converting {rel}")
                    p = subprocess.run(
                        [wabt_bins["wat2wasm"], str(full), "-o", str(target)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        timeout=120,
                    )
                    if p.returncode != 0 or not target.exists():
                        print(f"  [FAIL] wat2wasm: {p.stderr.strip()[:300]}")
                        continue
                samples.append((sample, rel, target))

    return samples


# ---------------------------------------------------------------------
# Phase 1: orig metrics (once per sample, cached)
# ---------------------------------------------------------------------

def _phase1_worker(args):
    (sample, rel, src_path, orig_copy_path, cache_path, out_dir,
     wabt_bins, wasmtime_bin, browser_runner_js, timeout,
     run_ghidra, ghidra_headless, ghidra_script_dir, ghidra_timeout) = args
    try:
        import shutil
        shutil.copy2(src_path, orig_copy_path)
        metrics = compute_orig_metrics(
            orig_copy_path, wabt_bins, wasmtime_bin, browser_runner_js,
            timeout, out_dir, run_ghidra=run_ghidra,
            ghidra_headless=ghidra_headless, ghidra_script_dir=ghidra_script_dir,
            ghidra_timeout=ghidra_timeout,
        )
        save_cache(cache_path, metrics)
        print(f"[orig] {rel} -> valid={metrics.get('valid')} run={metrics.get('run')}")
        return (rel, True)
    except Exception as e:
        print(f"[orig][ERROR] {rel}: {e}")
        return (rel, False)


def run_phase1(samples, tmp_root, out_root, wabt_bins, wasmtime_bin,
                browser_runner_js, timeout, cores, run_ghidra,
                ghidra_headless, ghidra_script_dir, ghidra_timeout):
    cache_dir = tmp_root / "orig_cache"
    orig_dir = tmp_root / "orig"
    cache_dir.mkdir(parents=True, exist_ok=True)
    orig_dir.mkdir(parents=True, exist_ok=True)

    tasks = []
    resolved = {}  # rel -> (sample, orig_copy_path, cache_path)
    for sample, rel, src_path in samples:
        h = sample_hash(rel)
        orig_copy_path = orig_dir / f"{h}.wasm"
        cache_path = cache_dir / f"{h}.json"
        resolved[rel] = (sample, orig_copy_path, cache_path)

        # resume check now actually validates the cache (version-checked
        # by load_cache), not just its existence on disk -- a stale cache
        # from a previous, buggier version of orig_metrics.py must NOT be
        # silently reused.
        if orig_copy_path.exists() and load_cache(cache_path) is not None:
            continue  # resume: already computed with the current code

        sample_out_dir = out_root / sample
        sample_out_dir.mkdir(parents=True, exist_ok=True)
        tasks.append((
            sample, rel, src_path, orig_copy_path, cache_path, sample_out_dir,
            wabt_bins, wasmtime_bin, browser_runner_js, timeout,
            run_ghidra, ghidra_headless, ghidra_script_dir, ghidra_timeout,
        ))

    print(f"[phase1] {len(tasks)} sample(s) need orig-metrics computation "
          f"({len(samples) - len(tasks)} resumed from cache)")

    if tasks:
        with multiprocessing.Pool(processes=cores) as pool:
            for _ in pool.imap_unordered(_phase1_worker, tasks):
                pass

    return resolved


# ---------------------------------------------------------------------
# Phase 2: per-combo obfuscation + metrics
# ---------------------------------------------------------------------

def _phase2_worker(args):
    try:
        return process_combo(*args)
    except Exception as e:
        sample, rel = args[0], args[1]
        combo_tuple, cli_flags = args[6], args[7]
        label = flags_label(cli_flags)
        print(f"[combo][ERROR] {rel} {label}: {e}")
        return {
            "sample": sample, "relpath_orig": rel,
            "obfuscation_transformation": label,
            "notes": [f"worker_exception:{e}"],
        }


def build_phase2_tasks(samples, resolved, out_root, wasmixer_cli, wabt_bins,
                        wasmtime_bin, browser_runner_js, timeout, tmp_root,
                        run_ghidra, ghidra_headless, ghidra_script_dir,
                        ghidra_timeout, done_combos):
    combos = generate_combinations()
    tasks = []
    for sample, rel, _ in samples:
        if rel not in resolved:
            continue
        _, orig_copy_path, cache_path = resolved[rel]
        if not cache_path.exists():
            continue  # phase1 failed for this sample; skip its combos
        orig_metrics = load_cache(cache_path, wasm_path=orig_copy_path, wabt_bins=wabt_bins)
        if orig_metrics is None:
            continue

        sample_out_dir = out_root / sample
        for combo_tuple, cli_flags in combos:
            # must match exactly what metrics_worker.process_combo() writes
            # into row["obfuscation_transformation"] (flags string, not
            # the internal T1+T3 shorthand), or resume silently reprocesses
            # everything.
            label = flags_label(cli_flags)
            if (rel, label) in done_combos:
                continue
            tasks.append((
                sample, rel, str(orig_copy_path), orig_metrics, str(sample_out_dir),
                str(wasmixer_cli), combo_tuple, cli_flags, wabt_bins, wasmtime_bin,
                str(browser_runner_js), timeout, str(tmp_root),
                run_ghidra, ghidra_headless, ghidra_script_dir, ghidra_timeout,
            ))
    return tasks


def normalize_row(res):
    row = {}
    for f in FIELDS:
        v = res.get(f)
        if isinstance(v, list):
            v = json.dumps(v)
        row[f] = v
    return row


# ---------------------------------------------------------------------
# main
# ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True, help="Root folder with .wasm/.wat/.c files (recursive)")
    ap.add_argument("--outdir", required=True, help="Where obfuscated binaries + logs are written")
    ap.add_argument("--csv", required=True, help="Output CSV path")
    ap.add_argument("--wasmixer", required=True, help="Path to the WASMixer repo root (contains cli/main.py)")
    ap.add_argument("--browser-runner", required=True, help="Path to browser_runner.js")
    ap.add_argument("--wabt-bin", default="/usr/bin")
    ap.add_argument("--wasmtime-bin", default=str(Path.home() / ".wasmtime/bin/wasmtime"))
    ap.add_argument("--tmp-root", default=None, help="Scratch space (default: <outdir>/../tmp_wasm_pipeline)")
    ap.add_argument("--timeout", type=int, default=60, help="Per-tool timeout in seconds")
    ap.add_argument("--cores", type=int, default=max(1, multiprocessing.cpu_count() - 1))
    ap.add_argument("--run-ghidra", action="store_true",
                     help="Enable Ghidra headless analysis (slow; requires a WASM-capable Ghidra install)")
    ap.add_argument("--ghidra-headless", default=None, help="Path to Ghidra's analyzeHeadless")
    ap.add_argument("--ghidra-script-dir", default=str(Path(__file__).parent.resolve()),
                     help="Directory containing ghidra_count_functions.py")
    ap.add_argument("--ghidra-timeout", type=int, default=300)
    args = ap.parse_args()

    dataset = Path(args.dataset)
    outdir = Path(args.outdir)
    csv_path = Path(args.csv)
    wasmixer_cli = Path(args.wasmixer) / "cli" / "main.py"
    if not wasmixer_cli.exists():
        print(f"ERROR: {wasmixer_cli} not found (check --wasmixer path)")
        sys.exit(1)

    tmp_root = Path(args.tmp_root) if args.tmp_root else outdir.parent / "tmp_wasm_pipeline"
    tmp_root.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    wabt_bins = {
        "wasm2wat": str(Path(args.wabt_bin) / "wasm2wat"),
        "wat2wasm": str(Path(args.wabt_bin) / "wat2wasm"),
        "validate": str(Path(args.wabt_bin) / "wasm-validate"),
    }

    print("=== Discovering dataset (recursive) ===")
    samples = discover_samples(dataset, tmp_root, wabt_bins)
    print(f"Found {len(samples)} sample(s) (.wasm / compiled .c / converted .wat)")
    if not samples:
        print("Nothing to do.")
        return

    print("=== Phase 1: original-side metrics (once per sample) ===")
    resolved = run_phase1(
        samples, tmp_root, outdir, wabt_bins, args.wasmtime_bin,
        args.browser_runner, args.timeout, args.cores,
        args.run_ghidra, args.ghidra_headless, args.ghidra_script_dir, args.ghidra_timeout,
    )

    print("=== Phase 2: obfuscation combos + comparison metrics ===")
    done_combos = load_done_combos(csv_path)
    print(f"{len(done_combos)} (sample, combo) pair(s) already in CSV -- will be skipped")

    tasks = build_phase2_tasks(
        samples, resolved, outdir, wasmixer_cli, wabt_bins, args.wasmtime_bin,
        args.browser_runner, args.timeout, tmp_root, args.run_ghidra,
        args.ghidra_headless, args.ghidra_script_dir, args.ghidra_timeout, done_combos,
    )
    print(f"{len(tasks)} combo task(s) to run "
          f"({len(samples)} sample(s) x up to 27 combos)")

    if not tasks:
        print("Nothing left to process. Done.")
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
            for res in pool.imap_unordered(_phase2_worker, tasks):
                if not isinstance(res, dict):
                    continue
                row = normalize_row(res)
                buffer.append(row)
                print(f"[combo] {row['relpath_orig']} [{row['obfuscation_transformation']}] "
                      f"-> valid_obf={row['valid_obf']} payload_preserved={row['payload_preserved']}")

                if len(buffer) >= BATCH_SIZE:
                    writer.writerows(buffer)
                    cf.flush()
                    os.fsync(cf.fileno())
                    buffer.clear()

        if buffer:
            writer.writerows(buffer)
            cf.flush()
            os.fsync(cf.fileno())

    print(f"\nDone. CSV written to {csv_path}")


if __name__ == "__main__":
    main()
