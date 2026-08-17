#!/usr/bin/env python3
# orig_metrics.py


import json
import time
from pathlib import Path

from common import (
    run_cmd, wasm2wat_text, wasm_dis_text, count_call_indirect,
    max_nesting, count_symbols, run_in_browser_and_hash,
)
from wasm_runtime import run_wasm_with_inferred_args
from deobfuscation_vulnerability import deobfuscation_vulnerability

# Bumped whenever the *_orig computation logic changes (bugfixes, new
# fields, ...). load_cache() rejects any cached JSON whose "_cache_version"
# doesn't match, so a code update automatically invalidates stale caches
# instead of silently reusing results computed by the old, buggy code --
# this is exactly what happened when the browser_res error-detection bug
# was fixed but old cached orig_metrics.json files kept getting reused.
CACHE_VERSION = 2


def compute_orig_metrics(wasm_path, wabt_bins, wasmtime_bin, browser_runner_js,
                          timeout, out_dir, run_ghidra=False,
                          ghidra_headless=None, ghidra_script_dir=None,
                          ghidra_timeout=300):
    """
    Returns a dict with all fields needed for the "*_orig" columns, plus a
    few internal-only fields (prefixed with "_") used by the per-combo
    worker (e.g. "_wat_text" is NOT written to the CSV).
    """
    wasm_path = Path(wasm_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    m = {
        "notes": [],
        "size": None, "valid": None,
        "call_ind": None, "max_nesting": None,
        "run": None, "run_time": None, "run_func": None, "retval": None,
        "state_hash": None, "import_trace_hash": None,
        "memory_pages": None, "exports_called": [], "browser_error": None,
        "disassembly_ok": None, "func_symbols": None, "type_symbols": None,
        "deobf_wabt": None, "deobf_binaryen": None, "deobf_ghidra": None,
        "deobf_ghidra_funcs": None, "deobf_score": None,
        "_wat_text": None, "_dis_text": None,
    }

    try:
        m["size"] = wasm_path.stat().st_size
    except Exception as e:
        m["notes"].append(f"stat_failed:{e}")

    rc, _, err = run_cmd([wabt_bins.get("validate", "wasm-validate"), str(wasm_path)], timeout)
    m["valid"] = "ok" if rc == 0 else f"invalid({rc})"

    wat_text = wasm2wat_text(wasm_path, wabt_bins.get("wasm2wat", "wasm2wat"))
    m["_wat_text"] = wat_text
    m["call_ind"] = count_call_indirect(wat_text)
    m["max_nesting"] = max_nesting(wat_text)

    dis_text = wasm_dis_text(wasm_path)
    m["_dis_text"] = dis_text
    m["disassembly_ok"] = "yes" if dis_text else "no"
    sym = count_symbols(dis_text)
    m["func_symbols"] = sym["func"]
    m["type_symbols"] = sym["type"]

    # native run (wasmtime), parameter-aware, _start preferred (survives T1)
    run_res = run_wasm_with_inferred_args(wasmtime_bin, wasm_path, wat_text, timeout)
    m["run"] = run_res["status"]
    m["run_time"] = run_res["elapsed_s"]
    m["run_func"] = run_res["func"]
    if run_res["status"] == "ok":
        m["retval"] = run_res["stdout"].strip()
        if run_res["notes"]:
            m["notes"].append("retval_may_include_stdout_side_effects")
    if run_res["notes"]:
        m["notes"].extend(f"run_native:{n}" for n in run_res["notes"])

    # browser run (behavioral ground truth: state_hash / import_trace_hash)
    browser_res = run_in_browser_and_hash(
        browser_runner_js, wasm_path,
        timeout_s=min(15, max(5, int(timeout / 2))),
        out_json_path=out_dir / "browser_orig.json",
    )
    # BUGFIX: browser_runner.js's JSON ALWAYS includes the "error" key
    # (set to `null` on success -- see line ~424 of browser_runner.js).
    # `"error" in browser_res` is therefore always True and the success
    # branch below was never reached. Must check the VALUE, not key
    # presence.
    if browser_res.get("error"):
        m["browser_error"] = browser_res.get("error")
        m["notes"].append(f"browser_orig_error:{browser_res.get('error')}")
    else:
        m["state_hash"] = browser_res.get("state_hash")
        m["import_trace_hash"] = browser_res.get("import_trace_hash")
        m["memory_pages"] = browser_res.get("memory_pages")
        m["exports_called"] = browser_res.get("exports_called", [])

    # deobfuscation-resistance baseline for this sample (unobfuscated)
    deobf = deobfuscation_vulnerability(
        wasm_path, timeout_wabt=timeout, timeout_binaryen=timeout,
        timeout_ghidra=ghidra_timeout, ghidra_headless=ghidra_headless,
        ghidra_script_dir=ghidra_script_dir, run_ghidra=run_ghidra,
    )
    m["deobf_wabt"] = deobf["wabt"]["success"]
    m["deobf_binaryen"] = deobf["binaryen"]["success"]
    if deobf["ghidra"] is not None:
        m["deobf_ghidra"] = deobf["ghidra"]["success"]
        m["deobf_ghidra_funcs"] = deobf["ghidra"]["func_count"]
    m["deobf_score"] = deobf["score"]

    return m


def save_cache(cache_path, metrics):
    """Persist orig metrics to disk (JSON) so a resumed run can skip recompute."""
    serializable = {k: v for k, v in metrics.items() if not k.startswith("_")}
    serializable["_cache_version"] = CACHE_VERSION
    Path(cache_path).write_text(json.dumps(serializable))


def load_cache(cache_path, wasm_path=None, wabt_bins=None):
    """
    Load cached orig metrics from disk. Returns None (=> caller must
    recompute) if the file is missing, unparseable, OR was written by a
    different CACHE_VERSION -- so a pipeline bugfix/update never gets
    silently shadowed by an old cached result.

    `_wat_text`/`_dis_text` are not persisted to JSON (kept internal-only
    within a single run) -- if `wasm_path` is given, they're cheaply
    regenerated here (just wasm2wat/wasm-dis, no Ghidra/browser/wasmtime
    re-run) so a resumed run's combo tasks still get wat_similarity /
    call_ind etc. for free.
    """
    try:
        data = json.loads(Path(cache_path).read_text())
    except Exception:
        return None

    if data.get("_cache_version") != CACHE_VERSION:
        return None  # stale cache from an older pipeline version -- recompute

    data["_wat_text"] = None
    data["_dis_text"] = None
    if wasm_path is not None:
        wabt_bins = wabt_bins or {}
        data["_wat_text"] = wasm2wat_text(wasm_path, wabt_bins.get("wasm2wat", "wasm2wat"))
        data["_dis_text"] = wasm_dis_text(wasm_path)
    return data
