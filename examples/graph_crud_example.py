import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from graph_crud import GraphCrud


def main() -> None:
    db_path = PROJECT_ROOT / "data" / "example_graph.db"
    db_path.unlink(missing_ok=True)
    graph = GraphCrud(db_path)

    graph.add_node("node1", "Node 1")
    graph.add_node("node2", "Node 2")
    graph.add_node("node3", "Node 3")

    graph.add_edge("node1", "node2")
    graph.add_edge("node1", "node3")
    graph.update_edge_weight_mtf("node1", "node2")

    print("All nodes:")
    print(graph.list_nodes())

    print("Outbound neighbors from node1:")
    print(graph.list_connected_nodes("node1"))


if __name__ == "__main__":
    main()
