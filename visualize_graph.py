from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from pyvis.network import Network

from graph_crud import (
    GraphCrud,
    REVIEW_FIELD_INTERVAL,
    REVIEW_FIELD_LATEST,
    resolve_db_name,
    resolve_db_number,
    resolve_db_path,
    sm2_interval_days,
)


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


# Public CDN images used as rank tier illustrations. The list is intentionally
# generic (Wikipedia / Wikimedia commons URLs) so the page degrades gracefully
# if any individual asset becomes unavailable.
RANK_TIERS = [
    {
        "name": "Bronze",
        "min_score": 0,
        "max_score": 2999,
        "color": "#a16a3c",
        "image": "https://upload.wikimedia.org/wikipedia/commons/thumb/5/52/Bronze_medal_icon.svg/120px-Bronze_medal_icon.svg.png",
        "comment": "Foundations being laid. Keep showing up - every reviewed node compounds.",
    },
    {
        "name": "Silver",
        "min_score": 3000,
        "max_score": 5999,
        "color": "#94a3b8",
        "image": "https://upload.wikimedia.org/wikipedia/commons/thumb/5/56/Silver_medal_icon.svg/120px-Silver_medal_icon.svg.png",
        "comment": "Solid progress. Recurring concepts are starting to feel familiar.",
    },
    {
        "name": "Gold",
        "min_score": 6000,
        "max_score": 11199,
        "color": "#facc15",
        "image": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/40/Gold_medal_icon.svg/120px-Gold_medal_icon.svg.png",
        "comment": "Strong command of the core graph. Spend cycles on weak edges.",
    },
    {
        "name": "Platinum",
        "min_score": 11200,
        "max_score": 15999,
        "color": "#22d3ee",
        "image": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/24/Platinum_medal_icon.svg/120px-Platinum_medal_icon.svg.png",
        "comment": "Most knowledge points are in long-term memory. Push the rare ones.",
    },
    {
        "name": "Diamond",
        "min_score": 16000,
        "max_score": 23999,
        "color": "#60a5fa",
        "image": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8e/Diamond_award.svg/120px-Diamond_award.svg.png",
        "comment": "Mastery territory. Maintain by hunting down any blurred entries.",
    },
    {
        "name": "King",
        "min_score": 24000,
        "max_score": None,
        "color": "#f472b6",
        "image": "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b6/Crown_of_Italy.svg/120px-Crown_of_Italy.svg.png",
        "comment": "King tier. The graph is yours - keep the throne by reviewing on cadence.",
    },
]


def parse_iso(value: str | None) -> float | None:
    """Parse an ISO8601 string into POSIX seconds; return None on failure."""
    if not value:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError):
        return None


def is_due(latest: str | None, interval_n: int, now_ts: float) -> bool:
    parsed = parse_iso(latest)
    if parsed is None:
        return True
    try:
        n = int(interval_n)
    except (TypeError, ValueError):
        return True
    if n <= 0:
        return True
    days = sm2_interval_days(n)
    return now_ts >= parsed + days * 86400


def node_score(interval_n: int) -> int:
    try:
        n = int(interval_n)
    except (TypeError, ValueError):
        return 0
    if n <= 0:
        return 0
    return n * 5 + n * n


def classify_node_type(node_id: str) -> str:
    """Return ``T`` for entry/题目 nodes, ``K`` for knowledge nodes."""
    if node_id.startswith("T-") or node_id.startswith("T_"):
        return "T"
    return "K"


def select_tier(score: int) -> dict:
    for tier in RANK_TIERS:
        upper = tier["max_score"]
        if upper is None or score <= upper:
            if score >= tier["min_score"]:
                return tier
    return RANK_TIERS[-1]


