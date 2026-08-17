#!/usr/bin/env python3
# pipeline_core.py
"""
Obfuscator-agnostic building blocks shared by the WasmMutate pipeline:
- recursive dataset discovery (+ .c/.wat -> .wasm normalization)
- phase 1: original-side metrics, computed once per sample and cached
  (see orig_metrics.py for what's computed and why it's cached)
- CSV schema + read/write helpers for resuming an interrupted run

"""

import csv
import hashlib
import json
import multiprocessing
import os
import subprocess
from pathlib import Path

from orig_metrics import compute_orig_metrics, save_cache, load_cache

FIELDS = [
    "sample", "relpath_orig", "obfuscation_transformation", "mutant_id",
    "size_orig", "size_obf", "call_ind_orig", "call_ind_obf",
    "max_nesting_orig", "max_nesting_obf", "valid_orig", "valid_obf",
    "run_orig", "run_obf", "run_time_orig", "run_time_obf",
    "import_trace_hash_orig", "import_trace_hash_obf", "import_trace_match",
    "payload_preserved", "memory_pages_orig", "memory_pages_obf",
    "exports_called_orig", "exports_called_obf",
    "browser_error_orig", "browser_error_obf",
    "disassembly_ok_orig", "disassembly_ok_obf",
    "wat_similarity", "cfg_similarity",
    "func_symbols_orig", "func_symbols_obf", "type_symbols_orig", "type_symbols_obf",
    "deobf_ghidra_funcs_orig", "deobf_ghidra_funcs_obf",
    "deobf_score_orig", "deobf_score_obf",
    "notes", "obf_time",
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


def normalize_row(res):
    row = {}
    for f in FIELDS:
        v = res.get(f)
        if isinstance(v, list):
            v = json.dumps(v)
        row[f] = v
    return row


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
     wabt_bins, runtime_bin, browser_runner_js, timeout,
     run_ghidra, ghidra_headless, ghidra_script_dir, ghidra_timeout, node_path) = args
    try:
        import shutil
        shutil.copy2(src_path, orig_copy_path)
        metrics = compute_orig_metrics(
            orig_copy_path, wabt_bins, runtime_bin, browser_runner_js,
            timeout, out_dir, run_ghidra=run_ghidra,
            ghidra_headless=ghidra_headless, ghidra_script_dir=ghidra_script_dir,
            ghidra_timeout=ghidra_timeout, node_path=node_path,
        )
        save_cache(cache_path, metrics)
        print(f"[orig] {rel} -> valid={metrics.get('valid')} run={metrics.get('run')}")
        return (rel, True)
    except Exception as e:
        print(f"[orig][ERROR] {rel}: {e}")
        return (rel, False)


def run_phase1(samples, tmp_root, out_root, wabt_bins, runtime_bin,
                browser_runner_js, timeout, cores, run_ghidra,
                ghidra_headless, ghidra_script_dir, ghidra_timeout, node_path=None):
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

        # resume check validates the cache (version-checked by load_cache),
        # not just its existence on disk -- a stale cache from a previous,
        # buggier version of orig_metrics.py must NOT be silently reused.
        if orig_copy_path.exists() and load_cache(cache_path) is not None:
            continue  # resume: already computed with the current code

        sample_out_dir = out_root / sample
        sample_out_dir.mkdir(parents=True, exist_ok=True)
        tasks.append((
            sample, rel, src_path, orig_copy_path, cache_path, sample_out_dir,
            wabt_bins, runtime_bin, browser_runner_js, timeout,
            run_ghidra, ghidra_headless, ghidra_script_dir, ghidra_timeout, node_path,
        ))

    print(f"[phase1] {len(tasks)} sample(s) need orig-metrics computation "
          f"({len(samples) - len(tasks)} resumed from cache)")

    if tasks:
        with multiprocessing.Pool(processes=cores) as pool:
            for _ in pool.imap_unordered(_phase1_worker, tasks):
                pass

    return resolved
