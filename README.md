# WebAssembly Obfuscation Framework: WasMixer, wasm-mutate and SWAMPED

This repository contains the experimental framework used to evaluate three WebAssembly obfuscation and mutation approaches:

* **WasMixer**
* **wasm-mutate**
* **SWAMPED**

The framework provides scripts and analysis tools to apply transformations on WebAssembly (`.wasm`) binaries, measure their impact, and evaluate their robustness against analysis and reverse-engineering techniques.

The repository is designed for research experiments, benchmarking, and comparative evaluation of WebAssembly obfuscation techniques.

---

# Repository Structure

```
WebAssembly_Obfuscation_Tools/

├── WasMixer/
│   └── wasmixer_pipeline/
│       ├── run_wasmixer.py
│       ├── metrics_worker.py
│       ├── orig_metrics.py
│       ├── cfg_similarity.py
│       ├── cfg_from_wat.py
│       ├── deobfuscation_vulnerability.py
│       ├── wasm_runtime.py
│       ├── browser_runner.js
│       └── other analysis scripts

├── wasm-mutate/
│   └── wasmmutate_pipeline/
│       ├── run_wasmmutate.py
│       ├── metrics_worker.py
│       ├── orig_metrics.py
│       ├── cfg_similarity.py
│       ├── cfg_from_wat.py
│       ├── wasm_runtime.py
│       ├── wasm_mutate_patch/
│       └── other analysis scripts

├── SWAMPED/
│   └── swamped_pipeline/
│       ├── run_swamped.py
│       ├── metrics_worker.py
│       ├── pipeline_core.py
│       ├── orig_metrics.py
│       ├── cfg_similarity.py
│       ├── cfg_from_wat.py
│       ├── wasm_runtime.py
│       ├── browser_runner.js
│       └── other analysis scripts

├── spectec/
│   └── spectec_pipeline/
│       ├── spectec_common.py
│       ├── spectec_analysis_wasmixer.py
│       ├── spectec_analysis_wasmmutate.py
│       ├── spectec_analysis_swamped.py
│       └── wasm_runtime.py

├── Dataset_officiel_wasm/
│   └── WebAssembly datasets (.wasm files)

└── README.md
```

---

# Objectives

This framework allows you to:

* apply different WebAssembly obfuscation and mutation techniques;
* evaluate several transformation strategies on large collections of `.wasm` binaries;
* compare the impact of different execution engines:

  * Wasmtime;
  * Wasmer;
* measure structural modifications using:

  * WAT similarity;
  * CFG similarity;
  * binary-level metrics;
* evaluate behavioral preservation through runtime execution;
* analyze resistance against reverse-engineering and recovery tools;
* verify formal validity and semantic equivalence using SpecTec.

---

# Dataset

The framework operates on WebAssembly binaries (`.wasm`).

The dataset directory should contain WebAssembly modules used as input for the different evaluation pipelines.

Example:

```
Dataset_officiel_wasm/

├── sample1.wasm
├── sample2.wasm
├── sample3.wasm
└── ...
```

The same dataset format can be used with WasMixer, wasm-mutate, and SWAMPED.

---

# Common Requirements

## System dependencies

Install the required WebAssembly tools:

```bash
sudo apt update

sudo apt install -y \
    nodejs \
    npm \
    wabt \
    binaryen
```

Required tools:

* WABT:

  * `wasm2wat`
  * `wat2wasm`
  * `wasm-validate`

* Binaryen:

  * `wasm-dis`
  * `wasm-opt`

---

## Install Emscripten

Some datasets or preprocessing steps require WebAssembly compilation.

```bash
git clone https://github.com/emscripten-core/emsdk.git

cd emsdk

./emsdk install latest

./emsdk activate latest

source ./emsdk_env.sh
```

---

# WasMixer Pipeline

## Installation

Install WasMixer:

```bash
cd WasMixer/wasmixer_pipeline

pip install -e .
```

Install Python dependencies:

```bash
pip install rapidfuzz numpy scipy networkx matplotlib
```

Verify required tools:

```bash
which wasm-dis
which wasm2wat
which wasm-opt
which wasmer
which wasmtime
```

---

## Execution

