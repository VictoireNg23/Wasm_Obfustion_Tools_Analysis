# SWAMPED CLI

CLI for applying 22 semantics-preserving perturbation methods to WebAssembly modules.

## Install

```bash
# Requires WABT (wasm2wat / wat2wasm) on PATH
brew install wabt        # macOS
apt install wabt         # Debian/Ubuntu

# Install swamped globally
pip install -e .
```

## Quick start

```bash
# List all 22 perturbation methods
swamped list

# Apply specific strategies
swamped obfuscate input.wasm -o output.wasm -s nop_insertion shift_transformation

# Apply all strategies at once
swamped obfuscate input.wasm -o output.wasm -s all

# Abort on first failure (useful in CI)
swamped obfuscate input.wasm -o output.wasm -s all --strict

# Combine seed + diff for reproducible experiments
swamped obfuscate input.wasm -o output.wasm -s all --seed 42 --diff -t
```

Accepts both `.wasm` and `.wast` as input/output — conversion is automatic.

## The 22 perturbation methods

### Structural perturbations (9)

| #   | Name                     | Description                                      |
| --- | ------------------------ | ------------------------------------------------ |
| 1   | `function_sig_insertion` | Inject unused function type signatures           |
| 2   | `import_insertion`       | Inject unused import declarations                |
| 3   | `function_insertion`     | Inject entire dummy function bodies              |
| 4   | `function_body_cloning`  | Clone functions with proxy redirection           |
| 5   | `global_insertion`       | Inject dummy global variables                    |
| 6   | `element_insertion`      | Inject table element entries                     |
| 7   | `export_insertion`       | Inject unused export declarations                |
| 8   | `data_insertion`         | Inject unused data segments                      |
| 9   | `data_encryption`        | XOR-encrypt data segments with runtime decryptor |

### Code-level perturbations (13)

| #   | Name                            | Description                                              |
| --- | ------------------------------- | -------------------------------------------------------- |
| 10  | `custom_section_insertion`      | Inject custom named sections _(not yet implemented)_     |
| 11  | `nop_insertion`                 | Insert NOP instructions                                  |
| 12  | `stack_op_insertion`            | Insert dummy stack operations (see sub-variants below)   |
| 13  | `opaque_predicate_insertion`    | Insert always-true/false Collatz-based predicates        |
| 14  | `proxy_function_insertion`      | Insert proxy wrapper functions _(not yet implemented)_   |
| 15  | `direct_to_indirect`            | Convert direct calls to indirect table calls             |
| 16  | `add_sub_transformation`        | Transform add/sub operations (a+b <-> a-(-b))            |
| 17  | `shift_transformation`          | Convert shifts to mul/div equivalents                    |
| 18  | `eqz_transformation`            | Rewrite eqz as comparison with zero                      |
| 19  | `offset_expansion`              | Decompose memory offset encoding                         |
| 20  | `mba_transformation`            | Replace XOR/OR with mixed boolean-arithmetic expressions |
| 21  | `constant_value_splitting`      | Split constants into arithmetic sums                     |
| 22  | `constant_value_transformation` | Replace constants with global variable reads             |

### Stack operation sub-variants (`--stackop`)

When using `stack_op_insertion`, you can select specific sub-variants with `--stackop`. If omitted, all 6 are applied.

| Flag | Description                    |
| ---- | ------------------------------ |
| `m`  | memory/local/global operations |
| `n`  | arithmetic operations          |
| `b`  | bitwise operations             |
| `c1` | type conversions (int/float)   |
| `c2` | floating-point conversions     |
| `f`  | float operations               |

Example: `swamped obfuscate input.wasm -o out.wasm -s stack_op_insertion --stackop m n b`

## Options

