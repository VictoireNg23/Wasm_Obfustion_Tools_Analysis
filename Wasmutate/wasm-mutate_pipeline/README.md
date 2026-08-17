# wasm-mutate Evaluation Pipeline

This repository contains the evaluation pipeline used to study WebAssembly mutations generated with `wasm-mutate` from the Bytecode Alliance `wasm-tools` project (Cabrera-Arteaga et al.).

Since the original `wasm-mutate` interface does not provide fine-grained control over mutation categories, this evaluation relies on a custom wrapper (`wasm_mutator_by_category`) and a patched version of `wasm-mutate` that introduces per-category mutation selection.

The pipeline automates large-scale experiments by:

* applying selected mutation categories to a WebAssembly dataset;
* generating multiple randomized variants for each configuration;
* computing structural and behavioral differences between original and mutated binaries;
* evaluating execution preservation;
* enriching results with formal validity and semantic equivalence analysis using SpecTec.

---

# Directory structure

```text
wasm_mutate_pipeline/
├── run_wasmmutate.py                  # Main driver: discovery, mutation, metrics, CSV generation
├── combos.py                          # I1-I7 mutation category configuration
├── metrics_worker.py                  # Worker processing one (sample, combination, variant)
├── pipeline_core.py                   # Dataset handling, caching, CSV management
├── orig_metrics.py                    # Original-binary metrics computation
├── common.py                          # Common helpers (wasm2wat, wasm-dis, symbol extraction)
├── wasm_runtime.py                    # Execution using Wasmtime or Wasmer
├── cfg_similarity.py                  # CFG extraction and similarity computation
├── cfg_from_wat.py                    # CFG reconstruction from WAT representation
├── deobfuscation_vulnerability.py     # Reverse-engineering recovery tests
├── browser_runner.js                  # Browser execution and trace collection
├── ghidra_count_functions.py          # Ghidra headless function extraction
│
├── wasm_mutate_patch/
│   ├── lib.rs                         # Patched wasm-mutate implementation
│   └── codemotion.rs                  # Patched code motion mutator handling
│
└── wasm_mutator_by_category_src/
    └── Rust wrapper providing category-based mutation selection


spectec_pipeline/
├── spectec_common.py                  # SpecTec execution and helper functions
└── spectec_analysis_wasmmutate.py     # SpecTec enrichment for wasm-mutate results
```

---

# Patched wasm-mutate requirement

The original `wasm-mutate` implementation does not support selecting individual mutation categories.

git link https://github.com/bytecodealliance/wasm-tools/tree/main/crates/wasm-mutate

In the default implementation:

* the CLI (`wasm-tools mutate`);
* and the public Rust API (`WasmMutate::run()`)

select mutations randomly from the complete internal mutator pool.

To evaluate individual mutation families, this project introduces a patch adding:

* a `MutationCategory` abstraction;
* a `--categories` command-line option;
* explicit mapping between category names and internal mutators.

The following categories are supported:

| Category             | CLI value              | Underlying mutators                                                                                  |
| -------------------- | ---------------------- | ---------------------------------------------------------------------------------------------------- |
| Add type             | `add-type`             | `AddTypeMutator`                                                                                     |
| Add function         | `add-function`         | `AddFunctionMutator`                                                                                 |
| Edit custom sections | `edit-custom-sections` | `AddCustomSectionMutator`, `ReorderCustomSectionMutator`, `CustomSectionMutator`                     |
| Peephole rewriting   | `peephole`             | `PeepholeMutator`                                                                                    |
| Dead-code removal    | `dead-code-removal`    | `RemoveItemMutator`, `RemoveSection`, `RemoveStartSection`, `SnipMutator`, `FunctionBodyUnreachable` |
| Conditional swap     | `conditional-swap`     | `IfSwapMutator`                                                                                      |
| Loop unrolling       | `loop-unrolling`       | `LoopUnrollOnlyMutator`                                                                              |

The patch does not modify the default behavior. When `--categories` is not provided, `wasm-mutate` still uses the complete original mutation pool.

---

# Building the patched version

Apply the patch:

```bash
cp wasm_mutate_patch/lib.rs \
   <wasm-tools>/crates/wasm-mutate/src/lib.rs

cp wasm_mutate_patch/codemotion.rs \
   <wasm-tools>/crates/wasm-mutate/src/mutators/codemotion.rs
```

Build:

```bash
cd <wasm-tools>

cargo test -p wasm-mutate

cargo build --release --bin wasm-tools


cd wasm_mutator_by_category_src

cargo build --release
```

After installation:

```bash
wasm-tools mutate --help
```

should display:

```text
--categories
```

If this option is missing, the binary is the original unpatched version.

---

# Requirements

## Python dependencies

