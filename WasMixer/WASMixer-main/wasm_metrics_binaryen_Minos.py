#!/usr/bin/env python3
# wasm_metrics_binaryen_Minos.py
"""
Worker: process_one
- tmp copy, run wasmixer, validate, native run (wasmtime, parameter-aware),
  browser run (puppeteer via node)
- compute state hashes, behavior_match, retro-engineering metrics
  (incl. structural CFG similarity and deobfuscation vulnerability)
- write summary.json in out combo dir
"""

import json, shutil, time, uuid, re, hashlib, subprocess
from pathlib import Path
import sys, os
from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from wasm_runtime import run_wasm_with_inferred_args
from cfg_similarity import cfg_similarity_structural
from deobfuscation_vulnerability import deobfuscation_vulnerability

# ---- CONFIG: path to Node runner (adjust if different) ----
BROWSER_RUNNER_NODE = Path("/srv/storage/killerdroid@storage3.rennes.grid5000.fr/datasets/Andromatch_Paper/SOK_WebAsssembly_2025_Grid5000/Wasm/WASMixer-main/browser_runner.js")

# ---- helpers ----
def run_cmd(cmd, timeout_s=None, cwd=None):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_s, cwd=cwd)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timeout after {timeout_s}s"
    except FileNotFoundError:
        return -2, "", f"Command not found: {cmd[0]}"

def wasm2wat_text(path, wasm2wat_bin):
    rc, out, err = run_cmd([wasm2wat_bin, str(path)])
    return out if rc == 0 else None

def count_call_indirect(wat_text):
    if not wat_text: return 0
    return len(re.findall(r"\bcall_indirect\b", wat_text))

def max_nesting(wat_text):
    if not wat_text: return 0
    depth = 0; maxd = 0
    for line in wat_text.splitlines():
        for t in re.findall(r"[()]", line):
            if t == "(":
                depth += 1; maxd = max(maxd, depth)
            else:
                depth = max(0, depth-1)
    return maxd

# ---- Binaryen helpers ----
def wasm_dis_text(path):
    rc, out, err = run_cmd(["wasm-dis", str(path)])
    return out if rc == 0 else None

def wat_similarity(t1, t2):
    if not t1 or not t2:
        return None
    return round(fuzz.ratio(t1, t2), 2)

def count_symbols(text):
    if not text:
        return {"func": None, "type": None}
    return {
        "func": len(re.findall(r"\(func\s+\$", text)),
        "type": len(re.findall(r"\(type\s+\$", text))
    }

def run_in_browser_and_hash(wasm_path, invoke_name="", timeout_s=10, out_json_path=None):
    """
    Calls node browser runner and returns parsed result dict or {'error':...}
    timeout_s is seconds for node process (total).
    """
    if not BROWSER_RUNNER_NODE.exists():
        return {"error": "browser_runner_not_found", "path": str(BROWSER_RUNNER_NODE)}

    timeout_ms = int(max(1000, int(timeout_s * 1000)))
    cmd = ["node", str(BROWSER_RUNNER_NODE), "--wasm", str(wasm_path), "--timeout-ms", str(timeout_ms)]
    if invoke_name:
        cmd += ["--invoke", invoke_name]
    if out_json_path:
        cmd += ["--out", str(out_json_path)]

    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_s + 10)
    except subprocess.TimeoutExpired:
        return {"error": "node_timeout"}
    except FileNotFoundError:
        return {"error": "node_not_found"}

    if p.returncode != 0:
        return {"error": "node_runner_failed", "rc": p.returncode, "stderr": p.stderr.strip(), "stdout": p.stdout.strip()}

    out = p.stdout.strip()
    if not out:
        return {"error": "node_no_stdout", "stderr": p.stderr}

    try:
        last = out.splitlines()[-1]
        data = json.loads(last)
        return data
    except Exception:
        try:
            data = json.loads(out)
            return data
        except Exception as e2:
            return {"error": "json_parse_failed", "exc": str(e2), "stdout": out, "stderr": p.stderr}

