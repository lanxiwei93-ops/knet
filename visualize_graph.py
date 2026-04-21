from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from pyvis.network import Network

from graph_crud import GraphCrud, resolve_db_name, resolve_db_number, resolve_db_path


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
        "--db-number",
        help="Database number from config.ini. Defaults to the [database].current value.",
    )
    parser.add_argument(
        "--db-path",
        help="SQLite database path override. When set, it takes precedence over --db-number.",
    )
    parser.add_argument(
        "--output",
        help="Output HTML path. Default: data/graph.html",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected_db_number = args.db_number.strip() if args.db_number else None
    effective_db_number = resolve_db_number(selected_db_number)
    db_path = resolve_db_path(args.db_path or selected_db_number)
    output_value = args.output or str(Path("data") / "graph.html")
    output_path = Path(output_value).resolve()
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
    print(f"Database path: {db_path}")
    print(f"Database label: {resolve_db_name(effective_db_number)}")


if __name__ == "__main__":
    main()
