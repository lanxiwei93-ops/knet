# simple-graph SQL 库

这里存放从 `dpapathanasiou/simple-graph` 引入的 SQLite 图结构 SQL 库，供当前项目直接引用。

## 文件说明

- `schema.sql`：初始化 `nodes` 与 `edges` 两张表及索引
- `insert-node.sql`：插入节点
- `update-node.sql`：更新节点
- `delete-node.sql`：删除节点
- `insert-edge.sql`：插入边
- `update-edge.sql`：更新边
- `delete-edge.sql`：删除单条边
- `delete-edges.sql`：删除某节点相关边
- `delete-incoming-edges.sql`：删除入边
- `delete-outgoing-edges.sql`：删除出边
- `search-edges.sql`：查询边
- `search-edges-inbound.sql`：查询入边
- `search-edges-outbound.sql`：查询出边
- `search-node.template`：节点查询模板
- `search-where.template`：条件片段模板
- `traverse.template`：路径遍历模板

## 初始化示例

```powershell
New-Item -ItemType Directory -Path .\data -Force | Out-Null
powershell -ExecutionPolicy Bypass -File .\scripts\sqlite.ps1 .\data\graph.db ".read .\sql\simple-graph\schema.sql"
```

## 当前约定

项目后续如果要做 CRUD，统一优先引用 `sql/simple-graph` 下的 SQL 文件，而不是直接依赖 `crud/sql`。