def compute_sha256_of_obj(obj):
    s = json.dumps(obj, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

# ---- main worker ----
def process_one(sample_rel, wasm_src_path, out_root, wasmixer_cli, opts_list, wabt_bins, timeout, tmp_root):
    wasm_src = Path(wasm_src_path)
    out_root = Path(out_root)
    wasmixer_cli = Path(wasmixer_cli)
    tmp_root = Path(tmp_root)

    sample = Path(sample_rel).name
    combo_label = "_".join(o.replace("--","") for o in opts_list) or "none"
    mutant_id = f"{combo_label}_{uuid.uuid4().hex[:8]}"
    out_combo_dir = out_root / f"{sample}__{mutant_id}"
    out_combo_dir.mkdir(parents=True, exist_ok=True)

    tmp_dir = tmp_root / (uuid.uuid4().hex[:10])
    tmp_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "sample": sample,
        "relpath": sample_rel,
        "combo": " ".join(opts_list),
        "mutant_id": mutant_id,
        "size_orig": None,
        "size_obf": None,
        "call_ind_orig": None,
        "call_ind_obf": None,
        "max_nesting_orig": None,
        "max_nesting_obf": None,
        "obf_time_s": None,
        "valid_orig": None,
        "valid_obf": None,
        "run_orig": None,
        "run_time_orig": None,
        "run_func_orig": None,
        "run_obf": None,
        "run_time_obf": None,
        "run_func_obf": None,
        "failed_mutations": None,
        "orig_state_hash": None,
        "obf_state_hash": None,
        "state_match": None,
        "behavior_match": None,
        "notes": [],
        # ----- Retro-engineering metrics -----
        "disassembly_ok_orig": None,
        "disassembly_ok_obf": None,
        "wat_similarity": None,
        "cfg_similarity": None,
        "func_symbols_orig": None,
        "func_symbols_obf": None,
        "type_symbols_orig": None,
        "type_symbols_obf": None,
        # ----- Deobfuscation Vulnerability (WABT / Binaryen / Ghidra) -----
        "deobf_wabt_orig": None,
        "deobf_wabt_obf": None,
        "deobf_binaryen_orig": None,
        "deobf_binaryen_obf": None,
        "deobf_ghidra_orig": None,
        "deobf_ghidra_obf": None,
        "deobf_ghidra_funcs_orig": None,
        "deobf_ghidra_funcs_obf": None,
        "deobf_score_orig": None,
        "deobf_score_obf": None,
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

    # size original
    try:
        summary["size_orig"] = tmp_wasm.stat().st_size
    except:
        summary["size_orig"] = None

    # validate original
    rc, out, err = run_cmd([wabt_bins.get("validate","wasm-validate"), str(tmp_wasm)])
    summary["valid_orig"] = "ok" if rc == 0 else f"invalid({rc})"

    # wat analysis orig
    wat_text = wasm2wat_text(tmp_wasm, wabt_bins.get("wasm2wat","wasm2wat"))
    summary["call_ind_orig"] = count_call_indirect(wat_text)
    summary["max_nesting_orig"] = max_nesting(wat_text)

    # ----- Binaryen metrics (orig) -----
    dis_orig = wasm_dis_text(tmp_wasm)
    summary["disassembly_ok_orig"] = "yes" if dis_orig else "no"
    sym_o = count_symbols(dis_orig)
    summary["func_symbols_orig"] = sym_o["func"]
    summary["type_symbols_orig"] = sym_o["type"]

    # native run original (wasmtime, parameter-aware: avoids false "no_entry")
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
    try:
        browser_orig = run_in_browser_and_hash(tmp_wasm, invoke_name="", timeout_s=min(15, max(5, int(timeout/2))), out_json_path=out_combo_dir/"browser_orig.json")
        if 'error' in browser_orig:
            summary["notes"].append(f"browser_orig_error:{browser_orig.get('error')}")
            if isinstance(browser_orig.get('stderr'), str):
                summary["notes"].append(f"browser_orig_stderr:{browser_orig.get('stderr')}")
            summary["orig_state_hash"] = None
        else:
            summary["orig_state_hash"] = browser_orig.get("state_hash")
    except Exception as e:
        summary["notes"].append(f"browser_orig_exc:{e}")

    # deobfuscation vulnerability (orig) -- WABT / Binaryen / Ghidra
    try:
        dv_orig = deobfuscation_vulnerability(
            tmp_wasm, ghidra_script_dir=str(wasmixer_cli.parent)
        )
        summary["deobf_wabt_orig"] = dv_orig["wabt"]["success"]
        summary["deobf_binaryen_orig"] = dv_orig["binaryen"]["success"]
        summary["deobf_ghidra_orig"] = dv_orig["ghidra"]["success"] if dv_orig["ghidra"] else None
        summary["deobf_ghidra_funcs_orig"] = dv_orig["ghidra"]["func_count"] if dv_orig["ghidra"] else None
        summary["deobf_score_orig"] = dv_orig["score"]
    except Exception as e:
        summary["notes"].append(f"deobf_orig_exc:{e}")

    # run WASMixer
    wasmixer_cmd = [sys.executable, str(wasmixer_cli), str(tmp_wasm)] + opts_list
    t0 = time.time()
    rc_mix, out_mix, err_mix = run_cmd(wasmixer_cmd, timeout, cwd=str(wasmixer_cli.parent))
    t1 = time.time()
    summary["obf_time_s"] = round(t1 - t0, 6)
    (out_combo_dir / "wasmixer_stdout.log").write_text(out_mix or "")
    (out_combo_dir / "wasmixer_stderr.log").write_text(err_mix or "")
    if rc_mix != 0:
        summary["notes"].append(f"wasmixer_rc:{rc_mix}")

    # find obf path
    obf_path = None
    expected = tmp_dir / f"{sample}_mixr.wasm"
    if expected.exists():
        obf_path = expected
    else:
        cands = [p for p in tmp_dir.glob("*.wasm") if p.stat().st_mtime >= t0]
        if cands:
            obf_path = max(cands, key=lambda p: p.stat().st_mtime)
    if not obf_path:
        cands = [p for p in wasmixer_cli.parent.glob("*.wasm") if p.stat().st_mtime >= t0]
        if cands:
            obf_path = max(cands, key=lambda p: p.stat().st_mtime)
            summary["notes"].append("obf_in_wasmixer_dir")
    if not obf_path or not obf_path.exists():
        summary["valid_obf"] = "missing"
        try: shutil.rmtree(tmp_dir)
        except: pass
        return summary

    out_obf = out_combo_dir / f"{sample}_mixr_{combo_label}.wasm"
    try:
        shutil.copy2(obf_path, out_obf)
    except Exception as e:
        summary["notes"].append(f"copy_obf_failed:{e}")
        try: shutil.rmtree(tmp_dir)
        except: pass
        return summary

    # size obf
    summary["size_obf"] = out_obf.stat().st_size if out_obf.exists() else None

    # validate obf
    rc2, o2, e2 = run_cmd([wabt_bins.get("validate","wasm-validate"), str(out_obf)])
    summary["valid_obf"] = "ok" if rc2 == 0 else f"invalid({rc2})"

    # wat obf metrics
    wat_obf_text = wasm2wat_text(out_obf, wabt_bins.get("wasm2wat","wasm2wat"))
    summary["call_ind_obf"] = count_call_indirect(wat_obf_text)
    summary["max_nesting_obf"] = max_nesting(wat_obf_text)

    # ----- Binaryen metrics (obf) -----
    dis_obf = wasm_dis_text(out_obf)
    summary["disassembly_ok_obf"] = "yes" if dis_obf else "no"
    sym_b = count_symbols(dis_obf)
    summary["func_symbols_obf"] = sym_b["func"]
    summary["type_symbols_obf"] = sym_b["type"]

    # ----- Similarities -----
    summary["wat_similarity"] = wat_similarity(dis_orig, dis_obf)
    # structural CFG similarity: BFS-depth / in-degree / out-degree signature
    # matching, NOT raw-text diffing (see cfg_similarity.py)
    try:
        summary["cfg_similarity"] = cfg_similarity_structural(tmp_wasm, out_obf, timeout_s=timeout)
    except Exception as e:
        summary["notes"].append(f"cfg_similarity_exc:{e}")

    # native run obf (wasmtime, parameter-aware, single execution only)
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
        browser_obf = run_in_browser_and_hash(out_obf, invoke_name="", timeout_s=min(15, max(5, int(timeout/2))), out_json_path=out_combo_dir/"browser_obf.json")
        if 'error' in browser_obf:
            summary["notes"].append(f"browser_obf_error:{browser_obf.get('error')}")
            if isinstance(browser_obf.get('stderr'), str):
                summary["notes"].append(f"browser_obf_stderr:{browser_obf.get('stderr')}")
            summary["obf_state_hash"] = None
        else:
            summary["obf_state_hash"] = browser_obf.get("state_hash")
    except Exception as e:
        summary["notes"].append(f"browser_obf_exc:{e}")

    # deobfuscation vulnerability (obf) -- WABT / Binaryen / Ghidra
    try:
        dv_obf = deobfuscation_vulnerability(
            out_obf, ghidra_script_dir=str(wasmixer_cli.parent)
        )
        summary["deobf_wabt_obf"] = dv_obf["wabt"]["success"]
        summary["deobf_binaryen_obf"] = dv_obf["binaryen"]["success"]
        summary["deobf_ghidra_obf"] = dv_obf["ghidra"]["success"] if dv_obf["ghidra"] else None
        summary["deobf_ghidra_funcs_obf"] = dv_obf["ghidra"]["func_count"] if dv_obf["ghidra"] else None
        summary["deobf_score_obf"] = dv_obf["score"]
    except Exception as e:
        summary["notes"].append(f"deobf_obf_exc:{e}")

    # compare states
    if summary.get("orig_state_hash") and summary.get("obf_state_hash"):
        summary["state_match"] = "yes" if summary["orig_state_hash"] == summary["obf_state_hash"] else "no"
    else:
        summary["state_match"] = "no"

    # decide behavior_match
    def is_ok(v): return v == "ok"
    valid_orig_flag = is_ok(summary.get("valid_orig"))
    valid_obf_flag = is_ok(summary.get("valid_obf"))
    run_ok_orig = (summary.get("run_orig") == "ok")
    run_ok_obf = (summary.get("run_obf") == "ok")
    summary["behavior_match"] = "yes" if (valid_orig_flag and valid_obf_flag and run_ok_orig and run_ok_obf and summary.get("state_match") == "yes") else "no"

    # write summary.json
    try:
        (out_combo_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    except Exception:
        pass

    # cleanup tmp
    try:
        shutil.rmtree(tmp_dir)
    except:
        pass

    return summary
