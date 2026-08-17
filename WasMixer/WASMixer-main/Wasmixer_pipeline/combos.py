#!/usr/bin/env python3
# combos.py

import itertools

FLAG = {
    "T1": "--name",
    "T2": "--memory",
    "T3": "--flatten",
    "T4": "--alias",
}

BASE_ORDER = ["T1", "T2", "T3", "T4"]  # canonical display order


def generate_combinations():
    """
    Returns a list of (combo_tuple, cli_flags) pairs, grouped by
    combination size (1, then 2, then 3, then 4, then 5 -- T5 counts
    towards the size like any other transformation).

    combo_tuple: e.g. ("T1", "T3", "T5")  -- always in canonical order,
                 T5 (if present) always last.
    cli_flags:   e.g. ["--name", "--flatten", "--cf", "--safe"]
    """
    base = BASE_ORDER
    combos = []
    for r in range(1, len(base) + 1):
        for c in itertools.combinations(base, r):
            combos.append(c)

    full = []
    for c in combos:
        flags = [FLAG[t] for t in c] + ["--safe"]
        full.append((c, flags))

        has_t3 = "T3" in c
        has_t4 = "T4" in c
        if has_t3 or has_t4:
            if has_t3 and has_t4:
                collatz_flag = "--collatz"
            elif has_t3:
                collatz_flag = "--cf"
            else:
                collatz_flag = "--ca"
            c5 = c + ("T5",)
            flags5 = [FLAG[t] for t in c] + [collatz_flag, "--safe"]
            full.append((c5, flags5))

    # Group by size: 4 individual transforms first, then all size-2 combos,
    # then size-3, size-4, size-5 -- T5 counts towards the size (e.g.
    # ("T3","T5") is size 2, right alongside ("T1","T2")).
    full.sort(key=lambda pair: (len(pair[0]), pair[0]))
    return full


def generate_combinations_grouped():
    """
    Same 27 combinations as generate_combinations(), but returned as an
    ordered dict {size: [(combo_tuple, cli_flags), ...]} for size in
    1..5 -- convenient when you want to process/display "individual
    transforms first, then pairs, then triples, ..." explicitly rather
    than just relying on sort order.
    """
    grouped = {1: [], 2: [], 3: [], 4: [], 5: []}
    for combo_tuple, cli_flags in generate_combinations():
        grouped[len(combo_tuple)].append((combo_tuple, cli_flags))
    return grouped


def combo_label(combo_tuple):
    """'T1+T3+T5' style label -- used internally for folder/mutant_id naming only."""
    return "+".join(combo_tuple)


def flags_label(cli_flags):
    """
    '--name --flatten --collatz' style label used in the CSV's
    obfuscation_transformation column (--safe stripped: it's a pipeline
    implementation detail, not an obfuscation transformation). This is
    the canonical key used for both the CSV column and resume matching,
    so the two never drift apart.
    """
    return " ".join(f for f in cli_flags if f != "--safe")


if __name__ == "__main__":
    grouped = generate_combinations_grouped()
    total = sum(len(v) for v in grouped.values())
    print(f"Total combinations: {total}\n")
    size_titles = {
        1: "Individual transformations",
        2: "Pairs",
        3: "Triples",
        4: "Quadruples",
        5: "All five (T1+T2+T3+T4+T5)",
    }
    for size in (1, 2, 3, 4, 5):
        combos = grouped[size]
        print(f"--- size {size}: {size_titles[size]} ({len(combos)}) ---")
        for c, flags in combos:
            print(f"  {combo_label(c):20s} -> {' '.join(flags)}")
        print()
