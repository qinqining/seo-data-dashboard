# 明道云 Python 代码块自动同步 — 逐步配置教程

**目标**：用「定时触发 + Python 代码块」自动跑 GSC + Ahrefs + 写看板，**不用每天点 `run_sync.bat`**。

**说明**：明道云这里**不能批量导入 JSON**，input 要 **一行一行点「添加」**。本教程按你界面上的操作顺序写，照着做即可。

**代码文件**（复制用）：[`script/mingdao_workflow_sync.py`](../script/mingdao_workflow_sync.py)

本地 `script/sync.py` 和 `run_sync.bat` **继续保留**，作备份和 GSC 备用。

---

## 第 0 步：先在电脑上准备好 8 个值

打开项目文件夹 `D:\seo-data-dashboard\`，用记事本打开下面两个文件，**先抄到纸上或另一个记事本**，等会往明道云一行一行粘贴。

### 从 `.env` 复制（6 个）

| 序号 | 在 .env 里找这一行 | 复制等号右边的值 |
|------|-------------------|------------------|
| ① | `MINGDAO_APP_KEY=` | 一长串 AppKey |
| ② | `MINGDAO_SIGN=` | 一长串 Sign |
| ③ | `AHREFS_API_TOKEN=` | Ahrefs Token |
| ④ | `GSC_SITE_URL=` | 如 `https://www.cncpioneer.com/`（**只能有一行**） |

### 从 `token.json` 复制（3 个）

用记事本打开项目根目录的 `token.json`：

| 序号 | JSON 里的字段名 | 复制引号里的整段 |
|------|----------------|------------------|
| ⑤ | `"client_id"` | 以 `.apps.googleusercontent.com` 结尾 |
| ⑥ | `"client_secret"` | 以 `GOCSPX-` 开头 |
| ⑦ | `"refresh_token"` | 以 `1//` 开头的一长串 |

可选核对（不显示完整密钥）：

```bat
python script\export_oauth_for_mingdao.py
```

### 固定值（第 8 行，先测 GSC 时用）

| 序号 | key | 值 |
|------|-----|-----|
| ⑧ | `skip_gsc` | 先填 `false`（若 GSC 测失败再改成 `true`） |

---

## 第 1 步：新建工作流 + 定时触发

1. 登录明道云 → 进入你的 **SEO 应用**
2. 左侧点 **工作流** → **新建工作流**
3. 工作流名称填：`SEO每周自动同步`
4. 画布上第一个节点选 **定时触发**

### 定时触发怎么填

| 界面项 | 建议填法 |
|--------|----------|
| 开始日期 | 选今天或下周一 |
| 触发频率 | **每周** 一次（做周报）或 **每天** 一次 |
| 具体时间 | 如 `09:00` |
| 说明 | 与 `DATA_DELAY_DAYS=2` 无冲突，代码里会自动算报告日 |

点 **保存**。先 **不要发布**，等 Python 测试成功再发布。

---

## 第 2 步：添加 Python 节点

1. 在「定时触发」下面点 **+**
2. 选 **Python**（或「代码块」）
3. 右侧确认语言是 **Python**
4. 勾选 **「代码块整体运行失败时自动重试」**

---

## 第 3 步：定义 input 对象 — 一行一行添加（共 8 行）

找到右侧 **「定义 input 对象」** 区域。

**操作方式**（每一行重复一次）：

1. 点 **「+ 添加」** / **「添加参数」**
2. 在 **key** 列输入下面表格里的 key（**必须完全一致，区分大小写**）
3. 在 **value** 列粘贴你在第 0 步准备好的值
4. 保存这一行，再添加下一行

> 没有「导入 JSON」就用这种方式。**一共添加 8 行**，不要少。

---

### 第 1 行

| 列 | 填什么 |
|----|--------|
| **key** | `mingdao_app_key` |
| **value** | 粘贴 ① `.env` 里 `MINGDAO_APP_KEY` 的值 |

---

### 第 2 行

| 列 | 填什么 |
|----|--------|
| **key** | `mingdao_sign` |
| **value** | 粘贴 ② `.env` 里 `MINGDAO_SIGN` 的值 |

---

### 第 3 行

| 列 | 填什么 |
|----|--------|
| **key** | `ahrefs_api_token` |
| **value** | 粘贴 ③ `.env` 里 `AHREFS_API_TOKEN` 的值 |

---

### 第 4 行

| 列 | 填什么 |
|----|--------|
| **key** | `gsc_site_url` |
| **value** | 粘贴 ④ `.env` 里 `GSC_SITE_URL` 的值 |

示例（cncpioneer）：

```text
https://www.cncpioneer.com/
```

必须与 Google Search Console 里显示的站点 **完全一致**（含 `https://`、有无 `www`、末尾斜杠）。

---

### 第 5 行

| 列 | 填什么 |
|----|--------|
| **key** | `google_client_id` |
| **value** | 粘贴 ⑤ `token.json` 里 `client_id` |

---

### 第 6 行

| 列 | 填什么 |
|----|--------|
| **key** | `google_client_secret` |
| **value** | 粘贴 ⑥ `token.json` 里 `client_secret` |

---

### 第 7 行

| 列 | 填什么 |
|----|--------|
| **key** | `google_refresh_token` |
| **value** | 粘贴 ⑦ `token.json` 里 `refresh_token` |

---

### 第 8 行

| 列 | 填什么 |
|----|--------|
| **key** | `skip_gsc` |
| **value** | `false` |

说明：

- 第一次测试填 **`false`**，让代码尝试拉 GSC
- 若测试报 **连不上 Google / oauth2 超时**，把这一行的 value 改成 **`true`**，只跑 Ahrefs + 写表；GSC 改由本地 `run_sync.bat` 补

