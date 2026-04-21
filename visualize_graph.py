from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from pyvis.network import Network

from graph_crud import GraphCrud


NETWORK_OPTIONS = """
const options = {
  "autoResize": true,
  "interaction": {
    "hover": true,
    "navigationButtons": true,
    "keyboard": true
  },
  "physics": {
    "enabled": true,
    "stabilization": {
      "enabled": true,
      "iterations": 200
    }
  },
  "edges": {
    "arrows": {
      "to": {
        "enabled": true
      }
    },
    "color": {
      "inherit": false
    },
    "font": {
      "align": "top"
    },
    "smooth": {
      "enabled": true,
      "type": "dynamic"
    }
  },
  "nodes": {
    "borderWidth": 1,
    "font": {
      "size": 16
    },
    "shape": "dot",
    "size": 18
  }
}
"""


def build_network(db_path: Path) -> Network:
    graph = GraphCrud(db_path)
    nodes = graph.list_nodes()
    edges = graph.list_edges()

    network = Network(
        height="820px",
        width="100%",
        directed=True,
        bgcolor="#ffffff",
        font_color="#1f2937",
        cdn_resources="remote",
    )
    network.set_options(NETWORK_OPTIONS)
    for node in nodes:
        title = (
            f"id: {node['id']}<br>"
            f"name: {node['name']}<br>"
            f"data: <pre>{json.dumps(node, ensure_ascii=False, indent=2)}</pre>"
        )
        network.add_node(
            node["id"],
            label=node["name"],
            title=title,
            color="#60a5fa",
        )

    for edge in edges:
        label = str(edge["weight"])
        title = (
            f"source: {edge['source_id']}<br>"
            f"target: {edge['target_id']}<br>"
            f"weight: {edge['weight']}<br>"
            f"properties: <pre>{json.dumps(edge['properties'], ensure_ascii=False, indent=2)}</pre>"
        )
        network.add_edge(
            edge["source_id"],
            edge["target_id"],
            label=label,
            title=title,
            width=max(1, edge["weight"] + 1),
            color="#94a3b8",
        )

    return network


def remove_default_heading_blocks(output_path: Path) -> None:
    html = output_path.read_text(encoding="utf-8")
    html = re.sub(
        r"\s*<center>\s*<h1>\s*Stored Graph\s*</h1>\s*</center>\s*",
        "\n",
        html,
        flags=re.IGNORECASE,
    )
    output_path.write_text(html, encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the stored graph into a pyvis HTML page.")
    parser.add_argument(
        "--db-path",
        default=str(Path("data") / "graph.db"),
        help="SQLite database path. Default: data/graph.db",
    )
    parser.add_argument(
        "--output",
        default=str(Path("data") / "graph.html"),
        help="Output HTML path. Default: data/graph.html",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db_path).resolve()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    network = build_network(db_path)
    current_dir = Path.cwd()
    try:
        os.chdir(output_path.parent)
        network.write_html(output_path.name, open_browser=False, notebook=False)
    finally:
        os.chdir(current_dir)

    remove_default_heading_blocks(output_path)
    print(f"Graph HTML written to: {output_path}")


if __name__ == "__main__":
    main()
