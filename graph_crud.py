from __future__ import annotations

import configparser
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REVIEW_FIELD_LATEST = "LatestReviewTime"
REVIEW_FIELD_INTERVAL = "Interval"
DEFAULT_NEW_NODE_INTERVAL_N = 0


def current_time_iso() -> str:
    """Return current local time as an ISO8601 string (seconds precision)."""
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def sm2_interval_days(n: int) -> int:
    """SM-2 style interval in days for level n.

    I0 = 0, I1 = 1, I2 = 3, I_n = I_{n-1} * 2 for n >= 3.
    Negative or non-integer n is treated as 0.
    """
    try:
        n = int(n)
    except (TypeError, ValueError):
        return 0
    if n <= 0:
        return 0
    if n == 1:
        return 1
    if n == 2:
        return 3
    value = 3
    for _ in range(n - 2):
        value *= 2
    return value


CONFIG_FILE_NAME = "config.ini"
DEFAULT_DB_SECTION = "database"
DEFAULT_DB_PATHS_SECTION = "database_paths"
DEFAULT_DB_NAMES_SECTION = "database_names"


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _load_config(config_path: str | Path | None = None) -> tuple[configparser.ConfigParser, Path]:
    resolved_config_path = Path(config_path) if config_path else _project_root() / CONFIG_FILE_NAME
    if not resolved_config_path.is_absolute():
        resolved_config_path = (_project_root() / resolved_config_path).resolve()

    parser = configparser.ConfigParser()
    if resolved_config_path.exists():
        parser.read(resolved_config_path, encoding="utf-8")

    return parser, resolved_config_path


def _is_path_like(db_selector: object) -> bool:
    if isinstance(db_selector, Path):
        return True
    if not isinstance(db_selector, str):
        return False

    candidate = db_selector.strip()
    if not candidate:
        return False

    return any(
        token in candidate
        for token in (
            "/",
            "\\",
            ".db",
            ".sqlite",
            ".sqlite3",
            ":",
        )
    )


def _normalize_db_number(db_selector: int | str | None, parser: configparser.ConfigParser) -> str:
    if db_selector is None:
        db_selector = parser.get(DEFAULT_DB_SECTION, "current", fallback="1")

    if isinstance(db_selector, int):
        db_number = str(db_selector)
    else:
        db_number = str(db_selector).strip()

    if not db_number.isdigit():
        raise ValueError(f"database selector must be a numeric id or a filesystem path: {db_selector}")

    return db_number


def resolve_db_path(
    db_selector: int | str | Path | None = None,
    *,
    config_path: str | Path | None = None,
) -> Path:
    parser, _ = _load_config(config_path)
    project_root = _project_root()

    if _is_path_like(db_selector):
        resolved_path = Path(str(db_selector))
        if not resolved_path.is_absolute():
            resolved_path = (project_root / resolved_path).resolve()
        return resolved_path

    db_number = _normalize_db_number(db_selector, parser)
    configured_path = parser.get(DEFAULT_DB_PATHS_SECTION, db_number, fallback="").strip()

    if configured_path:
        resolved_path = Path(configured_path)
    else:
        data_dir = parser.get(DEFAULT_DB_SECTION, "root", fallback="data").strip() or "data"
        filename_template = (
            parser.get(DEFAULT_DB_SECTION, "filename_template", fallback="graph_{db_number}.db").strip()
            or "graph_{db_number}.db"
        )
        resolved_path = Path(data_dir) / filename_template.format(db_number=db_number)

    if not resolved_path.is_absolute():
        resolved_path = (project_root / resolved_path).resolve()

    return resolved_path


def resolve_db_name(
    db_selector: int | str | None = None,
    *,
    config_path: str | Path | None = None,
) -> str:
    parser, _ = _load_config(config_path)
    db_number = _normalize_db_number(db_selector, parser)
    return parser.get(DEFAULT_DB_NAMES_SECTION, db_number, fallback=f"database_{db_number}").strip()