def build_network(db_path: Path, now_ts: float) -> tuple[Network, dict]:
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

    color_due = "#ef4444"   # red
    color_fresh = "#22c55e"  # green

    total_t = total_k = 0
    reviewed_t = reviewed_k = 0
    total_edges = len(edges)
    reviewed_edges = 0
    total_score = 0

    for node in nodes:
        latest = node.get(REVIEW_FIELD_LATEST, "")
        interval_n = node.get(REVIEW_FIELD_INTERVAL, 0) or 0
        due = is_due(latest, interval_n, now_ts)
        kind = classify_node_type(node["id"])
        if kind == "T":
            total_t += 1
            if not due:
                reviewed_t += 1
        else:
            total_k += 1
            if not due:
                reviewed_k += 1
        total_score += node_score(interval_n)

        title = (
            f"id: {node['id']}<br>"
            f"name: {node['name']}<br>"
            f"type: {kind}<br>"
            f"{REVIEW_FIELD_LATEST}: {latest or '(empty)'}<br>"
            f"{REVIEW_FIELD_INTERVAL} (n): {interval_n}<br>"
            f"data: <pre>{json.dumps(node, ensure_ascii=False, indent=2)}</pre>"
        )
        network.add_node(
            node["id"],
            label=node["name"],
            title=title,
            color=color_due if due else color_fresh,
        )

    for edge in edges:
        properties = edge.get("properties", {})
        latest = properties.get(REVIEW_FIELD_LATEST, "")
        interval_n = properties.get(REVIEW_FIELD_INTERVAL, 0) or 0
        due = is_due(latest, interval_n, now_ts)
        if not due:
            reviewed_edges += 1
        label = str(edge["weight"])
        title = (
            f"source: {edge['source_id']}<br>"
            f"target: {edge['target_id']}<br>"
            f"weight: {edge['weight']}<br>"
            f"{REVIEW_FIELD_LATEST}: {latest or '(empty)'}<br>"
            f"{REVIEW_FIELD_INTERVAL} (n): {interval_n}<br>"
            f"properties: <pre>{json.dumps(properties, ensure_ascii=False, indent=2)}</pre>"
        )
        network.add_edge(
            edge["source_id"],
            edge["target_id"],
            label=label,
            title=title,
            width=max(1, edge["weight"] + 1),
            color=color_due if due else color_fresh,
        )

    summary = {
        "total_t": total_t,
        "reviewed_t": reviewed_t,
        "total_k": total_k,
        "reviewed_k": reviewed_k,
        "total_edges": total_edges,
        "reviewed_edges": reviewed_edges,
        "total_score": total_score,
    }
    return network, summary


def build_dashboard_html(summary: dict, db_label: str, db_path: Path) -> str:
    total_nodes = summary["total_t"] + summary["total_k"]
    reviewed_nodes = summary["reviewed_t"] + summary["reviewed_k"]
    total_all = total_nodes + summary["total_edges"]
    reviewed_all = reviewed_nodes + summary["reviewed_edges"]
    score = summary["total_score"]
    tier = select_tier(score)

    return f"""
<style>
  .knet-bar {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #1f2937;
    padding: 6px 12px;
    border-bottom: 1px solid #e5e7eb;
    background: #f9fafb;
    font-size: 12px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 14px;
    line-height: 1.4;
  }}
  .knet-bar .sep {{ color: #d1d5db; }}
  .knet-bar b {{ color: #111827; }}
  .knet-bar .tier {{ color: {tier['color']}; font-weight: 600; }}
  .knet-bar img.tier-icon {{ width: 18px; height: 18px; vertical-align: middle; margin-right: 4px; }}
  .knet-bar .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; vertical-align: middle; margin-right: 3px; }}
  .knet-bar .dot.red {{ background: #ef4444; }}
  .knet-bar .dot.green {{ background: #22c55e; }}
</style>
<div class=\"knet-bar\">
  <span><b>{db_label}</b></span>
  <span class=\"sep\">|</span>
  <span><b>{reviewed_all}/{total_all}</b> reviewed (T {summary['reviewed_t']}/{summary['total_t']} &middot; K {summary['reviewed_k']}/{summary['total_k']} &middot; E {summary['reviewed_edges']}/{summary['total_edges']})</span>
  <span class=\"sep\">|</span>
  <span><img class=\"tier-icon\" src=\"{tier['image']}\" onerror=\"this.style.display='none'\" /><span class=\"tier\">{tier['name']}</span> {score} pts</span>
  <span class=\"sep\">|</span>
  <span><span class=\"dot red\"></span>due <span class=\"dot green\"></span>fresh</span>
</div>
""".strip()


def remove_default_heading_blocks(output_path: Path) -> None:
    html = output_path.read_text(encoding="utf-8")
    html = re.sub(
        r"\s*<center>\s*<h1>\s*Stored Graph\s*</h1>\s*</center>\s*",
        "\n",
        html,
        flags=re.IGNORECASE,
    )
    output_path.write_text(html, encoding="utf-8", newline="\n")


def inject_dashboard(output_path: Path, dashboard_html: str) -> None:
    html = output_path.read_text(encoding="utf-8")
    if "<body>" in html:
        html = html.replace("<body>", "<body>\n" + dashboard_html, 1)
    else:
        html = dashboard_html + html
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
    import time

    args = parse_args()
    selected_db_number = args.db_number.strip() if args.db_number else None
    effective_db_number = resolve_db_number(selected_db_number)
    db_path = resolve_db_path(args.db_path or selected_db_number)
    output_value = args.output or str(Path("data") / "graph.html")
    output_path = Path(output_value).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    now_ts = time.time()
    network, summary = build_network(db_path, now_ts)
    current_dir = Path.cwd()
    try:
        os.chdir(output_path.parent)
        network.write_html(output_path.name, open_browser=False, notebook=False)
    finally:
        os.chdir(current_dir)

    remove_default_heading_blocks(output_path)
    db_label = resolve_db_name(effective_db_number)
    dashboard_html = build_dashboard_html(summary, db_label, db_path)
    inject_dashboard(output_path, dashboard_html)
    print(f"Graph HTML written to: {output_path}")
    print(f"Database path: {db_path}")
    print(f"Database label: {db_label}")


if __name__ == "__main__":
    main()
