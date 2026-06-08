# SEO 数据看板 — 明道云字段方案（终稿）

> 本文档由 `need.docx` 与 `FIELD_SUGGESTIONS.md` 合并整理，并依据 **GSC / Ahrefs API 实际能力** 修订。  
> 目标平台：[明道云 HAP](https://www.mingdao.com/app)（替代原飞书多维表格）。  
> 单站示例：`https://www.cncpioneer.com/`（GSC 资源须与 `.env` 中 `GSC_SITE_URL` 一致）。

---

## 1.**明道云 API 参考：**

- [API 概览](https://help.mingdao.com/api/introduction/)
- [向工作表读写数据](https://help.mingdao.com/api/write-data-to-worksheet/)

---

## 2. 数据来源图例


| 标记         | 含义                              |
| ---------- | ------------------------------- |
| **GSC**    | Google Search Console API 自动写入  |
| **Ahrefs** | Ahrefs API 自动写入                 |
| **脚本**     | 同步脚本计算或规则生成（非第三方直出）             |
| **导入**     | Ahrefs 批量拉取后 **新建/更新行**（关键词、外链） |
| **人工**     | 运营 / 主管填写，脚本不覆盖                 |


**同步频率建议：** 每周手动执行一次（与原 `run_sync.bat` 一致）；GSC 单日数据常有 1–3 天延迟，属正常现象。

---

## 3. API 能力边界（必读）

### 3.1 已确认可接入


| API                                 | 能力                                                                   | 写入表                                |
| ----------------------------------- | -------------------------------------------------------------------- | ---------------------------------- |
| GSC Search Analytics                | 全站点击、展示、CTR、加权平均排名；单 URL 点击；7 天点击汇总；**Top queries / Top pages × 国家** | 看板、页面表、**GSC Top 查询表、GSC Top 页面表** |
| GSC URL Inspection                  | 单 URL 收录状态                                                           | 页面表；看板汇总                           |
| Ahrefs `organic-keywords`           | 站点排名词、搜索量、KD、排名、7 日排名变化、落地页 URL                                      | **关键词表（导入）**、看板                    |
| Ahrefs `keywords-explorer/overview` | 指定词的搜索量、KD（未进 organic 时补数）                                           | 关键词表                               |
| Ahrefs `refdomains-history`         | 近 7 天 referring domains 净值变化                                         | 看板                                 |
| Ahrefs `all-backlinks`              | 外链来源 URL、目标 URL、锚文本、DR、dofollow、首次发现、是否失效                            | **外链表（导入）**                        |
| Ahrefs `domain-rating`              | 来源域名 DR                                                              | 外链表、看板本站 DR                        |
| GSC Search Analytics（`page` 维）      | 单 URL 点击、展示、CTR、平均排名（锚点日）                                            | **页面管理表**                          |
| Ahrefs `metrics`（`target` = URL）    | 该 URL 估算有机流量、排名词数、流量价值（美元）                                           | **页面管理表（计划）**                      |
| Ahrefs `crawled-pages`              | 按 URL 匹配：UR、标题、HTTP 状态等                                              | **页面管理表（计划）**                      |
| Ahrefs `organic-keywords`（按落地页聚合）   | 该 URL 主关键词、主词搜索量（脚本聚合）                                               | **页面管理表（计划）**                      |
| Ahrefs `all-backlinks`（`url_to` 过滤） | 指向该 URL 的外链条数 / 引用域名数（可选，API 成本高）                                    | **页面管理表（计划）**                      |


**页面管理表明确不接：** `site-explorer/top-pages`（Top pages 为「全站流量页发现 / 搜索排序」，与本表「人工登记重点 URL、看站点状态」分工不同；全站 Top 页面仍走 **§4.8 GSC Top 页面明细**）。

### 3.2 做不到或本期不做


| 原方案说法                   | 实际情况                                         |
| ----------------------- | -------------------------------------------- |
| Google 全站收录页面总数         | GSC **无**全站收录总数 API；只能统计 **页面表里已填 URL** 的收录数 |
| 全站 404 / Coverage 异常总数  | 无一键全站同步；「异常数」= 已监控 URL 中未收录/异常数              |
| 核心关键词平均排名               | GSC 返回的是 **全站加权平均排名**，不是词库平均                 |
| 单日新增 RD                 | Ahrefs 为 **近 7 天 RD 净值变化**                   |
| 外链「Google 收录状态」         | Ahrefs 只能判断 **外链是否仍存活（live/lost）**           |
| 关键词「优化次数」               | 需跨表统计，**已删除**                                |
| 周复盘 OKR / 页面数 / RD 自动汇总 | **二期**；本期周复盘以人工 + 明道云视图汇总为主                  |


---

## 4. 五模块 · 八工作表字段定义

### 4.1 表 1：SEO 自动数据看板

**用途：** 每日 SEO 健康度快照，**全部自动**，禁止人工改数。

**Upsert 键：** `日期` + `独立站`（每站每天一行；同步窗口默认 7 天即每站 7 行）

**写入节奏：**


| 类型             | 字段                                                  | 行为                                                                  |
| -------------- | --------------------------------------------------- | ------------------------------------------------------------------- |
| **按日（GSC）**    | 自然点击、展示量、平均CTR、全站加权平均排名                             | 同步窗口内每天一行                                                           |
| **按日（Ahrefs）** | Top1-3～Top21-100 词数、周环比Top1-3～周环比Top21-100、**本站DR** | 每天：`organic-keywords`（`date` = 该行日期）；`domain-rating`（`date` = 该行日期） |
| **仅锚点日**       | Backlinks变化、收录/异常数、异常预警、周环比流量、周平均排名、周自然点击           | 锚点日汇总或 7 日 GSC 均值，只写在锚点那一行                                          |


锚点日默认 `今天 − DATA_DELAY_DAYS`（常 3），也可用 `run_sync.bat --anchor-date 2026-05-30` 指定。每站每轮看板同步约 **7 次** Ahrefs 有机词 API（`AHREFS_TARGET_COUNTRY=all` 时按国家倍增）。


| 字段名           | 明道云类型 | 来源          | 说明                                                              |
| ------------- | ----- | ----------- | --------------------------------------------------------------- |
| 日期            | 日期    | 脚本          | 数据所属日期（非点击同步时刻）                                                 |
| 独立站           | 单选    | 脚本          | 站点 key，与 `config/sites.json` 一致                                 |
| 自然点击          | 数值    | GSC         | **当日**全站自然搜索点击                                                  |
| 展示量           | 数值    | GSC         | **当日**展示次数                                                      |
| 平均CTR         | 数值    | GSC         | **当日** CTR，0~1 小数；百分比控件写入 0.052 = 5.2%                          |
| 全站加权平均排名      | 数值    | GSC         | **当日**全站加权平均排名；**不是**核心词平均排名                                    |
| 周平均排名         | 数值    | 脚本          | 7 日「全站加权平均排名」算术平均（÷7）；**仅锚点日一行**                                |
| 周自然点击         | 数值    | 脚本          | 7 日「自然点击」算术平均（÷7）；**仅锚点日一行**                                    |
| Top1-3词数      | 数值    | Ahrefs + 脚本 | 见下「四档词数」；**每天一行**                                               |
| Top4-10词数     | 数值    | Ahrefs + 脚本 | 同上                                                              |
| Top11-20词数    | 数值    | Ahrefs + 脚本 | 同上                                                              |
| Top21-100词数   | 数值    | Ahrefs + 脚本 | 同上                                                              |
| 周环比Top1-3词    | 数值    | Ahrefs + 脚本 | **当日** vs **当日−7** 同档词数变化率；**每天一行**                             |
| 周环比Top4-10词   | 数值    | Ahrefs + 脚本 | 同上                                                              |
| 周环比Top11-20词  | 数值    | Ahrefs + 脚本 | 同上                                                              |
| 周环比Top21-100词 | 数值    | Ahrefs + 脚本 | 同上                                                              |
| Backlinks变化   | 数值    | Ahrefs      | 近 7 天 referring domains **净值**；**仅锚点日一行**                       |
| 已监控URL收录数     | 数值    | GSC + 脚本    | 页面表已监控 URL 收录数；**仅锚点日一行**（需先跑页面表）                               |
| 已监控URL异常数     | 数值    | GSC + 脚本    | 页面表异常数；**仅锚点日一行**                                               |
| 异常预警          | 单选    | 脚本          | 正常 / 流量下跌 / 收录异常；**仅锚点日一行**                                     |
| 周环比流量         | 数值    | 脚本          | 锚点起算近 7 天点击 vs 再前 7 天；**仅锚点日一行**                                |
| 本站DR          | 数值    | Ahrefs      | 全站域名 Domain Rating；**同步窗口内每天一行**（`domain-rating`，`date` = 该行日期） |


**四档词数（替代旧方案 Top10词数 / Top30词数）：**

- **数据源：** 同步窗口内 **每个日历日** 各请求一次 Ahrefs `site-explorer/organic-keywords`：`date` = 该行 `日期`，`date_compared` = 该行 `日期 − 7 天`。
- **口径：** 对当次 API 返回的有机词（默认 Top 1000，`AHREFS_TARGET_COUNTRY` 如 `us`），按 `best_position` 落入 1–3 / 4–10 / 11–20 / 21–100 四档 **计数**；未进 Top100 的不计入。
- **不是：** GSC 指标；也不是关键词表里人工筛选后的 Top10/Top30。
- **周环比各档（每天）：** 该行四档词数 vs 该行日期往前 7 天的同档词数（API 字段 `best_position` / `best_position_prev`），无对比基期则不写入该档环比。

**已删除字段及原因：**

- **Top10词数 / Top30词数 / 周环比Top30词**：改为 Ahrefs 四档分桶 + 四档周环比，与 API `best_position` 一致。

**明道云视图建议：** 按「日期」降序；异常预警 ≠ 正常 时条件着色。

---

### 4.2 表 2：站点关键词库

**用途：** 以 Ahrefs **站点排名词（Organic Keywords）** 为主数据源，运营只做 **分级与落地页标注**。

**Upsert 键：** `关键词`（一行一词，英文小写归一后唯一）

**导入规则（新）：**

- 同步时调用 Ahrefs `site-explorer/organic-keywords`（默认 Top 1000，可按排名/搜索量过滤）。
- **自动新建或更新行**；不再要求运营先手工录入关键词。
- 运营仅维护：优先级、类型、优化状态、关联落地页。


| 字段名   | 明道云类型 | 来源     | 说明                                                                                                               |
| ----- | ----- | ------ | ---------------------------------------------------------------------------------------------------------------- |
| 关键词   | 文本    | **导入** | Ahrefs `keyword`；唯一键                                                                                             |
| 搜索量   | 数值    | **导入** | 月搜索量                                                                                                             |
| KD    | 数值    | **导入** | 关键词难度 0–100                                                                                                      |
| CPC   | 数值    | **导入** | **Cost Per Click，单次点击成本，单位：美元 (**Ahrefs 点击出价：API 为 **USD 美分**，脚本 ÷100 写入 **美元**（保留 2 位小数，如 1.99）；缺省则价值分按 0.5 美元计 |
| 当前排名  | 数值    | **导入** | Google 自然排名；未进 Top100 留空                                                                                         |
| 排名变化  | 文本    | **导入** | 7 日对比：↑3 / ↓2 / 持平 / 未进Top100                                                                                    |
| 排名落地页 | 链接    | **导入** | Ahrefs 该词最佳排名 URL（organic-keywords 扩展字段）                                                                         |
| 数据日期  | 日期    | 脚本     | 本条 API 快照日期                                                                                                      |
| 优先级   | 单选    | **人工** | P0 / P1 / P2 / 未分级（默认未分级）                                                                                        |
| 关键词类型 | 单选    | **人工** | 产品词 / 工艺词 / 应用词 / 材质词 / 询盘词                                                                                      |
| 优化状态  | 单选    | **人工** | 未开始 / 优化中 / 已上Top30 / 已上Top10 / 停滞                                                                               |
| 关联落地页 | 链接    | **人工** | 计划优化的站内 URL，可与「排名落地页」对比                                                                                          |


**已删除字段及原因：**


| 原字段            | 原因                          |
| -------------- | --------------------------- |
| 转化意图           | 与「关键词类型」重叠，考核靠优先级即可         |
| 优化次数           | API 未实现，易误导考核               |
| 绑定页面URL（强制一对一） | 改为「关联落地页」+ API「排名落地页」，更贴近实际 |


**明道云视图建议：**

- 「P0/P1 待优化」：`优先级` in (P0,P1) 且 `当前排名` > 30  
- 「已进 Top10」：`当前排名` ≤ 10

**看板四档词数口径：** 来自 Ahrefs 有机词 API 在 **锚点日** 的 `best_position` 分档计数（见 §4.1）。**关键词表**仍可自建视图统计 `当前排名 ≤ 10/30` 或 `优先级 = P0/P1`，与看板列无关。

---

### 4.3 表 3：页面管理表

**用途：** 登记本站 **重点 URL**，汇总 **GSC 真实表现 + Ahrefs 页面级参考指标**，查看各独立站页面状态；执行与质检类字段由运营维护。

**与 Top pages / GSC Top 页面 的分工：**


| 表 / 报告                 | 用途                                                                        |
| ---------------------- | ------------------------------------------------------------------------- |
| **本表**                 | 人工登记 URL → 看「这些重点页」的收录、GSC 点击/展示/排名、Ahrefs UR/流量估算等 **站点运营状态**            |
| **GSC Top 页面明细**（§4.8） | GSC 自动 Top N × 国家 × 7 日，**发现**全站哪些 URL 有搜索流量                              |
| **Ahrefs Top pages**   | **不接**。全站有机页排序/发现，易与上表混淆；指标改由 **按 URL** 的 `metrics`、`crawled-pages` 等写入本表 |


**Upsert 键：** `独立站` + `页面URL`（每站 URL 唯一）

**页面URL 导入规则（GSC API 自动，不用人工填）：**


| 规则       | 说明                                                                                                               |
| -------- | ---------------------------------------------------------------------------------------------------------------- |
| **来源**   | 同步时 GSC Search Analytics，`dimensions: ["page"]`，锚点日 **全国家合计**（与 GSC Top 页面「分国家」表不同）                              |
| **自动新建** | 表中尚无该 URL，且 `**GSC展示量 ≥ PAGE_IMPORT_MIN_IMPRESSIONS`**（默认 1，即只要有展示）→ 脚本 `**addRow`** 写入 `页面URL` + `独立站` + `数据日期` |
| **不进表**  | 锚点日 **展示为 0** 的 URL（GSC 批量结果中不出现或 impressions=0）                                                                 |
| **上限**   | 按 GSC 点击降序最多取 `**PAGES_GSC_IMPORT_LIMIT`** 行（默认 1000，可与 `GSC_TOP_PAGES_LIMIT` 一致）                                |
| **首页**   | 各站 `homepage_url` 仍 **seed 一行**（无展示也保留，作为基准页）                                                                    |
| **人工**   | **不必**再从 GSC Top 表复制 URL；运营只补 **运营页面类型** 等人工列                                                                    |
| **不用**   | Ahrefs Top pages / 手工整表粘贴 URL                                                                                    |


**写入节奏：** 锚点日（与 `DATA_DELAY_DAYS` / `--anchor-date` 一致）；GSC **自动 import URL**（有展示）→ 对已存在行 **editRow** 更新 GSC + Ahrefs API 列；**运营页面类型 / 优化日期 / 优化记录 / 质量校验** 脚本不覆盖。

**仅跑页面表：**

```bat
run_sync.bat --skip-keywords --skip-backlinks --skip-dashboard --skip-gsc-top-queries --skip-gsc-top-pages
```

---

#### 字段定义（终稿）


| 字段名        | 明道云类型 | 建议    | API 来源                                                 | 来源         | 说明                                                                                                                |
| ---------- | ----- | ----- | ------------------------------------------------------ | ---------- | ----------------------------------------------------------------------------------------------------------------- |
| 独立站        | 单选    | 必填    | —                                                      | 脚本         | Upsert 键；五站 key                                                                                                   |
| 页面URL      | 链接    | 必填    | GSC `page` 维                                           | **GSC**    | 锚点日自动 import（展示≥阈值）                                                                                               |
| 运营页面类型     | 单选    | 新行必填  | —                                                      | **人工**     | 8 类单选；脚本不写                                                                                                        |
| Ahrefs页面类型 | 文本    | 只读    | `top-pages` → `page_type`                              | **Ahrefs** | UI 有 Page type；**API 常为 `null`**，有值才写入                                                                            |
| 主关键词       | 文本    | 只读    | `top-pages` → `top_keyword`；兜底有机词落地页                   | **Ahrefs** | 对应 Ahrefs UI **Top keyword**                                                                                      |
| 主词搜索量      | 数值    | 只读    | `top-pages` → `top_keyword_volume`                     | **Ahrefs** | 对应 Ahrefs UI **Volume**（Top keyword 右侧月搜索量）                                                                       |
| 发布日期       | 日期    | 只读    | `crawled-pages` → `first_seen`                         | **Ahrefs** | 首次爬到该 URL；≠ 实际上线日；**须 URL 与 crawled 索引匹配**                                                                        |
| 优化日期       | 日期    | 选填    | —                                                      | **人工**     | 脚本不写                                                                                                              |
| 优化记录       | 多行文本  | 选填    | —                                                      | **人工**     | 脚本不写                                                                                                              |
| 质量校验       | 单选    | 选填    | —                                                      | **人工**     | 脚本不写                                                                                                              |
| 收录状态       | 单选    | 只读    | GSC URL Inspection                                     | **GSC**    | 已收录 / 未收录 / 索引异常                                                                                                  |
| GSC点击      | 数值    | 只读    | GSC `page` 维锚点日                                        | **GSC**    | 全国家合计                                                                                                             |
| GSC展示量     | 数值    | 只读    | 同上                                                     | **GSC**    | 全国家合计                                                                                                             |
| GSC平均CTR   | 数值    | 只读    | 同上                                                     | **GSC**    | 0~1 小数                                                                                                            |
| GSC平均排名    | 数值    | 只读    | 同上                                                     | **GSC**    | 加权平均排名                                                                                                            |
| 数据日期       | 日期    | 只读    | 脚本                                                     | **脚本**     | 快照锚点日                                                                                                             |
| URL权重UR    | 数值    | 只读    | `top-pages` → `ur`；兜底 `crawled-pages` → `url_rating`   | **Ahrefs** | 0–100；须 URL 匹配                                                                                                    |
| 页面外链数      | 数值    | 只读    | `all-backlinks` 按 `url_to` 聚合                          | **Ahrefs** | 有外链的 URL 才有值                                                                                                      |
| 引用域名数      | 数值    | 只读    | 同上                                                     | **Ahrefs** | 同上                                                                                                                |
| Ahrefs月流量  | 数值    | 只读    | `top-pages` → `sum_traffic`；兜底 `metrics`               | **Ahrefs** | 估算月有机流量                                                                                                           |
| Ahrefs流量价值 | 数值    | 只读    | `top-pages` → `value`；兜底 `metrics` → `org_cost`        | **Ahrefs** | 美元（API 美分÷100）                                                                                                    |
| 排名关键词数     | 数值    | 只读    | `top-pages` → `keywords`；兜底 `metrics` → `org_keywords` | **Ahrefs** | 对应 Ahrefs UI **Keywords** 列                                                                                       |
| 页面字数       | 数值    | 只读；二期 | Site Explorer **无**页面正文字段                              | **Ahrefs** | UI **Words** 列；`top-pages` 的 `words` 是关键词词数且 **select 会 400**；可选二期 `site-audit/page-explorer` → `content_nr_word` |


**Ahrefs Top pages 界面 → 本表：**


| Ahrefs UI 列          | 本表字段                              |
| -------------------- | --------------------------------- |
| Top keyword          | 主关键词                              |
| Volume（最右列）          | 主词搜索量                             |
| Keywords             | 排名关键词数                            |
| Words                | 页面字数（**API 暂无，脚本不写**）             |
| Page type            | Ahrefs页面类型                        |
| Traffic / Value / UR | Ahrefs月流量 / Ahrefs流量价值 / URL权重UR  |
| （不在 Top pages 表）     | 发布日期 ← `crawled-pages.first_seen` |


---

#### API 字段写入、空白原因与排错（2026-06-06 实测）

**同步分两阶段（「update 跑完」= 第 2 阶段对该站每一行都成功 `editRow` 至少一次）：**


| 阶段            | 明道云操作     | 写入列                         |
| ------------- | --------- | --------------------------- |
| 1. GSC import | `addRow`  | **仅** 独立站 + 页面URL + 数据日期    |
| 2. 逐行 update  | `editRow` | GSC 四指标、收录状态、Ahrefs 各 API 列 |


表里**只有三列有值** = 只完成了第 1 阶段，或第 2 阶段中途失败（常见：**Mingdao / GSC 读超时**）。报告 `Mingdao writes: N total` 含页面表写入次数；`看板 create/update` 仅在本次跑了 dashboard 模块时才有数。

**各 API 字段：脚本是否已接、能否导出、空白常见原因：**


| 字段               | 脚本已接  | API 能否导出                 | 空白常见原因                                                                                        |
| ---------------- | ----- | ------------------------ | --------------------------------------------------------------------------------------------- |
| Ahrefs页面类型       | ✅     | ⚠️ 常为 `null`             | 锚点日 `top-pages` 无该行；即使 UI 有 Page type，API `page_type` 也常空；**非明道云文本类型问题**                      |
| 发布日期             | ✅     | ✅（须匹配 URL）               | GSC URL 与 `crawled-pages` 路径不一致（如 `/page` vs `/ar/page`）；含 `#锚点` 的 GSC URL；crawled 仅 1000 条上限 |
| URL权重UR          | ✅     | ✅（须匹配 URL）               | 同上；或该页在 crawled 中 `url_rating` 为 0                                                            |
| 主关键词             | ✅     | ✅（须命中 top-pages 或有机词落地页） | 小站锚点日 **US** `organic-keywords=0` 且 `top-pages=0`；URL 不在 Ahrefs Top 流量页内                      |
| 主词搜索量            | ✅     | ✅（同上）                    | 同上；对应 UI **Volume**，不是 Keywords 列                                                             |
| 排名关键词数           | ✅     | ✅（含 0）                   | API 为 0 时明道云可能显示为空；或未跑到 update                                                                |
| Ahrefs月流量 / 流量价值 | ✅     | ✅（有流量页）                  | 小站/长尾页 `org_traffic=0`、`org_cost` 空；无 top-pages 命中                                            |
| 页面外链数 / 引用域名数    | ✅     | ✅（有反链的 URL）              | 该 URL 在 `all-backlinks` 聚合中无记录                                                                |
| 页面字数             | ❌ 暂不写 | ❌ Site Explorer          | UI 有 Words；`top-pages` **不能** select `words`（400）；二期见 `site-audit` `content_nr_word`          |
| GSC 四指标 / 收录状态   | ✅     | ✅                        | 未跑到 update；或 Mingdao 超时中断                                                                     |


**锚点日 2026-05-30、国家 `us`（`sync-report` + API 对照）：**


| 站点            | top-pages | organic (us) | 主关键词等                          | 发布日期/UR                                    |
| ------------- | --------- | ------------ | ------------------------------ | ------------------------------------------ |
| fecision      | 0         | 0            | 多为空（**API 无数据**）               | crawled 495 条，但 **GSC/crawled URL 路径常不一致** |
| cncpioneer    | 0         | 0            | 多为空                            | 部分 crawled 匹配则有                            |
| drametal      | 0         | 0            | 多为空                            | crawled 99 条，匹配则有                          |
| lasermicrofab | 0         | 0            | 多数空；GSC 列可有                    | 少数行有发布日期                                   |
| richconn      | **56**    | **80**       | **仅 top-pages 命中行**有主关键词/主词搜索量 | crawled 497，匹配则有                           |


**报告里要看的行（`reports/sync-report-*.txt`）：**

- `Ahrefs site-explorer/top-pages (page enrich) … urls=N` — 锚点日索引条数
- `organic-keywords … count=N` — US 有机词总数
- `[WRITE] 页面管理表 update … 主关键词=…` — 该行脚本算出的值（`None` = API 无）
- `Per site: FAIL — … Read timed out` — 超时后后续行未 update

**运维：**

- 明道云超时：`.env` 设 `MINGDAO_REQUEST_TIMEOUT=120`（默认已 120，VPN 慢可 **180**）；单次请求自动重试 3 次
- 五站分站补跑（建议 VPN 稳定时跑，大站 1～3 小时/站）：

```bat
run_sync.bat --skip-keywords --skip-backlinks --skip-dashboard --skip-gsc-top-queries --skip-gsc-top-pages --anchor-date 2026-05-30 --site cncpioneer
run_sync.bat --skip-keywords --skip-backlinks --skip-dashboard --skip-gsc-top-queries --skip-gsc-top-pages --anchor-date 2026-05-30 --site fecision
run_sync.bat --skip-keywords --skip-backlinks --skip-dashboard --skip-gsc-top-queries --skip-gsc-top-pages --anchor-date 2026-05-30 --site richconn
run_sync.bat --skip-keywords --skip-backlinks --skip-dashboard --skip-gsc-top-queries --skip-gsc-top-pages --anchor-date 2026-05-30 --site lasermicrofab
run_sync.bat --skip-keywords --skip-backlinks --skip-dashboard --skip-gsc-top-queries --skip-gsc-top-pages --anchor-date 2026-05-30 --site drametal
```

- `pages.index_status_option_keys` 须用 **收录状态** 字段真实 option UUID，**勿复用独立站** key

**总结：** 页面表 Ahrefs 列 **逻辑均已接入**（页面字数除外）；表内大面积空白，主因是 **Ahrefs 锚点日/US 无有机快照**、**GSC URL 与 crawled/top-pages 路径对不上**、`**page_type` API 常 null**，以及 **sync 中途 Mingdao/GSC 超时未跑完 update**——不是「文本字段不能导出」。有流量的 richconn 命中 top-pages 的行，报告里可见 `主关键词='…'` 已成功写入。

`**.env` 键名（覆盖 `mingdao_worksheets.json`）：** 见 §7 `MINGDAO_WORKSHEET_PAGES`、`MINGDAO_FIELD_PAGE_`*；明道云列「发布日期」= `MINGDAO_FIELD_PAGE_AHREFS_FIRST_SEEN`；超时 = `MINGDAO_REQUEST_TIMEOUT`。

---

#### 明道云建表注意

1. **单选选项文字**与上表 **完全一致**（含「运营页面类型」8 项、「收录状态」「质量校验」）。
2. **API 字段**建议字段级权限：运营只读，脚本账号可写。
3. **百分比**：若「GSC平均CTR」用百分比控件，写入规则同看板（0~1 小数）。
4. 字段 ID 写入 `config/mingdao_worksheets.json` 的 `pages.fields`，并用 `.env` 的 `MINGDAO_FIELD_PAGE_`* 覆盖（与看板、GSC Top 写法一致）。

---

#### 已删除 / 不再使用


| 原字段                    | 原因                                            |
| ---------------------- | --------------------------------------------- |
| 页面类型（旧单选：首页等）          | 拆为 **运营页面类型**（人工 8 类）+ **Ahrefs页面类型**（API 文本） |
| 页面流量                   | 改名为 **GSC点击**，与 Ahrefs 流量区分                   |
| 页面字数、H1/H2、内链数、ALT、CTA | 不 API 校验；必要时写进「优化记录」                          |
| 绑定核心关键词（1+5）           | 改为「关联关键词」                                     |
| 通过 **top-pages** 导入本表  | 已明确取消；Top 发现只用 GSC Top 页面表                    |


**填写注意：** 跑 `sync_pages` 前须已配置 `pages` 工作表字段 ID。新行 **运营页面类型** 仍须运营在明道云补填（脚本不写入）。首页由 `config/sites.json` → `homepage_url` **seed**（若尚无）。

**环境变量（页面 URL 自动导入）：**

```env
PAGES_GSC_IMPORT_LIMIT=1000
PAGE_IMPORT_MIN_IMPRESSIONS=1
```

---

### 4.4 表 4：外链监控表

**用途：** 以 Ahrefs **全部有效外链** 为数据源；主管审核是否「合格 RD」。

**Upsert 键：** `来源URL` + `目标URL`（组合唯一；同一来源链到多页则多行）

**导入规则（新）：**

- 同步时调用 Ahrefs `site-explorer/all-backlinks`（live 外链，建议 limit 按套餐控制）。
- **自动新建或更新**；运营不再手工填「来源域名」。
- 主管维护：行业相关性、审核结果、违规说明。


| 字段名        | 明道云类型 | 来源     | 说明                            |
| ---------- | ----- | ------ | ----------------------------- |
| 来源域名       | 文本    | **导入** | 从来源 URL 解析，便于分组               |
| 来源URL      | 链接    | **导入** | 外链所在页面                        |
| 目标URL      | 链接    | **导入** | 指向本站 URL                      |
| 锚文本        | 文本    | **导入** | Ahrefs anchor                 |
| 域名DR       | 数值    | **导入** | 来源域 DR；内部合格线建议 DR≥30          |
| 是否Dofollow | 单选    | **导入** | 是 / 否                         |
| 首次发现       | 日期    | **导入** | Ahrefs first_seen             |
| 外链存活       | 单选    | **导入** | 有效 / 已失效（对应 Ahrefs live/lost） |
| 数据日期       | 日期    | 脚本     | 本条快照日期                        |
| 行业相关性      | 单选    | **人工** | 高度相关 / 一般 / 不相关               |
| 审核结果       | 单选    | **人工** | 合格 / 不合格 / 待审核                |
| 违规说明       | 多行文本  | **人工** | 不合格原因                         |


**已删除字段及原因：**


| 原字段            | 原因                          |
| -------------- | --------------------------- |
| 外链发布日期         | 用 API「首次发现」替代               |
| 外链类型           | Ahrefs 类型与运营分类不一致，审核时人工判断即可 |
| 外链收录状态         | 改名为「外链存活」，避免与 Google 收录混淆   |
| 是否dofollow（人工） | 改由 API 导入                   |


**明道云视图建议：** 「合格 RD」=`审核结果=合格` 且 `外链存活=有效` 且 `域名DR≥30`。

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


**已删除字段及原因：**


| 原字段             | 原因                 |
| --------------- | ------------------ |
| 当日新增内链总数、技术修复数量 | 难核实，与 API 无关       |
| 当日合格RD数量        | 改由外链表视图统计，不在日日志重复填 |
| 当日合规（系统自动）      | 改主管/运营人工判定         |


---

### 4.6 表 5B：周绩效复盘

**用途：** 每周日复盘；**以人工为主**，数字类指标在明道云用 **汇总视图 / 关联记录** 核对。

**Upsert 键：** `周次` + `运营人`（周次示例：`2026-W22`）


| 字段名       | 明道云类型 | 来源     | 说明                      |
| --------- | ----- | ------ | ----------------------- |
| 周次        | 文本    | **人工** | 如 2026-W22              |
| 运营人       | 成员    | **人工** |                         |
| 本周Top30净增 | 数值    | **人工** | 对照看板四档词数/周环比或关键词表（旧名保留） |
| 本周合格RD数   | 数值    | **人工** | 对照外链表合格视图               |
| 本周新增页面数   | 数值    | **人工** | 对照页面表发布日期               |
| 本周优化页面数   | 数值    | **人工** | 对照页面表优化记录               |
| 本周有效动作总结  | 多行文本  | **人工** | ≥3 条                    |
| 本周无效动作总结  | 多行文本  | **人工** | ≥3 条                    |
| 问题根因分析    | 多行文本  | **人工** |                         |
| 下周KPI     | 多行文本  | **人工** | 可量化                     |
| 周考核等级     | 单选    | **人工** | 优秀 / 合格 / 不合格           |


**已删除字段及原因：**


| 原字段             | 原因                    |
| --------------- | --------------------- |
| OKR完成度          | 无稳定 API 口径，易空填        |
| 技术问题修复总数        | 无 API 支撑              |
| 核心词Top30净增长（自动） | 改为人工对照看板填写「本周Top30净增」 |


---

### 4.7 表 7：GSC Top 查询明细

**用途：** 五站各自 GSC 资源下，**搜索词（query）** 维度的 Top 明细，按 **国家** 拆分；**全部自动**，禁止人工改数。

**Upsert 键：** `数据日期` + `独立站` + `关键词` + `国家`（同一词在不同国家各一行）

**写入节奏：**


| 类型       | 规则                                                                |
| -------- | ----------------------------------------------------------------- |
| **同步窗口** | 与看板同一 **7 日窗口**：锚点−6 … 锚点（例 5/24～5/30）；**每天**各调一次 GSC             |
| **API**  | `startDate = endDate = 该行数据日期`，`dimensions: ["query", "country"]` |
| **排序**   | 按 **点击** 降序取 Top N（脚本默认 **1000** 行/站，可配置 `GSC_TOP_QUERIES_LIMIT`） |
| **五站**   | 每站读各自 `gsc_site_url`（见 `config/sites.json`），写入时带 `独立站` 单选         |


**与看板区别：** 看板「全站加权平均排名」是 **全站单日汇总**；本表「平均排名」是 **该 query 在该国当日的 query 级加权平均排名**，不可混读。


| 字段名   | 明道云类型 | 来源  | 说明                                                                                                     |
| ----- | ----- | --- | ------------------------------------------------------------------------------------------------------ |
| 数据日期  | 日期    | 脚本  | GSC 统计所属日期（**非**脚本执行时刻）；必填                                                                             |
| 独立站   | 单选    | 脚本  | `cncpioneer` / `fecision` / `richconn` / `lasermicrofab` / `drametal`；与 `config/sites.json` 的 `key` 一致 |
| 关键词   | 文本    | GSC | Search Analytics 的 `query` 原文；Upsert 键之一                                                               |
| 国家    | 单选    | GSC | **ISO 3166-1 alpha-3 小写**（如 `usa`、`gbr`、`ind`）；Upsert 键之一；选项须预先建好，见下「国家单选选项」                           |
| 点击    | 数值    | GSC | 该词在该国 **当日** 自然搜索点击（Clicks）                                                                            |
| 展示量   | 数值    | GSC | **当日** 展示次数（Impressions）                                                                               |
| 平均CTR | 数值    | GSC | **当日** CTR，0~1 小数；百分比控件写入 0.052 = 5.2%                                                                 |
| 平均排名  | 数值    | GSC | **当日** 该 query+country 的加权平均排名（Position）；未展示时可留空                                                       |


**明道云视图建议：** 按「数据日期」降序 + `点击` 降序；筛选 `独立站` + `国家 = usa` 看美国 Top 词。

**独立站单选选项（须与现有表一致）：** `cncpioneer`、`fecision`、`richconn`、`lasermicrofab`、`drametal`

**国家单选选项（两表共用同一套选项文字）：**

- **可以设为单选**，便于视图筛选；脚本写入的选项名须与明道云 **完全一致**（小写三字母码，无空格）。
- GSC 返回即为此格式；若某国 **尚未建选项**，同步会跳过该行并在 report **Warnings 列出国家码**（如 `lasermicrofab GSC Top 查询 缺少国家单选选项，跳过 2 行: bih×2`），补选项后重跑即可。
- **建议首批预建**（按 B2B 独立站常见流量国，可按需增减）：

`usa` · `gbr` · `deu` · `aus` · `can` · `ind` · `fra` · `ita` · `esp` · `nld` · `jpn` · `kor` · `bra` · `mex` · `pol` · `swe` · `che` · `aut` · `bel` · `sgp` · `hkg` · `twn` · `tha` · `vnm` · `phl` · `idn` · `mys` · `nzl` · `zaf` · `are` · `sau` · `tur` · `rus` · `ukr` · `chn`

- 建表后把各国家选项 key 写入 `config/mingdao_worksheets.json` → `gsc_top_queries.country_option_keys` / `gsc_top_pages.country_option_keys`（与 `独立站` 写法相同）。

---

### 4.8 表 8：GSC Top 页面明细

**用途：** 五站各自 GSC 资源下，**落地页（page）** 维度的 Top 明细，按 **国家** 拆分；**全部自动**，禁止人工改数。

**Upsert 键：** `数据日期` + `独立站` + `页面URL` + `国家`（同一 URL 在不同国家各一行）

**写入节奏：**


| 类型       | 规则                                                               |
| -------- | ---------------------------------------------------------------- |
| **同步窗口** | 与表 7 相同：锚点起 **7 日**，每天一行                                         |
| **API**  | `startDate = endDate = 该行数据日期`，`dimensions: ["page", "country"]` |
| **排序**   | 按 **点击** 降序取 Top N（脚本默认 **1000** 行/站，可配置 `GSC_TOP_PAGES_LIMIT`）  |
| **URL**  | 写入 GSC 返回的 page 字符串（可能与浏览器栏 www/协议略有差异，以 GSC 为准）                 |



| 字段名   | 明道云类型 | 来源  | 说明                               |
| ----- | ----- | --- | -------------------------------- |
| 数据日期  | 日期    | 脚本  | GSC 统计所属日期；必填                    |
| 独立站   | 单选    | 脚本  | 同上五站 key                         |
| 页面URL | 链接    | GSC | 完整 URL（`https://...`）；Upsert 键之一 |
| 国家    | 单选    | GSC | 同表 7；两表 **共用同一套国家选项**            |
| 点击    | 数值    | GSC | 该 URL 在该国 **当日** 自然搜索点击          |
| 展示量   | 数值    | GSC | **当日** 展示次数                      |
| 平均CTR | 数值    | GSC | **当日** CTR，0~1 小数                |
| 平均排名  | 数值    | GSC | **当日** 该 page+country 的加权平均排名    |


**与「页面管理表」区别：** 页面管理表是 **人工登记重点 URL** + 单 URL 流量/收录；本表是 GSC **自动 Top 页面全量/Top N 快照**，二者互补，不互相替代。

**明道云视图建议：** 按「数据日期」降序 + `点击` 降序；按 `独立站` 分组看各站流量页。

---

## 5. Upsert 规则汇总


| 工作表          | 唯一键                     | 同步行为                                     |
| ------------ | ----------------------- | ---------------------------------------- |
| SEO 自动数据看板   | 日期 + 独立站                | 有则更新，无则新增（每站 7 日窗口各一行）                   |
| 站点关键词库       | 关键词                     | **Ahrefs 导入** upsert                     |
| 页面管理表        | 独立站 + 页面URL             | **GSC 自动新建**（展示≥阈值）+ 更新 API 字段；可 seed 首页 |
| 外链监控表        | 来源URL + 目标URL           | **Ahrefs 导入** upsert                     |
| GSC Top 查询明细 | 数据日期 + 独立站 + 关键词 + 国家   | **GSC 导入** upsert（7 日窗口 × 五站，每日 Top N）   |
| GSC Top 页面明细 | 数据日期 + 独立站 + 页面URL + 国家 | **GSC 导入** upsert（7 日窗口 × 五站，每日 Top N）   |
| 每日执行日志       | 日期 + 运营人                | 脚本不写                                     |
| 周绩效复盘        | 周次 + 运营人                | 脚本不写                                     |


---

## 6. 明道云应用结构建议

```
应用：SEO 数据看板
├── 工作表1  SEO自动数据看板      ← GSC + Ahrefs API
├── 工作表2  站点关键词库          ← Ahrefs 导入 + 人工标注
├── 工作表3  页面管理表            ← 人工 URL + GSC/Ahrefs 按 URL（不接 top-pages）
├── 工作表4  外链监控表            ← Ahrefs 导入 + 人工审核
├── 工作表5  GSC Top 查询明细      ← GSC query × country（五站）
├── 工作表6  GSC Top 页面明细      ← GSC page × country（五站）
├── 工作表7  SEO每日执行日志       ← 纯人工
└── 工作表8  周绩效复盘            ← 纯人工
```

**权限建议（与 need.docx 一致）：**

- 看板、关键词 API 字段：运营 **只读**，IT/脚本账号可写  
- 页面、外链：运营可编辑人工字段，不可改 API 字段（明道云字段级权限）  
- 审核类字段：仅主管可写

---

## 7. 环境变量（明道云版预览）

原飞书变量将替换为明道云；建表后从 API 文档复制 ID：

```env
# 明道云
MINGDAO_APP_KEY=
MINGDAO_SIGN=
MINGDAO_WORKSHEET_DASHBOARD=
MINGDAO_WORKSHEET_KEYWORDS=
MINGDAO_WORKSHEET_PAGES=
# 页面管理表字段（列名「发布日期」= AHREFS_FIRST_SEEN）
# MINGDAO_FIELD_PAGE_SITE=
# MINGDAO_FIELD_PAGE_URL=
# MINGDAO_FIELD_PAGE_AHREFS_TYPE=
# MINGDAO_FIELD_PAGE_AHREFS_FIRST_SEEN=
# MINGDAO_FIELD_PAGE_WORD_COUNT=
# MINGDAO_FIELD_PAGE_PRIMARY_KEYWORD=
# MINGDAO_FIELD_PAGE_PRIMARY_KEYWORD_VOLUME=
# MINGDAO_FIELD_PAGE_INDEX_STATUS=
# MINGDAO_FIELD_PAGE_CLICKS=
# MINGDAO_FIELD_PAGE_IMPRESSIONS=
# MINGDAO_FIELD_PAGE_CTR=
# MINGDAO_FIELD_PAGE_POSITION=
# MINGDAO_FIELD_PAGE_DATA_DATE=
# MINGDAO_FIELD_PAGE_UR=
# MINGDAO_FIELD_PAGE_BACKLINKS=
# MINGDAO_FIELD_PAGE_REF_DOMAINS=
# MINGDAO_FIELD_PAGE_AHREFS_TRAFFIC=
# MINGDAO_FIELD_PAGE_AHREFS_VALUE=
# MINGDAO_FIELD_PAGE_KEYWORD_COUNT=
# PAGES_GSC_IMPORT_LIMIT=1000
# PAGE_IMPORT_MIN_IMPRESSIONS=1
MINGDAO_WORKSHEET_BACKLINKS=
# GSC Top 明细（建表后填 worksheetId + 各字段 controlId）
# MINGDAO_WORKSHEET_GSC_TOP_QUERIES=
# MINGDAO_WORKSHEET_GSC_TOP_PAGES=
# MINGDAO_FIELD_GSC_QUERY_DATA_DATE=
# MINGDAO_FIELD_GSC_QUERY_SITE=
# MINGDAO_FIELD_GSC_QUERY_KEYWORD=
# MINGDAO_FIELD_GSC_QUERY_COUNTRY=
# MINGDAO_FIELD_GSC_QUERY_CLICKS=
# MINGDAO_FIELD_GSC_QUERY_IMPRESSIONS=
# MINGDAO_FIELD_GSC_QUERY_CTR=
# MINGDAO_FIELD_GSC_QUERY_POSITION=
# MINGDAO_FIELD_GSC_PAGE_DATA_DATE=
# MINGDAO_FIELD_GSC_PAGE_SITE=
# MINGDAO_FIELD_GSC_PAGE_URL=
# MINGDAO_FIELD_GSC_PAGE_COUNTRY=
# MINGDAO_FIELD_GSC_PAGE_CLICKS=
# MINGDAO_FIELD_GSC_PAGE_IMPRESSIONS=
# MINGDAO_FIELD_GSC_PAGE_CTR=
# MINGDAO_FIELD_GSC_PAGE_POSITION=
# GSC_TOP_QUERIES_LIMIT=1000
# GSC_TOP_PAGES_LIMIT=1000
# 看板可选列（明道云建列后填 controlId）
# MINGDAO_FIELD_DASH_WEEKLY_AVG_POSITION=
# MINGDAO_FIELD_DASH_WEEKLY_CLICKS=
# 站点关键词库可选列
# MINGDAO_FIELD_KEYWORD_CPC=
# MINGDAO_FIELD_KEYWORD_VALUE_SCORE=
# 日日志、周复盘可选，同步脚本暂不写入
MINGDAO_WORKSHEET_DAILY_LOG=
MINGDAO_WORKSHEET_WEEKLY_REVIEW=

# GSC / Ahrefs（不变）
GSC_SITE_URL=https://www.cncpioneer.com/
GOOGLE_AUTH_MODE=oauth
AHREFS_API_TOKEN=
AHREFS_TARGET_DOMAIN=cncpioneer.com
AHREFS_TARGET_COUNTRY=us

SYNC_TIMEZONE=Asia/Shanghai
DATA_DELAY_DAYS=2
```

---

## 8. 与原方案差异一览


| 项     | 原方案（飞书）         | 终稿（明道云）                          |
| ----- | --------------- | -------------------------------- |
| 关键词   | 运营先填词，API 只更新   | **Ahrefs organic 词库导入**，运营只标注    |
| 外链    | 运营先填来源域名        | **Ahrefs all-backlinks 导入**，主管审核 |
| 看板字段名 | 易误解（全站收录、单日 RD） | 改为准确口径（见 4.1）                    |
| 页面表   | 10+ 合规细项        | 保留 URL + 执行记录 + GSC 指标           |
| 执行/复盘 | 部分写「系统自动」       | 未实现自动的一律标 **人工**                 |
| 平台    | 飞书 Bitable      | **明道云工作表 + Open API**            |


---

## 9. 建表后自检清单

- 8 张工作表已创建，单选选项与本文 **完全一致**（含 `独立站` 五选项 + GSC Top 两表 `**国家` 单选选项**）
- 各表 Upsert 键字段设为 **必填** 且 **不可重复**（明道云可配字段校验）
- 已开启应用 API，并记录各 `worksheetId`、`controlId`
- 页面表至少录入首页 + 3 个重点落地页 URL
- 跑通一次同步后：看板有数、关键词/外链表有 Ahrefs 导入行、页面表有流量/收录；GSC Top 两表在 **7 日窗口**内各有 Top 行（含 `数据日期` + `国家`）

---

## 10. 常见问题

**Q：还要不要先去 Ahrefs 网页看 Organic Keywords？**  
A：建议看一次便于理解导入内容；正式数据以 API 导入到「站点关键词库」为准。

**Q：某几天四档词数为空？**  
检查该日 Ahrefs 是否有历史快照、网络是否在有机词请求阶段超时；`sync-report` 应按日期出现多条 `organic-keywords date=YYYY-MM-DD`。

**Q：四档词数全是 0？**  
A：看板不依赖关键词表，直接读 Ahrefs `organic-keywords`（锚点日）。新站词少、国家码不匹配（如应用 `us` 但词主要在其它国）、或 Ahrefs 该日无快照时可能为 0；`sync-report` 里应有 `organic-keywords count=N`。

**Q：外链表会不会把垃圾链也导入？**  
A：会。导入后靠 `域名DR`、`外链存活` 筛选 + 主管 `审核结果` 控制绩效。

**Q：页面表能否也从 API 自动发现 URL？**  
A：**不用人工填 URL。** 脚本按锚点日 GSC `page` 维自动 `addRow`（展示≥阈值）；全站分国家明细看 **GSC Top 页面明细**（§4.8）。**不接 Ahrefs Top pages 批量发现**；Ahrefs 按 URL 补字段见 §4.3「API 字段写入、空白原因与排错」。

**Q：页面表 Ahrefs 列全是空的，是字段 ID 错还是没接 API？**  
A：先看 `sync-report` 是否跑完 **update**（不只 import 三列）、`top-pages urls=` 与 `organic-keywords count=`。逻辑已接；空白多为 **API 无数据**、**URL 不匹配**、**page_type 为 null** 或 **超时中断**。详见 §4.3 排错表。

**Q：运营页面类型和 Ahrefs 页面类型为什么要两列？**  
A：**运营页面类型**（8 类单选）用于考核与排期；**Ahrefs页面类型**（文本）为 API/导出原文，便于对标 Ahrefs 分类。二者不一致时以运营列为准做流程，以 Ahrefs 列做参考。

**Q：页面 URL 还要人工填吗？**  
A：**不用。** 跑同步时由 GSC API 按锚点日自动 `addRow`（`展示量 ≥ PAGE_IMPORT_MIN_IMPRESSIONS`，默认 1）。运营只需补 **运营页面类型** 等人工列。全站分国家明细仍看 **GSC Top 页面明细**；本表为 **page 维全国家合计** 的重点页状态表。

**Q：GSC Top 查询与 Ahrefs 关键词表、看板四档词数有何区别？**  
A：Top 查询表是 GSC **query × country** 当日点击/展示/排名；关键词表是 Ahrefs 有机词库；看板四档是 Ahrefs **best_position 分档计数**。三者口径不同，不要对同一列做交叉校验。

**Q：`国家` 用单选还是文本？**  
A：**推荐单选**（与 `独立站` 一致，视图更好筛）。选项文字用 GSC 的 ISO 3166-1 alpha-3 **小写**（如 `usa`）；须预先建齐，脚本通过 `country_option_keys` 映射写入。若 GSC 出现未建选项的国家，该行跳过；**sync-report Warnings 会列出国家码及跳过行数**（如 `bih×3`），在明道云补选项后重跑即可。

---

*文档版本：2026-06-06 · §4.3 页面表：GSC 自动 import + Ahrefs 按 URL 补字段；§4.3 增 API 排错与 Ahrefs UI 对照*