def resolve_db_number(
    db_selector: int | str | None = None,
    *,
    config_path: str | Path | None = None,
) -> str:
    parser, _ = _load_config(config_path)
    return _normalize_db_number(db_selector, parser)


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

    def __init__(
        self,
        db_path: int | str | Path | None = None,
        sql_dir: str | Path | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        _, resolved_config_path = _load_config(config_path)
        self.db_path = resolve_db_path(db_path, config_path=config_path)
        self.config_path = resolved_config_path
        self.sql_dir = Path(sql_dir) if sql_dir else Path(__file__).resolve().parent / "sql" / "simple-graph"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._schema_sql = self._read_sql("schema.sql")
        self._insert_node_sql = self._read_sql("insert-node.sql")
        self._insert_edge_sql = self._read_sql("insert-edge.sql")
        self._update_edge_sql = self._read_sql("update-edge.sql")
        self._delete_node_sql = self._read_sql("delete-node.sql")
        self._delete_edge_sql = self._read_sql("delete-edge.sql")
        self._delete_incoming_edges_sql = self._read_sql("delete-incoming-edges.sql")
        self._delete_outgoing_edges_sql = self._read_sql("delete-outgoing-edges.sql")

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

        payload = {"id": node_id, "name": name}
        # Default review fields: new node starts at n = 0, no review yet.
        payload[REVIEW_FIELD_LATEST] = ""
        payload[REVIEW_FIELD_INTERVAL] = DEFAULT_NEW_NODE_INTERVAL_N
        payload.update(extra)

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

            payload = {
                "weight": 0,
                REVIEW_FIELD_LATEST: "",
                REVIEW_FIELD_INTERVAL: DEFAULT_NEW_NODE_INTERVAL_N,
            }
            connection.execute(self._insert_edge_sql, (source_id, target_id, json.dumps(payload, ensure_ascii=False)))

        return {
            "source_id": source_id,
            "target_id": target_id,
            "weight": 0,
            REVIEW_FIELD_LATEST: "",
            REVIEW_FIELD_INTERVAL: DEFAULT_NEW_NODE_INTERVAL_N,
        }

    def delete_node(self, node_id: str) -> dict[str, Any]:
        self._validate_required_text("node_id", node_id)

        with self._connect() as connection:
            row = connection.execute("SELECT body FROM nodes WHERE id = ?", (node_id,)).fetchone()
            if not row:
                raise ValueError(f"node does not exist: {node_id}")

            connection.execute(self._delete_outgoing_edges_sql, (node_id,))
            connection.execute(self._delete_incoming_edges_sql, (node_id,))
            connection.execute(self._delete_node_sql, (node_id,))

        return self._decode_node_row(row["body"])

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

    def update_node_review(self, node_id: str, *, interval_n: int, latest_review_time: str | None = None) -> dict[str, Any]:
        """Update review fields on a node body.

        ``latest_review_time`` defaults to current local time. Pass an empty
        string to clear the timestamp (used by MarkUndo before n=0 reset).
        """
        self._validate_required_text("node_id", node_id)
        try:
            interval_n_int = int(interval_n)
        except (TypeError, ValueError) as exc:
            raise ValueError("interval_n must be an integer") from exc

        timestamp = current_time_iso() if latest_review_time is None else latest_review_time

        with self._connect() as connection:
            row = connection.execute("SELECT body FROM nodes WHERE id = ?", (node_id,)).fetchone()
            if not row:
                raise ValueError(f"node does not exist: {node_id}")
            body = self._decode_json(row["body"])
            body[REVIEW_FIELD_LATEST] = timestamp
            body[REVIEW_FIELD_INTERVAL] = interval_n_int
            connection.execute(
                "UPDATE nodes SET body = ? WHERE id = ?",
                (json.dumps(body, ensure_ascii=False), node_id),
            )

        return body

    def update_edge_review(
        self,
        source_id: str,
        target_id: str,
        *,
        interval_n: int,
        latest_review_time: str | None = None,
    ) -> dict[str, Any]:
        """Update review fields on an edge's properties JSON."""
        self._validate_required_text("source_id", source_id)
        self._validate_required_text("target_id", target_id)
        try:
            interval_n_int = int(interval_n)
        except (TypeError, ValueError) as exc:
            raise ValueError("interval_n must be an integer") from exc

        timestamp = current_time_iso() if latest_review_time is None else latest_review_time

        with self._connect() as connection:
            current = self._get_edge(connection, source_id, target_id)
            if not current:
                raise ValueError(f"edge does not exist: {source_id} -> {target_id}")
            payload = current["properties"]
            payload[REVIEW_FIELD_LATEST] = timestamp
            payload[REVIEW_FIELD_INTERVAL] = interval_n_int
            connection.execute(
                self._update_edge_sql,
                (json.dumps(payload, ensure_ascii=False), source_id, target_id),
            )

        return {
            "source_id": source_id,
            "target_id": target_id,
            "weight": int(payload.get("weight", 0)),
            REVIEW_FIELD_LATEST: timestamp,
            REVIEW_FIELD_INTERVAL: interval_n_int,
            "properties": payload,
        }

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT body FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not row:
            return None
        return self._decode_node_row(row["body"])

    def get_edge(self, source_id: str, target_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            current = self._get_edge(connection, source_id, target_id)
        if not current:
            return None
        properties = current["properties"]
        return {
            "source_id": current["source_id"],
            "target_id": current["target_id"],
            "weight": int(properties.get("weight", 0)),
            REVIEW_FIELD_LATEST: properties.get(REVIEW_FIELD_LATEST, ""),
            REVIEW_FIELD_INTERVAL: int(properties.get(REVIEW_FIELD_INTERVAL, 0) or 0),
            "properties": properties,
        }

    def backfill_review_fields(self, default_interval_n: int = DEFAULT_NEW_NODE_INTERVAL_N) -> dict[str, int]:
        """Ensure every node body and edge property has the two review fields.

        Missing fields are populated with default values; existing values are
        preserved. Returns counts of touched rows.
        """
        node_count = 0
        edge_count = 0
        with self._connect() as connection:
            for row in connection.execute("SELECT id, body FROM nodes").fetchall():
                body = self._decode_json(row["body"])
                changed = False
                if REVIEW_FIELD_LATEST not in body:
                    body[REVIEW_FIELD_LATEST] = ""
                    changed = True
                if REVIEW_FIELD_INTERVAL not in body:
                    body[REVIEW_FIELD_INTERVAL] = default_interval_n
                    changed = True
                if changed:
                    connection.execute(
                        "UPDATE nodes SET body = ? WHERE id = ?",
                        (json.dumps(body, ensure_ascii=False), row["id"]),
                    )
                    node_count += 1

            for row in connection.execute("SELECT source, target, properties FROM edges").fetchall():
                props = self._decode_json(row["properties"])
                changed = False
                if REVIEW_FIELD_LATEST not in props:
                    props[REVIEW_FIELD_LATEST] = ""
                    changed = True
                if REVIEW_FIELD_INTERVAL not in props:
                    props[REVIEW_FIELD_INTERVAL] = default_interval_n
                    changed = True
                if changed:
                    connection.execute(
                        self._update_edge_sql,
                        (json.dumps(props, ensure_ascii=False), row["source"], row["target"]),
                    )
                    edge_count += 1

        return {"nodes_updated": node_count, "edges_updated": edge_count}

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


__all__ = [
    "GraphCrud",
    "resolve_db_name",
    "resolve_db_number",
    "resolve_db_path",
    "current_time_iso",
    "sm2_interval_days",
    "REVIEW_FIELD_LATEST",
    "REVIEW_FIELD_INTERVAL",
    "DEFAULT_NEW_NODE_INTERVAL_N",
]
