# 同步命令速查（run_sync.bat）

入口：`run_sync.bat` → `script/sync.py`  
报告：`reports/sync-report-*.txt` · 日志：`logs/sync-*.log`

---

## 通用参数


| 参数                         | 说明                                                                      |
| -------------------------- | ----------------------------------------------------------------------- |
| `--anchor-date YYYY-MM-DD` | 锚点日。不写时默认 **今天 − `DATA_DELAY_DAYS`**（常 3）                               |
| `--site SITE`              | 只跑该站（`config/sites.json` 的 `key`），可重复：`--site richconn --site fecision` |
| `--refresh`                | 看板 GSC **忽略本地缓存**，7 日窗口全量重拉                                             |
| `--test-mingdao-only`      | 仅测明道云连通，不写 GSC/Ahrefs                                                   |


当前默认站点（`.env` → `SYNC_SITES`）：`cncpioneer`、`fecision`、`richconn`、`lasermicrofab`（`drametal` 常排除）。

---

## 锚点日与窗口（跑前先看）


| 表                       | 写入日期范围                                        |
| ----------------------- | --------------------------------------------- |
| **SEO 自动数据看板**          | 锚点往前 **7 天**（`DASHBOARD_SYNC_DAYS`，默认 7），每天一行 |
| **GSC 查询流量 / GSC 页面流量** | 同上，7 日窗口                                      |
| **Ahrefs 站点有机词库**       | **仅锚点日** 1 快照                                 |
| **页面管理表**               | **仅锚点日** 1 快照                                 |
| **外链建设记录**              | 不依赖锚点日写数；备注里的 sync 日期为 **跑脚本当天**              |
| **Ahrefs 重点监控词 / RT 概览** | **仅锚点日** 1 快照                                 |


日志里的 `Sync window: … (7 days)` 是全局提示；只跑有机词库/页面表时 **实际只写锚点日**。

---

## 各表单独运行命令

将 `2026-05-30` 换成你的锚点日；需要单站时加 `--site 站名`。

### 1. SEO 自动数据看板（GSC 7 日 + 锚点日 Ahrefs 汇总）

全看板（自然点击、四档词数、Backlinks 变化、收录/异常、异常预警、本站 DR 等）：

```bat
run_sync.bat --skip-keywords --skip-pages --skip-gsc-top-queries --skip-gsc-top-pages --anchor-date 2026-05-30
```

仅更新看板 **GSC 四档搜索词数**（不跑其它看板列、不跑其它表）：

```bat
run_sync.bat --only-dashboard-gsc-buckets --anchor-date 2026-05-30
```

仅更新看板 **Backlinks变化**（锚点日一行，仅 Ahrefs，不拉 GSC、不覆盖其它列）：

```bat
run_sync.bat --only-dashboard-backlinks --anchor-date 2026-06-07
```

补 5.24–6.07 各日 Backlinks（五站、每天一行）需 **按日期多次跑**，每次 `--anchor-date` = 该行「日期」：

```bat
run_sync.bat --only-dashboard-backlinks --anchor-date 2026-05-24
run_sync.bat --only-dashboard-backlinks --anchor-date 2026-05-25
:: … 直至 2026-06-07
```

强制重拉看板 GSC 缓存：

```bat
run_sync.bat --skip-keywords --skip-pages --skip-gsc-top-queries --skip-gsc-top-pages --anchor-date 2026-05-30 --refresh
```

---

### 2. Ahrefs 站点有机词库

```bat
run_sync.bat --skip-pages --skip-dashboard --skip-gsc-top-queries --skip-gsc-top-pages --anchor-date 2026-05-30
```

单站示例：

```bat
run_sync.bat --skip-pages --skip-dashboard --skip-gsc-top-queries --skip-gsc-top-pages --anchor-date 2026-05-30 --site lasermicrofab
```

---

### 3. 页面管理表

```bat
run_sync.bat --skip-keywords --skip-dashboard --skip-gsc-top-queries --skip-gsc-top-pages --anchor-date 2026-05-30
```

单站（最慢，建议分站跑）：

```bat
run_sync.bat --skip-keywords --skip-dashboard --skip-gsc-top-queries --skip-gsc-top-pages --anchor-date 2026-05-30 --site cncpioneer
```

---

### 4. GSC 查询流量（全国家）

GSC 拉取 + 默认 **Ahrefs enrich**（Volume/KD/CPC）：

```bat
run_sync.bat --skip-keywords --skip-pages --skip-dashboard --skip-gsc-top-pages --anchor-date 2026-05-30
```

GSC 拉取，**跳过 enrich**：

