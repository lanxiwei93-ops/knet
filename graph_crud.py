from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class GraphCrud:
    """Small Python wrapper around the local simple-graph SQL library.

    Node bodies are stored as JSON objects with at least:
    - id
    - name

    Edge properties are stored as JSON objects and currently use:
    - weight

    The MTF update is modeled as "move to front" for a node's outbound edges:
    when (source_id, target_id) is touched, that edge receives the current
    maximum outbound weight for source_id plus one.
    """

    def __init__(self, db_path: str | Path, sql_dir: str | Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.sql_dir = Path(sql_dir) if sql_dir else Path(__file__).resolve().parent / "sql" / "simple-graph"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._schema_sql = self._read_sql("schema.sql")
        self._insert_node_sql = self._read_sql("insert-node.sql")
        self._insert_edge_sql = self._read_sql("insert-edge.sql")
        self._update_edge_sql = self._read_sql("update-edge.sql")
        self._delete_edge_sql = self._read_sql("delete-edge.sql")

        self.initialize()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(self._schema_sql)

    def list_nodes(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT body
                FROM nodes
                ORDER BY json_extract(body, '$.name') ASC, id ASC
                """
            ).fetchall()

        return [self._decode_node_row(row["body"]) for row in rows]

    def list_edges(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT source, target, properties
                FROM edges
                ORDER BY
                    source ASC,
                    COALESCE(CAST(json_extract(properties, '$.weight') AS INTEGER), 0) DESC,
                    target ASC
                """
            ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            properties = self._decode_json(row["properties"])
            result.append(
                {
                    "source_id": row["source"],
                    "target_id": row["target"],
                    "weight": int(properties.get("weight", 0)),
                    "properties": properties,
                }
            )

        return result

    def add_node(self, node_id: str, name: str, **extra: Any) -> dict[str, Any]:
        self._validate_required_text("node_id", node_id)
        self._validate_required_text("name", name)

        if "id" in extra or "name" in extra:
            raise ValueError("extra fields must not override id or name")

        payload = {"id": node_id, "name": name, **extra}

        with self._connect() as connection:
            existing = connection.execute("SELECT 1 FROM nodes WHERE id = ?", (node_id,)).fetchone()
            if existing:
                raise ValueError(f"node already exists: {node_id}")

            connection.execute(self._insert_node_sql, (json.dumps(payload, ensure_ascii=False),))

        return payload

    def add_edge(self, source_id: str, target_id: str) -> dict[str, Any]:
        self._validate_required_text("source_id", source_id)
        self._validate_required_text("target_id", target_id)

        with self._connect() as connection:
            self._require_node(connection, source_id)
            self._require_node(connection, target_id)

            existing = self._get_edge(connection, source_id, target_id)
            if existing:
                return existing

            payload = {"weight": 0}
            connection.execute(self._insert_edge_sql, (source_id, target_id, json.dumps(payload, ensure_ascii=False)))

        return {"source_id": source_id, "target_id": target_id, "weight": 0}

    def list_connected_nodes(self, source_id: str) -> list[dict[str, Any]]:
        self._validate_required_text("source_id", source_id)

        with self._connect() as connection:
            self._require_node(connection, source_id)

            rows = connection.execute(
                """
                SELECT
                    e.source,
                    e.target,
                    e.properties,
                    n.body AS target_body
                FROM edges AS e
                JOIN nodes AS n
                    ON n.id = e.target
                WHERE e.source = ?
                ORDER BY
                    COALESCE(CAST(json_extract(e.properties, '$.weight') AS INTEGER), 0) DESC,
                    json_extract(n.body, '$.name') ASC,
                    e.target ASC
                """,
                (source_id,),
            ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            properties = self._decode_json(row["properties"])
            node = self._decode_node_row(row["target_body"])
            result.append(
                {
                    "source_id": row["source"],
                    "target_id": row["target"],
                    "weight": int(properties.get("weight", 0)),
                    "id": node["id"],
                    "name": node["name"],
                    "data": node,
                }
            )

        return result

    def update_edge_weight_mtf(self, source_id: str, target_id: str) -> dict[str, Any]:
        self._validate_required_text("source_id", source_id)
        self._validate_required_text("target_id", target_id)

        with self._connect() as connection:
            self._require_node(connection, source_id)
            self._require_node(connection, target_id)

            current = self._get_edge(connection, source_id, target_id)
            if not current:
                raise ValueError(f"edge does not exist: {source_id} -> {target_id}")

            max_weight_row = connection.execute(
                """
                SELECT COALESCE(MAX(CAST(json_extract(properties, '$.weight') AS INTEGER)), -1) AS max_weight
                FROM edges
                WHERE source = ?
                """,
                (source_id,),
            ).fetchone()

            next_weight = int(max_weight_row["max_weight"]) + 1
            payload = current["properties"]
            payload["weight"] = next_weight

            connection.execute(
                self._update_edge_sql,
                (json.dumps(payload, ensure_ascii=False), source_id, target_id),
            )

        return {"source_id": source_id, "target_id": target_id, "weight": next_weight}

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _read_sql(self, filename: str) -> str:
        path = self.sql_dir / filename
        return path.read_text(encoding="utf-8")

    def _require_node(self, connection: sqlite3.Connection, node_id: str) -> None:
        row = connection.execute("SELECT 1 FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not row:
            raise ValueError(f"node does not exist: {node_id}")

    def _get_edge(self, connection: sqlite3.Connection, source_id: str, target_id: str) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT source, target, properties
            FROM edges
            WHERE source = ? AND target = ?
            ORDER BY rowid ASC
            LIMIT 1
            """,
            (source_id, target_id),
        ).fetchone()
        if not row:
            return None

        return {
            "source_id": row["source"],
            "target_id": row["target"],
            "properties": self._decode_json(row["properties"]),
        }

    def _decode_node_row(self, body: str) -> dict[str, Any]:
        data = self._decode_json(body)
        if "id" not in data or "name" not in data:
            raise ValueError("node body must contain id and name")
        return data

    @staticmethod
    def _decode_json(payload: str | None) -> dict[str, Any]:
        if not payload:
            return {}
        return json.loads(payload)

    @staticmethod
    def _validate_required_text(field_name: str, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")


__all__ = ["GraphCrud"]
