#!/usr/bin/env python3
# wasm_metrics_binaryen_mutate.py
"""
Worker: process_one for wasm-mutate (wasm_mutator_by_category).

Mirrors wasm_metrics_binaryen_Minos.py (the WASMixer worker) exactly in the
metrics it computes, so the two pipelines' CSVs are directly comparable:

- size / call_indirect / max_nesting (orig vs mutant)
- validity (wasm-validate)
- native execution via wasmtime, with parameter inference instead of
  blind invocation (wasm_runtime.run_wasm_with_inferred_args)
- disassembly + symbol counts (Binaryen)
- wat_similarity (text) and cfg_similarity (structural: BFS depth / in-degree
  / out-degree signature matching, via cfg_similarity.cfg_similarity_structural)
- Deobfuscation Vulnerability: WABT / Binaryen / Ghidra recovery success
  (deobfuscation_vulnerability.deobfuscation_vulnerability)
- browser execution + state hash (via the project's existing puppeteer
  runner, run_browser_test.js), state_match / behavior_match

Only the obfuscation step itself differs: instead of invoking WASMixer's
CLI, this calls wasm_mutator_by_category with --categories.
"""

import json, shutil, time, uuid, re, hashlib, subprocess
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from wasm_runtime import run_wasm_with_inferred_args
from cfg_similarity import cfg_similarity_structural
from deobfuscation_vulnerability import deobfuscation_vulnerability

try:
    from rapidfuzz import fuzz
    def _text_similarity(t1, t2):
        if not t1 or not t2:
            return None
        return round(fuzz.ratio(t1, t2), 2)
except ImportError:
    from difflib import SequenceMatcher
    def _text_similarity(t1, t2):
        if not t1 or not t2:
            return None
        return round(SequenceMatcher(None, t1, t2).ratio() * 100, 2)


# ---------------------------------------------------------------------
# helpers (identical to the WASMixer worker)
# ---------------------------------------------------------------------

def run_cmd(cmd, timeout_s=None, cwd=None, input_text=None):
    try:
        p = subprocess.run(cmd, input=input_text, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=timeout_s, cwd=cwd)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timeout after {timeout_s}s"
    except FileNotFoundError:
        return -2, "", f"Command not found: {cmd[0]}"


def wasm2wat_text(path, wasm2wat_bin):
    rc, out, err = run_cmd([wasm2wat_bin, str(path)])
    return out if rc == 0 else None


def count_call_indirect(wat_text):
    if not wat_text:
        return 0
    return len(re.findall(r"\bcall_indirect\b", wat_text))


def max_nesting(wat_text):
    if not wat_text:
        return 0
    depth = 0
    maxd = 0
    for line in wat_text.splitlines():
        for t in re.findall(r"[()]", line):
            if t == "(":
                depth += 1
                maxd = max(maxd, depth)
            else:
                depth = max(0, depth - 1)
    return maxd


def wasm_dis_text(path):
    rc, out, err = run_cmd(["wasm-dis", str(path)])
    return out if rc == 0 else None


def count_symbols(text):
    if not text:
        return {"func": None, "type": None}
    return {
        "func": len(re.findall(r"\(func\s+\$", text)),
        "type": len(re.findall(r"\(type\s+\$", text)),
    }


