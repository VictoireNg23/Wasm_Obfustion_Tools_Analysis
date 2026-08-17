#!/usr/bin/env python3
# run_swamped.py
"""
Master pipeline for the SWAMPED NDSS evaluation.

Pipeline
--------
Resume behaviour
-----------------
- Phase 1 is skipped for a sample whose cache JSON + persistent .wasm
  copy already exist under --tmp-root/orig_cache and --tmp-root/orig.
- Phase 2 is skipped for a (relpath, strategy, ratio) triple already
  present in the output CSV.
Both make it safe to Ctrl-C and re-launch the same command.

Usage
-----
python run_swamped.py \
    --dataset /path/to/dataset \
    --outdir  /path/to/output_binaries \
    --csv     /path/to/results.csv \
    --swamped-cli /path/to/swamped_cli.py \
    --swamped-repo /path/to/SWAMPED \
    --browser-runner /path/to/browser_runner.js \
    --node-path /tmp/puppeteer_env/node_modules \
    --wabt-bin /usr/bin \
    --wasmer-bin /root/.wasmer/bin/wasmer \
    --cores 8 \
    [--run-ghidra --ghidra-headless /opt/ghidra/support/analyzeHeadless]
"""

import argparse
import csv
import json
import multiprocessing
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

from combos import generate_combinations, STRATEGIES, DEFAULT_RATIOS
from orig_metrics import load_cache
from metrics_worker import process_combo_swamped
from pipeline_core import FIELDS, discover_samples, run_phase1, csv_has_header, normalize_row

BATCH_SIZE = 20


def _phase2_worker(args):
    try:
        return process_combo_swamped(*args)
    except Exception as e:
        sample, rel = args[0], args[1]
        strategy, ratio = args[6], args[7]
        print(f"[combo][ERROR] {rel} {strategy} ratio={ratio}: {e}")
        return {
            "sample": sample, "relpath_orig": rel,
            "obfuscation_transformation": strategy, "ratio": ratio,
            "notes": [f"worker_exception:{e}"],
        }


def load_done_combos(csv_path):
    """(relpath, strategy, ratio) triples already present in the CSV."""
    done = set()
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return done
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            done.add((row["relpath_orig"], row["obfuscation_transformation"], row.get("ratio")))
    return done


def build_phase2_tasks(samples, resolved, out_root, swamped_cli, swamped_repo, wabt_bins,
                        runtime_bin, browser_runner_js, timeout, tmp_root, strategies, ratios,
                        run_ghidra, ghidra_headless, ghidra_script_dir, ghidra_timeout,
                        done_combos, node_path=None, swamped_python="python3"):
    combos = generate_combinations(strategies, ratios)
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
        for strategy, ratio in combos:
            key = (rel, strategy, ratio)
            if key in done_combos:
                continue
            tasks.append((
                sample, rel, str(orig_copy_path), orig_metrics, str(sample_out_dir),
                str(swamped_cli), str(swamped_repo), strategy, ratio, wabt_bins, runtime_bin,
                str(browser_runner_js), timeout, str(tmp_root),
                run_ghidra, ghidra_headless, ghidra_script_dir, ghidra_timeout, node_path,
                swamped_python,
            ))
    return tasks


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True, help="Root folder with .wasm/.wat/.c files (recursive)")
    ap.add_argument("--outdir", required=True, help="Where perturbed binaries + logs are written")
    ap.add_argument("--csv", required=True, help="Output CSV path")
    ap.add_argument("--swamped-cli", required=True, help="Path to swamped_cli.py")
    ap.add_argument("--swamped-repo", required=True,
                     help="Path to the SWAMPED repo root (kept as a cwd/PYTHONPATH safety "
                          "net; swamped_cli.py itself resolves its imports from its own "
                          "file location, not from this, but it's harmless to set)")
    ap.add_argument("--swamped-python", default="python3",
                     help="Python interpreter used to invoke swamped_cli.py, resolved from "
                          "PATH by default (matches how your previously-working driver "
                          "script invoked it). Deliberately NOT sys.executable (the "
                          "interpreter running this pipeline) -- those can be two different "
                          "Python installations. Point this explicitly at whichever "
                          "interpreter has matplotlib/numpy/scipy installed if unsure, e.g. "
                          "an absolute path to a specific venv's python3.")
    ap.add_argument("--browser-runner", required=True, help="Path to browser_runner.js")
    ap.add_argument("--node-path", default=os.environ.get("NODE_PATH"),
                     help="Directory containing node_modules/puppeteer, passed as NODE_PATH "
                          "to every browser_runner.js subprocess. Defaults to the current "
                          "NODE_PATH env var if already set.")
    ap.add_argument("--wabt-bin", default="/usr/bin")
    ap.add_argument("--runtime-bin", "--wasmer-bin", "--wasmtime-bin",
                     dest="runtime_bin", default=str(Path.home() / ".wasmer/bin/wasmer"),
                     help="Path to the wasm runtime binary -- wasmer (default) or wasmtime, "
                          "auto-detected from the filename (wasm_runtime.py).")
    ap.add_argument("--strategies", default=None,
                     help="Comma-separated subset of strategies to run (default: all 20 -- see combos.py)")
    ap.add_argument("--ratios", default=None,
                     help="Comma-separated subset of ratios to run (default: 0.1..1.0 step 0.1)")
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
    swamped_cli = Path(args.swamped_cli)
    swamped_repo = Path(args.swamped_repo)
    if not swamped_cli.exists():
        print(f"ERROR: {swamped_cli} not found (check --swamped-cli path)")
        sys.exit(1)
    if not swamped_repo.exists():
        print(f"ERROR: {swamped_repo} not found (check --swamped-repo path)")
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

    strategies = args.strategies.split(",") if args.strategies else STRATEGIES
    ratios = args.ratios.split(",") if args.ratios else DEFAULT_RATIOS

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

    print("=== Phase 2: SWAMPED strategy x ratio combos ===")
    done_combos = load_done_combos(csv_path)
    print(f"{len(done_combos)} (sample, strategy, ratio) triples already in CSV -- will be skipped")

    tasks = build_phase2_tasks(
        samples, resolved, outdir, swamped_cli, swamped_repo, wabt_bins, args.runtime_bin,
        args.browser_runner, args.timeout, tmp_root, strategies, ratios,
        args.run_ghidra, args.ghidra_headless, args.ghidra_script_dir, args.ghidra_timeout,
        done_combos, node_path=args.node_path, swamped_python=args.swamped_python,
    )
    print(f"{len(tasks)} task(s) to run (up to {len(samples)} sample(s) x "
          f"{len(strategies)} strategies x {len(ratios)} ratios)")

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
                print(f"[combo] {row['relpath_orig']} [{row['obfuscation_transformation']} "
                      f"r={row['ratio']}] -> valid_obf={row['valid_obf']} "
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
