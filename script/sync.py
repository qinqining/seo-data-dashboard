"""
SEO sync: pull GSC + Ahrefs and write to Mingdao worksheets.

Phase 1: SEO automatic dashboard only. Run via run_sync.bat (about once per week).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests
from dotenv import load_dotenv

try:
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    AuthorizedSession = None
    Request = None
    service_account = None
    Credentials = None
    InstalledAppFlow = None


ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
REPORT_DIR = ROOT / "reports"
OPTIONS_FILE = ROOT / "config" / "mingdao_options.json"
LOG_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

DASHBOARD_LABEL = "SEO自动数据看板"


@dataclass
class SyncReport:
    started_at: dt.datetime
    data_date: dt.date
    config: "Config"
    api_calls: list[str] | None = None
    writes: list[str] | None = None
    skips: list[str] | None = None
    warnings: list[str] | None = None

    def __post_init__(self) -> None:
        self.api_calls = []
        self.writes = []
        self.skips = []
        self.warnings = []

    def log_api(
        self,
        provider: str,
        endpoint: str,
        *,
        ok: bool = True,
        detail: str = "",
    ) -> None:
        status = "OK" if ok else "FAIL"
        message = f"[API][{status}] {provider} {endpoint}"
        if detail:
            message += f" | {detail}"
        self.api_calls.append(message)
        logging.info(message)

    def log_write(self, table: str, action: str, key: Any, fields: dict[str, Any]) -> None:
        rendered = format_fields_for_report(fields)
        message = f"[WRITE] {table} {action} key={key} fields={rendered}"
        self.writes.append(message)
        logging.info(message)

    def log_skip(self, table: str, reason: str) -> None:
        message = f"[SKIP] {table} | {reason}"
        self.skips.append(message)
        logging.info(message)

    def log_warning(self, message: str) -> None:
        self.warnings.append(message)
        logging.warning(message)

    def save(self) -> Path:
        finished_at = dt.datetime.now()
        report_path = REPORT_DIR / f"sync-report-{self.started_at.strftime('%Y%m%d-%H%M%S')}.txt"
        lines = [
            "SEO Mingdao Sync Report",
            "=" * 60,
            f"Started : {self.started_at.isoformat(sep=' ', timespec='seconds')}",
            f"Finished: {finished_at.isoformat(sep=' ', timespec='seconds')}",
            f"Data date: {self.data_date.isoformat()} (today - DATA_DELAY_DAYS={self.config.data_delay_days})",
            f"Site      : {self.config.sync_site}",
            f"GSC site  : {self.config.gsc_site_url}",
            f"Ahrefs    : {self.config.ahrefs_target_domain}",
            "",
            f"API calls ({len(self.api_calls)})",
            "-" * 60,
        ]
        lines.extend(self.api_calls or ["(none)"])
        lines.extend(["", f"Mingdao writes ({len(self.writes)})", "-" * 60])
        lines.extend(self.writes or ["(none)"])
        lines.extend(["", f"Skipped ({len(self.skips)})", "-" * 60])
        lines.extend(self.skips or ["(none)"])
        if self.warnings:
            lines.extend(["", f"Warnings ({len(self.warnings)})", "-" * 60])
            lines.extend(self.warnings)
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logging.info("Sync report saved: %s", report_path)
        return report_path


def format_fields_for_report(fields: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in fields.items():
        if isinstance(value, dt.date):
            parts.append(f"{key}={value.isoformat()}")
        else:
            parts.append(f"{key}={value!r}")
    return "{" + ", ".join(parts) + "}"


def setup_logging() -> None:
    log_file = LOG_DIR / f"sync-{dt.date.today().isoformat()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


@dataclass(frozen=True)
class DashboardFieldIds:
    date: str
    site: str
    clicks: str
    impressions: str
    ctr: str
    position: str
    top10: str
    top30: str
    rd_delta: str
    indexed: str
    issues: str
    alert: str
    traffic_wow: str
    top30_wow: str


@dataclass(frozen=True)
class Config:
    mingdao_app_key: str
    mingdao_sign: str
    mingdao_api_base: str
    mingdao_worksheet_dashboard: str
    dashboard_fields: DashboardFieldIds
    sync_site: str
    site_option_keys: dict[str, str]
    alert_option_keys: dict[str, str]
    gsc_site_url: str
    google_auth_mode: str
    google_credentials_file: str
    google_client_secret_file: str
    google_token_file: str
    ahrefs_api_token: str
    ahrefs_target_domain: str
    ahrefs_target_country: str
    data_delay_days: int

    @classmethod
    def load(cls) -> "Config":
        load_dotenv(ROOT / ".env")
        options = load_mingdao_options()
        return cls(
            mingdao_app_key=env_required("MINGDAO_APP_KEY"),
            mingdao_sign=env_required("MINGDAO_SIGN"),
            mingdao_api_base=os.getenv("MINGDAO_API_BASE", "https://api.mingdao.com/v2/open/worksheet").rstrip("/"),
            mingdao_worksheet_dashboard=env_required("MINGDAO_WORKSHEET_DASHBOARD"),
            dashboard_fields=DashboardFieldIds(
                date=env_required("MINGDAO_FIELD_DASH_DATE"),
                site=env_required("MINGDAO_FIELD_DASH_SITE"),
                clicks=env_required("MINGDAO_FIELD_DASH_CLICKS"),
                impressions=env_required("MINGDAO_FIELD_DASH_IMPRESSIONS"),
                ctr=env_required("MINGDAO_FIELD_DASH_CTR"),
                position=env_required("MINGDAO_FIELD_DASH_POSITION"),
                top10=env_required("MINGDAO_FIELD_DASH_TOP10"),
                top30=env_required("MINGDAO_FIELD_DASH_TOP30"),
                rd_delta=env_required("MINGDAO_FIELD_DASH_RD_DELTA"),
                indexed=env_required("MINGDAO_FIELD_DASH_INDEXED"),
                issues=env_required("MINGDAO_FIELD_DASH_ISSUES"),
                alert=env_required("MINGDAO_FIELD_DASH_ALERT"),
                traffic_wow=env_required("MINGDAO_FIELD_DASH_TRAFFIC_WOW"),
                top30_wow=env_required("MINGDAO_FIELD_DASH_TOP30_WOW"),
            ),
            sync_site=env_required("SYNC_SITE"),
            site_option_keys=options["sites"],
            alert_option_keys=options["alerts"],
            gsc_site_url=env_required("GSC_SITE_URL").strip(),
            google_auth_mode=os.getenv("GOOGLE_AUTH_MODE", "oauth").lower(),
            google_credentials_file=os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json"),
            google_client_secret_file=os.getenv("GOOGLE_CLIENT_SECRET_FILE", "client_secret.json"),
            google_token_file=os.getenv("GOOGLE_TOKEN_FILE", "token.json"),
            ahrefs_api_token=env_required("AHREFS_API_TOKEN"),
            ahrefs_target_domain=normalize_ahrefs_domain(env_required("AHREFS_TARGET_DOMAIN")),
            ahrefs_target_country=os.getenv("AHREFS_TARGET_COUNTRY", "us"),
            data_delay_days=int(os.getenv("DATA_DELAY_DAYS", "2")),
        )

    def site_option_key(self) -> str:
        key = self.site_option_keys.get(self.sync_site)
        if not key:
            known = ", ".join(sorted(self.site_option_keys))
            raise RuntimeError(f"Unknown SYNC_SITE={self.sync_site!r}. Known: {known}")
        return key

    def alert_option_key(self, label: str) -> str:
        key = self.alert_option_keys.get(label)
        if not key:
            known = ", ".join(sorted(self.alert_option_keys))
            raise RuntimeError(f"Unknown alert label {label!r}. Known: {known}")
        return key


def load_mingdao_options() -> dict[str, dict[str, str]]:
    if not OPTIONS_FILE.exists():
        raise RuntimeError(f"Missing {OPTIONS_FILE}")
    payload = json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
    return {"sites": payload["sites"], "alerts": payload["alerts"]}


def env_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def normalize_ahrefs_domain(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if "://" in raw:
        host = urlparse(raw).netloc
    else:
        host = raw.split("/", 1)[0]
    return host.lower().removeprefix("www.")


def get_target_date(config: Config) -> dt.date:
    return dt.date.today() - dt.timedelta(days=config.data_delay_days)


class MingdaoClient:
    DATE_TYPE = 15
    SELECT_TYPE = 11
    NUMBER_TYPE = 6

    def __init__(self, config: Config, report: SyncReport | None = None):
        self.config = config
        self.report = report
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.config.mingdao_api_base}/{endpoint.lstrip('/')}"
        body = {
            "appKey": self.config.mingdao_app_key,
            "sign": self.config.mingdao_sign,
            **payload,
        }
        resp = self.session.post(url, json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        ok = data.get("success") is True or data.get("error_code") == 1
        if not ok:
            raise RuntimeError(f"Mingdao API error ({endpoint}): {data}")
        return data

    def test_connection(self) -> int:
        rows = self.list_rows(self.config.mingdao_worksheet_dashboard, page_size=1)
        count = len(rows)
        if self.report:
            self.report.log_api("Mingdao", "getFilterRows (test)", detail=f"worksheet ok, sample_rows={count}")
        return count

    def list_rows(
        self,
        worksheet_id: str,
        *,
        filters: list[dict[str, Any]] | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "worksheetId": worksheet_id,
            "pageSize": page_size,
            "pageIndex": 1,
            "listType": 0,
        }
        if filters:
            payload["filters"] = filters

        data = self._post("getFilterRows", payload)
        rows = data.get("data", {}).get("rows", [])
        if self.report:
            self.report.log_api(
                "Mingdao",
                "getFilterRows",
                detail=f"worksheet={worksheet_id} rows={len(rows)}",
            )
        return rows

    def find_dashboard_row(self, data_date: dt.date, site_option_key: str) -> dict[str, Any] | None:
        fields = self.config.dashboard_fields
        filters = [
            {
                "controlId": fields.date,
                "dataType": self.DATE_TYPE,
                "spliceType": 1,
                "filterType": 17,
                "value": data_date.isoformat(),
            },
            {
                "controlId": fields.site,
                "dataType": self.SELECT_TYPE,
                "spliceType": 1,
                "filterType": 2,
                "values": [site_option_key],
            },
        ]
        rows = self.list_rows(self.config.mingdao_worksheet_dashboard, filters=filters, page_size=5)
        return rows[0] if rows else None

    def add_row(self, worksheet_id: str, controls: list[dict[str, str]]) -> str:
        data = self._post(
            "addRows",
            {
                "worksheetId": worksheet_id,
                "controls": controls,
                "triggerWorkflow": False,
            },
        )
        row_id = data.get("data")
        if self.report:
            self.report.log_api("Mingdao", "addRows", detail=f"rowId={row_id}")
        return str(row_id)

    def edit_row(self, worksheet_id: str, row_id: str, controls: list[dict[str, str]]) -> None:
        self._post(
            "editRow",
            {
                "worksheetId": worksheet_id,
                "rowId": row_id,
                "controls": controls,
                "triggerWorkflow": False,
            },
        )
        if self.report:
            self.report.log_api("Mingdao", "editRow", detail=f"rowId={row_id}")

    def upsert_dashboard(self, data_date: dt.date, logical_fields: dict[str, Any]) -> None:
        fields = self.config.dashboard_fields
        site_key = self.config.site_option_key()
        controls = build_dashboard_controls(self.config, logical_fields)

        existing = self.find_dashboard_row(data_date, site_key)
        key = f"{self.config.sync_site}@{data_date.isoformat()}"
        if existing:
            row_id = existing["rowid"]
            self.edit_row(self.config.mingdao_worksheet_dashboard, row_id, controls)
            if self.report:
                self.report.log_write(DASHBOARD_LABEL, "update", key, logical_fields)
        else:
            self.add_row(self.config.mingdao_worksheet_dashboard, controls)
            if self.report:
                self.report.log_write(DASHBOARD_LABEL, "create", key, logical_fields)


def build_dashboard_controls(config: Config, logical_fields: dict[str, Any]) -> list[dict[str, str]]:
    fields = config.dashboard_fields
    mapping = {
        "日期": fields.date,
        "独立站": fields.site,
        "自然点击": fields.clicks,
        "展示量": fields.impressions,
        "平均CTR": fields.ctr,
        "全站加权平均排名": fields.position,
        "Top10词数": fields.top10,
        "Top30词数": fields.top30,
        "近7天RD变化": fields.rd_delta,
        "已监控URL收录数": fields.indexed,
        "已监控URL异常数": fields.issues,
        "异常预警": fields.alert,
        "周环比流量": fields.traffic_wow,
        "周环比Top30词": fields.top30_wow,
    }

    controls: list[dict[str, str]] = []
    for name, control_id in mapping.items():
        if name not in logical_fields:
            continue
        value = logical_fields[name]
        if value is None:
            continue
        if name == "日期":
            controls.append({"controlId": control_id, "value": format_mingdao_date(value)})
        elif name == "独立站":
            controls.append({"controlId": control_id, "value": config.site_option_key()})
        elif name == "异常预警":
            controls.append({"controlId": control_id, "value": config.alert_option_key(str(value))})
        else:
            controls.append({"controlId": control_id, "value": format_mingdao_number(value)})
    return controls


def format_mingdao_date(value: dt.date | dt.datetime | str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    return value.isoformat()


def format_mingdao_number(value: Any) -> str:
    if isinstance(value, float):
        text = f"{value:.6f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


class GSCClient:
    SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
    API_BASE = "https://searchconsole.googleapis.com/webmasters/v3"
    REQUEST_TIMEOUT = 60
    MAX_RETRIES = 3

    def __init__(self, config: Config, report: SyncReport | None = None):
        if AuthorizedSession is None or Request is None:
            raise RuntimeError("Google API dependencies are not installed.")

        self.config = config
        self.report = report
        self.site_url = config.gsc_site_url
        credentials = self._load_credentials()
        self.session = AuthorizedSession(credentials)

    def _load_credentials(self) -> Any:
        if self.config.google_auth_mode == "service_account":
            return self._load_service_account_credentials()
        if self.config.google_auth_mode == "oauth":
            return self._load_oauth_credentials()
        raise RuntimeError(f"Unsupported GOOGLE_AUTH_MODE: {self.config.google_auth_mode}")

    def _load_service_account_credentials(self) -> Any:
        if service_account is None:
            raise RuntimeError("Google service account dependency is not installed.")
        credentials_path = ROOT / self.config.google_credentials_file
        if not credentials_path.exists():
            raise RuntimeError(f"Google credentials file not found: {credentials_path}")
        return service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=self.SCOPES,
        )

    def _load_oauth_credentials(self) -> Any:
        if Credentials is None or Request is None or InstalledAppFlow is None:
            raise RuntimeError("Google OAuth dependencies are not installed.")

        token_path = ROOT / self.config.google_token_file
        client_secret_path = ROOT / self.config.google_client_secret_file
        credentials = None

        if token_path.exists():
            credentials = Credentials.from_authorized_user_file(token_path, self.SCOPES)

        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())

        if not credentials or not credentials.valid:
            if not client_secret_path.exists():
                raise RuntimeError(f"Google OAuth client secret file not found: {client_secret_path}")
            logging.info("Opening browser for Google OAuth. Complete login to create token.json.")
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, self.SCOPES)
            credentials = flow.run_local_server(port=0)
            token_path.write_text(credentials.to_json(), encoding="utf-8")

        return credentials

    def query_site_summary(self, date_value: dt.date) -> dict[str, Any]:
        body = {
            "startDate": date_value.isoformat(),
            "endDate": date_value.isoformat(),
            "dimensions": ["date"],
            "rowLimit": 1,
        }
        result = self._query_search_analytics(body)
        rows = result.get("rows", [])
        if not rows:
            summary = {"clicks": 0, "impressions": 0, "ctr": 0, "position": 0}
        else:
            row = rows[0]
            summary = {
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": row.get("ctr", 0),
                "position": row.get("position", 0),
            }
        if self.report:
            self.report.log_api(
                "GSC",
                "searchAnalytics/query (site summary)",
                detail=(
                    f"date={date_value.isoformat()} clicks={summary['clicks']} "
                    f"impressions={summary['impressions']} ctr={summary['ctr']} "
                    f"position={summary['position']}"
                ),
            )
        return summary

    def query_clicks_sum(self, start_date: dt.date, end_date: dt.date) -> int:
        body = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "rowLimit": 1,
        }
        result = self._query_search_analytics(body)
        rows = result.get("rows", [])
        clicks = int(rows[0].get("clicks", 0)) if rows else 0
        if self.report:
            self.report.log_api(
                "GSC",
                "searchAnalytics/query (clicks sum)",
                detail=f"range={start_date.isoformat()}..{end_date.isoformat()} clicks={clicks}",
            )
        return clicks

    def _query_search_analytics(self, body: dict[str, Any]) -> dict[str, Any]:
        encoded_site = quote(self.site_url, safe="")
        url = f"{self.API_BASE}/sites/{encoded_site}/searchAnalytics/query"
        last_error: Exception | None = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = self.session.post(url, json=body, timeout=self.REQUEST_TIMEOUT)
                if response.status_code == 403:
                    self._raise_gsc_permission_error(response)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as exc:
                last_error = exc
                logging.warning("GSC request failed (attempt %s/%s): %s", attempt, self.MAX_RETRIES, exc)
                if attempt < self.MAX_RETRIES:
                    time.sleep(2)

        raise RuntimeError(
            "无法连接 Google Search Console API。请检查网络/VPN/代理，或在 .env 中设置 HTTPS_PROXY 后重试。"
        ) from last_error

    @staticmethod
    def _extract_error_message(response: requests.Response) -> str:
        try:
            payload = response.json()
            return payload.get("error", {}).get("message", response.text)
        except ValueError:
            return response.text

    def _raise_gsc_permission_error(self, response: requests.Response) -> None:
        message = self._extract_error_message(response)
        if "has not been used" in message or "is disabled" in message:
            raise RuntimeError(
                "Google Search Console API 未启用。请在 Cloud Console 启用 Search Console API 后重试。"
            ) from None
        raise RuntimeError(
            "Google Search Console 返回 403。"
            f"请确认 GSC_SITE_URL 与 Search Console 资源一致。详情: {message}"
        ) from None


class AhrefsClient:
    BASE_URL = "https://api.ahrefs.com/v3"

    def __init__(self, config: Config, report: SyncReport | None = None):
        self.config = config
        self.report = report
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.config.ahrefs_api_token}",
                "Accept": "application/json",
            }
        )
        self.report_date = get_target_date(config)
        self.compare_date = self.report_date - dt.timedelta(days=7)
        self._organic_rankings: dict[str, dict[str, Any]] | None = None

    def load_organic_rankings(self) -> dict[str, dict[str, Any]]:
        if self._organic_rankings is not None:
            return self._organic_rankings

        payload = self._request(
            "site-explorer/organic-keywords",
            {
                "target": self.config.ahrefs_target_domain,
                "country": self.config.ahrefs_target_country.lower(),
                "date": self.report_date.isoformat(),
                "date_compared": self.compare_date.isoformat(),
                "select": "keyword,volume,keyword_difficulty,best_position,best_position_diff",
                "limit": 1000,
            },
        )
        rankings: dict[str, dict[str, Any]] = {}
        for item in payload.get("keywords", []):
            keyword = item.get("keyword")
            if keyword:
                rankings[str(keyword).casefold()] = item
        self._organic_rankings = rankings
        logging.info("Loaded %s organic keywords from Ahrefs", len(rankings))
        if self.report:
            self.report.log_api(
                "Ahrefs",
                "site-explorer/organic-keywords",
                detail=f"date={self.report_date.isoformat()} count={len(rankings)}",
            )
        return rankings

    def get_dashboard_summary(self) -> dict[str, Any]:
        rankings = self.load_organic_rankings()
        top10_count = 0
        top30_count = 0
        previous_top30_count = 0
        for ranking in rankings.values():
            position = ranking.get("best_position")
            previous_position = ranking.get("best_position_prev")
            if position is not None and position <= 10:
                top10_count += 1
            if position is not None and position <= 30:
                top30_count += 1
            if previous_position is not None and previous_position <= 30:
                previous_top30_count += 1

        new_rd = self._get_refdomains_delta()
        top30_change = calc_ratio_change(top30_count, previous_top30_count)
        summary = {
            "top10_count": top10_count,
            "top30_count": top30_count,
            "new_referring_domains": new_rd,
            "top30_week_change": top30_change,
        }
        if self.report:
            self.report.log_api(
                "Ahrefs",
                "dashboard summary",
                detail=(
                    f"top10={top10_count} top30={top30_count} new_rd={new_rd} "
                    f"top30_week_change={top30_change}"
                ),
            )
        return summary

    def _get_refdomains_delta(self) -> int | None:
        start_date = self.report_date - dt.timedelta(days=7)
        payload = self._request(
            "site-explorer/refdomains-history",
            {
                "target": self.config.ahrefs_target_domain,
                "date_from": start_date.isoformat(),
                "date_to": self.report_date.isoformat(),
                "history_grouping": "daily",
            },
        )
        points = payload.get("refdomains", [])
        if len(points) < 2:
            delta = None
        else:
            delta = int(points[-1]["refdomains"]) - int(points[0]["refdomains"])
        if self.report:
            self.report.log_api(
                "Ahrefs",
                "site-explorer/refdomains-history",
                detail=f"range={start_date.isoformat()}..{self.report_date.isoformat()} delta={delta}",
            )
        return delta

    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        resp = self.session.get(url, params=params, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        if "error" in payload:
            if self.report:
                self.report.log_api("Ahrefs", path, ok=False, detail=str(payload["error"]))
            raise RuntimeError(f"Ahrefs API error ({path}): {payload['error']}")
        return payload


def calc_ratio_change(current: int, previous: int) -> float | None:
    if previous <= 0:
        return None
    return (current - previous) / previous


def build_dashboard_alert(traffic_week_change: float | None) -> str:
    if traffic_week_change is not None and traffic_week_change <= -0.2:
        return "流量下跌"
    return "正常"


def sync_dashboard(
    config: Config,
    mingdao: MingdaoClient,
    gsc: GSCClient,
    ahrefs: AhrefsClient,
    report: SyncReport,
) -> None:
    data_date = get_target_date(config)
    gsc_summary = gsc.query_site_summary(data_date)
    ahrefs_summary = ahrefs.get_dashboard_summary()

    this_week_start = data_date - dt.timedelta(days=6)
    last_week_end = data_date - dt.timedelta(days=7)
    last_week_start = data_date - dt.timedelta(days=13)
    this_week_clicks = gsc.query_clicks_sum(this_week_start, data_date)
    last_week_clicks = gsc.query_clicks_sum(last_week_start, last_week_end)
    traffic_week_change = calc_ratio_change(this_week_clicks, last_week_clicks)

    fields: dict[str, Any] = {
        "日期": data_date,
        "独立站": config.sync_site,
        "自然点击": gsc_summary["clicks"],
        "展示量": gsc_summary["impressions"],
        "平均CTR": gsc_summary["ctr"],
        "全站加权平均排名": round(gsc_summary["position"], 1) if gsc_summary["position"] else 0,
        "Top10词数": ahrefs_summary["top10_count"],
        "Top30词数": ahrefs_summary["top30_count"],
        "近7天RD变化": ahrefs_summary["new_referring_domains"],
        "已监控URL收录数": 0,
        "已监控URL异常数": 0,
        "异常预警": build_dashboard_alert(traffic_week_change),
    }
    if traffic_week_change is not None:
        fields["周环比流量"] = round(traffic_week_change, 4)
    if ahrefs_summary["top30_week_change"] is not None:
        fields["周环比Top30词"] = round(ahrefs_summary["top30_week_change"], 4)

    fields = {key: value for key, value in fields.items() if value is not None}
    mingdao.upsert_dashboard(data_date, fields)
    report.log_skip("页面管理表", "二期接入；收录数/异常数暂写 0")
    report.log_skip("关键词/外链表", "二期接入 Mingdao")


def run_sync(*, test_mingdao_only: bool = False) -> Path:
    setup_logging()
    logging.info("SEO Mingdao data sync started")

    config = Config.load()
    report = SyncReport(started_at=dt.datetime.now(), data_date=get_target_date(config), config=config)
    mingdao = MingdaoClient(config, report)

    mingdao.test_connection()

    if test_mingdao_only:
        report.log_skip("sync", "test-mingdao-only: skipped GSC/Ahrefs write")
        return report.save()

    gsc = GSCClient(config, report)
    ahrefs = AhrefsClient(config, report)
    sync_dashboard(config, mingdao, gsc, ahrefs, report)

    report_path = report.save()
    logging.info("SEO Mingdao data sync finished. Report: %s", report_path)
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync SEO data to Mingdao")
    parser.add_argument(
        "--test-mingdao-only",
        action="store_true",
        help="Only test Mingdao getFilterRows; do not call GSC/Ahrefs or write dashboard",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_sync(test_mingdao_only=args.test_mingdao_only)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("SEO Mingdao data sync failed")
        raise
