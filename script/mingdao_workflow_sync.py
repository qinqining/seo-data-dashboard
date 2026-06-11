# 明道云工作流 Python 代码块用（复制「代码块」区域到明道云，勿直接运行依赖 input）
# 教程：docs/mingdao-workflow-python.md

import json
import datetime as dt
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ========== 配置区：粘贴到明道云后改一次（与 .env / mingdao_options.json 一致）==========
WORKSHEET_ID = "6a1d1d1914420b8440cd6adf"
FIELD = {
    "date": "6a1d1d1914420b8440cd6ae0",
    "site": "6a1d26ece33c925fdd2ac216",
    "clicks": "6a1d22c2e30907a70fa427d5",
    "impressions": "6a1d22c2e30907a70fa427d6",
    "ctr": "6a1d22c2e30907a70fa427d7",
    "position": "6a1d22c2e30907a70fa427d8",
    "top10": "6a1d22c2e30907a70fa427d9",
    "top30": "6a1d22c2e30907a70fa427da",
    "backlinks": "6a1d22c2e30907a70fa427db",
    "indexed": "6a1d22c2e30907a70fa427dc",
    "issues": "6a1d22c2e30907a70fa427dd",
    "alert": "6a1d22c2e30907a70fa427de",
    "traffic_wow": "6a1d22c2e30907a70fa427df",
    "top30_wow": "6a1d22c2e30907a70fa427e0",
}
SITE_OPTION_KEY = "06445848-cf1b-4d3d-a63d-5da8ac85c093"  # cncpioneer
ALERT_KEYS = {"正常": "6d259ea7-aa61-4051-bb06-0f981647ab9b", "流量下跌": "06445848-cf1b-4d3d-a63d-5da8ac85c093"}
MINGDAO_API = "https://api.mingdao.com/v2/open/worksheet"
AHREFS_DOMAIN = "cncpioneer.com"
AHREFS_COUNTRY = "us"
DATA_DELAY_DAYS = 2
# =========================================================================================


def _inp(key, default=""):
    if isinstance(input, dict):
        v = input.get(key, default)
    else:
        v = getattr(input, key, default)
    return v if v is not None else default


