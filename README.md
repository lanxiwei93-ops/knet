# knet

## Conda 部署与引用

项目内统一使用 `tools/conda/conda.exe` 作为 Conda 入口，默认由 `D:/anaconda3/_conda.exe` 部署而来。

### 1. 部署 conda.exe

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy-conda.ps1
```

执行后会把 `D:/anaconda3/_conda.exe` 复制到：

```text
tools/conda/conda.exe
```

脚本会在复制后做 SHA256 校验，确保项目内文件与源文件一致。

### 2. 在项目中统一引用

后续脚本请优先通过下面这个入口调用：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\conda.ps1 --version
powershell -ExecutionPolicy Bypass -File .\scripts\conda.ps1 info
```

### 3. 自定义 Conda 路径

如果需要覆盖项目默认路径，可以设置环境变量 `KNET_CONDA_EXE`：

```powershell
$env:KNET_CONDA_EXE = "E:\knet\tools\conda\conda.exe"
powershell -ExecutionPolicy Bypass -File .\scripts\conda.ps1 env list
```

这样可以避免业务脚本直接硬编码 `D:/anaconda3/_conda.exe`，统一走项目入口。

## SQLite 部署与引用

项目内统一使用 `tools/sqlite/sqlite3.exe` 作为 SQLite 命令行入口，默认由 `D:/sqlite/sqlite3.exe` 部署而来。

### 1. 部署 sqlite3.exe

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy-sqlite.ps1
```

执行后会把 `D:/sqlite/sqlite3.exe` 复制到：

```text
tools/sqlite/sqlite3.exe
```

脚本会在复制后做 SHA256 校验，确保项目内文件与源文件一致。

### 2. 在项目中统一引用

后续脚本请优先通过下面这个入口调用：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\sqlite.ps1 -version
powershell -ExecutionPolicy Bypass -File .\scripts\sqlite.ps1 .\data\app.db ".tables"
```

### 3. 自定义 SQLite 路径

如果需要覆盖项目默认路径，可以设置环境变量 `KNET_SQLITE_EXE`：

```powershell
$env:KNET_SQLITE_EXE = "E:\knet\tools\sqlite\sqlite3.exe"
powershell -ExecutionPolicy Bypass -File .\scripts\sqlite.ps1 -version
```

这样可以避免业务脚本直接硬编码 `D:/sqlite/sqlite3.exe`，统一走项目入口。

## simple-graph SQL 库

从 `dpapathanasiou/simple-graph` 引入的 node / edge CRUD SQL 已并入项目目录：

```text
sql/simple-graph
```

主要文件包括：

- `schema.sql`
- `insert-node.sql`
- `update-node.sql`
- `delete-node.sql`
- `insert-edge.sql`
- `update-edge.sql`
- `delete-edge.sql`
- `search-edges.sql`
- `traverse.template`

初始化 SQLite 图库示例：

```powershell
New-Item -ItemType Directory -Path .\data -Force | Out-Null
powershell -ExecutionPolicy Bypass -File .\scripts\sqlite.ps1 .\data\graph.db ".read .\sql\simple-graph\schema.sql"
```

详细说明见 `sql/simple-graph/README.md`。

## Python 封装

项目根目录新增了一个 Python 封装：

```text
graph_crud.py
```

对外提供 `GraphCrud`，包含这几个操作：

- 列出所有节点：`list_nodes()`
- 增加一个指向：`add_edge(source_id, target_id)`
- 查询节点连接的所有节点，单向出边：`list_connected_nodes(source_id)`
- 按 MTF 更新边权重：`update_edge_weight_mtf(source_id, target_id)`
- 增加一个节点：`add_node(node_id, name, **extra)`

当前约定：

- 节点必须包含 `id` 和 `name`
- 边没有名称
- 边权重保存在 `properties.weight`
- MTF 采用 Move-To-Front 语义：访问一条出边时，把它的权重更新为当前最大出边权重加 1

示例见 `examples/graph_crud_example.py`。

## Pyvis 可视化

项目根目录新增了一个图可视化脚本：

```text
visualize_graph.py
```

它会读取 `data/graph.db`，生成一个可交互的 HTML 图页面。

默认命令：

```powershell
D:\anaconda3\python.exe .\visualize_graph.py
```

默认输出：

```text
data/graph.html
```

自定义数据库和输出文件：

```powershell
D:\anaconda3\python.exe .\visualize_graph.py --db-path .\data\graph.db --output .\data\graph.html
```

如果当前节点和边都为空，也会正常生成一个空白图界面。
