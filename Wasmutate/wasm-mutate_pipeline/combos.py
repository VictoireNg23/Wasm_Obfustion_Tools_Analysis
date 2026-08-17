#!/usr/bin/env python3
# combos.py
"""
Generates the I1-I7 category combinations for WasmMutate.

    I1 = Add type               -> add-type
    I2 = Add function            -> add-function
    I3 = Edit custom sections    -> edit-custom-sections
    I4 = Peephole rewriting      -> peephole
    I5 = Dead-code removal       -> dead-code-removal
    I6 = Conditional swap        -> conditional-swap
    I7 = Loop unrolling          -> loop-unrolling

"""

import itertools

CATEGORIES = [
    "add-type",              # I1
    "add-function",          # I2
    "edit-custom-sections",  # I3
    "peephole",               # I4
    "dead-code-removal",     # I5
    "conditional-swap",      # I6
    "loop-unrolling",        # I7
]

I_LABEL = {
    "add-type": "I1",
    "add-function": "I2",
    "edit-custom-sections": "I3",
    "peephole": "I4",
    "dead-code-removal": "I5",
    "conditional-swap": "I6",
    "loop-unrolling": "I7",
}


def generate_combinations(categories=None):
    """
    Returns a list of combo_tuple (e.g. ("peephole", "loop-unrolling")),
    grouped by size (1..7) ascending, then in canonical I1..I7 order
    within each size (not alphabetical -- e.g. add-type/I1 sorts before
    add-function/I2 despite "add-f" < "add-t" alphabetically).
    """
    cats = categories or CATEGORIES
    order = {c: i for i, c in enumerate(CATEGORIES)}
    combos = []
    n = len(cats)
    for r in range(1, n + 1):
        for c in itertools.combinations(cats, r):
            combos.append(c)
    combos.sort(key=lambda c: (len(c), [order[x] for x in c]))
    return combos


def combo_label(combo_tuple):
    """'I4+I7' style label -- internal, for folder/mutant_id naming only."""
    return "+".join(I_LABEL[c] for c in combo_tuple)


def categories_flag(combo_tuple):
    """'peephole,loop-unrolling' -- the actual --categories value, and
    what's written into the CSV's obfuscation_transformation column."""
    return ",".join(combo_tuple)


if __name__ == "__main__":
    combos = generate_combinations()
    print(f"Total combinations: {len(combos)}\n")
    by_size = {}
    for c in combos:
        by_size.setdefault(len(c), []).append(c)
    for size in sorted(by_size):
        print(f"--- size {size} ({len(by_size[size])}) ---")
        for c in by_size[size]:
            print(f"  {combo_label(c):20s} -> --categories {categories_flag(c)}")
        print()