def sha256_of_file(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except Exception:
        return None


def run_in_browser_and_hash(node_puppet, wasm_path, outdir, test_inputs, timeout_s=60):
    """
    Calls the project's existing puppeteer runner (run_browser_test.js),
    which writes outdir/browser_state.json. Returns its sha256 (or None).
    """
    if not Path(node_puppet).exists():
        return None
    cmd = ["node", str(node_puppet), "--wasm", str(wasm_path),
           "--outdir", str(outdir), "--inputs", test_inputs]
    run_cmd(cmd, timeout_s=timeout_s)
    return sha256_of_file(Path(outdir) / "browser_state.json")


# ---------------------------------------------------------------------
# main worker
# ---------------------------------------------------------------------

def process_one(sample_rel, wasm_src_path, out_root, mutator_bin, categories_list,
                 variant_idx, wabt_bins, timeout, tmp_root, node_puppet, test_inputs):
    wasm_src = Path(wasm_src_path)
    out_root = Path(out_root)
    mutator_bin = Path(mutator_bin)
    tmp_root = Path(tmp_root)

    sample = Path(sample_rel).name
    combo_label = "_".join(categories_list) or "none"
    mutant_id = f"{combo_label}_mut{variant_idx}_{uuid.uuid4().hex[:8]}"
    out_combo_dir = out_root / f"{sample}__{mutant_id}"
    out_combo_dir.mkdir(parents=True, exist_ok=True)

    tmp_dir = tmp_root / (uuid.uuid4().hex[:10])
    tmp_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "sample": sample,
        "relpath": sample_rel,
        "combo": combo_label,
        "variant": variant_idx,
        "mutant_id": mutant_id,
        "size_orig": None, "size_obf": None,
        "call_ind_orig": None, "call_ind_obf": None,
        "max_nesting_orig": None, "max_nesting_obf": None,
        "obf_time_s": None,
        "valid_orig": None, "valid_obf": None,
        "run_orig": None, "run_time_orig": None, "run_func_orig": None,
        "run_obf": None, "run_time_obf": None, "run_func_obf": None,
        "orig_state_hash": None, "obf_state_hash": None,
        "state_match": None, "behavior_match": None,
        "notes": [],
        "disassembly_ok_orig": None, "disassembly_ok_obf": None,
        "wat_similarity": None, "cfg_similarity": None,
        "func_symbols_orig": None, "func_symbols_obf": None,
        "type_symbols_orig": None, "type_symbols_obf": None,
        "deobf_wabt_orig": None, "deobf_wabt_obf": None,
        "deobf_binaryen_orig": None, "deobf_binaryen_obf": None,
        "deobf_ghidra_orig": None, "deobf_ghidra_obf": None,
        "deobf_ghidra_funcs_orig": None, "deobf_ghidra_funcs_obf": None,
        "deobf_score_orig": None, "deobf_score_obf": None,
    }

    # copy src to tmp
    tmp_wasm = tmp_dir / f"{sample}.wasm"
    try:
        shutil.copy2(wasm_src, tmp_wasm)
    except Exception as e:
        summary["notes"].append(f"copy_failed:{e}")
        try: shutil.rmtree(tmp_dir)
        except: pass
        return summary

    try:
        summary["size_orig"] = tmp_wasm.stat().st_size
    except Exception:
        summary["size_orig"] = None

    rc, out, err = run_cmd([wabt_bins.get("validate", "wasm-validate"), str(tmp_wasm)])
    summary["valid_orig"] = "ok" if rc == 0 else f"invalid({rc})"

    wat_text = wasm2wat_text(tmp_wasm, wabt_bins.get("wasm2wat", "wasm2wat"))
    summary["call_ind_orig"] = count_call_indirect(wat_text)
    summary["max_nesting_orig"] = max_nesting(wat_text)

    dis_orig = wasm_dis_text(tmp_wasm)
    summary["disassembly_ok_orig"] = "yes" if dis_orig else "no"
    sym_o = count_symbols(dis_orig)
    summary["func_symbols_orig"] = sym_o["func"]
    summary["type_symbols_orig"] = sym_o["type"]

    # native run original (parameter-aware)
    runtime_orig_log = out_combo_dir / "runtime_orig.log"
    run_res_orig = run_wasm_with_inferred_args(
        wabt_bins.get("wasmtime"), tmp_wasm, wat_text, timeout_s=timeout
    )
    summary["run_orig"] = run_res_orig["status"]
    summary["run_time_orig"] = run_res_orig["elapsed_s"]
    summary["run_func_orig"] = run_res_orig["func"]
    if run_res_orig["notes"]:
        summary["notes"].append(f"run_orig_notes:{run_res_orig['notes']}")
    runtime_orig_log.write_text(
        f"func={run_res_orig['func']} args={run_res_orig['args']} status={run_res_orig['status']}\n"
        + (run_res_orig.get("stdout") or "") + "\n" + (run_res_orig.get("stderr") or "")
    )

    # browser run original
    orig_browser_dir = out_combo_dir / "original"
    orig_browser_dir.mkdir(parents=True, exist_ok=True)
    try:
        summary["orig_state_hash"] = run_in_browser_and_hash(
            node_puppet, tmp_wasm, orig_browser_dir, test_inputs,
            timeout_s=min(60, max(10, int(timeout / 2)))
        )
    except Exception as e:
        summary["notes"].append(f"browser_orig_exc:{e}")

    # deobfuscation vulnerability (orig)
    try:
        dv_orig = deobfuscation_vulnerability(tmp_wasm, ghidra_script_dir=str(Path(__file__).parent.resolve()))
        summary["deobf_wabt_orig"] = dv_orig["wabt"]["success"]
        summary["deobf_binaryen_orig"] = dv_orig["binaryen"]["success"]
        summary["deobf_ghidra_orig"] = dv_orig["ghidra"]["success"] if dv_orig["ghidra"] else None
        summary["deobf_ghidra_funcs_orig"] = dv_orig["ghidra"]["func_count"] if dv_orig["ghidra"] else None
        summary["deobf_score_orig"] = dv_orig["score"]
    except Exception as e:
        summary["notes"].append(f"deobf_orig_exc:{e}")

    # ---- run wasm-mutate ----
    categories_arg = ",".join(categories_list)
    mutate_cmd = [str(mutator_bin), "--input", str(tmp_wasm), "--categories", categories_arg,
                  "--variants", "1", "--outdir", str(out_combo_dir)]
    t0 = time.time()
    rc_mut, out_mut, err_mut = run_cmd(mutate_cmd, timeout)
    t1 = time.time()
    summary["obf_time_s"] = round(t1 - t0, 6)
    (out_combo_dir / "mutator_stdout.log").write_text(out_mut or "")
    (out_combo_dir / "mutator_stderr.log").write_text(err_mut or "")
    if rc_mut != 0:
        summary["notes"].append(f"mutator_rc:{rc_mut}")

    obf_candidates = list(out_combo_dir.glob("*.wasm"))
    obf_path = obf_candidates[0] if obf_candidates else None
    if not obf_path or not obf_path.exists():
        summary["valid_obf"] = "missing"
        try: shutil.rmtree(tmp_dir)
        except: pass
        return summary

    out_obf = out_combo_dir / f"{sample}_mut_{combo_label}.wasm"
    if obf_path.resolve() != out_obf.resolve():
        try:
            shutil.copy2(obf_path, out_obf)
        except Exception as e:
            summary["notes"].append(f"copy_obf_failed:{e}")
            try: shutil.rmtree(tmp_dir)
            except: pass
            return summary
    else:
        out_obf = obf_path

    summary["size_obf"] = out_obf.stat().st_size if out_obf.exists() else None

    rc2, o2, e2 = run_cmd([wabt_bins.get("validate", "wasm-validate"), str(out_obf)])
    summary["valid_obf"] = "ok" if rc2 == 0 else f"invalid({rc2})"

    wat_obf_text = wasm2wat_text(out_obf, wabt_bins.get("wasm2wat", "wasm2wat"))
    summary["call_ind_obf"] = count_call_indirect(wat_obf_text)
    summary["max_nesting_obf"] = max_nesting(wat_obf_text)

    dis_obf = wasm_dis_text(out_obf)
    summary["disassembly_ok_obf"] = "yes" if dis_obf else "no"
    sym_b = count_symbols(dis_obf)
    summary["func_symbols_obf"] = sym_b["func"]
    summary["type_symbols_obf"] = sym_b["type"]

    summary["wat_similarity"] = _text_similarity(dis_orig, dis_obf)
    try:
        summary["cfg_similarity"] = cfg_similarity_structural(tmp_wasm, out_obf, timeout_s=timeout)
    except Exception as e:
        summary["notes"].append(f"cfg_similarity_exc:{e}")

    # native run obf (parameter-aware, single execution)
    runtime_obf_log = out_combo_dir / "runtime_obf.log"
    run_res_obf = run_wasm_with_inferred_args(
        wabt_bins.get("wasmtime"), out_obf, wat_obf_text, timeout_s=timeout
    )
    summary["run_obf"] = run_res_obf["status"]
    summary["run_time_obf"] = run_res_obf["elapsed_s"]
    summary["run_func_obf"] = run_res_obf["func"]
    if run_res_obf["notes"]:
        summary["notes"].append(f"run_obf_notes:{run_res_obf['notes']}")
    runtime_obf_log.write_text(
        f"func={run_res_obf['func']} args={run_res_obf['args']} status={run_res_obf['status']}\n"
        + (run_res_obf.get("stdout") or "") + "\n" + (run_res_obf.get("stderr") or "")
    )

    # browser run obf
    try:
        summary["obf_state_hash"] = run_in_browser_and_hash(
            node_puppet, out_obf, out_combo_dir, test_inputs,
            timeout_s=min(60, max(10, int(timeout / 2)))
        )
    except Exception as e:
        summary["notes"].append(f"browser_obf_exc:{e}")

    # deobfuscation vulnerability (obf)
    try:
        dv_obf = deobfuscation_vulnerability(out_obf, ghidra_script_dir=str(Path(__file__).parent.resolve()))
        summary["deobf_wabt_obf"] = dv_obf["wabt"]["success"]
        summary["deobf_binaryen_obf"] = dv_obf["binaryen"]["success"]
        summary["deobf_ghidra_obf"] = dv_obf["ghidra"]["success"] if dv_obf["ghidra"] else None
        summary["deobf_ghidra_funcs_obf"] = dv_obf["ghidra"]["func_count"] if dv_obf["ghidra"] else None
        summary["deobf_score_obf"] = dv_obf["score"]
    except Exception as e:
        summary["notes"].append(f"deobf_obf_exc:{e}")

    # state comparison
    if summary.get("orig_state_hash") and summary.get("obf_state_hash"):
        summary["state_match"] = "yes" if summary["orig_state_hash"] == summary["obf_state_hash"] else "no"
    else:
        summary["state_match"] = "no"

    def is_ok(v): return v == "ok"
    valid_orig_flag = is_ok(summary.get("valid_orig"))
    valid_obf_flag = is_ok(summary.get("valid_obf"))
    run_ok_orig = (summary.get("run_orig") == "ok")
    run_ok_obf = (summary.get("run_obf") == "ok")
    summary["behavior_match"] = "yes" if (valid_orig_flag and valid_obf_flag and run_ok_orig and run_ok_obf
                                           and summary.get("state_match") == "yes") else "no"

    try:
        (out_combo_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    except Exception:
        pass

    try:
        shutil.rmtree(tmp_dir)
    except Exception:
        pass

    return summary
