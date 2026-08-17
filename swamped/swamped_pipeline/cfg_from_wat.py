#!/usr/bin/env python3
# cfg_from_wat.py
"""
Builds a per-function control-flow graph directly from `wasm2wat` (WABT)
disassembly text.

Why this exists: `wasm-opt --print-cfg` (used by the original
cfg_similarity.py) is NOT a real Binaryen flag -- it does not exist in
mainline Binaryen (verified against the WebAssembly/binaryen source tree
and against wasm-opt 108, the version shipped by `apt install binaryen` on
Ubuntu 22.04: `wasm-opt --print-cfg` => "Unknown option '--print-cfg'").
That's why `cfg_similarity` was silently blank in every row: get_cfg_dot()
always failed, cfg_similarity_structural() always returned None.

This module reconstructs an equivalent CFG ourselves from WABT's flat
(non S-expression-folded) `wasm2wat` output, which is stable across
Binaryen/WABT versions and requires no unusual tool support:

    block  ;; label = @1
      ...
      br_if 0 (;@1;)
    loop  ;; label = @2
      ...
      br_if 0 (;@2;)
    end
    end

`block`/`loop`/`if` open a new frame and start a new basic block; `br` /
`br_if` / `br_table` target a *relative depth* (0 = innermost enclosing
frame) exactly like the WAT text already spells out; `end` closes the
innermost frame. loop targets branch back to the loop header (back-edge),
block/if targets branch forward to right after the matching `end`.

Known simplifications (documented, not hidden): multi-value block types
are not modelled beyond node identity; `br_table`'s default target and
all explicit targets are each given an edge; unreachable code after an
unconditional `br`/`return`/`unreachable` still gets a fresh (likely
in-degree-0) node rather than being dropped, which is fine for our
purpose since in/out-degree-0 nodes are a legitimate structural signal.
"""

import re
import networkx as nx

_FUNC_RE = re.compile(r'^\s*\(func\b')
_OPEN_RE = re.compile(r'^\s*(block|loop|if)\b')
_ELSE_RE = re.compile(r'^\s*else\b')
_END_RE = re.compile(r'^\s*end\b')
_BR_RE = re.compile(r'^\s*(br|br_if|br_table)\s+(.*)$')
_TERM_RE = re.compile(r'^\s*(return|unreachable)\b')


def _split_top_level_funcs(wat_text):
    """
    Yields the body lines (list[str]) of every top-level (func ...) form
    in flat (non-folded) wasm2wat output, using paren-depth tracking so
    nested nominal parens (e.g. in comments like `(;@1;)`) don't confuse
    the split.
    """
    lines = wat_text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _FUNC_RE.match(line):
            depth = line.count("(") - line.count(")")
            body = [line]
            i += 1
            while i < n and depth > 0:
                l = lines[i]
                depth += l.count("(") - l.count(")")
                body.append(l)
                i += 1
            yield body
        else:
            i += 1


def _relative_targets(rest_of_line):
    """Parses the target depth(s) out of a br/br_if/br_table operand list,
    ignoring the `(;@N;)` annotation comment WABT appends."""
    rest = re.sub(r'\(;.*?;\)', '', rest_of_line).strip()
    nums = re.findall(r'\d+', rest)
    return [int(x) for x in nums] if nums else [0]


def _new_bb(G, counter):
    bb = counter[0]
    counter[0] += 1
    G.add_node(bb)
    return bb


def build_function_cfg(func_lines):
    """
    Parses one (func ...) body (as produced by wasm2wat's flat output)
    into an nx.DiGraph of basic blocks.
    """
    G = nx.DiGraph()
    counter = [0]
    entry = _new_bb(G, counter)
    current = entry
    terminated = False  # True if `current` ends in an unconditional jump

    # frame: dict(kind='block'|'loop'|'if', header=bb, pending_exits=[bb,...],
    #             has_else=False)
    frames = []

    for raw in func_lines[1:]:  # skip the "(func ..." header line itself
        line = raw.strip()
        if not line or line in (")",):
            continue

        if _OPEN_RE.match(line):
            kind = line.split()[0]
            new_bb = _new_bb(G, counter)
            if not terminated:
                G.add_edge(current, new_bb)
            frames.append({"kind": kind, "header": new_bb, "pending_exits": [], "has_else": False})
            current = new_bb
            terminated = False
            continue

        if _ELSE_RE.match(line):
            if frames and frames[-1]["kind"] == "if":
                frame = frames[-1]
                if not terminated:
                    frame["pending_exits"].append(current)
                new_bb = _new_bb(G, counter)
                G.add_edge(frame["header"], new_bb)  # false-edge from the `if` header
                frame["has_else"] = True
                current = new_bb
                terminated = False
            continue

        if _END_RE.match(line):
            if not frames:
                continue  # malformed / top-level stray end, ignore defensively
            frame = frames.pop()
            exit_bb = _new_bb(G, counter)

            if not terminated:
                G.add_edge(current, exit_bb)
            for pending in frame["pending_exits"]:
                G.add_edge(pending, exit_bb)
            if frame["kind"] == "if" and not frame["has_else"]:
                G.add_edge(frame["header"], exit_bb)  # implicit false-edge, no else body

            current = exit_bb
            terminated = False
            continue

        m = _BR_RE.match(line)
        if m:
            instr, rest = m.group(1), m.group(2)
            targets = _relative_targets(rest)
            for depth in targets:
                if depth < len(frames):
                    target_frame = frames[-(depth + 1)]
                    if target_frame["kind"] == "loop":
                        G.add_edge(current, target_frame["header"])  # back-edge
                    else:
                        target_frame["pending_exits"].append(current)
                # depth >= len(frames): branches out of the function (rare/invalid), skip

            if instr in ("br", "br_table"):
                terminated = True
                new_bb = _new_bb(G, counter)  # holds any (unreachable) trailing code
                current = new_bb
            else:  # br_if: conditional, normal fallthrough continues
                new_bb = _new_bb(G, counter)
                G.add_edge(current, new_bb)
                current = new_bb
            continue

        if _TERM_RE.match(line):
            terminated = True
            new_bb = _new_bb(G, counter)
            current = new_bb
            continue

        # ordinary instruction: stays part of `current`, no graph change

    return G


def build_module_cfgs(wat_text):
    """Returns {func_index: nx.DiGraph} for every function in the module."""
    graphs = {}
    for idx, func_lines in enumerate(_split_top_level_funcs(wat_text)):
        g = build_function_cfg(func_lines)
        if g.number_of_nodes() > 0:
            graphs[idx] = g
    return graphs


if __name__ == "__main__":
    import sys
    text = open(sys.argv[1]).read() if len(sys.argv) > 1 else sys.stdin.read()
    graphs = build_module_cfgs(text)
    for idx, g in graphs.items():
        print(f"func {idx}: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")
        print("  edges:", list(g.edges()))
