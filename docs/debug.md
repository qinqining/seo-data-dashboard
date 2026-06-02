# 调试记录

**日期**：20260601

## 测试错误一览

| 错误 | 环节 | 简单原因 | 状态 |
|------|------|----------|------|
| **10060 / Timeout** | GSC | 旧库 `httplib2` 连 Google 不稳定 | ✅ 已改 `requests` |
| **403** | GSC | Cloud 项目未启用 Search Console API | ✅ 启用后正常 |
| **403** | GSC | `.env` 多行 `GSC_SITE_URL`，最后一行站点错（如 `drametal.com`） | ⚠️ 只保留一行正确 URL |
| **443 / SSL EOF** | Google OAuth | `.env` 写了 `HTTPS_PROXY=4780`，Python 走 HTTP 代理访问不了 Google | ✅ 删掉 HTTPS_PROXY，改系统代理 |
| **ConnectTimeout** | GSC | 去掉代理后 Python 直连不了 Google | ✅ `GOOGLE_PROXY` 留空 + Clash 开系统代理 |
| **10001 数据不能为空** | 明道云 | 用了 `addRows` 却传 `controls`，应改 `addRow` | ✅ 已修复 |
| **Missing MINGDAO_APP_KEY** | 明道云 | 未填 AppKey / Sign | ✅ 填好后正常 |
| **OAuth 验证失败** | Google | 测试用户未加或登录 Gmail 不一致 | ✅ 加测试用户即可 |
| **Top10/Top30 = 0** | Ahrefs | US 区该站可能无词进前 30，不一定是 bug | ℹ️ 对照 Ahrefs 网页 |
| **仅最后一站成功** | GSC OAuth 443 | 旧版每站重复刷新 token；现版已 **共用凭据 + 整站重试 3 次** | 仍失败则查 Clash，再跑 `run_sync.bat` |

## 推荐配置

- `.env` 只保留 **一行** `GSC_SITE_URL`
- **不要**写 `HTTPS_PROXY` / `HTTP_PROXY`
- Clash 开 **系统代理**（全局或智能均可）
- `GOOGLE_PROXY` 留空
