# SWAMPED Evaluation Pipeline

This repository contains the evaluation pipeline used to analyze WebAssembly obfuscations generated with SWAMPED. It complements the original SWAMPED documentation by focusing on large-scale experimentation: dataset processing, automated perturbation, similarity analysis, runtime validation, and semantic equivalence checking with SpecTec.

The pipeline provides scripts to:

* apply SWAMPED perturbation strategies to a collection of WebAssembly binaries;
* compute structural and behavioral metrics between original and perturbed binaries;
* evaluate execution preservation using WebAssembly runtimes and browser-based execution;
* analyze resistance against reverse-engineering tools;
* enrich the results with formal validity and semantic equivalence checks using SpecTec.

---

## Directory structure

```
swamped_pipeline/
├── run_swamped.py                  # Main pipeline driver: discovery, obfuscation, metrics, CSV generation
├── combos.py                       # Perturbation strategy and ratio configuration
├── metrics_worker.py               # Worker processing one (sample, strategy, ratio) experiment
├── pipeline_core.py                # Dataset handling, caching, CSV management
├── orig_metrics.py                 # Metrics computation for original binaries
├── common.py                       # Common helpers (wasm2wat, wasm-dis, symbol extraction)
├── wasm_runtime.py                 # WebAssembly execution using Wasmtime or Wasmer
├── cfg_similarity.py               # CFG extraction and similarity computation
├── cfg_from_wat.py                 # CFG reconstruction from WAT representation
├── deobfuscation_vulnerability.py  # Reverse-engineering recovery tests
├── browser_runner.js               # Browser execution for state and import traces
└── ghidra_count_functions.py       # Ghidra headless function extraction

spectec_pipeline/
├── spectec_common.py               # SpecTec execution and helper functions
├── spectec_analysis_swamped.py     # SpecTec analysis for SWAMPED results
├── spectec_analysis_wasmixer.py    # SpecTec analysis for WasMixer results
└── spectec_analysis_wasmmutate.py  # SpecTec analysis for wasm-mutate results
```

---

# Requirements

git clone  https://github.com/SKKU-SecLab/SWAMPED.git

The pipeline requires the following dependencies:

* Python 3 with:

  * `rapidfuzz`
  * `numpy`
  * `scipy`
  * `networkx`
  * `matplotlib`
  

The Python environment used to execute SWAMPED must include these dependencies. In particular, `strategies/code_perturbation.py` imports `matplotlib.pyplot` during module loading, therefore missing `matplotlib` prevents SWAMPED from starting.

* WABT tools:

  * `wasm2wat`
  * `wat2wasm`
  * `wasm-validate`

* Binaryen tools:

  * `wasm-dis`
  * `wasm-opt`

* A WebAssembly runtime:

  * Wasmtime
  * Wasmer

The runtime is automatically selected based on the provided executable path.

* Node.js with `puppeteer` installed for browser-based execution analysis.
* SpecTec reference interpreter for formal validation and semantic equivalence checking.
* Ghidra with WebAssembly support (optional) for deobfuscation analysis.

---

# Running SWAMPED evaluation

The main entry point is `run_swamped.py`.

For each WebAssembly binary located recursively inside `--dataset`, the pipeline performs the following steps:

1. Compute metrics for the original binary.

   These measurements are computed once and stored in a cache:

   * binary size;
   * indirect call count;
   * maximum nesting depth;
   * execution result;
   * execution time;
   * browser execution trace;
   * disassembly information;
   * deobfuscation analysis results.

   Cached results are reused when the pipeline is executed again.

2. Apply every selected SWAMPED perturbation strategy.

   Each generated binary is analyzed using the same metrics as the original file. Additional comparison metrics are computed:

   * WAT similarity;
   * CFG similarity;
   * import trace similarity;
   * behavior preservation.

---

## Execution command

```bash
python3 run_swamped.py \
    --dataset <path_to_dataset> \
    --outdir <output_directory> \
    --csv <metrics_csv> \
    --swamped-cli <path_to_swamped_cli.py> \
    --swamped-repo <SWAMPED_repository_path> \
    --swamped-python <python_environment_for_swamped> \
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

`--swamped-python` is intentionally independent from the Python interpreter running `run_swamped.py`. SWAMPED is executed as a subprocess, and dependency mismatches must be avoided between the two environments.

---

# Perturbation design space

The pipeline evaluates the perturbation strategies provided by SWAMPED.

Among the 22 strategies described in the SWAMPED paper, 20 are currently available through `swamped_cli.py`.

The following strategies are not implemented in the current CLI version:

* `custom_section_insertion`
* `proxy_function_insertion`

Each strategy is evaluated with ratios ranging from:

```
0.1, 0.2, ..., 1.0
```

This results in:

```
20 strategies × 10 ratios = 200 configurations
```

per input binary.

The complete configuration is defined in `combos.py`.

---

# Output structure

Generated binaries are stored as follows:

```
<outdir>/<sample>/<sample>__<strategy>_r<ratio>_<hash>/

    <sample>_<strategy>_r<ratio>.wasm
    <sample>_<strategy>_r<ratio>.wast

    meta/
        SWAMPED metadata

    swamped_stdout.log
    swamped_stderr.log
    browser_obf.json
```

---

# Metrics CSV format

The generated CSV contains the following information:

```
sample
relpath_orig
obfuscation_transformation
ratio
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

`payload_preserved` is computed from:

* import trace comparison;
* WebAssembly validity;
* successful execution of the perturbed binary.

If the original binary has no observable execution behavior (`run_orig != ok`), the value is reported as `n/a`.

---

# Runtime evaluation

Both Wasmtime and Wasmer are supported.

The runtime command is selected automatically:

```
Wasmtime:
wasmtime --invoke <function> <file.wasm> <args>


Wasmer:
wasmer run <file.wasm> --invoke <function> -- <args>
```

To evaluate the same dataset with both runtimes, use different:

* output directories;
* CSV files;
* temporary directories.

Execution results depend on the runtime and therefore original-binary caches must not be shared.

Example:

```
Wasmer:
--wasmer-bin <wasmer>
--outdir results/wasmer/
--tmp-root scratch/wasmer/


Wasmtime:
--wasmtime-bin <wasmtime>
--outdir results/wasmtime/
--tmp-root scratch/wasmtime/
```

---

