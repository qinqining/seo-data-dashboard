# GSC Top 查询明细 — Ahrefs 补数字段与脚本方案

**文档日期**：2026-06-08  
**读者**：运营、明道云建表、对接脚本的同事  
**状态**：**P1 已实现**（`script/sync.py` → `enrich_gsc_top_queries`）；须在明道云加列并配置 controlId 后启用。  
**相关**：`docs/dashboard.md` §4.7、`docs/20260608note_optimize.md`、`.cursor_checkpoint.md`

**说明**：本文替代原 `docs/20260605note.md` 中的 enrich 方案；Overview / CPC 概念说明仍见下文 §5、§6。

---

## 1. 要做什么

在 **GSC Top 查询明细** 已有 GSC 字段基础上，按 **关键词 + 国家** 调用 Ahrefs **`keywords-explorer/overview`**，把 **市场侧指标** 写回 **同一行**（`editRow`，不新建表）。

```
GSC 写入（已有）          Ahrefs enrich（待做）
─────────────────        ─────────────────────
关键词、国家、点击…   →    Ahrefs搜索量、Ahrefs KD、Ahrefs CPC
```

**Upsert 键不变：** `数据日期` + `独立站` + `关键词` + `国家`

---

## 2. 明道云要加哪些字段

### 2.1 首期必加（推荐列名）

与 GSC 字段区分开，列名带 **Ahrefs** 前缀；口径与 **站点关键词库** §4.2 的搜索量/KD/CPC **一致**。

| 字段名 | 明道云类型 | 建议 | 来源 | Ahrefs API 字段 | 说明 |
|--------|------------|------|------|-----------------|------|
| **Ahrefs搜索量** | **数值** | 只读 | Ahrefs | `volume` | 月搜索量（按国家）；**可以**，即你说的 Ahrefs Volume |
| **Ahrefs KD** | **数值** | 只读 | Ahrefs | `difficulty` 或 `kd` | 关键词难度 0–100 |
| **Ahrefs CPC** | **数值** | 只读 | Ahrefs | `cpc` | 单次点击成本，**美元**（API 美分 ÷100，保留 2 位小数） |

**不要改名的 GSC 列（脚本已有）：** 关键词、国家、点击、展示量、平均CTR、平均排名、数据日期、独立站。

**明道云控件建议：**

| 字段 | 控件 |
|------|------|
| Ahrefs搜索量 | 数值，整数即可 |
| Ahrefs KD | 数值，0–100 |
| Ahrefs CPC | 数值或金额，小数 2 位 |

**有值才写入：** API 无该词数据时 **留空**，不写 0（避免与「真实为 0」混淆）。

### 2.2 二期可选（首期不做）

| 字段名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| Ahrefs排名 | 数值 | `organic-keywords`（若该词已在站内有排名） | 与 GSC「平均排名」口径不同，勿混读 |
| Ahrefs排名变化 | 文本 | 同上 | ↑3 / ↓2 / 持平 |
| Ahrefs排名落地页 | 链接 | 同上 | 该词在 Ahrefs 的最佳 URL |
| Ahrefs补数日期 | 日期 | 脚本 | overview 快照日，默认可用锚点日 |

首期优先 **overview 三列**，实现简单，且覆盖「GSC 有、有机词库 Top 1000 没有」的长尾词。

### 2.3 建表后配置

1. 在明道云 **GSC Top 查询明细** 工作表添加上述三列。  
2. 把各列 `controlId` 写入：
   - `config/mingdao_worksheets.json` → `gsc_top_queries.fields`
   - `.env`（推荐）：

```env
MINGDAO_FIELD_GSC_QUERY_AHREFS_VOLUME=
MINGDAO_FIELD_GSC_QUERY_AHREFS_KD=
MINGDAO_FIELD_GSC_QUERY_AHREFS_CPC=
```

3. 与关键词表对照：关键词表列名是「搜索量 / KD / CPC」；本表用 **Ahrefs搜索量** 等，避免和 GSC 指标搞混。

---

## 3. 脚本怎么写（单独 py 还是写在 sync 里）

### 3.1 推荐：**逻辑在 `sync.py`，不必单独新仓库**

| 方式 | 做法 | 适用 |
|------|------|------|
| **推荐** | 在 `script/sync.py` 增加 `enrich_gsc_top_queries()`，在 `sync_gsc_top_queries()` **之后**调用 | 与现有 `run_sync.bat` 一条命令跑完 GSC + Ahrefs |
| **可选** | 另建 `script/enrich_gsc_top_queries.py`，**只 import sync 里的函数**，便于「只补 Ahrefs、不重拉 GSC」 | 省 GSC API、只补失败行时 |