```bat
run_sync.bat --skip-keywords --skip-pages --skip-dashboard --skip-gsc-top-pages --skip-gsc-top-queries-enrich --anchor-date 2026-05-30
```

**仅补 enrich**（不重拉 GSC，表里已有行才补）：

```bat
run_sync.bat --only-gsc-top-queries-enrich --anchor-date 2026-05-30
```

```bat
run_sync.bat --only-gsc-top-queries-enrich --anchor-date 2026-05-30 --site richconn
```

---

### 5. GSC 页面流量（全国家）

```bat
run_sync.bat --skip-keywords --skip-pages --skip-dashboard --skip-gsc-top-queries --skip-gsc-top-queries-enrich --anchor-date 2026-05-30
```

---

### 6. 外链建设记录

补 **日期 / 锚文本**（仅空列）；匹配备注（需配置 `MINGDAO_FIELD_LINK_REMARK`）：

```bat
run_sync.bat --only-link-building
```

指定锚点日（可选，Ahrefs 补数主要看 backlinks 本身）：

```bat
run_sync.bat --only-link-building --anchor-date 2026-05-30
```

全量 sync 时 **附带** 外链建设（不单独跑）：

```bat
run_sync.bat --with-link-building --anchor-date 2026-05-30
```

---

### 7. SEO 每日执行日志 · 8. 周绩效复盘

**脚本不写入**，无 `run_sync` 命令，明道云内手工维护。

---

## 全量与其它

默认全表（看板 + 有机词 + 页面 + GSC 两表 + enrich，**不含**外链建设）：

```bat
run_sync.bat --anchor-date 2026-05-30
```

全量 + 外链建设：

```bat
run_sync.bat --with-link-building --anchor-date 2026-05-30
```

仅测明道云 API：

```bat
run_sync.bat --test-mingdao-only
```

---

### 8. Ahrefs Rank Tracker（重点监控词 + 概览四档）

明细 + 概览（仅 Ahrefs，不拉 GSC）：

```bat
run_sync.bat --only-rank-tracker --anchor-date 2026-06-11
```

仅明细：

```bat
run_sync.bat --only-rank-tracker-keywords --anchor-date 2026-06-11
```

仅概览 Positions 四档（1-3 / 4-10 / 11-20 / 21-100）：

```bat
run_sync.bat --only-rank-tracker-overview --anchor-date 2026-06-11
```

单站示例：

```bat
run_sync.bat --only-rank-tracker --site lasermicrofab --anchor-date 2026-06-11
```

前置：`config/sites.json` → `rank_tracker_project_id`；`.env` → `MINGDAO_WORKSHEET_RT_*` / `MINGDAO_FIELD_RT_*`。

---

---

## 批量补历史（方案示例）

锚点 `2026-06-07`、需要 **8 日窗口** 时，先设环境变量再分表跑：

```bat
set DASHBOARD_SYNC_DAYS=8

:: 看板
run_sync.bat --skip-keywords --skip-pages --skip-gsc-top-queries --skip-gsc-top-pages --anchor-date 2026-06-07

:: GSC 查询 + enrich
run_sync.bat --skip-keywords --skip-pages --skip-dashboard --skip-gsc-top-pages --anchor-date 2026-06-07

:: GSC 页面
run_sync.bat --skip-keywords --skip-pages --skip-dashboard --skip-gsc-top-queries --skip-gsc-top-queries-enrich --anchor-date 2026-06-07

:: 有机词库（仅锚点日）
run_sync.bat --skip-pages --skip-dashboard --skip-gsc-top-queries --skip-gsc-top-pages --anchor-date 2026-06-07

:: 页面表（仅锚点日，最慢）
run_sync.bat --skip-keywords --skip-dashboard --skip-gsc-top-queries --skip-gsc-top-pages --anchor-date 2026-06-07
```

跑完后将 `DASHBOARD_SYNC_DAYS` 改回 `7`。

---

## 周更节奏建议


| 任务               | 建议命令                           |
| ---------------- | ------------------------------ |
| 看板 + GSC 两表（7 日） | 全量 skip 有机词+页面，或上表「看板 / GSC」三条 |
| 有机词库 + 页面表（锚点日）  | 有机词、页面两条命令，**同一锚点日各跑一次**       |
| 外链建设             | `--only-link-building`，随时补     |


---

## 参数互斥（勿组合）

- `--only-gsc-top-queries-enrich` 不能与 `--skip-gsc-top-queries` 同用
- `--only-dashboard-gsc-buckets` 不能与 `--skip-dashboard` 同用
- 任意两个 `--only-*` 不能同时开（含 `only-rank-tracker` / `only-rank-tracker-keywords` / `only-rank-tracker-overview`）

---

字段与表结构详见 [dashboard.md](./dashboard.md)。