# WasMixer Evaluation Pipeline

This repository contains the evaluation pipeline used to analyze WebAssembly obfuscations generated with WasMixer (Cao et al., ESORICS 2024).

The pipeline extends WasMixer's original workflow with large-scale experimentation support. It automates dataset processing, applies WasMixer transformations, computes structural and behavioral metrics between original and obfuscated binaries, and enriches the results with formal validity and semantic equivalence analysis using SpecTec.

The pipeline provides scripts to:

* apply WasMixer transformations to a collection of WebAssembly binaries;
* evaluate the impact of different transformation combinations;
* measure structural changes using WAT and CFG-based metrics;
* check behavioral preservation using native runtimes and browser execution;
* analyze resistance against reverse-engineering tools;
* verify semantic equivalence between original and obfuscated binaries using SpecTec.

---

# Directory structure

```
wasm_pipeline/
├── run_wasmixer.py                  # Main pipeline driver: discovery, obfuscation, metrics, CSV generation
├── combos.py                        # T1-T5 transformation configuration
├── metrics_worker.py                # Worker processing one (sample, combination) experiment
├── orig_metrics.py                  # Original-binary metrics computation and caching
├── common.py                        # Common helpers (wasm2wat, wasm-dis, symbol extraction)
├── wasm_runtime.py                  # WebAssembly execution using Wasmtime or Wasmer
├── cfg_similarity.py                # CFG extraction and similarity computation
├── cfg_from_wat.py                  # CFG reconstruction from WAT representation
├── deobfuscation_vulnerability.py   # Reverse-engineering recovery tests
├── browser_runner.js                # Browser execution for state and import traces
└── ghidra_count_functions.py        # Ghidra headless function extraction

spectec_pipeline/
├── spectec_common.py                # SpecTec execution and helper functions
└── spectec_analysis_wasmixer.py     # SpecTec analysis for WasMixer results
```

---

# Requirements

The evaluation requires the following components:

## WasMixer environment

WasMixer requires Python ≤ 3.10 because its `cyleb128` dependency does not currently build on newer Python versions.

Install WasMixer from its repository root:

```bash
git clone https://github.com/security-pride/WASMixer.git
pip install -e .
```

## Pipeline dependencies

The evaluation scripts require:

* `rapidfuzz`
* `numpy`
* `scipy`
* `networkx`

## WebAssembly tools

The following tools must be available in `PATH` or in a shared binary directory:

WABT:

* `wasm2wat`
* `wat2wasm`
* `wasm-validate`

Binaryen:

* `wasm-dis`
* `wasm-opt`

## Runtime and analysis tools

Required components:

* Wasmtime or Wasmer for native execution;
* Node.js with `puppeteer` for browser-based measurements;
* SpecTec reference interpreter for formal validation and semantic equivalence;
* Ghidra with WebAssembly support (optional) for deobfuscation analysis.

The pipeline automatically detects the selected WebAssembly runtime from the executable path.

---

# Running WasMixer evaluation

The main entry point is:

```text
run_wasmixer.py
```

For each WebAssembly file discovered recursively under `--dataset`:

1. The input file is converted to WebAssembly if necessary:

   * `.c` files are compiled using `emcc`;
   * `.wat` files are converted using `wat2wasm`.

2. Metrics are computed once for the original binary and stored in a cache.

   The cached measurements include:

   * binary size;
   * indirect call count;
   * maximum nesting depth;
   * execution result;
   * execution time;
   * browser execution information;
   * disassembly statistics;
   * deobfuscation analysis.

   Re-running the same command reuses existing cached results.

3. Each WasMixer transformation combination is applied.

   The generated binaries are analyzed using the same metrics, and comparison metrics are added:

   * WAT similarity;
   * CFG similarity;
   * import trace similarity;
   * behavior preservation.

---

# Execution command

```bash
python3 run_wasmixer.py \
    --dataset <path_to_dataset> \
    --outdir <output_directory> \
    --csv <metrics_csv> \
    --wasmixer <WasMixer_repository_path> \
    --browser-runner <path_to_browser_runner.js> \
    --node-path <node_modules_path> \
    --wabt-bin <WABT_directory> \
    --wasmer-bin <path_to_wasmer> \
    --tmp-root <local_scratch_directory> \
    --cores <number_of_workers>
```

For Wasmtime, replace:

```bash
--wasmer-bin <path_to_wasmer>
```

with:

```bash
--wasmtime-bin <path_to_wasmtime>
```

---

# Transformation design space

WasMixer provides five main transformations:

| ID | Transformation                  |
| -- | ------------------------------- |
| T1 | Name obfuscation                |
| T2 | Memory obfuscation              |
| T3 | Control-flow flattening         |
| T4 | Alias disruption                |
| T5 | Collatz-based opaque predicates |

The WasMixer CLI does not expose T5 as an independent transformation. The options:

```text
--collatz
--cf
--ca
```

are only interpreted inside the control-flow flattening and alias transformation paths.

Therefore, the evaluated design space is:

* all subsets of T1–T4:

```
2^4 - 1 = 15 combinations
```

* additional combinations where T5 is added to subsets containing T3 and/or T4:

```
12 additional combinations
```

In total:

```
27 transformation combinations per input binary
```

The complete list is generated automatically by `combos.py`.

The `--safe` option is always enabled when invoking WasMixer. This ensures that the generated file is written to a separate deterministic output path:

```text
<name>_mixr.wasm
```

without modifying the original binary.

---

# Output structure

Generated binaries are stored using the following layout:

```
<outdir>/<sample>/<sample>__<T-label>_<hash>/

    <sample>_mixr_<T-label>.wasm

    wasmixer_stdout.log
    wasmixer_stderr.log

    browser_obf.json
```

Example:

```text
sample__T1+T3+T5_xxxxx/

    sample_mixr_T1+T3+T5.wasm
```

---

# Metrics CSV format

The generated CSV contains:

```
sample
relpath_orig
obfuscation_transformation
mutant_id

size_orig
size_obf

call_ind_orig
call_ind_obf

max_nesting_orig
max_nesting_obf

valid_orig
valid_obf

run_orig
run_obf

run_time_orig
run_time_obf

import_trace_hash_orig
import_trace_hash_obf

import_trace_match

payload_preserved

memory_pages_orig
memory_pages_obf

exports_called_orig
exports_called_obf

browser_error_orig
browser_error_obf

disassembly_ok_orig
disassembly_ok_obf

wat_similarity
cfg_similarity

func_symbols_orig
func_symbols_obf

type_symbols_orig
type_symbols_obf

deobf_ghidra_funcs_orig
deobf_ghidra_funcs_obf

deobf_score_orig
deobf_score_obf

notes
obf_time
```

`obfuscation_transformation` stores the exact WasMixer CLI options applied, for example:

```text
--flatten --alias --collatz
```

The T-label notation is only used internally for directory names and mutant identifiers.

---

# Behavior preservation

`payload_preserved` combines execution-based observations.

For most transformations, it relies on:

* WebAssembly validity;
* successful execution;
* import trace comparison;
* state comparison when applicable.
---

# Runtime selection: Wasmer / Wasmtime

Both runtimes are supported without modifying the pipeline.

The execution command is selected automatically:

```
Wasmtime:
wasmtime --invoke <function> <file.wasm> <args>


Wasmer:
wasmer run <file.wasm> --invoke <function> -- <args>
```

