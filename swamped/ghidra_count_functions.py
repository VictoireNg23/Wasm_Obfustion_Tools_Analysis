# ghidra_count_functions.py
# Jython script run inside Ghidra headless via -postScript.
# Writes a small JSON report describing whether the current program loaded
# and how many functions Ghidra's analysis recovered from it.
#
# Usage (from deobfuscation_vulnerability.py):
#   analyzeHeadless <project_dir> <project_name> -import <file.wasm> \
#       -postScript ghidra_count_functions.py <out_json_path> \
#       -scriptPath <this_file's_dir> -deleteProject -overwrite
#
# Requires a WebAssembly-capable Ghidra install (loader/processor
# extension); Ghidra has no built-in .wasm support.

import json


def run():
    args = getScriptArgs()
    out_path = args[0] if args else "/tmp/ghidra_result.json"

    program = currentProgram if 'currentProgram' in globals() else getCurrentProgram()

    if program is None:
        result = {"loaded": False, "func_count": 0, "error": "no_program"}
    else:
        try:
            fm = program.getFunctionManager()
            func_count = fm.getFunctionCount()
            result = {
                "loaded": True,
                "func_count": int(func_count),
                "program_name": program.getName(),
                "language_id": str(program.getLanguageID()),
            }
        except Exception as e:
            result = {"loaded": True, "func_count": 0, "error": "introspection_failed:%s" % str(e)}

    f = open(out_path, "w")
    try:
        f.write(json.dumps(result))
    finally:
        f.close()


run()
