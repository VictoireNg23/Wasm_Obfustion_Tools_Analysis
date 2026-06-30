# SWAMPED (Systematic WebAssembly Module Perturbation Evaluation of Detectors)

SWAMPED systematically applies **22 types of binary-level transformations** while preserving the behavior of the original binary.

This framework is modular, extensible, and requires only standard Python dependencies and the WABT toolkit.

## Repository Structure

```bash
SWAMPED/
├── samples/                      # Input/output WASM binaries & text format files
├── strategies/
│   ├── data/                     # Templates and artifacts for perturbation
│   ├── code_perturbation.py     # Logic-level (instruction) perturbation
│   ├── structural_perturbation.py  # Structural (non-code) perturbation
│   └── state.py                 # Opcode list and distribution handler
├── wasmParser/
│   ├── parser.py                # Regex-based parser and perturbed wasm/wast writer
│   └── sectionStructure.py      # Section class definitions
└── perturb.ipynb                # Perturbation test script

```

---

## `samples/`

This directory contains `.wasm` and `.wast` files used for input/output testing.

> 🔧 When converting .wasm → .wast, always use:
> 

```bash
wasm2wat sample.wasm --generate-names -o sample.wast

```

---

## `wasmParser/`

### `parser.py`

- Uses regex to parse WebAssembly `.wast` text format
- Includes:
    - Section-level parsing
    - Utility to save perturbed '.wast' back to `.wasm`

### `sectionStructure.py`

- Defines each WebAssembly section as a Python class
- Provides structure for clean parsing & manipulation

---

## `strategies/`

Perturbation logic is implemented here as independent functions.

### `code_perturbation.py`

🔧 Code-level transformation:

- Applies logic-preserving rewrites to **instruction sequences**
- Focused on semantic equivalence while changing code layout

### `structural_perturbation.py`

🏗 Structural binary transformation:

- Modifies non-code components (e.g., types, function defs)
- Does **not** alter instruction logic

### `state.py`

- Stores opcode lists used for instruction-level perturbation
- Contains `getDist()` function to sample based on beta distribution

### `data/`

Artifacts used during perturbation:

- Function template snippets
- Additional section entries used to inject/replace content

---

## `perturb.ipynb` – Testing Notebook

Run perturbation examples from here.

Requires [`wabt`](https://github.com/WebAssembly/wabt) installed for:

```bash
wasm2wat   # with --generate-names
wat2wasm

```

---
