#!/usr/bin/env python3
# analyze_spectec_swamped.py
"""
SpecTec-based formal validity analysis for SWAMPED outputs.

"""

import argparse
import csv
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from spectec_core import (
    run_spectec, build_extra_row_fields, csv_has_header,
    load_existing_keys, read_input_csv, merged_fieldnames, BATCH_SIZE,
)


def resolve_ratio(row):
    if "ratio" in row and row["ratio"] not in (None, ""):
        try:
            return float(row["ratio"])
        except ValueError:
            pass
    # legacy fallback: old SWAMPED mutant_id format "sample_strategy_ratio"
    try:
        return float(row["mutant_id"].split("_")[-1])
    except Exception:
        return 1.0


def find_swamped_obf(outdir_root, rel_dir, ratio, sample, strategy):
    """
    SWAMPED output layout:
        outdir_root / rel_dir / ratio / sample / strategy / sample_strategy.wasm
    """
    path = (
        Path(outdir_root)
        / rel_dir
        / str(ratio)
        / sample
        / strategy
        / f"{sample}_{strategy}.wasm"
    )
    return path if path.exists() else None


def process_row(args):
    row, dataset_root, outdir_root, spectec_bin, timeout = args

    relpath = row["relpath"]
    sample = row["sample"]
    strategy = row["obfuscation_transformation"]
    ratio = resolve_ratio(row)
    rel_dir = Path(relpath).parent

    orig_wasm = Path(relpath)
    if not orig_wasm.is_absolute():
        orig_wasm = Path(dataset_root) / relpath

    obf_wasm = find_swamped_obf(outdir_root, rel_dir, ratio, sample, strategy)

    res_orig = run_spectec(spectec_bin, orig_wasm, timeout)
    res_obf = run_spectec(spectec_bin, obf_wasm, timeout)

    row_out = dict(row)
    row_out.update(build_extra_row_fields(res_orig, res_obf))

    print(f"[SWAMPED-SpecTec] {sample} [{strategy} | r={ratio}] -> "
          f"orig={row_out['spec_valid_orig']} obf={row_out['spec_valid_obf']} "
          f"both_valid={row_out['spec_valid_both_bool']}")

    return row_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-csv", required=True)
    ap.add_argument("--output-csv", required=True)
    ap.add_argument("--dataset-root", required=True)
    ap.add_argument("--outdir-root", required=True)
    ap.add_argument("--spectec-bin", default="./spectec/interpreter/wasm")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--cores", type=int, default=4)
    args = ap.parse_args()

    output_csv = Path(args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    original_fields, all_rows = read_input_csv(args.input_csv)
    new_fields = merged_fieldnames(original_fields)

    key_fields = ["relpath", "obfuscation_transformation", "mutant_id"]
    done_keys = load_existing_keys(output_csv, key_fields)
    print(f"Already processed rows: {len(done_keys)}")

    pending_rows = [r for r in all_rows if tuple(r.get(k, "") for k in key_fields) not in done_keys]
    print(f"Rows remaining: {len(pending_rows)} / {len(all_rows)}")

    if not pending_rows:
        print("Nothing to do.")
        return

    write_header = not csv_has_header(output_csv)
    tasks = [(row, args.dataset_root, args.outdir_root, args.spectec_bin, args.timeout) for row in pending_rows]

    buffer = []
    with open(output_csv, "a", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=new_fields, extrasaction="ignore")
        if write_header:
            writer.writeheader()
            f_out.flush()

        with Pool(args.cores) as pool:
            for row_out in pool.imap_unordered(process_row, tasks):
                buffer.append(row_out)
                if len(buffer) >= BATCH_SIZE:
                    writer.writerows(buffer)
                    f_out.flush()
                    buffer.clear()

            if buffer:
                writer.writerows(buffer)
                f_out.flush()
                buffer.clear()

    print(f"\nDONE -> {output_csv}")


if __name__ == "__main__":
    main()
