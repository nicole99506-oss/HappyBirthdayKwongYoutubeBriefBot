"""Render a knowledge tree (JSON) into a PNG mind map with graphviz."""
import json
import os
import textwrap

import graphviz

from . import config

PALETTE = ["#0F6B5C", "#1D7A8C", "#8C5A1D", "#6B3FA0", "#A03F5A", "#3F6BA0", "#5A8C1D"]
INK = "#12221E"
PAPER = "#F4F3EC"


def tree_path(channel_id: str) -> str:
    return os.path.join(config.MINDMAP_DIR, f"{channel_id}.json")


def png_path(channel_id: str) -> str:
    return os.path.join(config.MINDMAP_DIR, f"{channel_id}.png")


def load_tree(channel_id: str) -> dict | None:
    p = tree_path(channel_id)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_tree(channel_id: str, tree: dict) -> None:
    os.makedirs(config.MINDMAP_DIR, exist_ok=True)
    with open(tree_path(channel_id), "w", encoding="utf-8") as f:
        json.dump(tree, f, ensure_ascii=False, indent=2)


def _wrap(label: str, width: int = 18) -> str:
    return "\n".join(textwrap.wrap(label, width)) or label


def render(channel_id: str, tree: dict) -> str:
    g = graphviz.Digraph(
        graph_attr={
            "rankdir": "LR", "bgcolor": PAPER, "splines": "curved",
            "nodesep": "0.25", "ranksep": "0.9", "pad": "0.4",
            "label": tree.get("name", ""), "labelloc": "t",
            "fontname": "Helvetica-Bold", "fontsize": "22", "fontcolor": INK,
        },
        node_attr={"fontname": "Helvetica", "fontcolor": "white", "style": "filled,rounded",
                   "shape": "box", "penwidth": "0", "margin": "0.15,0.08"},
        edge_attr={"arrowhead": "none", "penwidth": "1.6"},
    )
    root_id = "n0"
    g.node(root_id, _wrap(tree.get("name", "Channel"), 14),
           fillcolor=INK, fontsize="16", fontname="Helvetica-Bold")

    counter = [0]

    def add(node: dict, parent_id: str, depth: int, color: str):
        counter[0] += 1
        nid = f"n{counter[0]}"
        size = max(10, 14 - depth)
        fill = color if depth == 1 else _lighten(color, depth)
        g.node(nid, _wrap(str(node.get("name", "")), 18 + depth * 4),
               fillcolor=fill, fontsize=str(size),
               fontcolor="white" if depth <= 2 else INK)
        g.edge(parent_id, nid, color=color)
        for child in node.get("children", []) or []:
            add(child, nid, depth + 1, color)

    for i, child in enumerate(tree.get("children", []) or []):
        add(child, root_id, 1, PALETTE[i % len(PALETTE)])

    os.makedirs(config.MINDMAP_DIR, exist_ok=True)
    out = g.render(filename=channel_id, directory=config.MINDMAP_DIR,
                   format="png", cleanup=True)
    return out


def _lighten(hex_color: str, depth: int) -> str:
    """Blend the branch color toward paper as depth increases."""
    t = min(0.75, 0.28 * (depth - 1))
    c = hex_color.lstrip("#")
    p = PAPER.lstrip("#")
    mixed = "".join(
        f"{round(int(c[i:i+2], 16) * (1 - t) + int(p[i:i+2], 16) * t):02x}"
        for i in (0, 2, 4)
    )
    return f"#{mixed}"
