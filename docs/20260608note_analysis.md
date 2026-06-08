# SEO 数据 Agent 分析方案

**文档日期**：2026-06-08  
**读者**：运营、技术、对接 Cursor Agent 的同事  
**背景**：`run_sync.bat` 已将 GSC / Ahrefs API 数据同步至明道云（页面管理表、GSC Top 查询/页面、关键词库等）。本文说明如何让 Agent 读取大量数据并产出可运营使用的分析结论。  
**相关文档**：`docs/dashboard.md`、`docs/20260608GSC_top-queries-update.md`、`.cursor_checkpoint.md`

---

## 核心思路

Agent **不适合**把明道云几千行原始数据全塞进对话。正确做法是：

**表格/API → 结构化快照 → 代码先聚合/筛选 → Agent 只分析「摘要 + 可下钻的小样本」**

现有 `script/sync.py` 已在写明道云；分析层只需再加一条「读回 + 导出 + 分析」链路。

---

## 三种实现路径（由简到强）

### 方案 A：快照文件 + Cursor Agent（最快落地，推荐先做）

```
run_sync.bat → 明道云
     ↓
export_snapshot.py（读 Mingdao API → parquet/csv）
     ↓
data/snapshots/2026-06-08/
  ├── pages_richconn.parquet
  ├── gsc_top_queries.parquet
  └── summary.json（预聚合指标）
     ↓
Cursor Agent：读文件 / 跑 analysis/*.py → 输出报告
```

**实现要点：**

- 复用现有 `MingdaoClient.list_all_rows`，按表导出
- 同步后自动跑 export（或在 `run_sync.bat` 末尾加一步）
- 写几个固定分析脚本（Python + pandas/duckdb），Agent 负责选脚本、解读结果、写运营语言

**Agent 怎么用：**

- 在 Cursor 里说：「读 `data/snapshots/latest/summary.json`，对比五站 GSC 点击 Top20，找出 Ahrefs 主关键词为空的重点页」
- Agent 跑 `python script/analyze_pages.py --site richconn --question "..."`

**优点：** 不依赖新平台；大量数据在本地，Agent 只看聚合结果  
**缺点：** 非实时（跟 sync 频率走）

---

### 方案 B：MCP 工具接明道云（Cursor 里「查表」）

给 Cursor 配一个 **Mingdao MCP Server**，暴露工具例如：

| 工具 | 作用 |
|------|------|
| `list_tables` | 页面表 / GSC Top 查询 / 关键词库 |
| `query_rows` | 按站点、日期、筛选条件分页读（limit 100） |
| `aggregate` | 服务端先算 sum/count/topN，只返回小结果 |

Agent 流程：先 `aggregate` 拿概览 → 再 `query_rows` 下钻异常行 → 写结论。

**优点：** 对话里直接查 live 数据  
**缺点：** 要写 MCP 服务；必须做 **分页 + 聚合**，否则 token 爆

---

### 方案 C：本地数仓 + SQL Agent（数据量大时最稳）

```
sync → 明道云
     ↓
export → DuckDB（单文件 data/seo.duckdb）
     ↓
Agent 工具：run_sql("SELECT ...")
     ↓
固定报告模板（markdown / 明道云写回）
```

DuckDB 可轻松处理万级行；Agent 只执行 SQL、看结果集（通常几十行）。

**适合：** 跨表 join（页面 × GSC Top 查询 × 关键词库）、趋势对比、五站横向排名。

---

## 分析层建议输出结构

不管用哪种工具，**分析脚本/Agent 应输出固定结构**，运营才好用：

```markdown
## 本周 SEO 摘要（锚点 2026-05-30）

### 1. 机会（GSC 有点击，Ahrefs 未覆盖）
- richconn /xxx — 展示 253，主关键词空 → 建议补内容/内链

### 2. 风险（收录异常 / 排名下滑）
- fecision 共 12 页未收录

### 3. 五站对比
| 站 | GSC 点击 | 有主关键词页数 | 未收录页 |

### 4. 建议动作（P0/P1）
```

Agent 的价值在 **解读 + 排优先级 + 写人话**，数值由代码/SQL 算好。

---

## 针对本项目的推荐组合

| 阶段 | 做什么 |
|------|--------|
| **第 1 步** | 加 `script/export_snapshot.py`，sync 后导出五张表到 `data/snapshots/{date}/` |
| **第 2 步** | 加 3～5 个分析脚本：页面机会、GSC Top 词 enrich 缺口、收录异常、五站对比 |
| **第 3 步** | Cursor 里用 Agent + `@data/snapshots` + 跑脚本；或写 `.cursor/rules` 固定分析 SOP |
| **第 4 步（可选）** | MCP 接 Mingdao，或 DuckDB 做跨表 SQL |

**不必一开始接 Agent 直读明道云 UI**——已有 API 和 `sync.py`，**本地快照 + 预聚合** 是成本最低、也最可控的路径。

---

## 一次典型 Agent 会话示例

```
你：分析 richconn 页面表，锚点 2026-05-30，找 GSC 展示>50 但主关键词为空的 URL

Agent：
1. 读 data/snapshots/2026-05-30/pages_richconn.parquet
2. 跑 filter + groupby
3. 输出 Top 20 列表 + 原因（top-pages 未命中 / URL 路径不一致）
4. 给运营 3 条可执行建议
```

---

## 其他可选工具

| 方式 | 适用场景 |
|------|----------|
| **明道云视图/统计** | 简单筛选够用，难做复杂跨表分析 |
| **Jupyter Notebook + Agent** | 探索性分析、一次性调研 |
| **n8n / 定时任务** | sync → export → 分析 → 发邮件或写明道云「分析报告」表 |
| **Metabase / Superset** | 连 DuckDB/Postgres，人工看板 + Agent 写解读 |

---

## 小结

让 Agent 分析大量 SEO 数据，关键是 **sync 后导出快照 + 代码先聚合，Agent 负责下钻和写报告**。现有 Python 栈加 `export_snapshot.py` 和几份分析脚本即可跑通。

**待实现（可选）：** `script/export_snapshot.py` + 「页面机会分析」示例脚本，作为 Agent 分析的标准入口。
