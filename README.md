# WebAssembly Obfuscation Framework: WASMixer & Wasmutate & Swamped

This repository contains scripts and tools to run two WebAssembly obfuscators — **WASMixer**, **Wasmutate** and **Swamped**— on multiple WebAssembly datasets in an experimental context (research, benchmarking, robustness evaluation, etc.).

---

##  Repository Structure

```text
WebAssembly_Obfuscation_Tools/
├── WasMixer/
│   └── WASMixer-main/
│       ├── run_wasmtime_binaryen_btree_manticore.py
│       ├── run_wasmer_binaryen_btree_manticore.py
│       └── ... (other dataset scripts)
├── Wasmutate/
│   ├── Run_Wasmmutate_Wasmtime_Btree_Manticore.sh
│   ├── Run_Wasmmutate_Btree_Manticore_wasmer.sh
│   └── ... (other scripts)
├── Swamped/
│   ├── Run_Swamped_Wasmtime_Btree_Manticore.py
│   ├── Run_Swamped_wasmer_Btree_Manticore.py
│   └── ... (other scripts)
├── spectec/
│   ├── analyse_spectec.py
│   ├── 
│   └── ... (other scripts)
├── Dataset_officiel_wasm/
│   └── (8 datasets: Btree Manticore, GillianC, Programs, MineRay, Minos, Btree Programs, RealWorld Applications, BasicAlgorithm)
├── README.md

```
---

##  Objective

This project allows you to:

- obfuscate WebAssembly (.wasm) files using three Wasm obfuscators,

- evaluate different obfuscators and compare different execution engines (Wasmtime, Wasmer),

- analyze their robustness against reverse engineering.


---

## Supported Datasets

The WASMixer, Wasmutate and Swamped scripts support the following datasets:

1. Btree Manticore

2. GillianC

3. Programs

4. MineRay

5. Minos

6. Btree Programs

7. RealWorld Applications

8. BasicAlgorithm

---

## Installation – WASMixer
System Prerequisites

### System Prerequisites


sudo apt update
sudo apt install -y nodejs npm wabt binaryen


###  Install Emscripten

git clone https://github.com/emscripten-core/emsdk.git
cd emsdk
./emsdk install latest
./emsdk activate latest
source ./emsdk_env.sh


###  Install WASMixer
cd WasMixer/WASMixer-main
pip install -e .


### Verify Tools

which wasm-dis
which wasm2wat
which wasm-opt
which wasmer
which wasmtime

## Execution – WASMixer


### Example with Wasmtime on the Btree Manticore dataset:

python3 run_wasmixer_binaryen_btree_manticore.py \
  --dataset /path/to/dataset \
  --outdir /path/to/output \
  --wasmixer /path/to/WasMixer/WASMixer-main \
  --wabt-bin /usr/bin \
  --timeout 60 \
  --cores 70


### Example with Wasmer:

python3 run_wasmer_binaryen_btree_manticore.py \
  --dataset /path/to/dataset \
  --outdir /path/to/output \
  --wasmixer /path/to/WasMixer/WASMixer-main \
  --wabt-bin /usr/bin \
  --timeout 60 \
  --cores 70


Des scripts similaires existent pour chaque dataset.


## Installation – Wasmutate

### Install Rust and Cargo

curl https://sh.rustup.rs -sSf | bash
source ~/.cargo/env 

### Install wasm-tools

cargo install wasm-tools
 
### Install Wasmtime

curl https://wasmtime.dev/install.sh -sSf | bash
export PATH="$HOME/.wasmtime/bin:$PATH"
echo 'export PATH="$HOME/.wasmtime/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc


### Install Wasmtime

curl https://get.wasmer.io -sSfL | sh
source ~/.bashrc


### Install WABT and Binaryen

sudo apt update
sudo apt install -y wabt binaryen


### Final Verification

which cargo
which wasm-tools
which wasm2wat
which wasm-opt
which wasmtime
which wasmer


## Execution – Wasmutate

### With Wasmtime:

bash Run_Wasmmutate_Wasmtime_Btree_Manticore.sh


### With Wasmer : 

bash Run_Wasmmutate_Btree_Manticore_wasmer.sh


## Execution – Swamped

### With Wasmtime & Wasmer :

python3  Run_Swamped_Wasmer_Btree_Manticore.py


## requirements_wasmixer.txt

rapidfuzz>=3.5.0

## requirements_wasmutate.txt

Rust, wasm-tools, wasmtime, wasmer, wabt, binaryen

## Author

Anonymous

=======
# Wasm_Obfuscator_2026
This repository contains scripts and tools to run three WebAssembly obfuscators — WASMixer, Swamped and Wasmutate


