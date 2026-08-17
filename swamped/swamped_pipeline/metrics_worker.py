#!/usr/bin/env python3
# metrics_worker.py
"""
Per-(sample, strategy, ratio) worker for SWAMPED: applies one perturbation
strategy at one ratio, computes every "*_obf" metric, and derives the
orig-vs-obf comparison fields.

Invocation, matching swamped_cli.py's real argparse interface (verified
against source):

    python3 swamped_cli.py obfuscate <input.wasm> -o <output.wasm> \
        -s <strategy> --ratio <ratio>
"""

import shutil
import time
import uuid
from pathlib import Path

from common import (
    run_cmd, wasm2wat_text, wasm_dis_text, count_call_indirect,
    max_nesting, count_symbols, wat_similarity, run_in_browser_and_hash,
)
from wasm_runtime import run_wasm_with_inferred_args
from cfg_similarity import cfg_similarity_structural
from deobfuscation_vulnerability import deobfuscation_vulnerability
from combos import combo_label


def _empty_obf_row_fields():
    return {
        "size_obf": None, "call_ind_obf": None, "max_nesting_obf": None,
        "valid_obf": "missing", "run_obf": None, "run_time_obf": None,
        "import_trace_hash_obf": None,
        "memory_pages_obf": None, "exports_called_obf": [],
        "browser_error_obf": None, "disassembly_ok_obf": None,
        "wat_similarity": None, "cfg_similarity": None,
        "func_symbols_obf": None, "type_symbols_obf": None,
        "deobf_ghidra_funcs_obf": None, "deobf_score_obf": None,
    }


