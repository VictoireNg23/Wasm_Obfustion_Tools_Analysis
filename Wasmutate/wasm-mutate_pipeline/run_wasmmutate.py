#!/usr/bin/env python3
# run_wasmmutate.py

import argparse
import csv
import json
import multiprocessing
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

from combos import generate_combinations, combo_label, categories_flag
from orig_metrics import load_cache
from metrics_worker import process_combo_mutate
from pipeline_core import FIELDS, discover_samples, run_phase1, csv_has_header, normalize_row

BATCH_SIZE = 20


def _phase2_worker(args):
    try:
        return process_combo_mutate(*args)
    except Exception as e:
        sample, rel = args[0], args[1]
        combo_tuple, variant_id = args[6], args[7]
        label = f"{categories_flag(combo_tuple)} (variant {variant_id})"
        print(f"[combo][ERROR] {rel} {label}: {e}")
        return {
            "sample": sample, "relpath_orig": rel,
            "obfuscation_transformation": categories_flag(combo_tuple),
            "notes": [f"worker_exception:{e}"],
        }


def build_phase2_tasks(samples, resolved, out_root, mutator_bin, wabt_bins,
                        runtime_bin, browser_runner_js, timeout, tmp_root,
                        n_variants, stack_depth, preserve_semantics, run_ghidra,
                        ghidra_headless, ghidra_script_dir, ghidra_timeout, done_combos,
                        node_path=None):
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
        for combo_tuple in combos:
            label = categories_flag(combo_tuple)
            for variant_id in range(1, n_variants + 1):
                key = (rel, f"{label}#v{variant_id}")
                if key in done_combos:
                    continue
                tasks.append((
                    sample, rel, str(orig_copy_path), orig_metrics, str(sample_out_dir),
                    str(mutator_bin), combo_tuple, variant_id, wabt_bins, runtime_bin,
                    str(browser_runner_js), timeout, str(tmp_root),
                    stack_depth, preserve_semantics,
                    run_ghidra, ghidra_headless, ghidra_script_dir, ghidra_timeout,
                    node_path,
                ))
    return tasks


def load_done_combos_with_variant(csv_path):
    """
    Same idea as a plain (relpath, combo) resume set, but the key must
    also encode the variant number (mutant_id's "_vN_" suffix), since
    several distinct mutants share the same obfuscation_transformation
    string (one per variant).
    """
    done = set()
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return done
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            mid = row.get("mutant_id", "") or ""
            variant = "1"
            if "_v" in mid:
                try:
                    variant = mid.split("_v", 1)[1].split("_", 1)[0]
                except Exception:
                    pass
            done.add((row["relpath_orig"], f"{row['obfuscation_transformation']}#v{variant}"))
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True, help="Root folder with .wasm/.wat/.c files (recursive)")
    ap.add_argument("--outdir", required=True, help="Where mutated binaries + logs are written")
    ap.add_argument("--csv", required=True, help="Output CSV path")
    ap.add_argument("--mutator", required=True, help="Path to the wasm_mutator_by_category binary")
    ap.add_argument("--browser-runner", required=True, help="Path to browser_runner.js")
    ap.add_argument("--node-path", default=os.environ.get("NODE_PATH"),
                     help="Directory containing node_modules/puppeteer, passed as NODE_PATH "
                          "to every browser_runner.js subprocess -- so puppeteer resolution "
                          "doesn't depend on the shell that launched this script having "
                          "exported NODE_PATH itself. Defaults to the current NODE_PATH env "
                          "var if already set; explicit --node-path always wins.")
    ap.add_argument("--wabt-bin", default="/usr/bin")
    ap.add_argument("--runtime-bin", "--wasmtime-bin", "--wasmtime-bin",
                     dest="runtime_bin", default=str(Path.home() / ".wasmtime/bin/wasmtime"),
                     help="Path to the wasm runtime binary -- wasmer (default) or wasmtime, "
                          "auto-detected from the filename (wasm_runtime.py).")
    ap.add_argument("--variants", type=int, default=3,
                     help="Independent random replicates per category-combo "
                          "(matches NB_MUTANTS in the bash script)")
    ap.add_argument("--stack-depth", type=int, default=1,
                     help="How many times to chain the mutator per variant "
                          "(default 1: apply the requested category-combo once)")
    ap.add_argument("--preserve-semantics", default="true", choices=["true", "false"],
                     help="Forwarded to the mutator's --preserve-semantics. Default true: "
                          "for an obfuscation-quality comparison you almost certainly want "
                          "behavior preserved by construction (wasm-tools mutate itself "
                          "defaults to false / fuzzing mode).")
    ap.add_argument("--tmp-root", default=None, help="Scratch space (default: <outdir>/../tmp_wasm_pipeline)")
    ap.add_argument("--timeout", type=int, default=60, help="Per-tool timeout in seconds")
    ap.add_argument("--cores", type=int, default=max(1, multiprocessing.cpu_count() - 1))
    ap.add_argument("--run-ghidra", action="store_true")
    ap.add_argument("--ghidra-headless", default=None)
    ap.add_argument("--ghidra-script-dir", default=str(Path(__file__).parent.resolve()))
    ap.add_argument("--ghidra-timeout", type=int, default=300)
    args = ap.parse_args()

    dataset = Path(args.dataset)
    outdir = Path(args.outdir)
    csv_path = Path(args.csv)
    mutator_bin = Path(args.mutator)
    if not mutator_bin.exists():
        print(f"ERROR: {mutator_bin} not found (check --mutator path)")
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
    print(f"Found {len(samples)} sample(s)")
    if not samples:
        print("Nothing to do.")
        return

    print("=== Phase 1: original-side metrics (shared/cached, obfuscator-agnostic) ===")
    resolved = run_phase1(
        samples, tmp_root, outdir, wabt_bins, args.runtime_bin,
        args.browser_runner, args.timeout, args.cores,
        args.run_ghidra, args.ghidra_headless, args.ghidra_script_dir, args.ghidra_timeout,
        node_path=args.node_path,
    )

    print("=== Phase 2: WasmMutate I1-I7 category combos x variants ===")
    preserve_semantics = args.preserve_semantics == "true"
    done_combos = load_done_combos_with_variant(csv_path)
    print(f"{len(done_combos)} (sample, combo, variant) already in CSV -- will be skipped")

    tasks = build_phase2_tasks(
        samples, resolved, outdir, mutator_bin, wabt_bins, args.runtime_bin,
        args.browser_runner, args.timeout, tmp_root, args.variants,
        args.stack_depth, preserve_semantics, args.run_ghidra, args.ghidra_headless,
        args.ghidra_script_dir, args.ghidra_timeout, done_combos,
        node_path=args.node_path,
    )
    print(f"{len(tasks)} task(s) to run (up to {len(samples)} sample(s) x "
          f"127 combos x {args.variants} variants)")

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
                      f"{row['mutant_id']} -> valid_obf={row['valid_obf']} "
                      f"payload_preserved={row['payload_preserved']}")

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