def http_json(method, url, headers=None, body=None, form=None, timeout=20):
    data = None
    hdrs = dict(headers or {})
    if form is not None:
        from urllib.parse import urlencode

        data = urlencode(form).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = Request(url, data=data, headers=hdrs, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {url}: {err[:500]}") from e
    except URLError as e:
        raise RuntimeError(f"Network error {url}: {e}") from e


def mingdao_post(endpoint, app_key, sign, payload):
    body = {"appKey": app_key, "sign": sign, **payload}
    data = http_json("POST", f"{MINGDAO_API}/{endpoint}", body=body)
    ok = data.get("success") is True or data.get("error_code") == 1
    if not ok:
        raise RuntimeError(f"Mingdao {endpoint}: {data}")
    return data


def fmt_num(v):
    if isinstance(v, float):
        t = f"{v:.6f}".rstrip("0").rstrip(".")
        return t or "0"
    return str(v)


GSC_TIMEOUT = 12
GSC_RETRIES = 2


def gsc_call(label, fn):
    last_err = None
    for attempt in range(1, GSC_RETRIES + 1):
        try:
            return fn()
        except Exception as exc:
            last_err = exc
            if attempt < GSC_RETRIES:
                continue
    raise RuntimeError(f"GSC {label} failed after {GSC_RETRIES} tries: {last_err}") from last_err


def gsc_access_token(client_id, client_secret, refresh_token):
    def _refresh():
        data = http_json(
            "POST",
            "https://oauth2.googleapis.com/token",
            form={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=GSC_TIMEOUT,
        )
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"token refresh bad response: {data}")
        return token

    return gsc_call("token refresh", _refresh)


def gsc_query(access_token, site_url, body):
    enc = quote(site_url, safe="")
    url = f"https://searchconsole.googleapis.com/webmasters/v3/sites/{enc}/searchAnalytics/query"

    def _query():
        return http_json(
            "POST",
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            body=body,
            timeout=GSC_TIMEOUT,
        )

    return gsc_call("searchAnalytics", _query)


def ahrefs_get(path, token, params):
    qs = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    url = f"https://api.ahrefs.com/v3/{path.lstrip('/')}?{qs}"
    data = http_json("GET", url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    if "error" in data:
        raise RuntimeError(f"Ahrefs {path}: {data['error']}")
    return data


def calc_ratio_change(current, previous):
    if previous <= 0:
        return None
    return (current - previous) / previous


def build_controls(logical):
    mapping = {
        "日期": FIELD["date"],
        "独立站": FIELD["site"],
        "自然点击": FIELD["clicks"],
        "展示量": FIELD["impressions"],
        "平均CTR": FIELD["ctr"],
        "全站加权平均排名": FIELD["position"],
        "Top10词数": FIELD["top10"],
        "Top30词数": FIELD["top30"],
        "Backlinks变化": FIELD["backlinks"],
        "异常预警": FIELD["alert"],
        "周环比流量": FIELD["traffic_wow"],
        "周环比Top30词": FIELD["top30_wow"],
    }
    controls = []
    for name, cid in mapping.items():
        if name not in logical or logical[name] is None:
            continue
        val = logical[name]
        if name == "日期":
            controls.append({"controlId": cid, "value": val.isoformat() if hasattr(val, "isoformat") else str(val)})
        elif name == "独立站":
            controls.append({"controlId": cid, "value": SITE_OPTION_KEY})
        elif name == "异常预警":
            controls.append({"controlId": cid, "value": ALERT_KEYS.get(str(val), ALERT_KEYS["正常"])})
        else:
            controls.append({"controlId": cid, "value": fmt_num(val)})
    return controls


def find_row(app_key, sign, data_date):
    filters = [
        {"controlId": FIELD["date"], "dataType": 15, "spliceType": 1, "filterType": 17, "value": data_date.isoformat()},
        {"controlId": FIELD["site"], "dataType": 11, "spliceType": 1, "filterType": 2, "values": [SITE_OPTION_KEY]},
    ]
    data = mingdao_post(
        "getFilterRows",
        app_key,
        sign,
        {"worksheetId": WORKSHEET_ID, "pageSize": 5, "pageIndex": 1, "listType": 0, "filters": filters},
    )
    rows = data.get("data", {}).get("rows", [])
    return rows[0] if rows else None


def upsert_dashboard(app_key, sign, data_date, logical):
    controls = build_controls(logical)
    if not controls:
        raise RuntimeError("controls empty")
    existing = find_row(app_key, sign, data_date)
    if existing:
        mingdao_post(
            "editRow",
            app_key,
            sign,
            {"worksheetId": WORKSHEET_ID, "rowId": existing["rowid"], "controls": controls, "triggerWorkflow": False},
        )
        action = "update"
    else:
        mingdao_post(
            "addRow",
            app_key,
            sign,
            {"worksheetId": WORKSHEET_ID, "controls": controls, "triggerWorkflow": False},
        )
        action = "create"
    return action


# ----- 主流程（明道云必须定义 output）-----
app_key = _inp("mingdao_app_key")
sign = _inp("mingdao_sign")
ahrefs_token = _inp("ahrefs_api_token")
gsc_site = _inp("gsc_site_url") or "https://www.cncpioneer.com/"
skip_gsc = str(_inp("skip_gsc", "false")).lower() in ("1", "true", "yes")

if not app_key or not sign or not ahrefs_token:
    raise RuntimeError("input 缺少 mingdao_app_key / mingdao_sign / ahrefs_api_token")

data_date = dt.date.today() - dt.timedelta(days=DATA_DELAY_DAYS)
compare_date = data_date - dt.timedelta(days=7)
log = []

# Ahrefs
kw = ahrefs_get(
    "site-explorer/organic-keywords",
    ahrefs_token,
    {
        "target": AHREFS_DOMAIN,
        "country": AHREFS_COUNTRY.lower(),
        "date": data_date.isoformat(),
        "date_compared": compare_date.isoformat(),
        "select": "keyword,volume,keyword_difficulty,best_position,best_position_diff",
        "limit": 1000,
    },
)
top10 = top30 = prev_top30 = 0
for item in kw.get("keywords", []):
    pos = item.get("best_position")
    prev = item.get("best_position_prev")
    if pos is not None and pos <= 10:
        top10 += 1
    if pos is not None and pos <= 30:
        top30 += 1
    if prev is not None and prev <= 30:
        prev_top30 += 1

rd_payload = ahrefs_get(
    "site-explorer/refdomains-history",
    ahrefs_token,
    {
        "target": AHREFS_DOMAIN,
        "date_from": compare_date.isoformat(),
        "date_to": data_date.isoformat(),
        "history_grouping": "daily",
    },
)
points = rd_payload.get("refdomains", [])
rd_delta = int(points[-1]["refdomains"]) - int(points[0]["refdomains"]) if len(points) >= 2 else None
top30_wow = calc_ratio_change(top30, prev_top30)
log.append(f"Ahrefs ok top10={top10} top30={top30} rd_delta={rd_delta}")

# GSC（明道云云端常连不上 Google：短超时 + 重试；仍失败则跳过，避免整段超时）
clicks = impressions = ctr = position = 0
traffic_wow = None
if skip_gsc:
    log.append("GSC skipped (skip_gsc=true)")
else:
    cid = _inp("google_client_id")
    csec = _inp("google_client_secret")
    refresh = _inp("google_refresh_token")
    if not all([cid, csec, refresh]):
        log.append("GSC skipped (missing oauth input)")
    else:
        try:
            access = gsc_access_token(cid, csec, refresh)
            summary = gsc_query(
                access,
                gsc_site,
                {"startDate": data_date.isoformat(), "endDate": data_date.isoformat(), "dimensions": ["date"], "rowLimit": 1},
            )
            rows = summary.get("rows", [])
            if rows:
                row = rows[0]
                clicks = row.get("clicks", 0)
                impressions = row.get("impressions", 0)
                ctr = row.get("ctr", 0)
                position = row.get("position", 0)
            tw_start = data_date - dt.timedelta(days=6)
            lw_end = data_date - dt.timedelta(days=7)
            lw_start = data_date - dt.timedelta(days=13)
            this_clicks = gsc_query(access, gsc_site, {"startDate": tw_start.isoformat(), "endDate": data_date.isoformat(), "rowLimit": 1})
            last_clicks = gsc_query(access, gsc_site, {"startDate": lw_start.isoformat(), "endDate": lw_end.isoformat(), "rowLimit": 1})
            tc = int((this_clicks.get("rows") or [{}])[0].get("clicks", 0))
            lc = int((last_clicks.get("rows") or [{}])[0].get("clicks", 0))
            traffic_wow = calc_ratio_change(tc, lc)
            log.append(f"GSC ok clicks={clicks} impressions={impressions}")
        except Exception as exc:
            log.append(f"GSC failed: {exc}")

alert = "流量下跌" if traffic_wow is not None and traffic_wow <= -0.2 else "正常"
logical = {
    "日期": data_date,
    "独立站": SITE_OPTION_KEY,
    "自然点击": clicks,
    "展示量": impressions,
    "平均CTR": ctr,
    "全站加权平均排名": round(position, 1) if position else 0,
    "Top10词数": top10,
    "Top30词数": top30,
    "Backlinks变化": rd_delta,
    "异常预警": alert,
}
if traffic_wow is not None:
    logical["周环比流量"] = round(traffic_wow, 4)
if top30_wow is not None:
    logical["周环比Top30词"] = round(top30_wow, 4)

action = upsert_dashboard(app_key, sign, data_date, logical)
log.append(f"Mingdao {action} date={data_date.isoformat()}")

output = {
    "success": True,
    "data_date": data_date.isoformat(),
    "action": action,
    "clicks": clicks,
    "top30": top30,
    "log": "; ".join(log),
}
