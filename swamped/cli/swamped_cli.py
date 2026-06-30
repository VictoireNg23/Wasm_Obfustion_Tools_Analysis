#!/usr/bin/env python3
"""
SWAMPED CLI - WebAssembly Binary Obfuscation Tool

Command-line interface for the SWAMPED framework.
Applies 22 semantics-preserving perturbation methods to WebAssembly modules.
"""

import argparse
import copy
import logging
import os
import subprocess
import sys
import textwrap
import time

# Ensure the project root is on the Python path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from wasmParser import parser
from strategies import structural_perturbation as sp
from strategies import code_perturbation as cp
from strategies import state as strategy_state

logger = logging.getLogger("swamped")

# ── Stack Operation Insertion sub-variants ────────────────────────────────

STACKOP_VARIANTS = {
    "m":  {"fn": cp.stackOP_insertion_memory,      "desc": "memory/local/global operations"},
    "n":  {"fn": cp.stackOP_insertion_numeric,     "desc": "arithmetic operations"},
    "b":  {"fn": cp.stackOP_insertion_bit,         "desc": "bitwise operations"},
    "c1": {"fn": cp.stackOP_insertion_conversion1, "desc": "type conversions (int/float)"},
    "c2": {"fn": cp.stackOP_insertion_conversion2, "desc": "floating-point conversions"},
    "f":  {"fn": cp.stackOP_insertion_floating,    "desc": "float operations"},
}


def _run_stack_op(parsedSection, alpha, beta, ratio, variants=None):
    """Run stack operation insertion. If variants is None, run all."""
    keys = variants if variants else list(STACKOP_VARIANTS.keys())
    for k in keys:
        STACKOP_VARIANTS[k]["fn"](parsedSection, alpha=alpha, beta=beta, ratio=ratio)


def _run_add_sub(parsedSection, alpha, beta, ratio):
    """Run both add→sub and sub→add transformations."""
    cp.add_sub_transformation(parsedSection, alpha=alpha, beta=beta, ratio=ratio)
    cp.sub_add_transformation(parsedSection, alpha=alpha, beta=beta, ratio=ratio)


def _run_mba(parsedSection, alpha, beta, ratio):
    """Run both XOR and OR MBA transformations."""
    cp.xor_MBA_transformation(parsedSection, alpha=alpha, beta=beta, ratio=ratio)
    cp.or_MBA_transformation(parsedSection, alpha=alpha, beta=beta, ratio=ratio)


# ── Registry of all 22 perturbation methods ───────────────────────────────

STRATEGIES = {
    # Structural perturbations (9)
    "function_sig_insertion": {"fn": sp.function_sig_insertion, "cat": "structural", "desc": "Inject unused function type signatures"},
    "import_insertion":       {"fn": sp.import_insertion,       "cat": "structural", "desc": "Inject unused import declarations"},
    "function_insertion":     {"fn": sp.function_insertion,     "cat": "structural", "desc": "Inject entire dummy function bodies"},
    "function_body_cloning":  {"fn": sp.function_body_cloning,  "cat": "structural", "desc": "Clone functions with proxy redirection"},
    "global_insertion":       {"fn": sp.global_insertion,       "cat": "structural", "desc": "Inject dummy global variables"},
    "element_insertion":      {"fn": sp.element_insertion,      "cat": "structural", "desc": "Inject table element entries"},
    "export_insertion":       {"fn": sp.export_insertion,       "cat": "structural", "desc": "Inject unused export declarations"},
    "data_insertion":         {"fn": sp.data_insertion,         "cat": "structural", "desc": "Inject unused data segments"},
    "data_encryption":        {"fn": sp.data_encryption,        "cat": "structural", "desc": "XOR-encrypt data segments with runtime decryptor"},

    # Code-level perturbations (13)
    "custom_section_insertion":  {"fn": None,                       "cat": "code", "desc": "Inject custom named sections (not yet implemented)"},
    "nop_insertion":             {"fn": cp.nop_insertion,            "cat": "code", "desc": "Insert NOP instructions"},
    "stack_op_insertion":        {"fn": _run_stack_op,               "cat": "code", "desc": "Insert dummy stack operations (all variants)"},
    "opaque_predicate_insertion": {"fn": cp.opaque_predicate_insertion, "cat": "code", "desc": "Insert always-true/false Collatz-based predicates"},
    "proxy_function_insertion":  {"fn": None,                       "cat": "code", "desc": "Insert proxy wrapper functions (not yet implemented)"},
    "direct_to_indirect":        {"fn": cp.direct_to_indirect,      "cat": "code", "desc": "Convert direct calls to indirect table calls"},
    "add_sub_transformation":    {"fn": _run_add_sub,               "cat": "code", "desc": "Transform add/sub operations (a+b <-> a-(-b))"},
    "shift_transformation":      {"fn": cp.shift_transformation,    "cat": "code", "desc": "Convert shifts to mul/div equivalents"},
    "eqz_transformation":        {"fn": cp.eqz_transformation,      "cat": "code", "desc": "Rewrite eqz as comparison with zero"},
    "offset_expansion":          {"fn": cp.load_store_transformation, "cat": "code", "desc": "Decompose memory offset encoding"},
    "mba_transformation":        {"fn": _run_mba,                   "cat": "code", "desc": "Replace XOR/OR with mixed boolean-arithmetic expressions"},
    "constant_value_splitting":  {"fn": cp.constant_value_splitting, "cat": "code", "desc": "Split constants into arithmetic sums"},
    "constant_value_transformation": {"fn": cp.constant_global_variables, "cat": "code", "desc": "Replace constants with global variable reads"},
}