The pipeline requires:

* `rapidfuzz`
* `numpy`
* `scipy`
* `networkx`

## WebAssembly tools

Available in `PATH` or a shared binary directory:

WABT:

* `wasm2wat`
* `wat2wasm`
* `wasm-validate`

Binaryen:

* `wasm-dis`
* `wasm-opt`

## Runtime and analysis tools

Required:

* Wasmtime or Wasmer for native execution;
* Node.js with `puppeteer` for browser-based measurements;
* SpecTec reference interpreter for semantic equivalence analysis.

Optional:

* Ghidra with WebAssembly support for deobfuscation analysis.

---

# Running mutation evaluation

The main entry point is:

```text
run_wasmmutate.py
```

For every `.wasm` binary found recursively under `--dataset`:

1. Original metrics are computed once and stored in a cache.

   The cache contains:

   * binary size;
   * indirect call count;
   * maximum nesting depth;
   * execution results;
   * browser execution information;
   * disassembly information;
   * deobfuscation metrics.

2. Mutation categories are applied using the wrapper:

```text
wasm_mutator_by_category
```

Example invocation:

```text
wasm_mutator_by_category \
    --input <file.wasm> \
    --categories <c1,c2,...> \
    --variants 1 \
    --stack-depth <depth> \
    --preserve-semantics true \
    --seed <seed> \
    --outdir <directory>
```

The generated binaries are then analyzed using the same metrics as the original file.

---

# Execution command

```bash
python3 run_wasmmutate.py \
    --dataset <path_to_dataset> \
    --outdir <output_directory> \
    --csv <metrics_csv> \
    --mutator <wasm_mutator_by_category_binary> \
    --browser-runner <path_to_browser_runner.js> \
    --node-path <node_modules_path> \
    --wabt-bin <WABT_directory> \
    --wasmer-bin <path_to_wasmer> \
    --variants <number_of_variants> \
    --preserve-semantics true \
    --tmp-root <local_scratch_directory> \
    --cores <number_of_workers>
```

For Wasmtime:

```bash
--wasmtime-bin <path_to_wasmtime>
```

can be used instead of:

```bash
--wasmer-bin
```

---

# Semantic preservation option

The pipeline enables:

```text
--preserve-semantics true
```

by default.

This restricts mutations to transformations that preserve module behavior according to `wasm-mutate`'s semantic checks.

The default `wasm-mutate` CLI behavior is different:

```text
--preserve-semantics=false
```

because the tool is mainly designed for fuzzing and bug discovery.

For obfuscation evaluation, semantic preservation is enabled so that failed behavior preservation reflects limitations of the transformation rather than intentional corruption.

---

# Mutation design space

Seven mutation categories are evaluated:

| ID | Category             |
| -- | -------------------- |
| I1 | Add type             |
| I2 | Add function         |
| I3 | Edit custom sections |
| I4 | Peephole rewriting   |
| I5 | Dead-code removal    |
| I6 | Conditional swap     |
| I7 | Loop unrolling       |

The evaluated design space is the complete powerset:

```text
2^7 - 1 = 127 combinations
```

Each combination is executed with multiple random variants.

The default configuration uses:

```text
3 variants per combination
```

Each variant uses an independent random seed stored in the results.

The complete combination list is generated by:

```text
combos.py
```

Unlike some other obfuscation frameworks, no category dependency is enforced: each mutation category can be evaluated independently.

---

# Output structure

Generated binaries are stored as:

```text
<outdir>/<sample>/<sample>__<I-label>_v<N>_<hash>/

    <sample>_mut_<I-label>_v<N>.wasm

    mutator_stdout.log
    mutator_stderr.log

    browser_obf.json
```

Example:

```text
sample__I4+I7_v1_xxxxx/

    sample_mut_I4+I7_v1.wasm
```

---

# Metrics CSV

The CSV format follows the same schema as the WasMixer evaluation pipeline.

The main fields include:

```text
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

wat_similarity
cfg_similarity

deobfuscation_metrics

notes
obf_time
```

`obfuscation_transformation` stores the selected category names:

Example:

```text
peephole,loop-unrolling
```

`mutant_id` contains:

* category combination;
* variant number;
* generated hash.

---

# Runtime selection: Wasmer / Wasmtime

The runtime handling is identical to the other evaluation pipelines.

The script:

```text
wasm_runtime.py
```

automatically selects the execution command.

Wasmtime:

```text
wasmtime --invoke <function> <file.wasm> <args>
```

Wasmer:

```text
wasmer run <file.wasm> --invoke <function> -- <args>
```

When comparing both runtimes, use independent:

* output directories;
* CSV files;
* temporary directories.

Execution results depend on the selected runtime and must not share the original metrics cache.

---