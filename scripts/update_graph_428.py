from pathlib import Path
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(".")

from graph_crud import GraphCrud


DB_PATH = Path("data/graph.db")
TOPIC_ID = "T-428-列拆分提系数换列求行列式"
TOPIC_NAME = "列拆分提系数换列求行列式"
TOPIC_EXPRESSION = r"A=[\alpha_1,\alpha_2,\alpha_3],\ B=[\alpha_3,2\alpha_1+\alpha_2,3\alpha_2],\ |A|=2,\ 求|B|"

TARGETS = [
    "K-行列式对单列线性性",
    "K-单列乘常数行列式同乘",
    "K-两列成比例则行列式为0",
    "K-交换两列或两行行列式变号",
]


def cleanup_garbled_topic() -> None:
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            DELETE FROM edges
            WHERE source LIKE 'T-428-%?%' OR target LIKE 'T-428-%?%'
            """
        )
        connection.execute(
            """
            DELETE FROM nodes
            WHERE id LIKE 'T-428-%?%'
            """
        )


def main() -> None:
    cleanup_garbled_topic()
    g = GraphCrud(DB_PATH)

    try:
        print(
            g.add_node(
                TOPIC_ID,
                TOPIC_NAME,
                category="topic",
                expression=TOPIC_EXPRESSION,
            )
        )
    except ValueError as exc:
        print(exc)

    for target in TARGETS:
        try:
            print(g.add_edge(TOPIC_ID, target))
        except ValueError as exc:
            print(exc)

    for target in TARGETS:
        try:
            print(g.update_edge_weight_mtf(TOPIC_ID, target))
        except ValueError as exc:
            print(exc)


if __name__ == "__main__":
    main()