Example using Wasmtime:

```bash
python3 run_wasmixer.py \
    --dataset /path/to/dataset \
    --outdir /path/to/output \
    --wasmixer /path/to/WasMixer \
    --wabt-bin /usr/bin \
    --timeout 1800 \
    --cores 200
```

Example using Wasmer:

```bash
python3 run_wasmixer.py \
    --dataset /path/to/dataset \
    --outdir /path/to/output \
    --wasmixer /path/to/WasMixer \
    --wasmer-bin /path/to/wasmer \
    --wabt-bin /usr/bin \
    --timeout 1800 \
    --cores 200
```

The pipeline automatically applies the selected WasMixer transformations and computes evaluation metrics.

---

# wasm-mutate Pipeline

## Installation

Install Rust:

```bash
curl https://sh.rustup.rs -sSf | bash

source ~/.cargo/env
```

Install WebAssembly tools:

```bash
cargo install wasm-tools
```

Install Wasmtime:

```bash
curl https://wasmtime.dev/install.sh -sSf | bash

export PATH="$HOME/.wasmtime/bin:$PATH"
```

Install Wasmer:

```bash
curl https://get.wasmer.io -sSfL | sh
```

Verify installation:

```bash
which cargo
which wasm-tools
which wasm2wat
which wasm-opt
which wasmtime
which wasmer
```

---

## Execution

Example:

```bash
python3 run_wasmmutate.py \
    --dataset /path/to/dataset \
    --outdir /path/to/output \
    --mutator /path/to/wasm_mutator_by_category \
    --wasmtime-bin /path/to/wasmtime \
    --cores 200
```

or:

```bash
python3 run_wasmmutate.py \
    --dataset /path/to/dataset \
    --outdir /path/to/output \
    --mutator /path/to/wasm_mutator_by_category \
    --wasmer-bin /path/to/wasmer \
    --cores 200
```

---

# SWAMPED Pipeline

## Installation

Install Python dependencies:

```bash
pip install rapidfuzz numpy scipy networkx matplotlib
```

Ensure that WABT, Binaryen, Wasmtime/Wasmer, and Node.js are available.

---

## Execution

Example:

```bash
python3 run_swamped.py \
    --dataset /path/to/dataset \
    --outdir /path/to/output \
    --swamped-cli /path/to/swamped_cli.py \
    --cores 200
```

The pipeline applies SWAMPED perturbation strategies and computes the corresponding structural and behavioral metrics.

---

# SpecTec Pipeline

The SpecTec pipeline is shared by all three evaluation frameworks.

It performs:

* formal WebAssembly validity checking;
* semantic equivalence analysis between original and transformed binaries.

The pipeline does not generate new obfuscated binaries. It enriches existing experiment results.

Directory:

```
spectec/
└── spectec_pipeline/
```

Available scripts:

```text
spectec_analysis_wasmixer.py
spectec_analysis_wasmmutate.py
spectec_analysis_swamped.py
```

Example:

```bash
python3 spectec_analysis_wasmixer.py \
    --dataset /path/to/dataset \
    --input-csv results.csv \
    --output-csv enriched_results.csv \
    --obf-dir /path/to/output \
    --spectec-bin /path/to/spectec
```

---

# Evaluation Metrics

The framework collects several categories of measurements:

## Structural metrics

* binary size;
* instruction-level changes;
* WAT similarity;
* CFG similarity;
* function and type information.

## Runtime metrics

* execution success;
* execution time;
* runtime compatibility;
* browser execution traces.

Supported runtimes:

* Wasmtime;
* Wasmer.

## Reverse-engineering metrics

* disassembly recovery;
* function recovery;
* deobfuscation analysis.

## Formal analysis

Using SpecTec:

* specification validity;
* semantic equivalence;
* interpreter errors.

---

# Reproducibility Notes

For large-scale experiments:

* use local storage instead of network filesystems mounted with `noexec`;
* keep generated binaries and temporary files on local disks;
* ensure that the same dataset paths are used between generation and analysis steps;
* keep the runtime configuration consistent when comparing Wasmtime and Wasmer.

---

# Author

Anonymous

# Wasm_Obfuscator_2026
