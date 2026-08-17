#!/usr/bin/env python3
# cfg_similarity.py


import numpy as np
from scipy.optimize import linear_sum_assignment

from cfg_from_wat import build_module_cfgs


def get_entry_node(G):
    candidates = [n for n in G.nodes if G.in_degree(n) == 0]
    if candidates:
        return candidates[0]
    return next(iter(G.nodes))


def node_signature(G, node, entry):
    try:
        import networkx as nx
        depth = nx.shortest_path_length(G, entry, node)
    except Exception:
        depth = -1  # unreachable from entry (rare, but obfuscation can create these)
    return (depth, G.in_degree(node), G.out_degree(node))


def collect_signatures(graphs):
    """Pool signatures from every function's CFG into one multiset."""
    sigs = []
    for _, G in graphs.items():
        entry = get_entry_node(G)
        for n in G.nodes:
            sigs.append(node_signature(G, n, entry))
    return sigs


def signature_set_similarity(sigs_a, sigs_b):
    """
    Optimal bipartite matching (Hungarian algorithm) between two multisets of
    (depth, in_deg, out_deg) signatures, minimizing total Euclidean distance.
    Returns a similarity score in [0, 100].
    """
    n, m = len(sigs_a), len(sigs_b)
    if n == 0 or m == 0:
        return None

    A = np.array(sigs_a, dtype=float)
    B = np.array(sigs_b, dtype=float)

    size = max(n, m)
    cost = np.full((size, size), 1e6)
    for i in range(n):
        cost[i, :m] = np.linalg.norm(B - A[i], axis=1)

    row_ind, col_ind = linear_sum_assignment(cost)

    real_dists = [cost[i, j] for i, j in zip(row_ind, col_ind) if i < n and j < m]
    n_unmatched = abs(n - m)

    if not real_dists:
        return 0.0

    max_dist = max(real_dists) if max(real_dists) > 0 else 1.0
    avg_norm_dist = sum(d / max_dist for d in real_dists) / len(real_dists)

    size_penalty = n_unmatched / size

    similarity = max(0.0, 1.0 - avg_norm_dist - size_penalty) * 100
    return round(similarity, 2)


def cfg_similarity_structural(wat_text_orig, wat_text_obf):
    """
    Full pipeline: parse both sides' wasm2wat text -> per-function CFGs ->
    pooled signatures -> optimal matching -> score in [0, 100], or None if
    either side has no parseable function.

    Takes WAT TEXT (not file paths) so callers can reuse text they already
    generated via wasm2wat elsewhere in the pipeline instead of invoking
    the tool a second time per comparison.
    """
    if not wat_text_orig or not wat_text_obf:
        return None

    graphs_orig = build_module_cfgs(wat_text_orig)
    graphs_obf = build_module_cfgs(wat_text_obf)
    if not graphs_orig or not graphs_obf:
        return None

    sigs_orig = collect_signatures(graphs_orig)
    sigs_obf = collect_signatures(graphs_obf)

    return signature_set_similarity(sigs_orig, sigs_obf)


if __name__ == "__main__":
    import sys
    from common import wasm2wat_text
    if len(sys.argv) != 3:
        print("Usage: python cfg_similarity.py <orig.wasm> <obf.wasm>")
        sys.exit(1)
    t1 = wasm2wat_text(sys.argv[1], "wasm2wat")
    t2 = wasm2wat_text(sys.argv[2], "wasm2wat")
    score = cfg_similarity_structural(t1, t2)
    print(f"CFG structural similarity: {score}")
