#!/usr/bin/env python3
# common.py
"""
Low-level helpers shared between the "original" and "obfuscated" analysis
passes, so the exact same code path is used on both sides of every
comparison (no accidental asymmetry between how orig/obf are measured).
"""

import json
import os
import re
import subprocess
from pathlib import Path

from rapidfuzz import fuzz


def run_cmd(cmd, timeout_s=None, cwd=None, input_text=None, extra_env=None):
    try:
        env = None
        if extra_env:
            env = {**os.environ, **extra_env}
        # capture as raw bytes (not text=True) so a tool that emits invalid
        # UTF-8 on stdout/stderr (e.g. a crashing subprocess dumping binary
        # garbage) can't raise UnicodeDecodeError and take down the whole
        # worker task -- decode leniently afterwards instead, replacing any
        # invalid bytes rather than failing outright.
        input_bytes = input_text.encode("utf-8") if input_text is not None else None
        p = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout_s, cwd=cwd, input=input_bytes, env=env,
        )
        out = p.stdout.decode("utf-8", errors="replace")
        err = p.stderr.decode("utf-8", errors="replace")
        return p.returncode, out, err
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
    """Lexical similarity between two disassembly texts. Dominated by any
    identifier-renaming transformation, since it operates purely on
    identifier strings."""
    if not t1 or not t2:
        return None
    return round(fuzz.ratio(t1, t2), 2)


def run_in_browser_and_hash(browser_runner_js, wasm_path, timeout_s=15,
                             out_json_path=None, node_path=None):
    """
    Calls node browser_runner.js and returns parsed result dict or {'error':...}.

    `node_path`, if given, is passed as the NODE_PATH environment variable
    for this specific subprocess call -- so puppeteer resolution doesn't
    depend on the ambient shell's NODE_PATH being correctly exported
    before the pipeline was launched (an easy thing to forget, especially
    across Grid5000 nodes/sessions where /tmp is wiped between
    reservations). If not given, falls back to whatever NODE_PATH (if
    any) is already in this process's environment.
    """
    if not Path(browser_runner_js).exists():
        return {"error": "browser_runner_not_found", "path": str(browser_runner_js)}

    timeout_ms = int(max(1000, int(timeout_s * 1000)))
    cmd = ["node", str(browser_runner_js), "--wasm", str(wasm_path), "--timeout-ms", str(timeout_ms)]
    if out_json_path:
        cmd += ["--out", str(out_json_path)]

    extra_env = {"NODE_PATH": str(node_path)} if node_path else None
    rc, out, err = run_cmd(cmd, timeout_s=timeout_s + 10, extra_env=extra_env)
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
