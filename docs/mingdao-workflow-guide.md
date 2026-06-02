# 明道云工作流接入 GSC + Ahrefs 教程

本地 `script/sync.py` **继续保留**，本教程是在明道云里**另开一条线**，用「连接 + 工作流定时」看自动调 API 的效果。两边可以并行对比。

> **更省事的做法**：直接用工作流 **Python 代码块** 跑完整同步，不用配连接/API 输入参数。见 **[Python 代码块教程](mingdao-workflow-python.md)**（推荐，可替代 run_sync.bat 定时）。

---

## 先搞清：两种接法怎么选

| 方式 | GSC | Ahrefs | 定时 | 难度 |
|------|-----|--------|------|------|
| **A. 明道云原生工作流** | 用 refresh_token 换 access_token（见下文） | Bearer Token，很好配 | 工作流「定时触发」 | Ahrefs 低，GSC 中 |
| **B. 本地脚本 + 计划任务** | `sync.py` + `token.json`（已跑通） | 同上 | Windows 任务计划 / `run_sync.bat` | 最低 |
| **C. 工作流 Webhook → 本地脚本** | 脚本里已有 | 脚本里已有 | 明道云定时发 Webhook | 需内网穿透 |

**建议学习顺序：**

1. 先在明道云接 **Ahrefs**（10 分钟能看到 API 返回 JSON）
2. 再建 **Google GSC 连接**（不要用 client_credentials，用 refresh_token）
3. 最后搭 **定时工作流**，把数据写入「SEO自动数据看板」

---

## 准备工作（从你现有项目复制）

打开项目里的这些文件，**不要删**，只复制值到明道云：

| 用途 | 来源 | 明道云里填到哪里 |
|------|------|------------------|
| Ahrefs Token | `.env` → `AHREFS_API_TOKEN` | Ahrefs 连接参数 |
| 目标域名 | `.env` → `AHREFS_TARGET_DOMAIN` | 工作流变量 / API Query |
| 国家 | `.env` → `AHREFS_TARGET_COUNTRY` | API Query（如 `us`） |
| GSC 站点 URL | `.env` → `GSC_SITE_URL`（**只能一行**） | GSC API 路径 |
| OAuth 三件套 | `token.json` | GSC 连接隐藏参数 |
| 独立站单选 key | `config/mingdao_options.json` | 写表时「独立站」字段 |
| 字段 controlId | `.env` → `MINGDAO_FIELD_DASH_*` | 开放 API 写表时用 |

导出 GSC OAuth 参数（不打印完整密钥到屏幕，只列出字段名）：

```bat
python script\export_oauth_for_mingdao.py
```

---

## 第一步：新建 Ahrefs 连接

路径：**应用 → 集成 → 连接 → 新建连接**

### 1.1 连接设置（对应你截图「连接设置」页）

**不要点 OAuth**。Ahrefs 只用 API Token。

| 参数名称 | 参数值 | 必填 | 隐藏 |
|----------|--------|------|------|
| `api_token` | `.env` 里 `AHREFS_API_TOKEN` | ✓ | ✓ |
| `target_domain` | 如 `cncpioneer.com` | ✓ | |
| `target_country` | 如 `us` | ✓ | |

保存并继续。

### 1.2 鉴权方式

选 **自定义 Header**（或「API Key / Bearer」类选项）：

- Header 名：`Authorization`
- Header 值：`Bearer {{api_token}}`（按明道云变量语法，可能是 `{{连接.api_token}}`，以界面为准）

另加 Header：`Accept: application/json`

### 1.3 API 管理 — 接口 1：有机关键词

| 项 | 值 |
|----|-----|
| 名称 | `organic-keywords` |
| 方法 | GET |
| URL | `https://api.ahrefs.com/v3/site-explorer/organic-keywords` |
| Query | 见下表 |

| 参数名 | 值 | 说明 |
|--------|-----|------|
| `target` | `{{target_domain}}` | 域名 |
| `country` | `{{target_country}}` | 国家 |
| `date` | 工作流传入，如 `2026-05-28` | 报告日 |
| `date_compared` | 报告日 − 7 天 | 对比日 |
| `select` | `keyword,volume,keyword_difficulty,best_position,best_position_diff` | 固定 |
| `limit` | `1000` | 固定 |

点 **「调试 / 发送请求」**，应返回 JSON，里面有 `keywords` 数组。

### 1.4 API 管理 — 接口 2：外链域历史