---

### input 添加完成自检

右侧表格里应 **正好 8 行**，key 依次为：

```text
mingdao_app_key
mingdao_sign
ahrefs_api_token
gsc_site_url
google_client_id
google_client_secret
google_refresh_token
skip_gsc
```

**常见错误**：key 写成 `MINGDAO_APP_KEY`（大写）→ 代码读不到，会报错。

---

## 第 4 步：粘贴代码块

1. 用 Cursor / 记事本打开：`D:\seo-data-dashboard\script\mingdao_workflow_sync.py`
2. **从第 4 行 `import json` 开始**，一直选到最后 `output = { ... }` 结束
3. **整段复制**，粘贴到明道云 **「代码块」** 大文本框里

不要复制文件最上面两行 `#` 注释（复制了也不影响运行）。

---

## 第 5 步：改代码里的「配置区」（只改 3 行）

粘贴后，在代码块 **最上面** 找到配置区，按当前站点改（默认已是 cncpioneer，一般只核对）：

**找到这一行，确认域名：**

```python
AHREFS_DOMAIN = "cncpioneer.com"
```

**找到这一行，确认国家：**

```python
AHREFS_COUNTRY = "us"
```

**找到这一行，确认独立站单选 key：**

```python
SITE_OPTION_KEY = "06445848-cf1b-4d3d-a63d-5da8ac85c093"  # cncpioneer
```

换其他站时，改这三处 + 第 4 行 input 的 `gsc_site_url`：

| 站名 | SITE_OPTION_KEY | AHREFS_DOMAIN |
|------|-----------------|---------------|
| cncpioneer | 06445848-cf1b-4d3d-a63d-5da8ac85c093 | cncpioneer.com |
| fecision | 386f967d-e856-4b2e-8c23-150cdf954576 | fecision.com |
| richconn | 6d259ea7-aa61-4051-bb06-0f981647ab9b | richconn.com |
| lasermicrofab | e9bbf789-6dd6-4d01-a006-8f63ef2dd37b | lasermicrofab.com |
| drametal | ad526b77-49df-4af2-9c1b-f62c95f2a16b | drametal.com |

`WORKSHEET_ID` 和 `FIELD = { ... }` 与 `.env` 里已配好的 controlId 一致，**不用改**。

---

## 第 6 步：测试

1. 确认 8 行 input 都已填 value
2. 点代码块下方 **「测试」**
3. 等待执行完成，看 **Output 对象参数列表**

成功时大致会看到：

| Output 字段 | 含义 |
|-------------|------|
| `success` | `True` |
| `data_date` | 报告日期（今天减 2 天） |
| `action` | `create` 或 `update` |
| `clicks` | GSC 自然点击（skip_gsc=true 时为 0） |
| `top30` | Ahrefs Top30 词数 |
| `log` | 执行摘要文字 |

4. 打开 **SEO自动数据看板**，筛选 **独立站 = cncpioneer**、**日期 = data_date**，应有新数据或更新

---

## 第 7 步：保存节点 + 发布工作流

1. Python 节点点 **保存**
2. 工作流右上角 **发布** / **启用**
3. 确认 **定时触发** 状态为已启用
4. 在 **运行记录 / 日志** 里可查看每次自动执行结果

完成后：**到点自动跑，不用再点 run_sync.bat**。

---

## 测试失败怎么办

| 报错里含这些字 | 处理 |
|----------------|------|
| `input 缺少 mingdao_app_key` | 检查 8 行 key 是否拼写正确、value 是否为空 |
| `Network error ... oauth2` / 超时 | 第 8 行 `skip_gsc` 改成 `true`，本地跑 GSC |
| `HTTP 403 ... searchAnalytics` | 第 4 行 `gsc_site_url` 与 Search Console 不一致 |
| `Ahrefs ... 401` | 第 3 行 token 错误或过期 |
| `Mingdao addRow` / `数据不能为空` | 第 1、2 行 AppKey/Sign 错误 |

GSC 在明道云云端经常因 **访问不了 Google** 失败，这是正常现象。推荐：

- 工作流：`skip_gsc` = `true` → 自动跑 **Ahrefs + 写表**
- 本地：每周一次 `run_sync.bat` → 补 **GSC 点击/展示/环比**

---

## 五站都要自动同步

明道云暂不支持 input 里一次填 JSON 数组，**最简单**：

1. 复制整份工作流 **5 份**
2. 每份只改：
   - input 第 4 行 `gsc_site_url`
   - 代码配置区 `SITE_OPTION_KEY`、`AHREFS_DOMAIN`
3. 五份都发布，各站独立定时

---

## 配置检查清单（打勾用）

- [ ] 第 0 步：8 个值已从 `.env` / `token.json` 抄好
- [ ] 第 1 步：定时触发已保存
- [ ] 第 3 步：input **8 行** 逐行添加完成
- [ ] 第 4 步：代码已完整粘贴
- [ ] 第 5 步：配置区站点正确
- [ ] 第 6 步：测试 `success = True`，看板有数
- [ ] 第 7 步：工作流已发布

---

## 和本地脚本的关系

| 文件 | 作用 |
|------|------|
| `script/mingdao_workflow_sync.py` | 复制到明道云代码块 |
| `script/sync.py` | 本地完整版，逻辑一致 |
| `run_sync.bat` | 手动 / GSC 备用 |
| `.env` / `token.json` | 密钥来源，**不要提交 Git** |

改同步逻辑时：先改 `sync.py`，再同步改 `mingdao_workflow_sync.py`，重新粘贴到明道云。
