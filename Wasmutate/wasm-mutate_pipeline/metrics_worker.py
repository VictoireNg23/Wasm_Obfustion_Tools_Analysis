#!/usr/bin/env python3
# metrics_worker.py


import functools
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
from combos import combo_label, categories_flag


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


@functools.lru_cache(maxsize=None)
def _mutator_capabilities(mutator_bin):
    """
    Probes `$MUTATOR --help` once per (mutator_bin) and caches the result
    (cheap, but no need to repeat it for every one of the 127 combos x N
    variants). Returns a frozenset of the long-flag names this specific
    binary actually supports, detected from its own --help text rather
    than assumed -- so the pipeline adapts automatically whether it's
    pointed at an old wrapper build (only --input/--outdir/--variants/
    --stack-depth) or the corrected one (adds --preserve-semantics,
    --seed, --categories). This avoids the exact class of "unexpected
    argument" failure that comes from a stale --mutator path: whichever
    binary is actually configured, the pipeline sends only the flags it
    understands instead of erroring out on every single task.
    """
    rc, out, err = run_cmd([str(mutator_bin), "--help"], timeout_s=15)
    text = (out or "") + (err or "")
    supported = set()
    for flag in ("--categories", "--stack-depth", "--preserve-semantics", "--seed"):
        if flag in text:
            supported.add(flag)
    return frozenset(supported)


def process_combo_mutate(sample, rel, orig_wasm_path, orig_metrics, out_root,
                          mutator_bin, combo_tuple, variant_id, wabt_bins,
                          runtime_bin, browser_runner_js, timeout, tmp_root,
                          stack_depth=1, preserve_semantics=True,
                          run_ghidra=False, ghidra_headless=None,
                          ghidra_script_dir=None, ghidra_timeout=300,
                          node_path=None):
    out_root = Path(out_root)
    mutator_bin = Path(mutator_bin)
    tmp_root = Path(tmp_root)
    orig_wasm_path = Path(orig_wasm_path)

    label = combo_label(combo_tuple)  # "I4+I7" -- folder/mutant_id only
    display_label = categories_flag(combo_tuple)  # "peephole,loop-unrolling" -- CSV column
    mutant_id = f"{label}_v{variant_id}_{uuid.uuid4().hex[:8]}"
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

    # --- fresh copy of the ORIGINAL, isolated per task ---
    tmp_wasm = tmp_dir / f"{sample}.wasm"
    try:
        shutil.copy2(orig_wasm_path, tmp_wasm)
    except Exception as e:
        row["notes"].append(f"copy_failed:{e}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return row

    # --- run WasmMutate: writes into its own --outdir, input untouched.
    #     The exact flags sent are auto-detected from THIS mutator_bin's
    #     own --help output (see _mutator_capabilities), so the pipeline
    #     never sends a flag the configured binary doesn't understand --
    #     whether that's an old wrapper build (only --input/--outdir/
    #     --variants/--stack-depth) or the corrected one (adds
    #     --categories/--preserve-semantics/--seed). If --categories
    #     isn't supported, category selection silently can't happen (the
    #     binary draws from wasm-mutate's unrestricted pool) -- this is
    #     surfaced in `notes` so it's visible in the CSV, not silent. ---
    mut_outdir = tmp_dir / "mut_out"
    mut_outdir.mkdir(parents=True, exist_ok=True)
    seed = uuid.uuid4().int & 0xFFFFFFFFFFFFFFF  # 60-bit, fits comfortably in u64
    caps = _mutator_capabilities(str(mutator_bin))
    mutate_cmd = [str(mutator_bin), "--input", str(tmp_wasm), "--variants", "1"]
    if "--stack-depth" in caps:
        mutate_cmd += ["--stack-depth", str(stack_depth)]
    if "--preserve-semantics" in caps:
        mutate_cmd += ["--preserve-semantics", "true" if preserve_semantics else "false"]
    if "--seed" in caps:
        mutate_cmd += ["--seed", str(seed)]
    if "--categories" in caps:
        mutate_cmd += ["--categories", display_label]
    else:
        row["notes"].append(
            "mutator_no_categories_support:this binary does not support "
            "--categories -- category selection did NOT happen, results "
            "are from wasm-mutate's unrestricted pool regardless of the "
            "obfuscation_transformation label. Rebuild from "
            "wasm_mutator_by_category_src/ against the patched wasm-tools."
        )
    mutate_cmd += ["--outdir", str(mut_outdir)]
    t0 = time.time()
    rc_mut, out_mut, err_mut = run_cmd(mutate_cmd, timeout)
    t1 = time.time()
    row["obf_time"] = round(t1 - t0, 6)
    (out_combo_dir / "mutator_stdout.log").write_text(out_mut or "")
    (out_combo_dir / "mutator_stderr.log").write_text(err_mut or "")
    # the corrected wrapper prints a machine-parseable summary line per
    # variant (seed, chain levels actually applied) -- surface it in notes
    # for full reproducibility / to spot when preserve_semantics starved
    # most levels of any applicable mutation.
    for line in (out_mut or "").splitlines():
        if line.startswith("MUTANT "):
            row["notes"].append(line.strip())

    obf_candidates = list(mut_outdir.glob("*.wasm"))
    if rc_mut != 0 or not obf_candidates:
        row["valid_obf"] = "missing"
        row["notes"].append(f"mutator_failed:rc={rc_mut}:{(err_mut or '').strip()[:200]}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return row
    obf_path = obf_candidates[0]  # --variants 1 -> exactly one expected

    out_obf = out_combo_dir / f"{sample}_mut_{label}_v{variant_id}.wasm"
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

    # ---- structural / lexical similarity (cfg_similarity built from
    #      wasm2wat text, not the nonexistent `wasm-opt --print-cfg`) ----
    row["wat_similarity"] = wat_similarity(orig_metrics.get("_dis_text"), dis_obf_text)
    row["cfg_similarity"] = cfg_similarity_structural(orig_metrics.get("_wat_text"), wat_obf_text)

    # ---- native run ----
    run_res = run_wasm_with_inferred_args(runtime_bin, out_obf, wat_obf_text, timeout)
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

    # ---- payload_preserved (no T2-style carve-out needed here -- see
    #      module docstring) ----
    if row["run_orig"] != "ok":
        row["payload_preserved"] = "n/a"
    else:
        base_ok = (row["valid_obf"] == "ok" and row["run_obf"] == "ok"
                   and row["import_trace_match"] == "yes")
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
