#!/usr/bin/env python3
# metrics_worker.py


import shutil
import sys
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
from combos import combo_label, flags_label as _flags_label


def _empty_obf_row_fields():
    return {
        "size_obf": None, "call_ind_obf": None, "max_nesting_obf": None,
        "valid_obf": "missing", "run_obf": None, "run_time_obf": None,
        "run_func_obf": None, "retval_obf": None,
        "state_hash_obf": None, "import_trace_hash_obf": None,
        "memory_pages_obf": None, "exports_called_obf": [],
        "browser_error_obf": None, "disassembly_ok_obf": None,
        "wat_similarity": None, "cfg_similarity": None,
        "func_symbols_obf": None, "type_symbols_obf": None,
        "deobf_wabt_obf": None, "deobf_binaryen_obf": None,
        "deobf_ghidra_obf": None, "deobf_ghidra_funcs_obf": None,
        "deobf_score_obf": None,
    }


def process_combo(sample, rel, orig_wasm_path, orig_metrics, out_root,
                   wasmixer_cli, combo_tuple, cli_flags, wabt_bins,
                   wasmtime_bin, browser_runner_js, timeout, tmp_root,
                   run_ghidra=False, ghidra_headless=None,
                   ghidra_script_dir=None, ghidra_timeout=300):
    out_root = Path(out_root)
    wasmixer_cli = Path(wasmixer_cli)
    tmp_root = Path(tmp_root)
    orig_wasm_path = Path(orig_wasm_path)

    label = combo_label(combo_tuple)  # "T1+T3+T5" -- used only for folder/mutant_id readability
    # CSV column shows the actual CLI flags (what the user asked for), not
    # the internal T1..T5 shorthand -- e.g. "--name --flatten --collatz".
    # --safe is stripped since it's a pipeline implementation detail, not
    # an obfuscation transformation.
    display_label = _flags_label(cli_flags)
    mutant_id = f"{label}_{uuid.uuid4().hex[:8]}"
    out_combo_dir = out_root / f"{sample}__{mutant_id}"
    out_combo_dir.mkdir(parents=True, exist_ok=True)

    tmp_dir = tmp_root / uuid.uuid4().hex[:10]
    tmp_dir.mkdir(parents=True, exist_ok=True)

    row = {
        "sample": sample, "relpath_orig": rel,
        "obfuscation_transformation": display_label, "mutant_id": mutant_id,
        "size_orig": orig_metrics.get("size"),
        "call_ind_orig": orig_metrics.get("call_ind"),
        "max_nesting_orig": orig_metrics.get("max_nesting"),
        "valid_orig": orig_metrics.get("valid"),
        "run_orig": orig_metrics.get("run"),
        "run_time_orig": orig_metrics.get("run_time"),
        "run_func_orig": orig_metrics.get("run_func"),
        "retval_orig": orig_metrics.get("retval"),
        "state_hash_orig": orig_metrics.get("state_hash"),
        "import_trace_hash_orig": orig_metrics.get("import_trace_hash"),
        "memory_pages_orig": orig_metrics.get("memory_pages"),
        "exports_called_orig": orig_metrics.get("exports_called"),
        "browser_error_orig": orig_metrics.get("browser_error"),
        "disassembly_ok_orig": orig_metrics.get("disassembly_ok"),
        "func_symbols_orig": orig_metrics.get("func_symbols"),
        "type_symbols_orig": orig_metrics.get("type_symbols"),
        "deobf_wabt_orig": orig_metrics.get("deobf_wabt"),
        "deobf_binaryen_orig": orig_metrics.get("deobf_binaryen"),
        "deobf_ghidra_orig": orig_metrics.get("deobf_ghidra"),
        "deobf_ghidra_funcs_orig": orig_metrics.get("deobf_ghidra_funcs"),
        "deobf_score_orig": orig_metrics.get("deobf_score"),
        "notes": list(orig_metrics.get("notes", [])),
        "obf_time": None,
    }
    row.update(_empty_obf_row_fields())

    # --- fresh copy of the ORIGINAL, isolated per task (never mutate the
    #     persistent orig copy or the source dataset file) ---
    tmp_wasm = tmp_dir / f"{sample}.wasm"
    try:
        shutil.copy2(orig_wasm_path, tmp_wasm)
    except Exception as e:
        row["notes"].append(f"copy_failed:{e}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return row

    # --- run WasMixer (cli_flags already includes --safe -> deterministic
    #     output path, no mtime/glob heuristic needed) ---
    wasmixer_cmd = [sys.executable, str(wasmixer_cli), str(tmp_wasm)] + list(cli_flags)
    t0 = time.time()
    rc_mix, out_mix, err_mix = run_cmd(wasmixer_cmd, timeout, cwd=str(wasmixer_cli.parent))
    t1 = time.time()
    row["obf_time"] = round(t1 - t0, 6)
    (out_combo_dir / "wasmixer_stdout.log").write_text(out_mix or "")
    (out_combo_dir / "wasmixer_stderr.log").write_text(err_mix or "")

    base = str(tmp_wasm)[:-len(".wasm")] if str(tmp_wasm).endswith(".wasm") else str(tmp_wasm)
    obf_path = Path(f"{base}_mixr.wasm")

    if rc_mix != 0 or not obf_path.exists():
        row["valid_obf"] = "missing"
        row["notes"].append(f"wasmixer_failed:rc={rc_mix}:{(err_mix or '').strip()[:200]}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return row

    # persist the obfuscated binary
    out_obf = out_combo_dir / f"{sample}_mixr_{label}.wasm"
    try:
        shutil.copy2(obf_path, out_obf)
    except Exception as e:
        row["notes"].append(f"copy_obf_failed:{e}")
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
    # cfg_similarity is now built from wasm2wat text (see cfg_from_wat.py) --
    # `wasm-opt --print-cfg` is not a real Binaryen flag and always failed
    # silently in earlier versions of this pipeline.
    row["cfg_similarity"] = cfg_similarity_structural(orig_metrics.get("_wat_text"), wat_obf_text)

    # ---- native run (wasmtime), same entry-point-selection logic as orig ----
    run_res = run_wasm_with_inferred_args(wasmtime_bin, out_obf, wat_obf_text, timeout)
    row["run_obf"] = run_res["status"]
    row["run_time_obf"] = run_res["elapsed_s"]
    row["run_func_obf"] = run_res["func"]
    if run_res["status"] == "ok":
        row["retval_obf"] = run_res["stdout"].strip()
    if run_res["notes"]:
        row["notes"].extend(f"run_native_obf:{n}" for n in run_res["notes"])

    if row["run_orig"] == "ok" and row["run_obf"] == "ok":
        row["retval_match"] = "yes" if row["retval_orig"] == row["retval_obf"] else "no"
    else:
        row["retval_match"] = "n/a"

    # ---- browser run (behavioral ground truth) ----
    browser_res = run_in_browser_and_hash(
        browser_runner_js, out_obf,
        timeout_s=min(15, max(5, int(timeout / 2))),
        out_json_path=out_combo_dir / "browser_obf.json",
    )
    # BUGFIX: see orig_metrics.py -- "error" key is always present (null on
    # success), must test its value, not membership.
    if browser_res.get("error"):
        row["browser_error_obf"] = browser_res.get("error")
        row["notes"].append(f"browser_obf_error:{browser_res.get('error')}")
    else:
        row["state_hash_obf"] = browser_res.get("state_hash")
        row["import_trace_hash_obf"] = browser_res.get("import_trace_hash")
        row["memory_pages_obf"] = browser_res.get("memory_pages")
        row["exports_called_obf"] = browser_res.get("exports_called", [])

    if row["state_hash_orig"] and row["state_hash_obf"]:
        row["state_match"] = "yes" if row["state_hash_orig"] == row["state_hash_obf"] else "no"
    else:
        row["state_match"] = "n/a"

    if row["import_trace_hash_orig"] and row["import_trace_hash_obf"]:
        row["import_trace_match"] = "yes" if row["import_trace_hash_orig"] == row["import_trace_hash_obf"] else "no"
    else:
        row["import_trace_match"] = "n/a"

    # ---- payload_preserved ----
    # "Preserved" presupposes there was observable baseline behavior to
    # preserve in the first place. If the ORIGINAL never ran (no invocable
    # export, timeout, trap, etc.) there is nothing to compare against --
    # report "n/a", not "no" (a "no" would misleadingly read as "WasMixer
    # broke this sample", when in fact the sample had no runtime behavior
    # before obfuscation either).
    #
    # T2 (memory obfuscation) legitimately breaks raw state_hash comparison
    # (encrypted-at-rest memory, decrypted only through hooked accesses that
    # the snapshot never exercises) -- so import_trace_match is the primary
    # signal whenever T2 is present; state_match is required in addition
    # only when T2 is absent.
    if row["run_orig"] != "ok":
        row["payload_preserved"] = "n/a"
    else:
        has_t2 = "T2" in combo_tuple
        base_ok = (row["valid_obf"] == "ok" and row["run_obf"] == "ok"
                   and row["import_trace_match"] == "yes")
        if has_t2:
            row["payload_preserved"] = "yes" if base_ok else "no"
        else:
            row["payload_preserved"] = "yes" if (base_ok and row["state_match"] == "yes") else "no"

    # ---- deobfuscation resistance (obf side) ----
    deobf = deobfuscation_vulnerability(
        out_obf, timeout_wabt=timeout, timeout_binaryen=timeout,
        timeout_ghidra=ghidra_timeout, ghidra_headless=ghidra_headless,
        ghidra_script_dir=ghidra_script_dir, run_ghidra=run_ghidra,
    )
    row["deobf_wabt_obf"] = deobf["wabt"]["success"]
    row["deobf_binaryen_obf"] = deobf["binaryen"]["success"]
    if deobf["ghidra"] is not None:
        row["deobf_ghidra_obf"] = deobf["ghidra"]["success"]
        row["deobf_ghidra_funcs_obf"] = deobf["ghidra"]["func_count"]
    row["deobf_score_obf"] = deobf["score"]

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return row