| 项 | 值 |
|----|-----|
| 名称 | `refdomains-history` |
| 方法 | GET |
| URL | `https://api.ahrefs.com/v3/site-explorer/refdomains-history` |

| 参数名 | 值 |
|--------|-----|
| `target` | `{{target_domain}}` |
| `date_from` | 报告日 − 7 天 |
| `date_to` | 报告日 |
| `history_grouping` | `daily` |

### 1.5 授权到应用

在 **「授权到应用」** 里勾选你的 SEO 应用，保存。

---

## 第二步：新建 Google GSC 连接

### 2.1 重要：别选 client_credentials

你截图里的 **「OAuth 2.0 认证 (客户端凭证 client credentials)」对 GSC 不适用**。  
GSC 是个人 Google 账号授权，要用 **refresh_token**。

做法：在 **连接参数** 里存三件套，用 **普通 HTTP API** 换 token，不用明道云 OAuth 向导。

| 参数名称 | 参数值 | 必填 | 隐藏 |
|----------|--------|------|------|
| `client_id` | `token.json` → `client_id` | ✓ | ✓ |
| `client_secret` | `token.json` → `client_secret` | ✓ | ✓ |
| `refresh_token` | `token.json` → `refresh_token` | ✓ | ✓ |
| `gsc_site_url` | `.env` → `GSC_SITE_URL` | ✓ | |

示例格式：`https://www.cncpioneer.com/`（必须与 Search Console 资源完全一致）

### 2.2 API 管理 — 接口 1：刷新 Access Token

| 项 | 值 |
|----|-----|
| 名称 | `refresh-access-token` |
| 方法 | POST |
| URL | `https://oauth2.googleapis.com/token` |
| Content-Type | `application/x-www-form-urlencoded` |

**Body（表单字段，不是 JSON）：**

| 字段 | 值 |
|------|-----|
| `client_id` | `{{client_id}}` |
| `client_secret` | `{{client_secret}}` |
| `refresh_token` | `{{refresh_token}}` |
| `grant_type` | `refresh_token` |

调试成功后，返回里要有 `access_token`。

> **网络说明**：明道云服务器在国内，调 Google 可能失败。若调试超时，GSC 这一步只能改走 **本地 sync.py**（方案 B），Ahrefs 仍可在明道云跑。

### 2.3 API 管理 — 接口 2：站点汇总

| 项 | 值 |
|----|-----|
| 名称 | `search-analytics-summary` |
| 方法 | POST |
| URL | `https://searchconsole.googleapis.com/webmasters/v3/sites/{{gsc_site_url_encoded}}/searchAnalytics/query` |

`gsc_site_url_encoded` 需要对站点 URL 做 **URL 编码**，例如：

- 原文：`https://www.cncpioneer.com/`
- 编码：`https%3A%2F%2Fwww.cncpioneer.com%2F`

可在工作流里用「文本替换 / 编码」节点生成，或连接参数里直接存编码后的值。

**Header：**

- `Authorization: Bearer {{access_token}}`（上一步返回）
- `Content-Type: application/json`

**Body（JSON）：**

```json
{
  "startDate": "2026-05-28",
  "endDate": "2026-05-28",
  "dimensions": ["date"],
  "rowLimit": 1
}
```

返回示例：`rows[0].clicks`、`impressions`、`ctr`、`position`。

### 2.4 API 管理 — 接口 3：周点击量（算环比）

同上 URL，Body 去掉 `dimensions`：

```json
{
  "startDate": "2026-05-22",
  "endDate": "2026-05-28",
  "rowLimit": 1
}
```

工作流里跑两次（本周 / 上周），用公式算 `(本周-上周)/上周`。

---

## 第三步：搭定时工作流（看自动触发效果）

路径：**应用 → 工作流 → 新建工作流**

### 3.1 触发器

- 类型：**定时触发**
- 建议：每周一 09:00（与 `run_sync.bat` 频率接近）
- 可先设 **「立即运行一次」** 看效果

### 3.2 计算报告日期

与脚本一致：`报告日 = 今天 − DATA_DELAY_DAYS`（`.env` 默认 `2`）。

明道云用「日期计算」节点：`addDays(今天, -2)` → 得到 `data_date`。

对比日：`addDays(data_date, -7)`。

### 3.3 节点顺序（推荐）

```
定时触发
  → 计算 data_date / compare_date
  → [GSC] refresh-access-token
  → [GSC] search-analytics-summary（写入变量 gsc_clicks 等）
  → [GSC] 两次 clicks sum（可选，算周环比）
  → [Ahrefs] organic-keywords
  → [Ahrefs] refdomains-history
  → 代码/公式：统计 Top10、Top30、RD 差值
  → 查找看板记录（独立站 + 日期）
  → 有则更新 / 无则新增
```

