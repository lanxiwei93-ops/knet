"""Spaced-repetition review utilities backed by GraphCrud.

Algorithm: SM-2 style fixed schedule.

  I0 = 0 day
  I1 = 1 day
  I2 = 3 days
  In = I_{n-1} * 2  for n >= 3

The interval level ``n`` is stored on each node body / edge properties as
``Interval``; the most recent review timestamp is stored as
``LatestReviewTime``. A node/edge is considered "due" when

    LatestReviewTime + Interval(n) <= CurrentTime

or when either field is empty.

This module exposes four operations required by the review pipeline:

* ListReviewingKs / list_reviewing_ks - enumerate all due nodes and edges.
* MarkComplete / mark_complete       - increment n by 1 (I2, I3, I4, ...).
* MarkUndo     / mark_undo           - reset n to 0 (I0).
* MarkBlurred  / mark_blurred        - jump to n = 1 (I1).

Edges are addressed via (source_id, target_id) tuples; nodes via node id.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from graph_crud import (
    DEFAULT_NEW_NODE_INTERVAL_N,
    GraphCrud,
    REVIEW_FIELD_INTERVAL,
    REVIEW_FIELD_LATEST,
    current_time_iso,
    sm2_interval_days,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_due(latest: str | None, interval_n: int, now: datetime) -> bool:
    """Return True when this entry should be reviewed at ``now``."""
    parsed = _parse_iso(latest)
    if parsed is None:
        return True
    try:
        n = int(interval_n)
    except (TypeError, ValueError):
        return True
    if n <= 0:
        return True
    days = sm2_interval_days(n)
    due_at = parsed + timedelta(days=days)
    # Compare in the same naive/aware mode as ``parsed``.
    if parsed.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    elif parsed.tzinfo is not None and now.tzinfo is None:
        now = now.astimezone(parsed.tzinfo)
    return now >= due_at


def _now() -> datetime:
    return datetime.now().astimezone()


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------


class Review:
    """High-level review operations on top of :class:`GraphCrud`."""

    def __init__(self, graph: GraphCrud | None = None, db_path: int | str | Path | None = None) -> None:
        self.graph = graph if graph is not None else GraphCrud(db_path)

    # ---- listing --------------------------------------------------------

    def list_reviewing_ks(self) -> dict[str, list[dict[str, Any]]]:
        """List all nodes and edges that are currently due for review."""
        now = _now()

        due_nodes: list[dict[str, Any]] = []
        for node in self.graph.list_nodes():
            latest = node.get(REVIEW_FIELD_LATEST, "")
            interval_n = node.get(REVIEW_FIELD_INTERVAL, 0) or 0
            if _is_due(latest, interval_n, now):
                due_nodes.append(
                    {
                        "id": node["id"],
                        "name": node["name"],
                        REVIEW_FIELD_LATEST: latest,
                        REVIEW_FIELD_INTERVAL: int(interval_n) if str(interval_n).lstrip("-").isdigit() else 0,
                    }
                )

        due_edges: list[dict[str, Any]] = []
        for edge in self.graph.list_edges():
            props = edge.get("properties", {})
            latest = props.get(REVIEW_FIELD_LATEST, "")
            interval_n = props.get(REVIEW_FIELD_INTERVAL, 0) or 0
            if _is_due(latest, interval_n, now):
                due_edges.append(
                    {
                        "source_id": edge["source_id"],
                        "target_id": edge["target_id"],
                        "weight": edge["weight"],
                        REVIEW_FIELD_LATEST: latest,
                        REVIEW_FIELD_INTERVAL: int(interval_n) if str(interval_n).lstrip("-").isdigit() else 0,
                    }
                )

        return {"nodes": due_nodes, "edges": due_edges}

    # ---- mark operations -----------------------------------------------

    def mark_complete_node(self, node_id: str) -> dict[str, Any]:
        node = self.graph.get_node(node_id)
        if node is None:
            raise ValueError(f"node does not exist: {node_id}")
        current_n = int(node.get(REVIEW_FIELD_INTERVAL, 0) or 0)
        # MarkComplete advances to I2 the first time, then I3, I4, ...
        new_n = max(current_n + 1, 2)
        return self.graph.update_node_review(node_id, interval_n=new_n)

    def mark_undo_node(self, node_id: str) -> dict[str, Any]:
        node = self.graph.get_node(node_id)
        if node is None:
            raise ValueError(f"node does not exist: {node_id}")
        return self.graph.update_node_review(node_id, interval_n=0)

    def mark_blurred_node(self, node_id: str) -> dict[str, Any]:
        node = self.graph.get_node(node_id)
        if node is None:
            raise ValueError(f"node does not exist: {node_id}")
        return self.graph.update_node_review(node_id, interval_n=1)

    def mark_complete_edge(self, source_id: str, target_id: str) -> dict[str, Any]:
        edge = self.graph.get_edge(source_id, target_id)
        if edge is None:
            raise ValueError(f"edge does not exist: {source_id} -> {target_id}")
        current_n = int(edge.get(REVIEW_FIELD_INTERVAL, 0) or 0)
        new_n = max(current_n + 1, 2)
        return self.graph.update_edge_review(source_id, target_id, interval_n=new_n)

    def mark_undo_edge(self, source_id: str, target_id: str) -> dict[str, Any]:
        if self.graph.get_edge(source_id, target_id) is None:
            raise ValueError(f"edge does not exist: {source_id} -> {target_id}")
        return self.graph.update_edge_review(source_id, target_id, interval_n=0)

    def mark_blurred_edge(self, source_id: str, target_id: str) -> dict[str, Any]:
        if self.graph.get_edge(source_id, target_id) is None:
            raise ValueError(f"edge does not exist: {source_id} -> {target_id}")
        return self.graph.update_edge_review(source_id, target_id, interval_n=1)

    # ---- bulk helpers (mark a node together with its outgoing edges) ---

    def mark_complete(self, node_id: str, *, include_outgoing_edges: bool = True) -> dict[str, Any]:
        node = self.mark_complete_node(node_id)
        edges_updated: list[dict[str, Any]] = []
        if include_outgoing_edges:
            for edge in self.graph.list_edges():
                if edge["source_id"] == node_id:
                    edges_updated.append(self.mark_complete_edge(node_id, edge["target_id"]))
        return {"node": node, "edges": edges_updated}

    def mark_undo(self, node_id: str, *, include_outgoing_edges: bool = True) -> dict[str, Any]:
        node = self.mark_undo_node(node_id)
        edges_updated: list[dict[str, Any]] = []
        if include_outgoing_edges:
            for edge in self.graph.list_edges():
                if edge["source_id"] == node_id:
                    edges_updated.append(self.mark_undo_edge(node_id, edge["target_id"]))
        return {"node": node, "edges": edges_updated}

    def mark_blurred(self, node_id: str, *, include_outgoing_edges: bool = True) -> dict[str, Any]:
        node = self.mark_blurred_node(node_id)
        edges_updated: list[dict[str, Any]] = []
        if include_outgoing_edges:
            for edge in self.graph.list_edges():
                if edge["source_id"] == node_id:
                    edges_updated.append(self.mark_blurred_edge(node_id, edge["target_id"]))
        return {"node": node, "edges": edges_updated}


# ---------------------------------------------------------------------------
# Functional, snake_case wrappers
# ---------------------------------------------------------------------------


def list_reviewing_ks(db_path: int | str | Path | None = None) -> dict[str, list[dict[str, Any]]]:
    return Review(db_path=db_path).list_reviewing_ks()


def mark_complete(node_id: str, db_path: int | str | Path | None = None, *, include_outgoing_edges: bool = True) -> dict[str, Any]:
    return Review(db_path=db_path).mark_complete(node_id, include_outgoing_edges=include_outgoing_edges)


def mark_undo(node_id: str, db_path: int | str | Path | None = None, *, include_outgoing_edges: bool = True) -> dict[str, Any]:
    return Review(db_path=db_path).mark_undo(node_id, include_outgoing_edges=include_outgoing_edges)


def mark_blurred(node_id: str, db_path: int | str | Path | None = None, *, include_outgoing_edges: bool = True) -> dict[str, Any]:
    return Review(db_path=db_path).mark_blurred(node_id, include_outgoing_edges=include_outgoing_edges)


# CamelCase aliases mirroring the spec.
ListReviewingKs = list_reviewing_ks
MarkComplete = mark_complete
MarkUndo = mark_undo
MarkBlurred = mark_blurred


__all__ = [
    "Review",
    "list_reviewing_ks",
    "mark_complete",
    "mark_undo",
    "mark_blurred",
    "ListReviewingKs",
    "MarkComplete",
    "MarkUndo",
    "MarkBlurred",
    "sm2_interval_days",
]