**不建议：** 完全独立、复制一套 Mingdao/Ahrefs 客户端的脚本（难维护）。

### 3.2 建议的流水线

```
sync_site()
  ├── sync_gsc_top_queries()     # 已有：GSC query×country → addRow/editRow
  └── enrich_gsc_top_queries()   # 新增：读表 → overview → editRow 写 Ahrefs 三列
```

### 3.3 CLI 开关（已实现）

```bat
# 默认：GSC Top 查询 sync 后自动 enrich
run_sync.bat --skip-keywords --skip-pages ...

# 只跳过 Ahrefs 补数（仍拉 GSC）
run_sync.bat --skip-gsc-top-queries-enrich ...

# 只补 Ahrefs 三列（不重拉 GSC）
run_sync.bat --only-gsc-top-queries-enrich --site richconn --anchor-date 2026-05-30
```

### 3.4 enrich 实现要点

1. **去重：** 7 日窗口内同一 `关键词 + 国家` 只调 **1 次** overview，结果写回该组合的所有日期行。  
2. **国家映射：** GSC `usa` → Ahrefs `us`（alpha-3 → alpha-2）。  
3. **控量（拍板默认值，可 env 覆盖）：**
   - 建议首期：**仅 enrich 7 日内总点击 > 0 的去重词**，或 **每站最多 500 去重 query×country**（取总点击 Top）。  
   - 可选 **国家白名单**：先做 `usa`。  
4. **缓存：** 内存 + 可选本地 JSON，避免同周重复扣 Ahrefs 额度。  
5. **失败：** overview 失败 **跳过该行 Ahrefs 列**，不写假数据；report 记 `[SKIP]` / Warnings。

---

## 4. 运营怎么用（补数后）

| 视图 | 筛选 |
|------|------|
| 高价值低难度 | `国家=usa` · `点击>0` · **Ahrefs KD < 30** · **Ahrefs CPC** 偏高 |
| 大盘机会 | **Ahrefs搜索量** 高 · GSC 点击仍低 · 平均排名 11–30 |
| 长尾已起量 | GSC 点击高 · **Ahrefs搜索量** 低（品牌/长尾） |

**决策权重：** 点击/展示/排名 → **GSC**；盘子/难度/商业价值 → **Ahrefs 三列**。

---

## 5. 与关键词库、看板的区别

| 表 | 看什么 |
|----|--------|
| **GSC Top 查询 + Ahrefs 三列** | 用户 **真实搜了啥** + 该词 **市场上** 多大、多难、多值钱 |
| **站点关键词库** | 全站 **排名词资产** + 人工 P0/P1、落地页 |
| **看板四档词数** | 整站 SEO **趋势**，不是词级清单 |

FAQ：**不要用 Ahrefs排名 和 GSC 平均排名做「是否一致」的校验。**

---

## 6. Overview / CPC 概念（简）

- **Overview API：** `keywords-explorer/overview`，传入 **词 + 国家**，返回词库市场指标（**不要求**你站已排名）。  
- **CPC：** Ahrefs 估算的广告点击成本，**不是**你 Google Ads 账单；看 **商业强度** 用。  
- **Volume / KD / CPC：** 均为 Ahrefs **模型估算**，与 GSC 实测不能逐词对平。

---

## 7. 开发前检查清单

- [ ] 明道云已加 **Ahrefs搜索量、Ahrefs KD、Ahrefs CPC** 三列（数值、只读）  
- [ ] `mingdao_worksheets.json` + `.env` 已填 controlId  
- [ ] 拍板 enrich 策略：去重 Top 500 或「仅点击>0」、是否只做 usa  
- [ ] `sync.py` 实现 `enrich_gsc_top_queries` + CLI 开关  
- [ ] 更新 `docs/dashboard.md` §4.7 字段表  
- [ ] 单站试跑 `--site richconn`，核对 report 与明道云几行样本  

---

## 8. 「Top N」与「点击 > 0」（enrich 策略）

| 说法 | 含义 |
|------|------|
| **Top N**（如 1000） | GSC 拉数按点击排序，**最多 N 行/天**（`GSC_TOP_QUERIES_LIMIT`） |
| **点击 > 0** | 该行当日该国 **至少有 1 次点击** |
| **Top 500 去重 enrich** | 7 天内总点击最高的 **500 个不重复词×国**，控制 Ahrefs 调用次数 |

Top 1000 **尾部常有展示、点击 0**；enrich 时可 **不查 Ahrefs** 以省 API。

---

*文档版本：2026-06-08 · 替代 20260605note 中的 GSC Top enrich 方案；原 20260605note 保留 Overview/CPC 延伸阅读时可合并查阅。*