| Flag         | Default | Description                                                  |
| ------------ | ------- | ------------------------------------------------------------ |
| `-s`         | —       | Strategy names, or `all` / `structural` / `code`             |
| `-e`         | —       | Exclude strategies (useful with `all`/`structural`/`code`)   |
| `-o`         | —       | Output path (`.wasm` or `.wast`)                             |
| `--stackop`  | all     | Stack operation sub-variants: `m`, `n`, `b`, `c1`, `c2`, `f` |
| `--ratio`    | `1.0`   | Fraction of targets to perturb                               |
| `--alpha`    | `1.0`   | Beta-distribution alpha (target selection bias)              |
| `--beta`     | `1.0`   | Beta-distribution beta (target selection bias)               |
| `--validate` | off     | Run `wasm-validate` on the output                            |
| `--seed`     | —       | RNG seed for reproducible runs (see below)                   |
| `--diff`     | off     | Print a before/after summary of sections and instructions    |
| `--strict`   | off     | Abort immediately on the first strategy failure              |
| `-v`         | off     | Verbose (debug-level) logging                                |
| `-q`         | off     | Quiet mode — only print errors                               |

## Parameters

Defaults (`alpha=1, beta=1, ratio=1`) match the original project.

**`--ratio`** controls how much gets perturbed:

- `1.0` = everything (default), `0.5` = half, `0.1` = light

**`--alpha`** and **`--beta`** shape a [Beta distribution](https://en.wikipedia.org/wiki/Beta_distribution) that determines _where_ perturbations are applied within each function or section. Instead of picking targets purely at random, these parameters let you bias selection toward specific regions of the instruction sequence:

- `alpha=1, beta=1` — uniform distribution, all positions equally likely (default)
- `alpha=1, beta=3` — skewed toward the beginning (early instructions are more likely to be perturbed)
- `alpha=3, beta=1` — skewed toward the end (later instructions are more likely to be perturbed)
- `alpha=2, beta=2` — bell-shaped, concentrates perturbations in the middle

If you just want to control how much gets changed, `--ratio` is enough. Use `--alpha`/`--beta` when you need finer control over the spatial distribution of perturbations.

**`--seed`** enables **reproducible runs**. Given the same input file, seed, and parameters, SWAMPED will produce the exact same output. This is useful for:

- **Research** — reproduce an experiment exactly and report the seed alongside results
- **Debugging** — if a run produces an invalid module, re-run with the same seed to investigate
- **Comparison** — test different strategy sets against the same input with identical perturbation distributions

```bash
swamped obfuscate input.wasm -o out.wasm -s all --seed 42
swamped obfuscate input.wasm -o out.wasm -s all --seed 42   # same output
```

Without `--seed`, every run uses a fresh unseeded RNG (non-deterministic).

## Preliminary tests

**Setup:** the `function_insertion` strategy requires a symlink `strategies/data/function_body.pkl` pointing to one of the precomputed pool files. Create it before running obfuscation:

```bash
ln -s function_body_tmp100.pkl strategies/data/function_body.pkl
```

> [!TIP]
> The CLI takes a snapshot of the section before each strategy. If a strategy crashes mid-execution, the section is automatically rolled back to its pre-strategy state, so partial modifications never corrupt the output.

> [!WARNING]
> **There are known issue on specific combos**
>
> - `function_insertion* + function_body_cloning`
>   - `function_insertion` creates functions with `header=''` (empty string) instead of the expected `[[line, tag], ...]` list (`structural_perturbation.py:113`). When `function_body_cloning` runs next on the same section, it tries to access `header[0][0]` on one of those functions (`structural_perturbation.py:184-185`), which crashes because you can't index into an empty string. The CLI rolls back the section on failure, so the output stays valid — but `function_body_cloning` is effectively skipped.
> - `data_encryption` — injected decryption function may have mismatched signatures on certain modules

> [!NOTE]
> Use `--validate` to catch failures, and `-e` to exclude problematic strategies:

```bash
swamped obfuscate input.wasm -o out.wasm -s structural -e data_encryption function_body_cloning --validate
```

## License

See [LICENSE](../LICENSE).