def process_combo_swamped(sample, rel, orig_wasm_path, orig_metrics, out_root,
                           swamped_cli, swamped_repo, strategy, ratio, wabt_bins,
                           runtime_bin, browser_runner_js, timeout, tmp_root,
                           run_ghidra=False, ghidra_headless=None,
                           ghidra_script_dir=None, ghidra_timeout=300,
                           node_path=None, swamped_python="python3"):
    out_root = Path(out_root)
    swamped_cli = Path(swamped_cli)
    swamped_repo = Path(swamped_repo)
    tmp_root = Path(tmp_root)
    orig_wasm_path = Path(orig_wasm_path)

    label = combo_label(strategy, ratio)  # "nop_insertion_r0.5" -- folder/mutant_id only
    mutant_id = f"{label}_{uuid.uuid4().hex[:8]}"
    out_combo_dir = out_root / f"{sample}__{mutant_id}"
    out_combo_dir.mkdir(parents=True, exist_ok=True)

    tmp_dir = tmp_root / uuid.uuid4().hex[:10]
    tmp_dir.mkdir(parents=True, exist_ok=True)

    row = {
        "sample": sample, "relpath_orig": rel,
        "obfuscation_transformation": strategy, "ratio": ratio, "mutant_id": mutant_id,
        "size_orig": orig_metrics.get("size"),
        "call_ind_orig": orig_metrics.get("call_ind"),
        "max_nesting_orig": orig_metrics.get("max_nesting"),
        "valid_orig": orig_metrics.get("valid"),
        "run_orig": orig_metrics.get("run"),
        "run_time_orig": orig_metrics.get("run_time"),
        "import_trace_hash_orig": orig_metrics.get("import_trace_hash"),
        "memory_pages_orig": orig_metrics.get("memory_pages"),
        "exports_called_orig": orig_metrics.get("exports_called"),
        "browser_error_orig": orig_metrics.get("browser_error"),
        "disassembly_ok_orig": orig_metrics.get("disassembly_ok"),
        "func_symbols_orig": orig_metrics.get("func_symbols"),
        "type_symbols_orig": orig_metrics.get("type_symbols"),
        "deobf_ghidra_funcs_orig": orig_metrics.get("deobf_ghidra_funcs"),
        "deobf_score_orig": orig_metrics.get("deobf_score"),
        "notes": list(orig_metrics.get("notes", [])),
        "obf_time": None,
    }
    row.update(_empty_obf_row_fields())

    # --- fresh copy of the ORIGINAL, isolated per task ---
    tmp_wasm = tmp_dir / f"{sample}.wasm"
    try:
        shutil.copy2(orig_wasm_path, tmp_wasm)
    except Exception as e:
        row["notes"].append(f"copy_failed:{e}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return row

    # --- run SWAMPED ---
    out_obf = out_combo_dir / f"{sample}_{label}.wasm"
    swamped_cmd = [
        swamped_python, str(swamped_cli), "obfuscate", str(tmp_wasm),
        "-o", str(out_obf), "-s", strategy, "--ratio", str(ratio),
    ]
    t0 = time.time()
    rc_sw, out_sw, err_sw = run_cmd(
        swamped_cmd, timeout, cwd=str(swamped_repo),
        extra_env={"PYTHONPATH": str(swamped_repo)},
    )
    t1 = time.time()
    row["obf_time"] = round(t1 - t0, 6)
    (out_combo_dir / "swamped_stdout.log").write_text(out_sw or "")
    (out_combo_dir / "swamped_stderr.log").write_text(err_sw or "")

    if rc_sw != 0 or not out_obf.exists():
        row["valid_obf"] = "missing"
        row["notes"].append(f"swamped_failed:rc={rc_sw}:{(err_sw or '').strip()[:200]}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return row

    # ---- obf-side static metrics ----
    try:
        row["size_obf"] = out_obf.stat().st_size
    except Exception:
        pass

    rc_v, _, _ = run_cmd([wabt_bins.get("validate", "wasm-validate"), str(out_obf)], timeout)
    row["valid_obf"] = "ok" if rc_v == 0 else f"invalid({rc_v})"

    wat_obf_text = wasm2wat_text(out_obf, wabt_bins.get("wasm2wat", "wasm2wat"))
    row["call_ind_obf"] = count_call_indirect(wat_obf_text)
    row["max_nesting_obf"] = max_nesting(wat_obf_text)

    dis_obf_text = wasm_dis_text(out_obf)
    row["disassembly_ok_obf"] = "yes" if dis_obf_text else "no"
    sym_obf = count_symbols(dis_obf_text)
    row["func_symbols_obf"] = sym_obf["func"]
    row["type_symbols_obf"] = sym_obf["type"]

    # ---- structural / lexical similarity ----
    row["wat_similarity"] = wat_similarity(orig_metrics.get("_dis_text"), dis_obf_text)
    row["cfg_similarity"] = cfg_similarity_structural(orig_metrics.get("_wat_text"), wat_obf_text)

    # ---- native run ----
    run_res = run_wasm_with_inferred_args(runtime_bin, out_obf, wat_obf_text, timeout)
    row["run_obf"] = run_res["status"]
    row["run_time_obf"] = run_res["elapsed_s"]
    if run_res["notes"]:
        row["notes"].extend(f"run_native_obf:{n}" for n in run_res["notes"])

    # ---- browser run ----
    browser_res = run_in_browser_and_hash(
        browser_runner_js, out_obf,
        timeout_s=min(15, max(5, int(timeout / 2))),
        out_json_path=out_combo_dir / "browser_obf.json",
        node_path=node_path,
    )
    if browser_res.get("error"):
        row["browser_error_obf"] = browser_res.get("error")
        row["notes"].append(f"browser_obf_error:{browser_res.get('error')}")
    else:
        row["import_trace_hash_obf"] = browser_res.get("import_trace_hash")
        row["memory_pages_obf"] = browser_res.get("memory_pages")
        row["exports_called_obf"] = browser_res.get("exports_called", [])

    if row["import_trace_hash_orig"] and row["import_trace_hash_obf"]:
        row["import_trace_match"] = "yes" if row["import_trace_hash_orig"] == row["import_trace_hash_obf"] else "no"
    else:
        row["import_trace_match"] = "n/a"

    # ---- payload_preserved ----
    # SWAMPED's perturbations are documented as semantics-preserving by
    # design (paper, Section III-B: "Both types of perturbations preserve
    # the program's original semantics"), so a "no" here is a genuine
    # correctness signal worth flagging in the paper, not an expected
    # trade-off the way WasMixer's T2/memory-encryption case was.
    if row["run_orig"] != "ok":
        row["payload_preserved"] = "n/a"
    else:
        row["payload_preserved"] = "yes" if (
            row["valid_obf"] == "ok" and row["run_obf"] == "ok"
            and row["import_trace_match"] == "yes"
        ) else "no"

    # ---- deobfuscation resistance (obf side) ----
    deobf = deobfuscation_vulnerability(
        out_obf, timeout_wabt=timeout, timeout_binaryen=timeout,
        timeout_ghidra=ghidra_timeout, ghidra_headless=ghidra_headless,
        ghidra_script_dir=ghidra_script_dir, run_ghidra=run_ghidra,
    )
    if deobf["ghidra"] is not None:
        row["deobf_ghidra_funcs_obf"] = deobf["ghidra"]["func_count"]
    row["deobf_score_obf"] = deobf["score"]

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return row
