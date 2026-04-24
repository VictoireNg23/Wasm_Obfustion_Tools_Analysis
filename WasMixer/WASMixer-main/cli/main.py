#!/usr/bin/env python3
import argparse
import sys
import os
import shutil

try:
    from WASMixer import WASMixer
except ImportError:
    print("ERROR: WASMixer is not installed.")
    print("To install in editable/dev mode, run:")
    print("  pip install -e .")
    print("Make sure you have all dependencies from requirements.txt installed as well.")
    sys.exit(1)

OBFUSCATION_LEVELS = {
    "flatten": "Control flow flattening",
    "alias": "Alias disruption",
    "name": "Name obfuscation",
    "memory": "Memory obfuscation"
}

def list_levels() -> None:
    """Print available obfuscation levels."""
    print("Available obfuscation levels:")
    for key, desc in OBFUSCATION_LEVELS.items():
        print(f"  --{key}: {desc}")

def get_output_path(input_path: str, safe: bool) -> str:
    """Return the output path for the obfuscated file."""
    if safe:
        base, ext = os.path.splitext(input_path)
        return f"{base}_mixr{ext}"
    else:
        return input_path

def obfuscate_wasm(input_path: str, output_path: str, args: argparse.Namespace) -> None:
    """
    Obfuscate a wasm file using selected options.
    If --safe is set, copy the original file before processing.
    The obfuscated file is saved as <name>_obf.wasm only in safe mode.
    Otherwise, the original file is overwritten.
    """
    if args.safe:
        shutil.copy2(input_path, output_path)
        print(f"Copied original to {output_path} (safe mode, original not modified)")
        obf_input = output_path
    else:
        obf_input = input_path

    obfuscator = WASMixer(obf_input)
    did_something = False
    if args.flatten:
        if args.cf or args.collatz:
            obfuscator.code_flatten(collatz=True)
        else:
            obfuscator.code_flatten()
        did_something = True
    if args.alias:
        if args.ca or args.collatz:
            obfuscator.alias_disruption(collatz=True)
        else:
            obfuscator.alias_disruption()
        did_something = True
    if args.name:
        obfuscator.name_obfuscation()
        did_something = True
    if args.memory:
        obfuscator.memory_obfuscation(key=0)
        did_something = True
    if not did_something:
        print("No obfuscation level selected. Use --list to see options.")
        sys.exit(1)
    obfuscator.wasm_binary.emit_binary()
    print(f"Obfuscated binary saved as {output_path}.")

def main() -> None:
    """
    WASMixer CLI tool for obfuscating .wasm binaries.

    Usage:
      python main.py <wasm_file> [--flatten] [--alias] [--name] [--memory] [--all] [--safe]
      python main.py --list

    Options:
      <wasm_file>   Input .wasm file to obfuscate
      --flatten     Apply control flow flattening
      --alias       Apply alias disruption
      --name        Apply name obfuscation
      --memory      Apply memory obfuscation
      --collatz     Apply Collatz transformation on all applicable obfuscations
        --cf          Collatz transformation on flattening
        --ca          Collatz transformation on alias disruption
      --all         Apply all obfuscation levels
      --safe        Do not overwrite original file; process a copy
      --list        List available obfuscation levels and exit
    """
    parser = argparse.ArgumentParser(description="WASMixer CLI tool for obfuscating .wasm binaries.")
    parser.add_argument("wasm", nargs="?", help="Input .wasm file to obfuscate")
    parser.add_argument("--flatten", action="store_true", help="Apply control flow flattening")
    parser.add_argument("--alias", action="store_true", help="Apply alias disruption")
    parser.add_argument("--name", action="store_true", help="Apply name obfuscation")
    parser.add_argument("--memory", action="store_true", help="Apply memory obfuscation")
    parser.add_argument("--collatz", action="store_true", help="Apply Collatz transformation on all applicable obfuscations")
    parser.add_argument("--cf", action="store_true", help="Collatz transformation on flattening")
    parser.add_argument("--ca", action="store_true", help="Collatz transformation on alias disruption")
    parser.add_argument("--list", action="store_true", help="List available obfuscation levels")
    parser.add_argument("--all", action="store_true", help="Apply all obfuscation levels")
    parser.add_argument("--safe", action="store_true", help="Do not overwrite original file; process a copy.")
    args = parser.parse_args()

    if args.list:
        list_levels()
        sys.exit(0)

    if args.all:
        args.flatten = args.alias = args.name = args.memory = True

    if not args.wasm:
        print("Error: You must specify a .wasm file to obfuscate.")
        parser.print_help()
        sys.exit(1)

    output_path = get_output_path(args.wasm, args.safe)
    obfuscate_wasm(args.wasm, output_path, args)

if __name__ == "__main__":
    main()
