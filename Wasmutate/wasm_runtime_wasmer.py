#!/usr/bin/env python3
# wasm_runtime.py
"""
Parameter-aware native execution of WebAssembly binaries, across multiple
runtimes (wasmtime, wasmer).
"""

import re
import time
import subprocess
from pathlib import Path

DEFAULT_ARG_BY_TYPE = {
    "i32": "1",
    "i64": "1",
    "f32": "1.0",
    "f64": "1.0",
    # v128 / reference types are not invokable via CLI arg parsers in most
    # runtime versions; flagged explicitly rather than guessed.
}

ARG_COUNT_MISMATCH_PATTERNS = (
    re.compile(r"expected\s+\d+\s+argument", re.IGNORECASE),
    re.compile(r"argument count mismatch", re.IGNORECASE),
    re.compile(r"wrong number of (arguments|parameters)", re.IGNORECASE),
    re.compile(r"invalid number of arguments", re.IGNORECASE),  # wasmer phrasing
)


def run_cmd(cmd, timeout_s=None, input_text=None):
    try:
        p = subprocess.run(
            cmd,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError as e:
        return -2, "", f"command not found: {e}"


# ---------------------------------------------------------------------
# Export / signature recovery from .wat text (runtime-agnostic)
# ---------------------------------------------------------------------

# (export "name" (func $id_or_index))
_EXPORT_REF_RE = re.compile(r'\(export\s+"([^"]+)"\s+\(func\s+(\$\S+|\d+)\)\)')
# (func $id (export "name") ...)   -- inline export form
_INLINE_EXPORT_RE = re.compile(r'\(func\s+(\$\S+)\s*\(export\s+"([^"]+)"\)')
_PARAM_RE = re.compile(r'\(param(?:\s+\$\S+)?((?:\s+\w+)+)\)')
_TYPE_REF_RE = re.compile(r'\(type\s+(\$\S+|\d+)\)')
_TYPE_DEF_RE = re.compile(r'\(type\s+(\$\S+|\d+)\s+\(func((?:\s*\(param(?:\s+\$\S+)?(?:\s+\w+)+\))*)')


def list_func_exports(wat_text):
    """Return {export_name: func_id} for every exported function."""
    exports = {}
    for name, fid in _EXPORT_REF_RE.findall(wat_text):
        exports[name] = fid
    for fid, name in _INLINE_EXPORT_RE.findall(wat_text):
        exports[name] = fid
    return exports


def _params_from_inline_header(func_block_text):
    params = []
    for group in _PARAM_RE.findall(func_block_text):
        params.extend(group.split())
    return params if params else None


def _params_from_type_section(wat_text, type_id):
    for tid, params_blob in _TYPE_DEF_RE.findall(wat_text):
        if tid == type_id:
            params = []
            for group in _PARAM_RE.findall(params_blob):
                params.extend(group.split())
            return params
    return None


def get_func_param_types(wat_text, func_id):
    """
    Best-effort recovery of a function's parameter types by id ($name or
    numeric index). Returns a list of WebAssembly value types, or None if
    it could not be determined.
    """
    escaped_id = re.escape(func_id)
    header_pat = re.compile(r'\(func\s+' + escaped_id + r'\b')
    m = header_pat.search(wat_text)
    if not m:
        return None

    start = m.start()
    next_func = re.search(r'\n\s*\(func\s', wat_text[m.end():])
    end = m.end() + next_func.start() if next_func else len(wat_text)
    block = wat_text[start:end]

    inline = _params_from_inline_header(block)
    if inline is not None:
        return inline

    type_ref = _TYPE_REF_RE.search(block)
    if type_ref:
        return _params_from_type_section(wat_text, type_ref.group(1))

    return []  # func with no params and no type ref => zero-arity


def synthesize_args(param_types):
    """
    Build a deterministic default argument vector from a list of value
    types. Returns (args, fully_supported).
    """
    args = []
    fully_supported = True
    for t in param_types:
        if t in DEFAULT_ARG_BY_TYPE:
            args.append(DEFAULT_ARG_BY_TYPE[t])
        else:
            fully_supported = False
            args.append("0")
    return args, fully_supported


def _looks_like_arg_mismatch(stderr_text):
    if not stderr_text:
        return False
    return any(p.search(stderr_text) for p in ARG_COUNT_MISMATCH_PATTERNS)


# ---------------------------------------------------------------------
# Per-runtime command construction
# ---------------------------------------------------------------------
#
# wasmtime CLI: wasmtime --invoke <func> <file.wasm> [args...]
#
# wasmer CLI: invocation syntax has changed across major wasmer versions.
# The form below matches the modern `wasmer run` subcommand:
#     wasmer run <file.wasm> --invoke <func> -- [args...]
# If your installed wasmer version uses a different flag (older 2.x CLIs
# used `wasmer <file.wasm> --invoke <func> [args...]` without `run`/`--`),
# adjust build_wasmer_cmd() below to match `wasmer --help` / `wasmer run --help`
# on your actual install before trusting results at scale.

def build_wasmtime_cmd(runtime_bin, wasm_path, func_name, args):
    return [str(runtime_bin), "--invoke", func_name, str(wasm_path)] + args


def build_wasmer_cmd(runtime_bin, wasm_path, func_name, args):
    cmd = [str(runtime_bin), "run", str(wasm_path), "--invoke", func_name]
    if args:
        cmd += ["--"] + args
    return cmd


RUNTIME_BUILDERS = {
    "wasmtime": build_wasmtime_cmd,
    "wasmer": build_wasmer_cmd,
}


# ---------------------------------------------------------------------
# Single-runtime entry point
# ---------------------------------------------------------------------

def run_wasm_with_inferred_args(runtime, runtime_bin, wasm_path, wat_text, timeout_s,
                                 stdin_text="1\n", preferred_names=("main", "_start")):
    """
    Pick an exported function, infer its parameters, invoke it with
    synthesized arguments under the given `runtime` ("wasmtime" or
    "wasmer"). Returns:

        {
          "runtime": "wasmtime" | "wasmer",
          "status": "ok" | "err:<rc>" | "timeout" | "no_entry" | "no_sig" | "skipped",
          "func": <export name used> or None,
          "args": [...],
          "elapsed_s": float or None,
          "stdout": str, "stderr": str,
          "notes": [str, ...],
        }
    """
    result = {
        "runtime": runtime, "status": "no_entry", "func": None, "args": [],
        "elapsed_s": None, "stdout": "", "stderr": "", "notes": [],
    }

    if runtime not in RUNTIME_BUILDERS:
        result["status"] = "skipped"
        result["notes"].append(f"unknown_runtime:{runtime}")
        return result

    if not runtime_bin or not Path(runtime_bin).exists():
        result["status"] = "skipped"
        result["notes"].append(f"{runtime}_binary_missing")
        return result

    if not wat_text:
        result["notes"].append("no_wat_text")
        return result

    exports = list_func_exports(wat_text)
    if not exports:
        return result  # genuinely no_entry

    target_name = next((n for n in preferred_names if n in exports), None)
    if target_name is None:
        target_name = next(iter(exports))
    func_id = exports[target_name]
    result["func"] = target_name

    param_types = get_func_param_types(wat_text, func_id)

    if param_types is None:
        result["status"] = "no_sig"
        result["notes"].append("signature_recovery_failed")
        args = []
    else:
        args, fully_supported = synthesize_args(param_types)
        if not fully_supported:
            result["notes"].append("unsupported_param_type_defaulted")
        result["args"] = args

    cmd = RUNTIME_BUILDERS[runtime](runtime_bin, wasm_path, target_name, args)

    t0 = time.time()
    rc, out, err = run_cmd(cmd, timeout_s=timeout_s, input_text=stdin_text)
    t1 = time.time()

    result["stdout"], result["stderr"] = out, err

    if rc == -1 and err == "timeout":
        result["status"] = "timeout"
    elif rc == 0:
        result["status"] = "ok"
        result["elapsed_s"] = round(t1 - t0, 6)
    else:
        if _looks_like_arg_mismatch(err) and param_types is None:
            result["status"] = "no_sig"
            result["notes"].append("confirmed_arg_mismatch")
        else:
            result["status"] = f"err:{rc}"

    return result


# ---------------------------------------------------------------------
# Convenience: run across all configured runtimes in one call
# ---------------------------------------------------------------------

def run_wasm_all_runtimes(wasm_path, wat_text, timeout_s,
                           wasmtime_bin=None, wasmer_bin=None,
                           stdin_text="1\n"):
 
    out = {"wasmtime": None, "wasmer": None}

    if wasmtime_bin is not None:
        out["wasmtime"] = run_wasm_with_inferred_args(
            "wasmtime", wasmtime_bin, wasm_path, wat_text, timeout_s, stdin_text
        )

    if wasmer_bin is not None:
        out["wasmer"] = run_wasm_with_inferred_args(
            "wasmer", wasmer_bin, wasm_path, wat_text, timeout_s, stdin_text
        )

    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 4:
        print("Usage: python wasm_runtime.py <wasmtime_bin|-> <wasmer_bin|-> <file.wasm>")
        print("  pass '-' to skip a runtime")
        sys.exit(1)
    wasmtime_bin, wasmer_bin, wasm_path = sys.argv[1], sys.argv[2], sys.argv[3]
    wasmtime_bin = None if wasmtime_bin == "-" else wasmtime_bin
    wasmer_bin = None if wasmer_bin == "-" else wasmer_bin

    rc, wat, err = run_cmd(["wasm2wat", wasm_path])
    if rc != 0:
        print("wasm2wat failed:", err)
        sys.exit(1)

    res = run_wasm_all_runtimes(wasm_path, wat, timeout_s=10,
                                 wasmtime_bin=wasmtime_bin, wasmer_bin=wasmer_bin)
    for rt, r in res.items():
        print(rt, ":", r)