# ── Helpers ────────────────────────────────────────────────────────────────

def wasm_to_wast(wasm_path, wast_path):
    """Convert .wasm binary to .wast text format using WABT."""
    result = subprocess.run(
        ["wasm2wat", wasm_path, "--generate-names", "-o", wast_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.error("wasm2wat failed: %s", result.stderr.strip())
        sys.exit(1)


def resolve_input(input_path, tmp_dir):
    """Return the path to a .wast file, converting from .wasm if necessary."""
    if input_path.endswith(".wasm"):
        wast_path = os.path.join(tmp_dir, os.path.basename(input_path).replace(".wasm", ".wast"))
        logger.info("[*] Converting %s -> WAT ...", input_path)
        wasm_to_wast(input_path, wast_path)
        return wast_path
    return input_path


def list_strategies():
    """Print all 22 perturbation methods grouped by category."""
    idx = 1
    print("\n  Structural perturbations (9):\n")
    for name, info in STRATEGIES.items():
        if info["cat"] == "structural":
            print(f"    {idx:>2}. {name:<35s} {info['desc']}")
            idx += 1
    print("\n  Code-level perturbations (13):\n")
    for name, info in STRATEGIES.items():
        if info["cat"] == "code":
            print(f"    {idx:>2}. {name:<35s} {info['desc']}")
            if name == "stack_op_insertion":
                for k, v in STACKOP_VARIANTS.items():
                    print(f"        --stackop-{k:<4s} {v['desc']}")
            idx += 1
    print()


def _count_body_instructions(parsed):
    """Count total body instructions across all functions."""
    total = 0
    for f in parsed.get("Function", {}).values():
        if f.body:
            total += len(f.body)
    return total


def _section_counts(parsed):
    """Return a dict of section_name -> entry count."""
    return {sec: len(entries) for sec, entries in parsed.items()}


def _print_diff(before_counts, before_instructions, after_counts, after_instructions):
    """Print a summary of what changed."""
    print("\n  Diff summary:\n")
    print(f"    {'Section':<20s} {'Before':>8s} {'After':>8s} {'Delta':>8s}")
    print(f"    {'─' * 20} {'─' * 8} {'─' * 8} {'─' * 8}")
    for sec in before_counts:
        b = before_counts[sec]
        a = after_counts.get(sec, 0)
        delta = a - b
        marker = f"+{delta}" if delta > 0 else str(delta) if delta < 0 else "0"
        if delta != 0:
            print(f"    {sec:<20s} {b:>8d} {a:>8d} {marker:>8s}")
    instr_delta = after_instructions - before_instructions
    marker = f"+{instr_delta}" if instr_delta > 0 else str(instr_delta) if instr_delta < 0 else "0"
    if instr_delta != 0:
        print(f"    {'instructions':<20s} {before_instructions:>8d} {after_instructions:>8d} {marker:>8s}")
    print()


# ── CLI entry point ───────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        prog="swamped",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
            SWAMPED - WebAssembly Binary Obfuscation CLI

            A framework incorporating 22 semantics-preserving perturbation methods.

            commands:
              list          Show all available perturbation strategies
              obfuscate     Apply perturbations to a .wasm or .wast module
        """),
        epilog=textwrap.dedent("""\
            examples:
              swamped list
              swamped obfuscate input.wasm -o out.wasm -s nop_insertion shift_transformation
              swamped obfuscate input.wasm -o out.wasm -s all --ratio 0.5
              swamped obfuscate input.wasm -o out.wasm -s code -e direct_to_indirect
              swamped obfuscate input.wasm -o out.wasm -s structural --alpha 2 --beta 5
              swamped obfuscate input.wasm -o out.wasm -s stack_op_insertion --stackop m b
              swamped obfuscate input.wasm -o out.wasm -s all --seed 42 --diff
        """),
    )
    sub = p.add_subparsers(dest="command", required=True)

    # ── list ──
    sub.add_parser("list", help="Show all 22 perturbation methods")

    # ── obfuscate ──
    obf = sub.add_parser(
        "obfuscate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="Apply perturbations to a WASM/WAST module",
        description=textwrap.dedent("""\
            Apply one or more perturbation methods to a WebAssembly module.

            strategy selectors (-s):
              <name>        A single strategy name (see 'swamped list')
              all           All 22 perturbation methods (structural + code)
              structural    Only structural perturbations (9 methods)
              code          Only code-level perturbations (13 methods)

            You can combine selectors and exclude specific ones with -e:
              -s all -e data_encryption          All except data_encryption
              -s code -e nop_insertion eqz_transformation

            stack_op_insertion sub-variants (--stackop):
              m     memory/local/global operations
              n     arithmetic operations
              b     bitwise operations
              c1    type conversions (int/float)
              c2    floating-point conversions
              f     float operations
              If --stackop is omitted, all 6 variants are applied.
        """),
    )
    obf.add_argument("input", help="Input file (.wasm or .wast)")
    obf.add_argument("-o", "--output", required=True, help="Output file path (.wasm or .wast)")
    obf.add_argument(
        "-s", "--strategies", nargs="+", required=True,
        metavar="NAME",
        help="Strategies to apply: strategy names, 'all', 'structural', or 'code'",
    )
    obf.add_argument(
        "-e", "--exclude", nargs="+", default=[], metavar="NAME",
        help="Exclude specific strategies (useful with all/structural/code)",
    )
    obf.add_argument(
        "--stackop", nargs="+", default=None,
        choices=list(STACKOP_VARIANTS.keys()),
        metavar="VARIANT",
        help="Stack operation sub-variants: m, n, b, c1, c2, f (default: all)",
    )
    obf.add_argument("--alpha", type=float, default=1.0, help="Beta-distribution alpha (default: 1.0)")
    obf.add_argument("--beta",  type=float, default=1.0, help="Beta-distribution beta (default: 1.0)")
    obf.add_argument("--ratio", type=float, default=1.0, help="Perturbation ratio 0.0-1.0 (default: 1.0)")
    obf.add_argument("--validate", action="store_true", help="Run wasm-validate on the output")
    obf.add_argument("-t", "--timing", action="store_true", help="Show execution time for each strategy")
    obf.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible runs")
    obf.add_argument("--diff", action="store_true", help="Show a summary of sections/instructions changed")
    obf.add_argument("--strict", action="store_true", help="Abort on the first strategy failure")
    obf.add_argument("-v", "--verbose", action="store_true", help="Enable debug-level logging")
    obf.add_argument("-q", "--quiet", action="store_true", help="Suppress all output except errors")

    return p


def resolve_strategy_names(requested, excluded):
    """Expand meta-names (all / structural / code), apply exclusions, and validate."""
    names = []
    for r in requested:
        if r == "all":
            names.extend(STRATEGIES.keys())
        elif r == "structural":
            names.extend(k for k, v in STRATEGIES.items() if v["cat"] == "structural")
        elif r == "code":
            names.extend(k for k, v in STRATEGIES.items() if v["cat"] == "code")
        elif r in STRATEGIES:
            names.append(r)
        else:
            logger.error("Unknown strategy: '%s'", r)
            logger.error("Run 'swamped list' to see available strategies.")
            sys.exit(1)

    # Validate exclusions
    for e in excluded:
        if e not in STRATEGIES:
            logger.error("Unknown strategy to exclude: '%s'", e)
            sys.exit(1)
    exclude_set = set(excluded)

    # Deduplicate while preserving order, then exclude
    seen = set()
    unique = []
    for n in names:
        if n not in seen and n not in exclude_set:
            seen.add(n)
            unique.append(n)

    if not unique:
        logger.error("No strategies left after exclusions.")
        sys.exit(1)

    # Skip not-yet-implemented strategies with a warning
    final = []
    for n in unique:
        if STRATEGIES[n]["fn"] is None:
            logger.warning("%s is not yet implemented, skipping.", n)
        else:
            final.append(n)

    if not final:
        logger.error("No implemented strategies left.")
        sys.exit(1)

    return final


def cmd_obfuscate(args):
    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)

    if not os.path.isfile(input_path):
        logger.error("Input file not found: %s", input_path)
        sys.exit(1)

    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)

    # Seed RNG if requested
    if args.seed is not None:
        strategy_state.set_seed(args.seed)
        logger.info("[*] RNG seed set to %d", args.seed)

    # Convert .wasm to .wast if needed
    wast_path = resolve_input(input_path, output_dir)

    # Parse
    logger.info("[*] Parsing %s ...", wast_path)
    with open(wast_path) as f:
        origin_wast = f.readlines()
    parsed = parser.parseWast(origin_wast)

    # Snapshot before-counts for --diff
    if args.diff:
        before_counts = _section_counts(parsed)
        before_instructions = _count_body_instructions(parsed)

    # Apply strategies sequentially
    strategy_names = resolve_strategy_names(args.strategies, args.exclude)
    section = copy.deepcopy(parsed)

    logger.info("[*] Applying %d perturbation(s) (alpha=%s, beta=%s, ratio=%s):\n",
                len(strategy_names), args.alpha, args.beta, args.ratio)
    timings = []
    for name in strategy_names:
        entry = STRATEGIES[name]
        logger.info("    -> %s", name)
        snapshot = copy.deepcopy(section)
        t0 = time.monotonic()
        try:
            if name == "stack_op_insertion":
                entry["fn"](section, alpha=args.alpha, beta=args.beta, ratio=args.ratio, variants=args.stackop)
            else:
                entry["fn"](section, alpha=args.alpha, beta=args.beta, ratio=args.ratio)
            elapsed = time.monotonic() - t0
            timings.append((name, elapsed, True))
            if args.timing:
                logger.info("       (%0.2fs)", elapsed)
        except Exception as e:
            elapsed = time.monotonic() - t0
            timings.append((name, elapsed, False))
            section = snapshot  # rollback to avoid corrupted state
            if args.strict:
                logger.error("    [error] %s failed: %s", name, e)
                sys.exit(1)
            else:
                logger.warning("    [warning] %s failed (rolled back): %s", name, e)

    if args.timing and len(timings) > 1:
        total = sum(t for _, t, _ in timings)
        slowest = max(timings, key=lambda x: x[1])
        logger.info("\n    total: %.2fs | slowest: %s (%.2fs)", total, slowest[0], slowest[1])

    # --diff summary
    if args.diff:
        after_counts = _section_counts(section)
        after_instructions = _count_body_instructions(section)
        _print_diff(before_counts, before_instructions, after_counts, after_instructions)

    # Save output
    output_name = os.path.basename(output_path)
    if output_path.endswith(".wasm"):
        # savePertWasm writes .wast and converts to .wasm
        wast_out = output_path.replace(".wasm", ".wast")
        logger.info("[*] Writing %s ...", wast_out)
        parser.savePertWasm(output_dir + "/", os.path.basename(wast_out), section)
        if os.path.isfile(output_path):
            logger.info("[+] Done! Output: %s", output_path)
        else:
            logger.error("[!] WAT written but wat2wasm conversion may have failed.")
            logger.error("    WAT output: %s", wast_out)
            sys.exit(1)
    else:
        # .wast output
        logger.info("[*] Writing %s ...", output_path)
        parser.savePertWasm(output_dir + "/", output_name, section)
        logger.info("[+] Done! Output: %s", output_path)

    # Validate
    if args.validate:
        wasm_file = output_path if output_path.endswith(".wasm") else output_path.replace(".wast", ".wasm")
        if not os.path.isfile(wasm_file):
            logger.error("[!] No .wasm file to validate.")
            sys.exit(1)
        logger.info("[*] Validating %s ...", wasm_file)
        result = subprocess.run(["wasm-validate", wasm_file], capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("[+] Validation passed.")
        else:
            logger.error("[!] Validation failed: %s", result.stderr.strip())
            sys.exit(1)


def _setup_logging(verbose=False, quiet=False):
    """Configure logging. Default output matches the original print() behaviour."""
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)


def main():
    p = build_parser()
    args = p.parse_args()

    # Logging setup — only relevant for obfuscate (list always uses print)
    if args.command == "obfuscate":
        _setup_logging(verbose=args.verbose, quiet=args.quiet)

    if args.command == "list":
        list_strategies()
    elif args.command == "obfuscate":
        cmd_obfuscate(args)


if __name__ == "__main__":
    main()
