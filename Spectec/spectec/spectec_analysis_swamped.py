#!/usr/bin/env python3
# spectec_analysis_swamped.py
"""
Usage
-----
python3 spectec_analysis_swamped.py \
    --dataset    /path/to/orig/dataset \
    --input-csv  /path/to/swamped_results.csv \
    --output-csv /path/to/swamped_results_spectec.csv \
    --obf-dir    /path/to/swamped_outdir \
    --spectec-bin /path/to/spectec/interpreter/wasm \
    --wabt-bin /usr/bin \
    --cores 8
"""

import argparse
import csv
import os
import sys
from pathlib import Path
from multiprocessing import Pool

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from spectec_common import (
    sanitize, wasm2wat_text, run_spectec, semantic_equivalence,
    find_obf_path, csv_has_header, load_done, EXTRA_FIELDS,
)

# populated by _init_worker() in each pool process (module-level globals
# are the simplest way to pass fixed config into multiprocessing.Pool
# workers without re-pickling it on every single task)
_CFG = {}


def _init_worker(dataset, obf_dir, spectec_bin, wasm2wat_bin, timeout, n_inputs):
    _CFG.update(dataset=dataset, obf_dir=obf_dir, spectec_bin=spectec_bin,
                wasm2wat_bin=wasm2wat_bin, timeout=timeout, n_inputs=n_inputs)


def process_row(row):
    orig_path = Path(_CFG["dataset"]) / row.get("relpath_orig", "")
    obf_path = find_obf_path(_CFG["obf_dir"], row.get("sample", ""), row.get("mutant_id", ""))
    sample = row.get("sample", "?")
    flags = row.get("obfuscation_transformation", "?")

    if orig_path.exists():
        valid_o, crash_o, rc_o, out_o = run_spectec(orig_path, _CFG["spectec_bin"], _CFG["timeout"])
    else:
        valid_o, crash_o, rc_o, out_o = False, True, -2, f"orig_file_not_found:{orig_path}"

    if obf_path and obf_path.exists():
        valid_b, crash_b, rc_b, out_b = run_spectec(obf_path, _CFG["spectec_bin"], _CFG["timeout"])
    else:
        valid_b, crash_b, rc_b, out_b = False, True, -2, "obf_file_not_found"

    if orig_path.exists() and obf_path and obf_path.exists():
        wat = wasm2wat_text(orig_path, _CFG["wasm2wat_bin"])
        sem_equiv = semantic_equivalence(orig_path, obf_path, wat, _CFG["spectec_bin"],
                                          _CFG["timeout"], _CFG["n_inputs"])
    else:
        sem_equiv = "skipped"

    extra = {
        "spec_valid_orig": "yes" if valid_o else "no",
        "spec_valid_obf": "yes" if valid_b else "no",
        "semantic_equivalence_bool": sem_equiv,
        "spec_errors_orig": sanitize(out_o) if not valid_o else "",
        "spec_errors_obf": sanitize(out_b) if not valid_b else "",
        "spec_violation_count": (0 if valid_o else 1) + (0 if valid_b else 1),
        "interpreter_crash": "yes" if (crash_o or crash_b) else "no",
    }

    result = dict(row)
    result.update(extra)
    print(f"  [SpecTec] {sample[:25]} [{flags}] "
          f"valid_orig={extra['spec_valid_orig']} valid_obf={extra['spec_valid_obf']} "
          f"equiv={extra['semantic_equivalence_bool']} crash={extra['interpreter_crash']}")
    return result


def worker_wrapper(row):
    try:
        return process_row(row)
    except Exception as e:
        result = dict(row)
        for f in EXTRA_FIELDS:
            result.setdefault(f, "")
        result["spec_errors_orig"] = sanitize(f"worker_exc:{e}")
        return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True,
                     help="The ORIGINAL dataset root -- must match run_swamped.py's own --dataset "
                          "exactly, since relpath_orig in the CSV is relative to it")
    ap.add_argument("--input-csv", required=True, help="SWAMPED metrics CSV to enrich")
    ap.add_argument("--output-csv", required=True, help="Enriched CSV output path (resumable)")
    ap.add_argument("--obf-dir", required=True, help="run_swamped.py's --outdir")
    ap.add_argument("--spectec-bin", required=True, help="Path to the SpecTec reference interpreter binary")
    ap.add_argument("--wabt-bin", default="/usr/bin", help="Directory containing wasm2wat")
    ap.add_argument("--timeout", type=int, default=120, help="Per-SpecTec-call timeout (seconds)")
    ap.add_argument("--n-inputs", type=int, default=5, help="Input vectors tried for semantic equivalence")
    ap.add_argument("--cores", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=50)
    args = ap.parse_args()

    dataset = Path(args.dataset)
    input_csv = Path(args.input_csv)
    output_csv = Path(args.output_csv)
    spectec_bin = Path(args.spectec_bin)
    wasm2wat_bin = str(Path(args.wabt_bin) / "wasm2wat")

    if not dataset.exists():
        print(f"[FATAL] --dataset not found: {dataset}")
        sys.exit(1)
    if not input_csv.exists():
        print(f"[FATAL] Input CSV not found: {input_csv}")
        sys.exit(1)
    if not spectec_bin.exists():
        print(f"[FATAL] SpecTec binary not found: {spectec_bin}")
        sys.exit(1)

    print(f"Dataset (orig) : {dataset}")
    print(f"SpecTec binary : {spectec_bin}")
    print(f"Input CSV      : {input_csv}")
    print(f"Output CSV     : {output_csv}")
    print(f"Obf dir        : {args.obf_dir}")

    with open(input_csv, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    new_fields = list(fieldnames) + [fld for fld in EXTRA_FIELDS if fld not in fieldnames]

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(output_csv)
    print(f"Already processed: {len(done)} / {len(rows)}")

    pending = [r for r in rows if (r.get("relpath_orig", ""), r.get("mutant_id", "")) not in done]
    print(f"Remaining: {len(pending)}")
    if not pending:
        print("Nothing to do.")
        return

    write_header = not csv_has_header(output_csv)
    buf = []
    with open(output_csv, "a", newline="") as cf:
        writer = csv.DictWriter(cf, fieldnames=new_fields, extrasaction="ignore", quoting=csv.QUOTE_ALL)
        if write_header:
            writer.writeheader()
            cf.flush()
            os.fsync(cf.fileno())

        with Pool(args.cores, initializer=_init_worker,
                  initargs=(str(dataset), args.obf_dir, str(spectec_bin), wasm2wat_bin,
                            args.timeout, args.n_inputs)) as pool:
            for res in pool.imap_unordered(worker_wrapper, pending):
                if not isinstance(res, dict):
                    continue
                buf.append(res)
                if len(buf) >= args.batch_size:
                    writer.writerows(buf)
                    cf.flush()
                    os.fsync(cf.fileno())
                    buf.clear()

        if buf:
            writer.writerows(buf)
            cf.flush()
            os.fsync(cf.fileno())

    print(f"\nDone. Enriched CSV -> {output_csv}")


if __name__ == "__main__":
    main()