### 3.4 Ahrefs 汇总公式（与 sync.py 一致）

对工作流里 `organic-keywords` 返回的 `keywords` 数组：

- **Top10词数**：`best_position <= 10` 的条数
- **Top30词数**：`best_position <= 30` 的条数
- **周环比Top30**：用 `best_position_prev <= 30` 算上周 Top30，再 `(今-昨)/昨`

对 `refdomains-history`：

- **近7天RD变化**：`refdomains[最后] - refdomains[第一个]`

### 3.5 写入「SEO自动数据看板」

**方式 1（推荐先试）：工作表节点**

- 工作表：SEO自动数据看板
- 条件：独立站 = `cncpioneer`（单选），日期 = `data_date`
- 映射字段：

| 看板字段 | 来源 |
|----------|------|
| 日期 | `data_date` |
| 独立站 | 单选 key（见 mingdao_options.json） |
| 自然点击 | GSC rows[0].clicks |
| 展示量 | GSC rows[0].impressions |
| 平均CTR | GSC rows[0].ctr |
| 全站加权平均排名 | GSC rows[0].position |
| Top10词数 / Top30词数 | Ahrefs 公式 |
| 近7天RD变化 | Ahrefs refdomains 差值 |
| 周环比流量 | GSC 两次 clicks 公式 |
| 已监控URL收录数 / 异常数 | 暂写 `0`（与脚本一致） |
| 异常预警 | 流量环比 ≤ -20% →「流量下跌」，否则「正常」 |

**方式 2：开放 API（与 sync.py 相同）**

POST `https://api.mingdao.com/v2/open/worksheet/addRow`

```json
{
  "appKey": "你的 MINGDAO_APP_KEY",
  "sign": "你的 MINGDAO_SIGN",
  "worksheetId": "6a1d1d1914420b8440cd6adf",
  "controls": [
    {"controlId": "6a1d1d1914420b8440cd6ae0", "value": "2026-05-28"},
    {"controlId": "6a1d26ece33c925fdd2ac216", "value": "06445848-cf1b-4d3d-a63d-5da8ac85c093"},
    {"controlId": "6a1d22c2e30907a70fa427d5", "value": "9"}
  ],
  "triggerWorkflow": false
}
```

单选字段 value 必须是 **option 的 key（UUID）**，不是中文站名。完整 ID 见 `.env.example`。

---

## 第四步：验证「自动触发」是否成功

1. 工作流 → **手动运行一次**
2. 看每个「调用连接 API」节点的 **请求 / 响应日志**
3. 打开看板，按「独立站 + 日期」筛选，应有新行或更新
4. 与本地脚本对比：

```bat
run_sync.bat
```

