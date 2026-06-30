#!/usr/bin/env python3
# cfg_similarity.py
"""
Structural CFG similarity based on Binaryen's --print-cfg output.

Methodology:
- Extract the CFG of each function via `wasm-opt --print-cfg` (dot-style output).
- For every basic-block node, build a structural signature:
      (bfs_depth_from_entry, in_degree, out_degree)
  rather than comparing raw block labels/instructions.
- Pool all node signatures from the whole module (across all functions) into
  two multisets (orig vs obf) and find an optimal bipartite matching that
  minimizes the total signature distance (Hungarian algorithm).
- Convert the matching cost into a similarity score in [0, 100].

NOTE: wasm-opt's exact dot syntax can vary slightly between Binaryen
versions. Run `wasm-opt --print-cfg yourfile.wasm` once and confirm the
regexes in parse_cfg_dot() match your installed version's output before
trusting results at scale.
"""

import re
import subprocess
import numpy as np
import networkx as nx
from scipy.optimize import linear_sum_assignment


# ---------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------

def run_cmd(cmd, timeout_s=None):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, timeout=timeout_s)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -2, "", f"command not found: {cmd[0]}"


def get_cfg_dot(path, timeout_s=60):
    """Dump the per-function CFG of a wasm binary via Binaryen."""
    rc, out, err = run_cmd(["wasm-opt", "--print-cfg", str(path)], timeout_s)
    return out if rc == 0 else None


# ---------------------------------------------------------------------
# Parsing: dot-style CFG text -> {func_name: nx.DiGraph}
# ---------------------------------------------------------------------

FUNC_HEADER_RE = re.compile(r';;\s*function[: ]\s*(\S+)', re.IGNORECASE)
EDGE_RE = re.compile(r'"([^"]+)"\s*->\s*"([^"]+)"')
NODE_RE = re.compile(r'"([^"]+)"\s*\[')


def parse_cfg_dot(dot_text):
    """
    Parse Binaryen's --print-cfg dot output into one DiGraph per function.
    Falls back to a single 'module' graph if no per-function headers are found,
    so the script still works if your Binaryen version formats things differently.
    """
    graphs = {}
    current_func = "module"
    current_graph = nx.DiGraph()
    graphs[current_func] = current_graph
    saw_header = False

    for line in dot_text.splitlines():
        line = line.strip()

        m_func = FUNC_HEADER_RE.match(line)
        if m_func:
            saw_header = True
            current_func = m_func.group(1)
            current_graph = graphs.setdefault(current_func, nx.DiGraph())
            continue

        m_edge = EDGE_RE.search(line)
        if m_edge:
            a, b = m_edge.groups()
            current_graph.add_edge(a, b)
            continue

        m_node = NODE_RE.search(line)
        if m_node:
            current_graph.add_node(m_node.group(1))

    if not saw_header:
        # everything landed in the 'module' bucket; that's fine, it's just
        # treated as one big graph instead of per-function subgraphs.
        pass

    # drop empty graphs
    return {k: g for k, g in graphs.items() if g.number_of_nodes() > 0}


# ---------------------------------------------------------------------
# Structural signatures
# ---------------------------------------------------------------------

def get_entry_node(G):
    """Heuristic entry point: node with in-degree 0, else first inserted node."""
    candidates = [n for n in G.nodes if G.in_degree(n) == 0]
    if candidates:
        return candidates[0]
    return next(iter(G.nodes))


def node_signature(G, node, entry):
    """(bfs_depth_from_entry, in_degree, out_degree)."""
    try:
        depth = nx.shortest_path_length(G, entry, node)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
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


# ---------------------------------------------------------------------
# Matching-based similarity
# ---------------------------------------------------------------------

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
    # large finite penalty for padding rows/cols (unmatched nodes)
    cost = np.full((size, size), 1e6)
    for i in range(n):
        cost[i, :m] = np.linalg.norm(B - A[i], axis=1)

    row_ind, col_ind = linear_sum_assignment(cost)

    real_dists = [cost[i, j] for i, j in zip(row_ind, col_ind) if i < n and j < m]
    n_unmatched = abs(n - m)

    if not real_dists:
        return 0.0

    # normalize by the largest signature distance actually observed
    max_dist = max(real_dists) if max(real_dists) > 0 else 1.0
    avg_norm_dist = sum(d / max_dist for d in real_dists) / len(real_dists)

    # penalize unmatched (size-mismatched) nodes proportionally
    size_penalty = n_unmatched / size

    similarity = max(0.0, 1.0 - avg_norm_dist - size_penalty) * 100
    return round(similarity, 2)


def cfg_similarity_structural(path_orig, path_obf, timeout_s=60):
    """
    Full pipeline: extract -> parse -> signature -> match -> score.
    Returns a float in [0, 100], or None if extraction failed.
    """
    dot_orig = get_cfg_dot(path_orig, timeout_s)
    dot_obf = get_cfg_dot(path_obf, timeout_s)
    if not dot_orig or not dot_obf:
        return None

    graphs_orig = parse_cfg_dot(dot_orig)
    graphs_obf = parse_cfg_dot(dot_obf)
    if not graphs_orig or not graphs_obf:
        return None

    sigs_orig = collect_signatures(graphs_orig)
    sigs_obf = collect_signatures(graphs_obf)

    return signature_set_similarity(sigs_orig, sigs_obf)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python cfg_similarity.py <orig.wasm> <obf.wasm>")
        sys.exit(1)
    score = cfg_similarity_structural(sys.argv[1], sys.argv[2])
    print(f"CFG structural similarity: {score}")
