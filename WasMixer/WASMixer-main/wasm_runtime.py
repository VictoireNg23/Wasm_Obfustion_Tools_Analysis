#!/usr/bin/env python3
# wasm_runtime.py
"""
Parameter-aware native execution of WebAssembly binaries via wasmtime.
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
    # v128 / reference types are not invokable via wasmtime's CLI arg
    # parser in most versions; flagged explicitly rather than guessed.
}

ARG_COUNT_MISMATCH_PATTERNS = (
    re.compile(r"expected\s+\d+\s+argument", re.IGNORECASE),
    re.compile(r"argument count mismatch", re.IGNORECASE),
    re.compile(r"wrong number of (arguments|parameters)", re.IGNORECASE),
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
# Export / signature recovery from .wat text
# ---------------------------------------------------------------------

# (export "name" (func $id_or_index))
_EXPORT_REF_RE = re.compile(r'\(export\s+"([^"]+)"\s+\(func\s+(\$\S+|\d+)\)\)')
# (func $id (export "name") ...)   -- inline export form
_INLINE_EXPORT_RE = re.compile(r'\(func\s+(\$\S+)\s*\(export\s+"([^"]+)"\)')
# function header: (func $id (type $t)? (param i32 i32)* (result ...)*
_FUNC_HEADER_RE = re.compile(r'\(func\s+(\$\S+|\(;\d+;\))')
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
    """Extract param types directly listed on a func's own header/body."""
    params = []
    for group in _PARAM_RE.findall(func_block_text):
        params.extend(group.split())
    return params if params else None


def _params_from_type_section(wat_text, type_id):
    """Look up param types via a (type $t (func (param ...))) definition."""
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
    # locate the func's own block: from its header to the next top-level
    # "(func " or end of text, to scope the param/type regexes correctly.
    escaped_id = re.escape(func_id)
    header_pat = re.compile(r'\(func\s+' + escaped_id + r'\b')
    m = header_pat.search(wat_text)
    if not m:
        return None

    start = m.start()
    next_func = re.search(r'\n\s*\(func\s', wat_text[m.end():])
    end = m.end() + next_func.start() if next_func else len(wat_text)
    block = wat_text[start:end]

    # case 1: params listed inline on this func
    inline = _params_from_inline_header(block)
    if inline is not None:
        return inline

    # case 2: func references a shared (type $t), look it up
    type_ref = _TYPE_REF_RE.search(block)
    if type_ref:
        return _params_from_type_section(wat_text, type_ref.group(1))

    return []  # func with no params and no type ref => zero-arity


# ---------------------------------------------------------------------
# Argument synthesis
# ---------------------------------------------------------------------

def synthesize_args(param_types):
    """
    Build a deterministic default argument vector from a list of value
    types. Returns (args, fully_supported) where fully_supported is False
    if any type could not be mapped to a CLI-passable default (e.g. v128).
    """
    args = []
    fully_supported = True
    for t in param_types:
        if t in DEFAULT_ARG_BY_TYPE:
            args.append(DEFAULT_ARG_BY_TYPE[t])
        else:
            fully_supported = False
            args.append("0")  # best-effort filler, won't be type-correct
    return args, fully_supported


def _looks_like_arg_mismatch(stderr_text):
    if not stderr_text:
        return False
    return any(p.search(stderr_text) for p in ARG_COUNT_MISMATCH_PATTERNS)


# ---------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------

def run_wasm_with_inferred_args(wasmtime_bin, wasm_path, wat_text, timeout_s,
                                 stdin_text="1\n", preferred_names=("main", "_start")):
    """
    Pick an exported function, infer its parameters, invoke it with
    synthesized arguments. Returns a dict:

        {
          "status": "ok" | "err:<rc>" | "timeout" | "no_entry" | "no_sig",
          "func": <export name used> or None,
          "args": [...],
          "elapsed_s": float or None,
          "stdout": str, "stderr": str,
          "notes": [str, ...],
        }
    """
    result = {
        "status": "no_entry", "func": None, "args": [],
        "elapsed_s": None, "stdout": "", "stderr": "", "notes": [],
    }

    if not wasmtime_bin or not Path(wasmtime_bin).exists():
        result["notes"].append("wasmtime_binary_missing")
        return result

    if not wat_text:
        result["notes"].append("no_wat_text")
        return result

    exports = list_func_exports(wat_text)
    if not exports:
        return result  # genuinely no_entry

    # choose target: prefer canonical entry names, else first export
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

    cmd = [str(wasmtime_bin), "--invoke", target_name, str(wasm_path)] + args

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
            # confirms this was a true signature-recovery failure, not a
            # generic runtime trap -- keep it distinguishable in the CSV.
            result["status"] = "no_sig"
            result["notes"].append("confirmed_arg_mismatch")
        else:
            result["status"] = f"err:{rc}"

    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python wasm_runtime.py <wasmtime_bin> <file.wasm>")
        sys.exit(1)
    wasmtime_bin, wasm_path = sys.argv[1], sys.argv[2]
    rc, wat, err = run_cmd(["wasm2wat", wasm_path])
    if rc != 0:
        print("wasm2wat failed:", err)
        sys.exit(1)
    res = run_wasm_with_inferred_args(wasmtime_bin, wasm_path, wat, timeout_s=10)
    print(res)