对比 `logs\` 里最新报告与明道云工作流执行记录。

---

## 五站怎么扩展

当前脚本一次只跑 `.env` 里 `SYNC_SITE` 一个站。工作流里可以：

1. **复制工作流** 5 份，每份改 `target_domain`、`gsc_site_url`、独立站单选 key；或
2. 用 **循环节点** 遍历 5 站配置表（进阶）

`GSC_SITE_URL` 在 `.env` 里**不能写多行**；工作流里每站单独配参数。

| 站 key | 单选 key (mingdao_options.json) |
|--------|----------------------------------|
| cncpioneer | 06445848-cf1b-4d3d-a63d-5da8ac85c093 |
| fecision | 386f967d-e856-4b2e-8c23-150cdf954576 |
| richconn | 6d259ea7-aa61-4051-bb06-0f981647ab9b |
| lasermicrofab | e9bbf789-6dd6-4d01-a006-8f63ef2dd37b |
| drametal | ad526b77-49df-4af2-9c1b-f62c95f2a16b |

---

## 常见问题

| 现象 | 原因 | 处理 |
|------|------|------|
| GSC 连接调试超时 | 明道云服务器访问不了 Google | GSC 继续用本地 `sync.py`；工作流只接 Ahrefs |
| GSC 403 | 站点 URL 不对或账号无权限 | 核对 `GSC_SITE_URL` 与 Search Console |
| Ahrefs 401 | Token 错或过期 | 检查 Ahrefs 后台 API Token |
| 看板写了但单选不对 | 用了中文站名而不是 UUID | 用 mingdao_options.json 里的 key |
| Top10/Top30 为 0 | 该国别下确实没词进前 30 | 与 Ahrefs 网页 US 筛选对比，非 bug |
| 明道云 OAuth 向导 | client_credentials 不适用 GSC | 用 refresh_token 表单换 token |

---

## 与本地脚本的关系

| 项目文件 | 作用 |
|----------|------|
| `script/sync.py` | 完整 GSC+Ahrefs+写表，已跑通，**保留** |
| `run_sync.bat` | 手动 / 计划任务触发 |
| `.env` / `token.json` | 密钥与 OAuth，**不要提交 Git** |
| 本教程 | 明道云里复刻同一套 API 调用，便于你看工作流日志 |

两边写入同一张看板时，以 **独立站 + 日期** 为唯一键；后跑的会覆盖先跑的（与脚本 upsert 行为一致）。

---

## 附录：你截图「输入参数」怎么填（逐行对照）

教程主文档就是本文件：`docs/mingdao-workflow-guide.md`  
你卡在 **API 管理 → 某个 API → 输入参数** 这一页，按下面表格 **一行一行复制** 即可。

### 先搞懂 5 列分别是什么

| 列名 | 填什么 | 举例 |
|------|--------|------|
| **类型** | 数据格式 | 日期、文本都用「文本」即可 |
| **字段名** | 明道云内部名字（工作流里引用） | `报告日期`、`目标域名` |
| **参数名** | **发给外部 API 的真实 key** | Ahrefs 用 `target`；GSC 表单用 `grant_type` |
| **说明** | 备注，可空 | `Ahrefs 域名` |
| **必填** | 是否必传 | 建议全勾 |

点 **「+ 添加参数」** 加一行；填完点 **保存**。

---

### 填 API 之前的 3 步（别跳过）

在「输入参数」**之前**，同一个 API 页面还要设：

| 步骤 | 填什么 |
|------|--------|
| 1. API 名称 | 如 `organic-keywords`（Ahrefs）或 `refresh-access-token`（GSC） |
| 2. 请求方法 | Ahrefs 用 **GET**；GSC 换 token 用 **POST** |
| 3. 请求 URL | 见下面每个 API 的 URL 行 |

然后再进 **输入参数**。

---

### 表 1：Ahrefs — `organic-keywords`（建议第一个练手）

**请求方法**：GET  
**请求 URL**（整段粘贴）：

```text
https://api.ahrefs.com/v3/site-explorer/organic-keywords
```

**输入参数**（共 6 行）：

| 类型 | 字段名 | 参数名 | 说明 | 必填 | 测试时填的默认值 |
|------|--------|--------|------|------|------------------|
| 文本 | 目标域名 | `target` | 域名，不含 https | ✓ | `cncpioneer.com` |
| 文本 | 国家 | `country` | 国家代码小写 | ✓ | `us` |
| 文本 | 报告日期 | `date` | 与脚本一致：今天−2天 | ✓ | `2026-05-28` |
| 文本 | 对比日期 | `date_compared` | 报告日−7天 | ✓ | `2026-05-21` |
| 文本 | 返回字段 | `select` | 固定，勿改 | ✓ | `keyword,volume,keyword_difficulty,best_position,best_position_diff` |
| 文本 | 条数上限 | `limit` | 固定 | ✓ | `1000` |

保存后点 **调试 / 发送**，成功应看到 JSON 里有 `"keywords": [...]`。

> 若连接参数里已有 `target_domain`，测试阶段也可在默认值写 `cncpioneer.com`；工作流跑通后再改成引用连接变量。

---

### 表 2：Ahrefs — `refdomains-history`

**请求方法**：GET  
**请求 URL**：

```text
https://api.ahrefs.com/v3/site-explorer/refdomains-history
```

**输入参数**（4 行）：

| 类型 | 字段名 | 参数名 | 说明 | 必填 | 测试默认值 |
|------|--------|--------|------|------|------------|
| 文本 | 目标域名 | `target` | 域名 | ✓ | `cncpioneer.com` |
| 文本 | 起始日 | `date_from` | 报告日−7天 | ✓ | `2026-05-21` |
| 文本 | 结束日 | `date_to` | 报告日 | ✓ | `2026-05-28` |
| 文本 | 分组 | `history_grouping` | 固定 | ✓ | `daily` |

---

### 表 3：GSC — `refresh-access-token`（换 Access Token）

**请求方法**：POST  
**请求 URL**：

```text
https://oauth2.googleapis.com/token
```

**Content-Type**（在 Header 或请求体类型里选）：`application/x-www-form-urlencoded`

**输入参数**（4 行，参数名必须和 Google 要求完全一致）：

| 类型 | 字段名 | 参数名 | 说明 | 必填 | 参数值从哪来 |
|------|--------|--------|------|------|--------------|
| 文本 | 客户端ID | `client_id` | OAuth | ✓ | `token.json` → `client_id` |
| 文本 | 客户端密钥 | `client_secret` | OAuth | ✓ | `token.json` → `client_secret` |
| 文本 | 刷新令牌 | `refresh_token` | OAuth | ✓ | `token.json` → `refresh_token` |
| 文本 | 授权类型 | `grant_type` | 固定 | ✓ | 固定填 `refresh_token` |

调试成功返回示例：`{"access_token":"ya29....","expires_in":3599,...}`

本地核对命令：

```bat
python script\export_oauth_for_mingdao.py
```

> **不要**在「输入参数」里填 `access_token`；它是本 API **返回**的，下一步 GSC 查询再用。

---

### 表 4：GSC — `search-analytics-summary`（拉点击/展示）

**请求方法**：POST  

**请求 URL**（注意：`{站点}` 必须是 **URL 编码** 后的 GSC 资源地址）：

```text
https://searchconsole.googleapis.com/webmasters/v3/sites/https%3A%2F%2Fwww.cncpioneer.com%2F/searchAnalytics/query
```

把 `www.cncpioneer.com` 换成你 `.env` 里 `GSC_SITE_URL` 对应的站；整段 URL 编码后再贴进 URL 框。

**Header**（不在输入参数里，在「请求头」里加）：

| Header 名 | Header 值 |
|-----------|-----------|
| `Authorization` | `Bearer {{上一步的 access_token}}` |
| `Content-Type` | `application/json` |

**输入参数 — 两种方式任选一种**

#### 方式 A：点「从 JSON 示例生成」（推荐）

粘贴下面 JSON，再生成字段：

```json
{
  "startDate": "2026-05-28",
  "endDate": "2026-05-28",
  "dimensions": ["date"],
  "rowLimit": 1
}
```

生成后确认参数名为：`startDate`、`endDate`、`dimensions`、`rowLimit`。

#### 方式 B：手动 4 行

| 类型 | 字段名 | 参数名 | 必填 | 测试默认值 |
|------|--------|--------|------|------------|
| 文本 | 开始日期 | `startDate` | ✓ | `2026-05-28` |
| 文本 | 结束日期 | `endDate` | ✓ | `2026-05-28` |
| 文本 | 维度 | `dimensions` | ✓ | `["date"]` 或按界面选数组 |
| 文本 | 行数上限 | `rowLimit` | ✓ | `1` |

成功返回：`rows[0].clicks`、`impressions`、`ctr`、`position`。

---

### 表 5：GSC — 周点击量（算环比，可选）

URL 与表 4 相同，**Body 去掉 dimensions**：

```json
{
  "startDate": "2026-05-22",
  "endDate": "2026-05-28",
  "rowLimit": 1
}
```

工作流里跑 **两次**（本周区间、上周区间），用公式算环比。

---

### 连接参数 vs 输入参数（别混）

| 位置 | 什么时候填 | 填什么 |
|------|------------|--------|
| **连接设置 → 连接参数** | 建连接时，全 API 共用 | Ahrefs 的 `api_token`；GSC 的 `client_id` 等 |
| **API 管理 → 输入参数** | 每个 API 单独填 | 每次请求变的：`date`、`startDate`；或固定 `limit`、`grant_type` |

鉴权 Header（Ahrefs 的 `Authorization`）在 **连接鉴权** 里配，**不要**放进输入参数。

---

### 还是不会？按这个顺序只做 1 个 API

1. 只建 **Ahrefs 连接**（连接参数只填 `api_token`，隐藏）  
2. 只建 **表 1** 这一个 API + 输入参数 6 行  
3. 点 **调试**，截图返回 JSON 或报错发我  
4. 成功后再建表 3（GSC 换 token）

---

## 快速试跑清单（今天就能做）

- [ ] 建 Ahrefs 连接 → 调试 `organic-keywords` 看到 JSON
- [ ] 建 GSC 连接 → 调试 `refresh-access-token`（若失败则跳过，改本地 GSC）
- [ ] 建测试工作流：只调 Ahrefs + 写看板一个数字（如 Top30词数）
- [ ] 手动运行工作流 → 看板有数据
- [ ] 打开定时 → 等下一次自动执行
- [ ] 本地再跑一次 `run_sync.bat` 对比结果
