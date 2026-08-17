#!/usr/bin/env python3
# combos.py

STRATEGIES = [
    "function_sig_insertion", "import_insertion", "function_insertion", "function_body_cloning",
    "global_insertion", "element_insertion", "export_insertion", "data_insertion", "data_encryption",
    "nop_insertion", "stack_op_insertion", "opaque_predicate_insertion", "direct_to_indirect",
    "add_sub_transformation", "shift_transformation", "eqz_transformation", "offset_expansion",
    "mba_transformation", "constant_value_splitting", "constant_value_transformation",
]

# SWAMPED's own perturbation ratio ranges from 10% to 100% in increments of
# 10 (see paper, Section IV-A: "we generate 10 variants covering different
# ratios ranging from 10 to 100 in increments of 10"). Represented as
# strings with one decimal place to match your original script's "1.0"
# formatting convention for --ratio.
DEFAULT_RATIOS = ["0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "1.0"]


def generate_combinations(strategies=None, ratios=None):
    """
    Returns a list of (strategy, ratio) tuples, ordered strategy-major
    then ratio-ascending (so all ratios of one strategy are grouped
    together in the CSV, easier to eyeball a strategy's ratio sweep).
    """
    strategies = strategies or STRATEGIES
    ratios = ratios or DEFAULT_RATIOS
    return [(s, r) for s in strategies for r in ratios]


def combo_label(strategy, ratio):
    """Internal label for folder/mutant_id naming -- 'nop_insertion_r0.5'."""
    return f"{strategy}_r{ratio}"


if __name__ == "__main__":
    combos = generate_combinations()
    print(f"Total (strategy, ratio) combinations: {len(combos)} "
          f"({len(STRATEGIES)} strategies x {len(DEFAULT_RATIOS)} ratios)")
    for s, r in combos[:15]:
        print(f"  {combo_label(s, r):40s} -> -s {s} --ratio {r}")
    print("  ...")
