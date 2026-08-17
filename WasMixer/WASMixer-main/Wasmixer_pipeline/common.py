#!/usr/bin/env python3
# common.py
"""
Low-level helpers shared between the "original" and "obfuscated" analysis
passes, so the exact same code path is used on both sides of every
comparison (no accidental asymmetry between how orig/obf are measured).
"""

import json
import re
import subprocess
from pathlib import Path

from rapidfuzz import fuzz


def run_cmd(cmd, timeout_s=None, cwd=None, input_text=None):
    try:
        p = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout_s, cwd=cwd, input=input_text,
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timeout after {timeout_s}s"
    except FileNotFoundError:
        return -2, "", f"Command not found: {cmd[0]}"


def wasm2wat_text(path, wasm2wat_bin):
    rc, out, err = run_cmd([wasm2wat_bin, str(path)])
    return out if rc == 0 else None


def wasm_dis_text(path):
    rc, out, err = run_cmd(["wasm-dis", str(path)])
    return out if rc == 0 else None


def count_call_indirect(wat_text):
    if not wat_text:
        return None
    return len(re.findall(r"\bcall_indirect\b", wat_text))


def max_nesting(wat_text):
    if not wat_text:
        return None
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


def count_symbols(dis_text):
    if not dis_text:
        return {"func": None, "type": None}
    return {
        "func": len(re.findall(r"\(func\s+\$", dis_text)),
        "type": len(re.findall(r"\(type\s+\$", dis_text)),
    }


def wat_similarity(t1, t2):
    """Lexical similarity between two disassembly texts. Dominated by T1
    (name obfuscation) since it operates purely on identifier strings."""
    if not t1 or not t2:
        return None
    return round(fuzz.ratio(t1, t2), 2)


def run_in_browser_and_hash(browser_runner_js, wasm_path, timeout_s=15, out_json_path=None):
    """Calls node browser_runner.js and returns parsed result dict or {'error':...}."""
    if not Path(browser_runner_js).exists():
        return {"error": "browser_runner_not_found", "path": str(browser_runner_js)}

    timeout_ms = int(max(1000, int(timeout_s * 1000)))
    cmd = ["node", str(browser_runner_js), "--wasm", str(wasm_path), "--timeout-ms", str(timeout_ms)]
    if out_json_path:
        cmd += ["--out", str(out_json_path)]

    rc, out, err = run_cmd(cmd, timeout_s=timeout_s + 10)
    if rc != 0:
        return {"error": "node_runner_failed", "rc": rc, "stderr": (err or "").strip()[:300]}

    out = (out or "").strip()
    if not out:
        return {"error": "node_no_stdout", "stderr": err}

    try:
        last = out.splitlines()[-1]
        return json.loads(last)
    except Exception as e:
        return {"error": "json_parse_failed", "exc": str(e), "stdout": out[:300], "stderr": err}
