# SEO 数据看板 — 明道云字段方案（终稿）

> 本文档由 `need.docx` 与 `FIELD_SUGGESTIONS.md` 合并整理，并依据 **GSC / Ahrefs API 实际能力** 修订。  
> 目标平台：[明道云 HAP](https://www.mingdao.com/app)（替代原飞书多维表格）。  
> 单站示例：`https://www.cncpioneer.com/`（GSC 资源须与 `.env` 中 `GSC_SITE_URL` 一致）。

---

## 1.**明道云 API 参考：**

- [API 概览](https://help.mingdao.com/api/introduction/)
- [向工作表读写数据](https://help.mingdao.com/api/write-data-to-worksheet/)

---

**国家/范围列说明（§4 各表字段表共用）：**


| 标注                       | 含义                                                                                                |
| ------------------------ | ------------------------------------------------------------------------------------------------- |
| **全站**                   | 不分国家，整域汇总（GSC 全国家合计，或 Ahrefs 域名级）                                                                 |
| **按行国家**                 | 该行「国家」列所示 GSC 国家（ISO alpha-3 小写，如 `usa`）                                                          |
| **all**（默认）              | Ahrefs **全球市场/多国聚合**；`.env` → `AHREFS_TARGET_COUNTRY=all`（默认）；有机词合并见 `AHREFS_AGGREGATE_COUNTRIES` |
| **us**                   | 仅美国 Google 市场；`.env` 设为 `AHREFS_TARGET_COUNTRY=us` 时启用                                            |
| **all**（聚合说明）            | `organic-keywords` / `top-pages` 不传 `country` 或按 `metrics-by-country` 多国拉取后 **同词取最佳排名/流量**        |
| **all（enrich）**          | GSC 查询流量 Ahrefs 补数默认 **全部国家**；`.env` → `GSC_TOP_QUERIES_ENRICH_COUNTRIES` **留空**；填 `usa,gbr` 可限国  |
| **仅 lasermicrofab: usa** | 该站在 `config/sites.json` 设 `gsc_top_countries: ["usa"]`，GSC 查询/页面流量两表只写入美国行                        |


**同步频率建议：** 每周手动执行一次（与原 `run_sync.bat` 一致）；GSC 单日数据常有 1–3 天延迟，属正常现象。

---

## 3. API 能力边界（必读）

### 3.1 已确认可接入


| API                                         | 能力                                                                                      | 写入表                                    |
| ------------------------------------------- | --------------------------------------------------------------------------------------- | -------------------------------------- |
| GSC Search Analytics                        | 全站点击、展示、CTR、加权平均排名；**query 维四档搜索词计数**；单 URL 点击；7 天点击汇总；**Top queries / Top pages × 国家** | 看板、页面表、**GSC 查询流量（全国家）、GSC 页面流量（全国家）** |
| GSC URL Inspection                          | 单 URL 收录状态                                                                              | 页面表                                    |
| Ahrefs `organic-keywords`                   | 站点排名词、搜索量、KD、排名、7 日排名变化、落地页 URL                                                         | **Ahrefs 站点有机词库**（**不再写入看板四档**）        |
| Ahrefs `keywords-explorer/overview`         | 指定词的搜索量、KD（未进 organic 时补数）                                                              | 关键词表                                   |
| Ahrefs `refdomains-history`                 | 近 7 天 referring domains 净值变化                                                            | 看板                                     |
| Ahrefs `all-backlinks`                      | 按发文页 + 目标链匹配 **锚文本**、**首次发现日**（`first_seen_link` / `first_seen`）                        | **外链建设记录**（§4.4，仅补空列）                  |
| Ahrefs `domain-rating`                      | 全站域名 DR（页面表 **全球排名DR** + 看板本站 DR）                                                       | 页面管理表、看板                               |
| Ahrefs `top-pages`                          | 有机流量页 **URL 导入** + UR/流量/主词等                                                            | **页面管理表**                              |
| GSC Search Analytics（`page` 维）              | 单 URL 点击、展示、CTR、平均排名（**update 已存在行**）                                                   | **页面管理表**                              |
| Ahrefs `crawled-pages`                      | 按 URL 匹配：UR、**发布日期**（first_seen）等                                                       | **页面管理表**                              |
| Ahrefs `organic-keywords`（按落地页聚合）           | 该 URL Top keyword / Volume（脚本聚合兜底）                                                      | **页面管理表**                              |
| Ahrefs **Rank Tracker** `overview`          | 项目内 **重点监控词** 排名、流量、KD、URL、Location、Added 等                                             | **§4.9 明细表**                                  |
| Ahrefs **Rank Tracker** `competitors-stats` | 项目 **Positions** 分档词数（1-3 / 4-10 / 11-20 / 21-100）                                      | **§4.9 概览表**（待接脚本）                     |


**页面管理表明确不接：** GSC `page` 维 **批量发现 URL**（改由 Ahrefs `top-pages`）；全站分国家页面明细仍走 **§4.8 GSC 页面流量（全国家）**。页面表 **GSC 四指标 + 收录状态** 仍按已登记 URL 逐行更新。

### 3.2 GSC 查询/页面流量（全国家）— Top N 与 Ahrefs enrich

两表共用 **7 日同步窗口**（锚点 −6 … 锚点，与看板一致）；**每站、每表、每个日历日各调 1 次 GSC Search Analytics**，按 **点击降序** 取 Top N，**仅写入点击 > 0 的行**（0 点击丢弃，不占明道云行数）。


| 表                       | GSC 维度              | Top N（默认）      | 环境变量                    | 说明                                       |
| ----------------------- | ------------------- | -------------- | ----------------------- | ---------------------------------------- |
| **GSC 查询流量（全国家）**（§4.7） | `query` × `country` | **1000** 行/站/日 | `GSC_TOP_QUERIES_LIMIT` | GSC 按点击 Top 1000 拉取后，**只入库点击 > 0**；非全量词库 |
| **GSC 页面流量（全国家）**（§4.8） | `page` × `country`  | **1000** 行/站/日 | `GSC_TOP_PAGES_LIMIT`   | 同上，**只入库点击 > 0** 的 URL×国家                |


**国家范围：** 默认 **全部国家**（GSC 返回什么国写什么国）。某站若在 `config/sites.json` 设 `gsc_top_countries`（如 lasermicrofab 仅 `usa`），脚本只保留所列国家。

**量级估算（默认）：** 每站每轮写入行数 ≤ **7 × 1000**，实际通常更少（尾部 0 点击已过滤）。sync-report 有 `skip_zero_clicks` / `跳过0点击` 统计。

**Ahrefs enrich（仅 GSC 查询流量表）：** GSC 写入完成后自动执行 `enrich_gsc_top_queries`（可用 `--skip-gsc-top-queries-enrich` 跳过）。


| 项         | 当前策略（2026-06-10 起）                           | 环境变量                                                          |
| --------- | -------------------------------------------- | ------------------------------------------------------------- |
| **国家范围**  | **全部国家**（7 日窗口内表里有行的 query×country）          | `GSC_TOP_QUERIES_ENRICH_COUNTRIES` **留空**；填 `usa,gbr` 则仅这些国家  |
| **点击筛选**  | 7 日 **总点击 > 0** 才查 Ahrefs                    | `GSC_TOP_QUERIES_ENRICH_MODE=clicks_gt_zero`                  |
| **Top N** | 按 7 日总点击降序，最多 **500** 个不重复 **query×country** | `GSC_TOP_QUERIES_ENRICH_LIMIT=500`                            |
| **写入列**   | Ahrefs搜索量、Ahrefs KD、Ahrefs CPC               | `keywords-explorer/overview`；GSC 国码 → Ahrefs 国码（如 `usa`→`us`） |


**变更说明：** 此前 enrich 默认仅 **usa** 且有点击；现改为 **全部国家** 且有点击，便于多市场词看搜索量/KD/CPC。无 Ahrefs 国码映射的国家会在 sync-report **Warnings** 跳过；**伊朗（`irn`）** Ahrefs 不支持 overview，脚本 **静默跳过**（不请求 API）。

**常用命令：**

```bat
:: 全量（含 GSC Top 两表 + enrich）
run_sync.bat --anchor-date 2026-06-06

:: 仅补 Ahrefs 三列（不重拉 GSC）
run_sync.bat --only-gsc-top-queries-enrich --anchor-date 2026-06-06 --site richconn

:: 跳过 enrich
run_sync.bat --skip-gsc-top-queries-enrich --anchor-date 2026-06-06
```

---

## 4. 五模块 · 八工作表字段定义

### 4.1 表 1：SEO 自动数据看板

**用途：** 每日 SEO 健康度快照，**全部自动**，禁止人工改数。

**Upsert 键：** `日期` + `独立站`（每站每天一行；同步窗口默认 7 天即每站 7 行）

**写入节奏：**


| 类型             | 字段                                                    | 行为                                       |
| -------------- | ----------------------------------------------------- | ---------------------------------------- |
| **按日（GSC）**    | 自然点击、展示量、平均CTR、全站加权平均排名、**GSC Top1-3～Top21-100 搜索词数** | 同步窗口内每天一行；四档由 GSC `query` 维 **全国家合计** 聚合 |
| **按日（Ahrefs）** | **本站DR**                                              | 每天：`domain-rating`（`date` = 该行日期）        |
| **仅锚点日**       | Backlinks变化、异常预警                                      | 锚点日 Ahrefs/GSC 汇总，只写在锚点那一行               |


锚点日默认 `今天 − DATA_DELAY_DAYS`（常 3），也可用 `run_sync.bat --anchor-date 2026-05-30` 指定。看板四档 **不再调用** Ahrefs `organic-keywords`；每站每轮约 **7 次** GSC query 拉取（同步窗口内每天一次）。


| 字段名                    | 明道云类型 | 来源       | 国家/范围  | 说明                                                                                 |
| ---------------------- | ----- | -------- | ------ | ---------------------------------------------------------------------------------- |
| 日期                     | 日期    | 脚本       | —      | 数据所属日期（GSC 统计日，非脚本执行时刻）                                                            |
| 独立站                    | 单选    | 脚本       | —      | 站点 key，与 `config/sites.json` 一致                                                    |
| 自然点击                   | 数值    | GSC      | **全站** | **当日**全站自然搜索点击；GSC Search Analytics 无 `country` 维度，**全国家合计**                       |
| 展示量                    | 数值    | GSC      | **全站** | **当日**展示次数；**全国家合计**                                                               |
| 平均CTR                  | 数值    | GSC      | **全站** | **当日** CTR，0~1 小数（如 0.052 = 5.2%）；**全国家合计**                                        |
| 平均排名                   | 数值    | GSC      | **全站** | **当日**全站加权平均排名（GSC `position`）；**不是**核心词平均排名                                       |
| **GSC Top1-3 搜索词数**    | 数值    | GSC + 脚本 | **全站** | 当日 GSC query（**全国家合计**）中，**平均排名** 取整后落在 **1–3** 的搜索词个数；见下「四档搜索词数」；**每天一行**         |
| **GSC Top4-10 搜索词数**   | 数值    | GSC + 脚本 | **全站** | 同上，排名 **4–10**                                                                     |
| **GSC Top11-20 搜索词数**  | 数值    | GSC + 脚本 | **全站** | 同上，排名 **11–20**                                                                    |
| **GSC Top21-100 搜索词数** | 数值    | GSC + 脚本 | **全站** | 同上，排名 **21–100**；排名 >100 或无展示的 query 不计                                            |
| Backlinks变化            | 文本    | Ahrefs   | **全站** | 近 7 天 referring domains **净值**（`refdomains-history`）；写入带符号如 `+5` / `-3`；**仅锚点日一行** |
| 异常预警                   | 单选    | 脚本       | **全站** | 正常 / 流量下跌；由近 7 天 vs 再前 7 天 GSC 全站点击判定（**不写单独环比列**）；**仅锚点日一行**                      |
| 本站DR                   | 数值    | Ahrefs   | **全站** | 全站域名 Domain Rating（`domain-rating`，无国家）；**同步窗口内每天一行**                              |



|     |     |
| --- | --- |
|     |     |


- **统计对象：** GSC **搜索词（query）**；**全国家合计**（`dimensions: ["query"]`，不按 `country` 拆分）。
- **API：** 每个日历日 `startDate = endDate = 该行日期`，按 **点击降序** Top N（env `DASHBOARD_GSC_QUERY_LIMIT`，默认 **1000**）。
- **分档：** 每 query 的 GSC `**position`（平均排名）** 向下取整 → **1–3 / 4–10 / 11–20 / 21–100** 四档计数。
- **与关键词表区别：** 关键词表仍为 Ahrefs **有机词 + 美国市场**；看板四档为 GSC **有流量 query 子集 + 全国家**；**不可对数**。

**明道云视图建议：** 按「日期」降序；异常预警 ≠ 正常 时条件着色；四档列可加「GSC」前缀便于与关键词表区分。

**仅同步 GSC 四档搜索词数（不改其它看板列）：**

```bat
run_sync.bat --only-dashboard-gsc-buckets --anchor-date 2026-05-30

:: 单站
run_sync.bat --only-dashboard-gsc-buckets --site richconn --anchor-date 2026-05-30
```

**仅同步 Backlinks变化（锚点日一行，仅 Ahrefs，不改其它看板列）：**

```bat
run_sync.bat --only-dashboard-backlinks --anchor-date 2026-06-07
```

补历史各日需对每个「日期」各跑一次（`--anchor-date` = 该行日期）。

环境变量：`DASHBOARD_GSC_QUERY_LIMIT=1000`（GSC query 按点击 Top N，全国家合计）。

---

### 4.2 表 2：Ahrefs 站点有机词库

**用途：** 以 Ahrefs **站点排名词（Organic Keywords）** 为主数据源，运营只做 **分级与落地页标注**。

**Upsert 键：** `关键词`（一行一词，英文小写归一后唯一）

**导入规则（新）：**

- 同步时调用 Ahrefs `site-explorer/organic-keywords`（默认 Top 1000，可按排名/搜索量过滤）。
- **市场范围：** 默认 `**AHREFS_TARGET_COUNTRY=all`**（全球/多国聚合）；`organic-keywords` 按 `metrics-by-country` 或 `AHREFS_AGGREGATE_COUNTRIES` 合并（同词取最佳排名）。单市场可设 `us` 等。
- 运营仅维护：优化状态、关联落地页。


| 字段名   | 明道云类型 | 来源     | 国家/范围       | 说明                                                 |
| ----- | ----- | ------ | ----------- | -------------------------------------------------- |
| 关键词   | 文本    | **导入** | **all**（默认） | Ahrefs `organic-keywords` → `keyword`；唯一键；多国聚合词库   |
| 月搜索量  | 数值    | **导入** | **all**（默认） | 该词月搜索量（`volume`；聚合后取最佳）                            |
| KD    | 数值    | **导入** | **all**（默认） | 关键词难度 0–100（`keyword_difficulty`）                  |
| CPC   | 数值    | **导入** | **all**（默认） | **Cost Per Click**，美元（API 美分 ÷100）；缺省则价值分按 0.5 美元计 |
| 当前排名  | 数值    | **导入** | **all**（默认） | Google 自然排名（`best_position`）；未进 Top100 留空          |
| 排名变化  | 文本    | **导入** | **all**（默认） | 7 日对比（`best_position` vs `best_position_prev`）     |
| 排名落地页 | 链接    | **导入** | **all**（默认） | 最佳排名 URL（`best_position_url`）                      |
| 数据日期  | 日期    | 脚本     | —           | 锚点日 API 快照日期                                       |
| 优先级   | 单选    | **脚本** | —           | P0 / P1 / P2 / 未分级（默认未分级）                          |
| 关键词类型 | 单选    | **脚本** | —           | 搜索意图                                               |
| 优化状态  | 单选    | **人工** | —           | 未开始 / 优化中 / 已上Top30 / 已上Top10 / 停滞                 |
| 关联落地页 | 链接    | **人工** | —           | 计划优化的站内 URL，可与「排名落地页」对比                            |



|                | 原因                          |
| -------------- | --------------------------- |
| 转化意图           | 与「关键词类型」重叠，考核靠优先级即可         |
| 优化次数           | API 未实现，易误导考核               |
| 绑定页面URL（强制一对一） | 改为「关联落地页」+ API「排名落地页」，更贴近实际 |


**明道云视图建议：**

- 「P0/P1 待优化」：`优先级` in (P0,P1) 且 `当前排名` > 30  
- 「已进 Top10」：`当前排名` ≤ 10

**看板四档口径：** 来自 GSC **query 维、全国家合计** 的 `position` 分档（见 §4.1 新列名 **GSC Top1-3 搜索词数** 等）。**Ahrefs 站点有机词库**仍为 Ahrefs 有机词；二者 **不可对数**。

---

### 4.3 表 3：页面管理表

**用途：** 以 Ahrefs **Top pages** 自动发现 URL，汇总 **Ahrefs 页面指标 + GSC 真实表现/收录**，查看各独立站页面状态；执行与质检类字段由运营维护。

**与 GSC Top 页面 / 外链表的分工：**


| 表 / 来源                  | 用途                                                                           |
| ----------------------- | ---------------------------------------------------------------------------- |
| **本表**                  | Ahrefs **top-pages** 自动 import URL → 页面级 Ahrefs 指标 + **全球排名DR** + GSC 点击/收录等 |
| **GSC 页面流量（全国家）**（§4.8） | GSC **page × country** 流量发现，与本表互补                                            |
| **外链建设记录**（§4.4）        | 买链登记 + Ahrefs 补 **日期/锚文本**；**不再**使用旧外链监控表自动导入                                |


**Upsert 键：** `独立站` + `页面URL`（每站 URL 唯一）

**页面URL 导入规则（Ahrefs API 自动，不用人工填）：**


| 规则        | 说明                                                                                                          |
| --------- | ----------------------------------------------------------------------------------------------------------- |
| **来源**    | Ahrefs `site-explorer/top-pages`（锚点日，默认 `**AHREFS_TARGET_COUNTRY=all`**，全球/不传 country）                      |
| **自动新建**  | 表中尚无该 URL，且 `**sum_traffic ≥ PAGES_AHREFS_IMPORT_MIN_TRAFFIC`**（默认 0）→ `addRow` 写入 `页面URL` + `独立站` + `数据日期` |
| **排序/上限** | 按 Ahrefs **月流量** 降序，最多 `**PAGES_AHREFS_IMPORT_LIMIT`** 行（默认 1000）                                           |
| **首页**    | 各站 `homepage_url` 仍 **seed 一行**（无 top-pages 命中也保留）                                                          |
| **不用**    | GSC `page` 维批量 import URL（已废弃）；手工整表粘贴 URL                                                                   |
| **人工**    | 运营只补 **运营页面类型** 等人工列                                                                                        |


**写入节奏：** 锚点日；Ahrefs **top-pages import URL** → 逐行 `editRow` 更新 Ahrefs 列 + **全球排名DR** + GSC 四指标 + 收录状态；**运营页面类型 / 优化日期 / 优化记录 / 质量校验** 脚本不覆盖。

**仅跑页面表：**

```bat
run_sync.bat --skip-keywords --skip-dashboard --skip-gsc-top-queries --skip-gsc-top-pages
```

---

#### 字段定义（终稿）


| 字段名         | 明道云类型 | 建议    | API 来源                                               | 来源         | 国家/范围            | 说明                                             |
| ----------- | ----- | ----- | ---------------------------------------------------- | ---------- | ---------------- | ---------------------------------------------- |
| 独立站         | 单选    | 必填    | —                                                    | 脚本         | —                | Upsert 键；五站 key                                |
| 页面URL       | 链接    | 必填    | `top-pages` → `url`                                  | **Ahrefs** | **all**（默认）      | 锚点日 **top-pages 自动 import**（全球有机 Top N）        |
| GSC页面URL    | 链接/文本 | 只读    | GSC `page` 维批量匹配到的 `url`                             | **GSC**    | **全站**           | 与 **页面URL** 模糊匹配；无匹配留空；有值时才跑 **收录 Inspection** |
| 运营页面类型      | 单选    | 新行必填  | —                                                    | **人工**     | —                | 8 类单选；脚本不写                                     |
| Top keyword | 文本    | 只读    | `top-pages` → `top_keyword`；兜底有机词落地页                 | **Ahrefs** | **all**（默认）      | 该 URL 流量最大的代表词                                 |
| Volume      | 数值    | 只读    | `top-pages` → `top_keyword_volume`                   | **Ahrefs** | **all**（默认）      | Top keyword 月搜索量（非页面 Traffic）                  |
| 发布日期        | 日期    | 只读    | `crawled-pages` → `first_seen`                       | **Ahrefs** | **全站**           | 首次爬到该 URL；须 URL 与 crawled 索引匹配                 |
| 优化日期        | 日期    | 选填    | —                                                    | **人工**     | —                | 脚本不写                                           |
| 优化记录        | 多行文本  | 选填    | —                                                    | **人工**     | —                | 脚本不写                                           |
| 质量校验        | 单选    | 选填    | —                                                    | **人工**     | —                | 脚本不写                                           |
| 收录状态        | 单选    | 只读    | GSC URL Inspection（**仅当有 GSC页面URL** 时写入）             | **GSC**    | **全站**           | 已收录 / 未收录 / 索引异常；无 GSC 匹配时 **不更新**本列           |
| GSC点击       | 数值    | 只读    | GSC `page` 维锚点日                                      | **GSC**    | **全站**           | 全国家合计；仅 **update** 已存在行                        |
| GSC展示量      | 数值    | 只读    | 同上                                                   | **GSC**    | **全站**           | 同上                                             |
| GSC平均CTR    | 数值    | 只读    | 同上                                                   | **GSC**    | **全站**           | 0~1 小数                                         |
| GSC平均排名     | 数值    | 只读    | 同上                                                   | **GSC**    | **全站**           | 加权平均排名                                         |
| 数据日期        | 日期    | 只读    | 脚本                                                   | **脚本**     | —                | 快照锚点日                                          |
| UR          | 数值    | 只读    | `top-pages` → `ur`；兜底 `crawled-pages` → `url_rating` | **Ahrefs** | **all** / **全站** | URL Rating；crawled 兜底为域名级 UR                   |
| **全球排名DR**  | 数值    | 只读    | `domain-rating`                                      | **Ahrefs** | **全站**           | 本站 **Domain Rating**（全球域名级）；每行写入同一站点 DR        |
| Traffic     | 数值    | 只读    | `top-pages` → `sum_traffic`                          | **Ahrefs** | **all**（默认）      | 页面估算月有机流量（≠ Volume）                            |
| Value       | 数值    | 只读    | `top-pages` → `value`                                | **Ahrefs** | **all**（默认）      | 流量价值美元（API 美分÷100；≠ Traffic）                   |
| Keywords    | 数值    | 只读    | `top-pages` → `keywords`                             | **Ahrefs** | **all**（默认）      | 该 URL 排名关键词个数                                  |
| 页面字数        | 数值    | 只读；二期 | —                                                    | **Ahrefs** | —                | 二期 `site-audit`；脚本暂不写                          |


**Ahrefs Top pages 界面 → 本表：**


| Ahrefs UI 列          | 本表字段                                           |
| -------------------- | ---------------------------------------------- |
| URL                  | **页面URL**（import 来源）                           |
| Top keyword / Volume | Top keyword / Volume（列名与 UI 一致）                |
| Keywords             | Keywords                                       |
| Traffic / Value / UR | Traffic / Value / UR                           |
| （Site DR）            | **全球排名DR** ← `domain-rating`（全站，非 Top pages 列） |
| （crawled）            | 发布日期 ← `crawled-pages.first_seen`              |


---

#### API 字段写入、空白原因与排错

**同步分两阶段：**


| 阶段               | 明道云操作     | 写入列                               |
| ---------------- | --------- | --------------------------------- |
| 1. Ahrefs import | `addRow`  | **仅** 独立站 + 页面URL + 数据日期          |
| 2. 逐行 update     | `editRow` | Ahrefs 各列、**全球排名DR**、GSC 四指标、收录状态 |


**各 API 字段：**


| 字段                      | 脚本已接    | 空白常见原因                                                        |
| ----------------------- | ------- | ------------------------------------------------------------- |
| 页面URL（新行）               | ✅       | 锚点日 `top-pages=0`（Ahrefs 无全球快照）；或 `sum_traffic < min_traffic` |
| 全球排名DR                  | ✅       | Ahrefs 该日无 DR；或未配 `MINGDAO_FIELD_PAGE_GLOBAL_DR`              |
| 发布日期                    | ✅       | URL 与 `crawled-pages` 路径不一致                                   |
| Top keyword / Traffic 等 | ✅       | URL 不在 top-pages；小站全球有机快照为空                                   |
| GSC 四指标 / 收录            | ✅       | GSC 429/超时；URL 与 GSC 路径不一致                                    |
| ~~页面外链数 / 引用域名数~~       | **已删除** | 改看 **外链建设记录**（§4.4）                                           |


**运维：** 五站分站补跑见下；`MINGDAO_REQUEST_TIMEOUT=180`（VPN 慢）。

`**.env` 键名：**

```env
AHREFS_TARGET_COUNTRY=all
# 可选：限制有机词聚合国家，逗号分隔
# AHREFS_AGGREGATE_COUNTRIES=us,gb,de,au,ca,in,jp,kr,tw,pl
MINGDAO_FIELD_PAGE_GLOBAL_DR=
PAGES_AHREFS_IMPORT_LIMIT=1000
PAGES_AHREFS_IMPORT_MIN_TRAFFIC=0
```

（其余 `MINGDAO_FIELD_PAGE_*` 见 `.env.example`）

---

#### 已删除 / 不再使用


| 原字段                        | 原因                                          |
| -------------------------- | ------------------------------------------- |
| **Ahrefs页面类型**             | API `page_type` 常为 null；与 **运营页面类型** 重复，已删列 |
| **页面外链数 / 引用域名数**          | 与外链表重复；页面表聚焦 Ahrefs 流量页 + GSC 表现            |
| **GSC 批量 import URL**      | 改为 Ahrefs `top-pages` 发现 URL                |
| 通过 top-pages 仅补字段、不 import | **已改为 top-pages 负责 import**                 |


**填写注意：** 新行 **运营页面类型** 须运营补填。首页由 `homepage_url` **seed**。

---

### 4.4 表 4：外链建设记录

**用途：** 外链同事登记 **买链**（Website、link1/link2、Article 等）；脚本从 Ahrefs **仅补空列** **日期**、**锚文本**。旧「外链监控表」Ahrefs 全量导入 **已废弃**。

**Upsert 键：** 无自动新建；同事手工 `addRow`，脚本只对已有行 `editRow`。

**匹配逻辑（Ahrefs `all-backlinks`）：**


| 步骤  | 说明                                                              |
| --- | --------------------------------------------------------------- |
| 分组  | 按行 **独立站** 对应 `config/sites.json` → Ahrefs `target`             |
| 来源页 | 有 **URL** 列 → 与 Ahrefs `url_from` 精确匹配；无 URL 时退回 **Website** 域名 |
| 目标链 | **link1** 优先匹配 Ahrefs `url_to`；未命中且填了 **link2** 再试 link2        |
| 写入  | 仅当 **日期** 或 **锚文本** 为空时写入；**不覆盖**同事已填内容                         |
| 日期  | `first_seen_link` 优先，否则 `first_seen`（Ahrefs 首次发现，非下单日）          |


**独立站选项：** 与全库共用 `config/mingdao_options.json` → `sites`（与看板一致）。

**命令：**

```bat
:: 仅补外链建设记录（推荐）
run_sync.bat --only-link-building

:: 全量 sync 时附带
run_sync.bat --with-link-building --skip-dashboard ...
```

**环境变量：** `MINGDAO_WORKSHEET_LINK_BUILDING`、`MINGDAO_FIELD_LINK_`*、`.env.example`；`AHREFS_LINK_BUILDING_LIMIT`（默认 5000）。

---

### 4.5 表 5A：SEO 每日执行日志

**用途：** 运营每日 15 分钟记录；**全部人工**（脚本本期不写入）。

**Upsert 键：** `日期` + `运营人`


| 字段名     | 明道云类型 | 来源     | 说明                 |
| ------- | ----- | ------ | ------------------ |
| 日期      | 日期    | **人工** | 执行日                |
| 运营人     | 成员    | **人工** |                    |
| 今日主攻词   | 文本    | **人工** | 从关键词表选 1 个 P0/P1   |
| 新增页面URL | 链接    | **人工** | 当日新上线页，可空          |
| 优化页面URL | 链接    | **人工** | 当日深度优化页；新增与优化至少填一项 |
| 今日有效动作  | 多行文本  | **人工** | 必填                 |
| 今日无效动作  | 多行文本  | **人工** | 必填                 |
| 数据波动判断  | 多行文本  | **人工** | 对照看板异常时的原因         |
| 明日攻坚任务  | 多行文本  | **人工** | ≤3 条               |
| 当日合规    | 单选    | **人工** | 达标 / 未达标           |


---

### 4.6 表 5B：周绩效复盘

**用途：** 每周日复盘；**以人工为主**，数字类指标在明道云用 **汇总视图 / 关联记录** 核对。

**Upsert 键：** `周次` + `运营人`（周次示例：`2026-W22`）


| 字段名       | 明道云类型 | 来源     | 说明                              |
| --------- | ----- | ------ | ------------------------------- |
| 周次        | 文本    | **人工** | 如 2026-W22                      |
| 运营人       | 成员    | **人工** |                                 |
| 本周Top30净增 | 数值    | **人工** | 对照看板 **GSC 四档搜索词数** 或关键词表（旧名保留） |
| 本周合格RD数   | 数值    | **人工** | 对照外链表合格视图                       |
| 本周新增页面数   | 数值    | **人工** | 对照页面表发布日期                       |
| 本周优化页面数   | 数值    | **人工** | 对照页面表优化记录                       |
| 本周有效动作总结  | 多行文本  | **人工** | ≥3 条                            |
| 本周无效动作总结  | 多行文本  | **人工** | ≥3 条                            |
| 问题根因分析    | 多行文本  | **人工** |                                 |
| 下周KPI     | 多行文本  | **人工** | 可量化                             |
| 周考核等级     | 单选    | **人工** | 优秀 / 合格 / 不合格                   |



|     |     |
| --- | --- |
|     |     |
|     |     |
|     |     |


---

### 4.7 表 7：GSC 查询流量（全国家）

**用途：** 五站各自 GSC 资源下，**搜索词（query）** 维度的 Top 明细，按 **国家** 拆分；**全部自动**，禁止人工改数。

**Upsert 键：** `数据日期` + `独立站` + `关键词` + `国家`（同一词在不同国家各一行）

**写入节奏：**


| 类型                | 规则                                                                                                                                                             |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **同步窗口**          | 与看板同一 **7 日窗口**：锚点−6 … 锚点（例 5/24～5/30）；**每天**各调一次 GSC                                                                                                          |
| **API**           | `startDate = endDate = 该行数据日期`，`dimensions: ["query", "country"]`                                                                                              |
| **排序**            | 按 **点击** 降序取 Top N（脚本默认 **1000** 行/站，可配置 `GSC_TOP_QUERIES_LIMIT`）                                                                                              |
| **点击筛选**          | **仅写入点击 > 0**；GSC 返回的 0 点击行不入库（§3.2）                                                                                                                           |
| **国家**            | 默认 **全部国家**；`config/sites.json` 若设 `gsc_top_countries` 则只保留所列国家（如 lasermicrofab 仅 `usa`）                                                                       |
| **五站**            | 每站读各自 `gsc_site_url`（见 `config/sites.json`），写入时带 `独立站` 单选                                                                                                      |
| **Ahrefs enrich** | GSC sync 后自动 `enrich_gsc_top_queries`：**全部国家**（`GSC_TOP_QUERIES_ENRICH_COUNTRIES` 留空）+ 7 日总点击>0 + Top **500** query×country，写 **Ahrefs搜索量/KD/CPC**；详见 **§3.2** |


**与看板区别：** 看板「全站加权平均排名」是 **全站单日汇总**；本表「平均排名」是 **该 query 在该国当日的 query 级加权平均排名**，不可混读。


| 字段名        | 明道云类型 | 来源     | 国家/范围            | 说明                                                                                                                |
| ---------- | ----- | ------ | ---------------- | ----------------------------------------------------------------------------------------------------------------- |
| 数据日期       | 日期    | 脚本     | —                | GSC 统计所属日期（**非**脚本执行时刻）；必填                                                                                        |
| 独立站        | 单选    | 脚本     | —                | `cncpioneer` / `fecision` / `richconn` / `lasermicrofab` / `drametal`；与 `config/sites.json` 的 `key` 一致            |
| 关键词        | 文本    | GSC    | **按行国家**         | Search Analytics `query` 原文；Upsert 键之一                                                                            |
| 国家         | 单选    | GSC    | **按行国家**         | **ISO 3166-1 alpha-3 小写**（如 `usa`、`gbr`）；Upsert 键之一；GSC 返回什么国就写什么国；lasermicrofab 仅 `usa`                          |
| 点击         | 数值    | GSC    | **按行国家**         | 该词在该国 **当日** 自然搜索点击（Clicks）                                                                                       |
| 展示量        | 数值    | GSC    | **按行国家**         | 该词在该国 **当日** 展示次数（Impressions）                                                                                    |
| 平均CTR      | 数值    | GSC    | **按行国家**         | 该词在该国 **当日** CTR，0~1 小数；百分比控件写入 0.052 = 5.2%                                                                      |
| 平均排名       | 数值    | GSC    | **按行国家**         | 该词在该国 **当日** query 级加权平均排名（Position）；未展示时可留空                                                                      |
| Ahrefs搜索量  | 数值    | Ahrefs | **按行国家**（enrich） | `keywords-explorer/overview` → `volume`；**全部国家** + 7 日总点击>0 + Top 500 query×country（§3.2）；GSC `usa` → Ahrefs `us` |
| Ahrefs KD  | 数值    | Ahrefs | **按行国家**（enrich） | overview → `difficulty`；同上 enrich 策略；API 无值则留空                                                                    |
| Ahrefs CPC | 数值    | Ahrefs | **按行国家**（enrich） | overview → `cpc`，美元（美分÷100）；同上 enrich 策略；品牌/长尾常 null                                                              |


**明道云视图建议：** 按「数据日期」降序 + `点击` 降序；筛选 `独立站` + `国家 = usa` 看美国 Top 词。

**独立站单选选项（须与现有表一致）：** `cncpioneer`、`fecision`、`richconn`、`lasermicrofab`、`drametal`

**国家单选选项（两表共用同一套选项文字）：**

- **可以设为单选**，便于视图筛选；脚本写入的选项名须与明道云 **完全一致**（小写三字母码，无空格）。
- GSC 返回即为此格式；若某国 **尚未建选项**，同步会跳过该行并在 report **Warnings 列出国家码**（如 `lasermicrofab GSC 查询流量（全国家） 缺少国家单选选项，跳过 2 行: bih×2`），补选项后重跑即可。
- **建议首批预建**（按 B2B 独立站常见流量国，可按需增减）：

`usa` · `gbr` · `deu` · `aus` · `can` · `ind` · `fra` · `ita` · `esp` · `nld` · `jpn` · `kor` · `bra` · `mex` · `pol` · `swe` · `che` · `aut` · `bel` · `sgp` · `hkg` · `twn` · `tha` · `vnm` · `phl` · `idn` · `mys` · `nzl` · `zaf` · `are` · `sau` · `tur` · `rus` · `ukr` · `chn`

- 建表后把各国家选项 key 写入 `config/mingdao_worksheets.json` → `gsc_top_queries.country_option_keys` / `gsc_top_pages.country_option_keys`（与 `独立站` 写法相同）。

---

### 4.8 表 8：GSC 页面流量（全国家）

**用途：** 五站各自 GSC 资源下，**落地页（page）** 维度的 Top 明细，按 **国家** 拆分；**全部自动**，禁止人工改数。

**Upsert 键：** `数据日期` + `独立站` + `页面URL` + `国家`（同一 URL 在不同国家各一行）

**写入节奏：**


| 类型       | 规则                                                               |
| -------- | ---------------------------------------------------------------- |
| **同步窗口** | 与表 7 相同：锚点起 **7 日**，每天一行                                         |
| **API**  | `startDate = endDate = 该行数据日期`，`dimensions: ["page", "country"]` |
| **排序**   | 按 **点击** 降序取 Top N（脚本默认 **1000** 行/站，可配置 `GSC_TOP_PAGES_LIMIT`）  |
| **点击筛选** | **仅写入点击 > 0**；GSC 返回的 0 点击行不入库（§3.2）                             |
| **国家**   | 默认 **全部国家**；`gsc_top_countries` 可限制（如 lasermicrofab 仅 `usa`）     |
| **URL**  | 写入 GSC 返回的 page 字符串（可能与浏览器栏 www/协议略有差异，以 GSC 为准）                 |



| 字段名   | 明道云类型 | 来源  | 国家/范围    | 说明                                          |
| ----- | ----- | --- | -------- | ------------------------------------------- |
| 数据日期  | 日期    | 脚本  | —        | GSC 统计所属日期；必填                               |
| 独立站   | 单选    | 脚本  | —        | 同上五站 key                                    |
| 页面URL | 链接    | GSC | **按行国家** | 完整 URL（`https://...`）；Upsert 键之一            |
| 国家    | 单选    | GSC | **按行国家** | 同表 7；两表 **共用同一套国家选项**；lasermicrofab 仅 `usa` |
| 点击    | 数值    | GSC | **按行国家** | 该 URL 在该国 **当日** 自然搜索点击                     |
| 展示量   | 数值    | GSC | **按行国家** | 该 URL 在该国 **当日** 展示次数                       |
| 平均CTR | 数值    | GSC | **按行国家** | 该 URL 在该国 **当日** CTR，0~1 小数                 |
| 平均排名  | 数值    | GSC | **按行国家** | 该 URL 在该国 **当日** page 级加权平均排名               |


---

### 4.9 表 9：Ahrefs Rank Tracker（重点监控词）

**用途：** 同步 Ahrefs **Rank Tracker** 里你为各站 **手动添加的重点监控词**（不是 Site Explorer 全站有机词）。对应 UI 路径：`Rank Tracker → [项目名] → Overview`。

**与 §4.1 SEO 自动数据看板、§4.2 有机词库的关系：**

- **不写入 §4.1 看板**；明道云建 **两张独立工作表**（明细 + 概览），本节只定义字段。
- §4.1 四档 = **GSC 全站 query** 计数；本节概览四档 = **RT 重点词** 在 Ahrefs 排名分档，**不可对数**。
- §4.2 有机词库 = 全站自动发现词；本节 = RT 项目内 **Tracked keywords** 表。

**脚本状态：** 已接 `--only-rank-tracker*`。API **可免费导出**（Rank Tracker 端点 **不消耗 API units**）。

---

#### `project_id` 是什么？

`**project_id`** = Ahrefs 里 **每一个 Rank Tracker 项目的数字编号**，API 用它指定「拉哪个项目的监控词」。

**怎么找：**

1. 浏览器打开该站的 Rank Tracker 项目（例如 Lasermicrofab）。
2. 看地址栏 URL，形如：
  `https://app.ahrefs.com/rank-tracker/overview/28673928/`  
   其中 `**28673928`** 就是 `project_id`（每站、每项目一个，与 `config/sites.json` 的 `key` 不是同一个东西）。
3. 也可在 UI 点 **API {}** 按钮，生成的示例请求里会带 `project_id=...`。

**配置（脚本待接）：** 在 `config/sites.json` 每个独立站增加：

```json
"rank_tracker_project_id": 28673928
```

五站 = 五个 RT 项目 = **五个不同的 project_id**（若某站尚未建 RT 项目，可先不配，同步时跳过该站）。

---

#### 表 A：重点监控词 · 明细

**明道云工作表名建议：** `Ahrefs 重点监控词`  
**Upsert 键：** `Date` + `独立站` + `Keyword` + `location`（同一词在不同 location 各一行）  
**API：** `GET /v3/rank-tracker/overview`  
**请求要点：** `project_id`、`date`（锚点日）、`date_compared`（UI 右上角对比日）、`device`（`desktop` / `mobile`，与 UI 设备切换一致）

**字段定义（列名与 Ahrefs UI「Tracked keywords」表头一致）：**


| 字段名（明道云列名）   | 类型建议  | API 导出含义                                                                                                                                        |
| ------------ | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Date         | 日期    | 快照日；请求参数 `date`（非「今天跑脚本」的时刻）                                                                                                                    |
| 独立站          | 单选    | 脚本写入；option 与全库 `mingdao_options.json` → `sites` 共用                                                                                                |
| Keyword      | 文本    | `keyword`：该监控词原文                                                                                                                                |
| Position     | 数值    | `position`：当前 **有机** 最佳排名；未进 SERP 为 null                                                                                                        |
| Change       | 文本    | `position_diff`：相对 `date_compared` 的排名变化（如 `+3`、`-2`）；UI 显示 **New** 时多为对比日无排名、当日有排名（`position_prev` 空且 `position` 有值）                           |
| Tags         | 文本    | `tags`：项目里给该词打的标签，数组拼接为逗号分隔                                                                                                                     |
| Intents      | 文本    | `is_informational` / `is_commercial` / `is_transactional` / `is_navigational` / `is_branded` / `is_local` 等为 true 的意图缩写（与 UI 图标 I/C/T/N/B/L 对应） |
| Volume       | 数值    | `volume`：该词月搜索量（受请求参数 `volume_mode` 影响，默认 monthly）                                                                                              |
| Traffic      | 数值    | `traffic`：该词带来的估算 **月有机流量**                                                                                                                     |
| Change       | 文本/数值 | `traffic_diff`：相对对比日的流量变化（UI 在 Traffic 列旁第二个 **Change**；明道云若不能两列同名，显示名可用 **Change (Traffic)**，说明仍对应 `traffic_diff`）                             |
| KD           | 数值    | `keyword_difficulty`：关键词难度 0–100                                                                                                                |
| Clicks       | 数值    | `clicks`：该词 SERP 的月均 **总点击** 估算；无数据时常 null（UI **N/A**）                                                                                          |
| CPC          | 数值    | `cost_per_click`：付费点击均价，API 为 **美分**；写入前 ÷100 得美元                                                                                               |
| Parent topic | 文本    | `parent_topic`：Ahrefs 计算的父主题词                                                                                                                   |
| SF           | 文本    | `serp_features`：该词 SERP 出现的特性列表（如 snippet、video 等），拼接存储                                                                                         |
| URL          | 文本    | `url`：当前排名最高的落地页 URL                                                                                                                            |
| location     | 文本    | `location`：该词在 RT 中设置的跟踪地域（国家/州/市，如 United States）                                                                                              |
| Added        | 日期    | `created_at`：该词 **加入本项目** 的日期                                                                                                                   |

`date_compared`、`device` 仅用于 API 请求（对比日默认锚点 −7 天；设备默认 desktop），**不导出到明道云**。

---

#### 表 B：重点监控词 · 概览（Positions 四档）

**明道云工作表名建议：** `Ahrefs RT 概览`  
**用途：** 做明道云 **看板/图表** 用；对应 UI **Overview 顶部 → Positions** 卡片里的分档 **词数**（只做四档，便于和 GSC 看板并列展示）。  
**Upsert 键：** `Date` + `独立站`  
**API：** `GET /v3/rank-tracker/competitors-stats`（取 **本项目目标站** 对应 `competitor` 那一行；`device` 仅作请求参数，默认 `AHREFS_RANK_TRACKER_DEVICE=desktop`，**不写入明道云**）

**只同步以下四档（列名与 UI Positions 区域一致）：**


| 字段名（明道云列名）    | 类型建议 | API 导出含义                                                                                    |
| ------------- | ---- | ------------------------------------------------------------------------------------------- |
| Date          | 日期   | 快照日；请求参数 `date`                                                                             |
| 独立站           | 单选   | 脚本写入；option 与全库 `mingdao_options.json` → `sites` 共用                                      |
| positon1-3    | 数值   | `pos_1_3`：监控词中，**有机排名前 3** 的词个数                                                             |
| positon4-10   | 数值   | `pos_4_10`：排名 **第 4–10** 的词个数                                                               |
| positon11-20  | 数值   | `pos_11_20`：排名 **第 11–20** 的词个数                                                             |
| positon21-100 | 数值   | API **无** 单独 `pos_21_100`；脚本写入 `**pos_21_50` + `pos_51_plus`**（排名 21–100 的监控词合计；不含 No rank） |


**本期概览不同步：** Share of Voice、Average position、Traffic 顶部卡片、51+ 单独列、No rank 等（若以后要加再扩表）。

---

#### `.env` 模板（建表后填 controlId）

```env
# —— 表 A：明细 ——
MINGDAO_WORKSHEET_RT_KEYWORDS=
MINGDAO_FIELD_RT_KW_SITE=
MINGDAO_FIELD_RT_KW_DATE=
MINGDAO_FIELD_RT_KW_KEYWORD=
MINGDAO_FIELD_RT_KW_POSITION=
MINGDAO_FIELD_RT_KW_CHANGE_POSITION=
MINGDAO_FIELD_RT_KW_TAGS=
MINGDAO_FIELD_RT_KW_INTENTS=
MINGDAO_FIELD_RT_KW_VOLUME=
MINGDAO_FIELD_RT_KW_TRAFFIC=
MINGDAO_FIELD_RT_KW_CHANGE_TRAFFIC=
MINGDAO_FIELD_RT_KW_KD=
MINGDAO_FIELD_RT_KW_CLICKS=
MINGDAO_FIELD_RT_KW_CPC=
MINGDAO_FIELD_RT_KW_PARENT_TOPIC=
MINGDAO_FIELD_RT_KW_SF=
MINGDAO_FIELD_RT_KW_URL=
MINGDAO_FIELD_RT_KW_LOCATION=
MINGDAO_FIELD_RT_KW_ADDED=

# —— 表 B：概览（Positions 四档）——
MINGDAO_WORKSHEET_RT_OVERVIEW=
MINGDAO_FIELD_RT_OV_SITE=
MINGDAO_FIELD_RT_OV_DATE=
MINGDAO_FIELD_RT_OV_POS_1_3=
MINGDAO_FIELD_RT_OV_POS_4_10=
MINGDAO_FIELD_RT_OV_POS_11_20=
MINGDAO_FIELD_RT_OV_POS_21_100=

AHREFS_RANK_TRACKER_DEVICE=desktop
AHREFS_RANK_TRACKER_COMPARE_DAYS=7
```

**规划命令（脚本接好后）：**

```bat
run_sync.bat --only-rank-tracker --anchor-date 2026-06-11
run_sync.bat --only-rank-tracker-keywords --anchor-date 2026-06-11
run_sync.bat --only-rank-tracker-overview --anchor-date 2026-06-11
```

---

## 5. Upsert 规则汇总


| 工作表              | 唯一键                             | 同步行为                                     |
| ---------------- | ------------------------------- | ---------------------------------------- |
| SEO 自动数据看板       | 日期 + 独立站                        | 有则更新，无则新增（每站 7 日窗口各一行）                   |
| Ahrefs 站点有机词库    | 关键词                             | **Ahrefs 导入** upsert                     |
| 页面管理表            | 独立站 + 页面URL                     | **GSC 自动新建**（展示≥阈值）+ 更新 API 字段；可 seed 首页 |
| 外链建设记录           | 同事手工建行                          | **Ahrefs 补数**（仅空列 日期/锚文本）                |
| GSC 查询流量（全国家）    | 数据日期 + 独立站 + 关键词 + 国家           | **GSC 导入** upsert（7 日窗口 × 五站，每日 Top N）   |
| GSC 页面流量（全国家）    | 数据日期 + 独立站 + 页面URL + 国家         | **GSC 导入** upsert（7 日窗口 × 五站，每日 Top N）   |
| Ahrefs 重点监控词（明细） | Date + 独立站 + Keyword + location | **overview** upsert                            |
| Ahrefs RT 概览（四档） | Date + 独立站                       | **competitors-stats** upsert                   |


---

## 6. 明道云应用结构建议

```
应用：SEO 数据看板
├── 工作表1  SEO自动数据看板      ← GSC + Ahrefs API
├── 工作表2  Ahrefs 站点有机词库   ← Ahrefs organic-keywords + 人工标注
├── 工作表3  页面管理表            ← 人工 URL + GSC/Ahrefs 按 URL（不接 top-pages）
├── 工作表4  外链建设记录            ← 人工登记 + Ahrefs 补日期/锚文本
├── 工作表5  GSC 查询流量（全国家） ← GSC query × country（五站）
├── 工作表6  GSC 页面流量（全国家） ← GSC page × country（五站）
├── 工作表9  Ahrefs 重点监控词      ← RT 明细 overview
├── 工作表10 Ahrefs RT 概览        ← RT Positions 四档
├── 工作表7  SEO每日执行日志       ← 纯人工
└── 工作表8  周绩效复盘            ← 纯人工
```

**权限建议（与 need.docx 一致）：**

- 看板、关键词 API 字段：运营 **只读**，IT/脚本账号可写  
- 页面、外链：运营可编辑人工字段，不可改 API 字段（明道云字段级权限）  
- 审核类字段：仅主管可写

---

---

---

**Q：GSC 查询流量、看板四档、Ahrefs 有机词库怎么读？**  
A：看板 = GSC **全国家 query** 分档 **计数**；GSC 查询流量 = **query × 国家** 明细；Ahrefs 站点有机词库 = Ahrefs **有机词（默认 all 全球聚合）**。不要逐词对平。

**Q：页面表 Ahrefs 列全是空的，是字段 ID 错还是没接 API？**  
A：先看 `sync-report` 是否跑完 **update**（不只 import 三列）、`top-pages urls=` 与 `organic-keywords count=`。逻辑已接；空白多为 **API 无数据**、**URL 不匹配** 或 **超时中断**。详见 §4.3 排错表。

**Q：GSC 查询流量与 Ahrefs 有机词库、看板 GSC 四档有何区别？**  
A：看板四档 = GSC **全国家 query** 分档 **计数**（列名 **GSC Top1-3 搜索词数** 等）；GSC 查询流量 = **query × 国家** 明细行；Ahrefs 站点有机词库 = Ahrefs organic-keywords。

**Q：GSC 查询/页面流量 API 各取 Top 多少？**  
A：默认各按 **点击降序 Top 1000** 拉取/站/日，**只写入点击 > 0 的行**（`GSC_TOP_QUERIES_LIMIT` / `GSC_TOP_PAGES_LIMIT`）。7 日窗口 = 每站每表约 7 次 GSC 调用。详见 **§3.2**。

**Q：GSC 查询流量的 Ahrefs 搜索量/KD/CPC 补哪些国家？**  
A：**2026-06-10 起** 默认 **全部国家**，且 7 日 **总点击 > 0**；按总点击取 Top **500** 个 query×country 调 Ahrefs overview。仅补美国时设 `GSC_TOP_QUERIES_ENRICH_COUNTRIES=usa`。详见 **§3.2**。

**Q：enrich 报「跳过未知国家映射」？**  
A：GSC 国码（alpha-3）须在 `script/sync.py` → `GSC_COUNTRY_TO_AHREFS` 有 Ahrefs 国码（alpha-2）；已与明道云 `country_option_keys` 对齐（`**zzz` 除外**）。补映射后重跑 enrich；Ahrefs 某国无 overview 数据时，搜索量/KD 仍可能为空。`**irn`（伊朗）** 在 `GSC_ENRICH_SKIP_COUNTRIES` 中固定跳过，不再触发 400

**Q：重点监控词表和有机词库有什么区别？能都用 API 吗？**
A：有机词库 = Site Explorer 全站发现词；重点监控词 = Rank Tracker 项目里 **你指定** 的词。两者 API 不同，**都可以导出**；RT 端点 **不耗 API units**。详见 **§4.9**。

**Q：RT 顶部 Positions 1-3 / 4-10 能 API 导出吗？**
A：能，用 `competitors-stats`；**21-100** = `pos_21_50` + `pos_51_plus`。写入 **§4.9 概览表**，不进 §4.1 看板。详见 **§4.9 表 B**。

**Q：project_id 是什么？**
A：Rank Tracker **项目 URL 里的数字 ID**，每站一个；写在 `config/sites.json` → `rank_tracker_project_id`。详见 **§4.9**。

---

*文档版本：2026-06-11 · §4.9 Rank Tracker 明细 + 概览四档（已接 sync）*