"""
Single-site SEO sync (MVP): pull GSC + Ahrefs data for one site and write to Feishu Bitable.

Run manually via run_sync.bat (about once per week). Multi-site support is not implemented yet.
"""
from __future__ import annotations

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


ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
REPORT_DIR = ROOT / "reports"
LOG_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

TABLE_LABELS = {
    "dashboard": "SEO自动数据看板",
    "keywords": "核心关键词总库",
    "pages": "页面全生命周期管理表",
    "backlinks": "外链建设管控表",
}


@dataclass
class SyncReport:
    started_at: dt.datetime
    data_date: dt.date
    config: Config
    api_calls: list[str] = None  # type: ignore[assignment]
    writes: list[str] = None  # type: ignore[assignment]
    skips: list[str] = None  # type: ignore[assignment]
    warnings: list[str] = None  # type: ignore[assignment]

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
            "SEO Feishu Sync Report",
            "=" * 60,
            f"Started : {self.started_at.isoformat(sep=' ', timespec='seconds')}",
            f"Finished: {finished_at.isoformat(sep=' ', timespec='seconds')}",
            f"Data date: {self.data_date.isoformat()} (today - DATA_DELAY_DAYS={self.config.data_delay_days})",
            f"GSC site : {self.config.gsc_site_url}",
            f"Ahrefs   : {self.config.ahrefs_target_domain}",
            "",
            f"API calls ({len(self.api_calls)})",
            "-" * 60,
        ]
        lines.extend(self.api_calls or ["(none)"])
        lines.extend(["", f"Feishu writes ({len(self.writes)})", "-" * 60])
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
class Config:
    feishu_app_id: str
    feishu_app_secret: str
    feishu_base_app_token: str
    feishu_table_dashboard_id: str
    feishu_table_keywords_id: str
    feishu_table_pages_id: str
    feishu_table_backlinks_id: str
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
        return cls(
            feishu_app_id=env_required("FEISHU_APP_ID"),
            feishu_app_secret=env_required("FEISHU_APP_SECRET"),
            feishu_base_app_token=env_required("FEISHU_BASE_APP_TOKEN"),
            feishu_table_dashboard_id=env_required("FEISHU_TABLE_DASHBOARD_ID"),
            feishu_table_keywords_id=env_required("FEISHU_TABLE_KEYWORDS_ID"),
            feishu_table_pages_id=env_required("FEISHU_TABLE_PAGES_ID"),
            feishu_table_backlinks_id=env_required("FEISHU_TABLE_BACKLINKS_ID"),
            gsc_site_url=env_required("GSC_SITE_URL"),
            google_auth_mode=os.getenv("GOOGLE_AUTH_MODE", "oauth").lower(),
            google_credentials_file=os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json"),
            google_client_secret_file=os.getenv("GOOGLE_CLIENT_SECRET_FILE", "client_secret.json"),
            google_token_file=os.getenv("GOOGLE_TOKEN_FILE", "token.json"),
            ahrefs_api_token=env_required("AHREFS_API_TOKEN"),
            ahrefs_target_domain=env_required("AHREFS_TARGET_DOMAIN"),
            ahrefs_target_country=os.getenv("AHREFS_TARGET_COUNTRY", "us"),
            data_delay_days=int(os.getenv("DATA_DELAY_DAYS", "2")),
        )


FEISHU_DATE_FIELDS = {"日期"}


def get_target_date(config: Config) -> dt.date:
    return dt.date.today() - dt.timedelta(days=config.data_delay_days)


def feishu_date_ms(value: dt.date | dt.datetime | str) -> int:
    if isinstance(value, str):
        date_value = dt.date.fromisoformat(value)
    elif isinstance(value, dt.datetime):
        date_value = value.date()
    else:
        date_value = value
    midnight_utc = dt.datetime.combine(date_value, dt.time.min, tzinfo=dt.timezone.utc)
    return int(midnight_utc.timestamp() * 1000)


def normalize_feishu_write_fields(fields: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in fields.items():
        if key in FEISHU_DATE_FIELDS and value is not None:
            normalized[key] = feishu_date_ms(value)
        else:
            normalized[key] = value
    return normalized


def feishu_field_equals(field_name: str, stored: Any, expected: Any) -> bool:
    if stored == expected:
        return True
    if field_name not in FEISHU_DATE_FIELDS or expected is None:
        return False
    try:
        expected_ms = feishu_date_ms(expected)
    except ValueError:
        return False
    if isinstance(stored, (int, float)):
        return int(stored) == expected_ms
    if isinstance(stored, str):
        try:
            return feishu_date_ms(stored) == expected_ms
        except ValueError:
            return False
    return False


def env_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


class FeishuClient:
    def __init__(self, config: Config, report: SyncReport | None = None):
        self.config = config
        self.report = report
        self.base_url = "https://open.feishu.cn/open-apis"
        self.session = requests.Session()
        self.tenant_access_token = self.get_tenant_access_token()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.tenant_access_token}",
                "Content-Type": "application/json; charset=utf-8",
            }
        )

    def get_tenant_access_token(self) -> str:
        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        resp = requests.post(
            url,
            json={
                "app_id": self.config.feishu_app_id,
                "app_secret": self.config.feishu_app_secret,
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"Failed to get Feishu token: {payload}")
        if self.report:
            self.report.log_api("Feishu", "auth/v3/tenant_access_token/internal", detail="token acquired")
        return payload["tenant_access_token"]

    def list_records(self, table_id: str, page_size: int = 100) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            url = (
                f"{self.base_url}/bitable/v1/apps/"
                f"{self.config.feishu_base_app_token}/tables/{table_id}/records"
            )
            payload = self._request("GET", url, params=params)
            data = payload.get("data", {})
            records.extend(data.get("items", []))
            if not data.get("has_more"):
                return records
            page_token = data.get("page_token", "")

    def upsert_record(
        self,
        table_id: str,
        key_field: str,
        key_value: Any,
        fields: dict[str, Any],
        *,
        table_label: str = "",
    ) -> None:
        existing = self.find_record_by_field(table_id, key_field, key_value)
        label = table_label or table_id
        if existing:
            self.update_record(
                table_id,
                existing["record_id"],
                fields,
                table_label=label,
                action="update",
                key_value=key_value,
            )
        else:
            self.create_record(table_id, fields, table_label=label, action="create", key_value=key_value)

    def create_record(
        self,
        table_id: str,
        fields: dict[str, Any],
        *,
        table_label: str = "",
        action: str = "create",
        key_value: Any = "",
    ) -> dict[str, Any]:
        url = (
            f"{self.base_url}/bitable/v1/apps/"
            f"{self.config.feishu_base_app_token}/tables/{table_id}/records"
        )
        payload = self._request("POST", url, json={"fields": normalize_feishu_write_fields(fields)})
        if self.report:
            self.report.log_write(table_label or table_id, action, key_value, fields)
        return payload

    def update_record(
        self,
        table_id: str,
        record_id: str,
        fields: dict[str, Any],
        *,
        table_label: str = "",
        action: str = "update",
        key_value: Any = "",
    ) -> dict[str, Any]:
        url = (
            f"{self.base_url}/bitable/v1/apps/"
            f"{self.config.feishu_base_app_token}/tables/{table_id}/records/{record_id}"
        )
        payload = self._request("PUT", url, json={"fields": normalize_feishu_write_fields(fields)})
        if self.report:
            self.report.log_write(table_label or table_id, action, key_value or record_id, fields)
        return payload

    def find_record_by_field(self, table_id: str, key_field: str, key_value: Any) -> dict[str, Any] | None:
        for record in self.list_records(table_id):
            fields = record.get("fields", {})
            stored = fields.get(key_field)
            if feishu_field_equals(key_field, stored, key_value) or stored == key_value:
                return record
        return None

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        resp = self.session.request(method, url, timeout=60, **kwargs)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"Feishu API error: {payload}")
        return payload


class GSCClient:
    SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
    API_BASE = "https://searchconsole.googleapis.com/webmasters/v3"
    INSPECTION_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
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
        result = self._query_search_analytics(body, label="query_site_summary")
        rows = result.get("rows", [])
        if not rows:
            summary = {
                "clicks": 0,
                "impressions": 0,
                "ctr": 0,
                "position": 0,
            }
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
        result = self._query_search_analytics(
            body,
            label=f"query_clicks_sum {start_date.isoformat()}..{end_date.isoformat()}",
        )
        rows = result.get("rows", [])
        clicks = int(rows[0].get("clicks", 0)) if rows else 0
        if self.report:
            self.report.log_api(
                "GSC",
                "searchAnalytics/query (clicks sum)",
                detail=f"range={start_date.isoformat()}..{end_date.isoformat()} clicks={clicks}",
            )
        return clicks

    def query_page_clicks(self, date_value: dt.date, page_url: str) -> int:
        body = {
            "startDate": date_value.isoformat(),
            "endDate": date_value.isoformat(),
            "dimensions": ["page"],
            "dimensionFilterGroups": [
                {
                    "filters": [
                        {
                            "dimension": "page",
                            "operator": "equals",
                            "expression": page_url,
                        }
                    ]
                }
            ],
            "rowLimit": 1,
        }
        result = self._query_search_analytics(body, label=f"query_page_clicks {page_url}")
        rows = result.get("rows", [])
        clicks = int(rows[0].get("clicks", 0)) if rows else 0
        if self.report:
            self.report.log_api(
                "GSC",
                "searchAnalytics/query (page clicks)",
                detail=f"date={date_value.isoformat()} page={page_url} clicks={clicks}",
            )
        return clicks

    def inspect_page_index_status(self, page_url: str) -> str | None:
        if not page_url_belongs_to_property(page_url, self.site_url):
            message = (
                f"页面 URL 不在 GSC 资源范围内: {page_url} "
                f"(当前 GSC_SITE_URL={self.site_url})"
            )
            if self.report:
                self.report.log_warning(message)
            return None

        body = {
            "inspectionUrl": page_url,
            "siteUrl": self.site_url,
        }
        last_error: Exception | None = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = self.session.post(
                    self.INSPECTION_URL,
                    json=body,
                    timeout=self.REQUEST_TIMEOUT,
                )
                if response.status_code == 403:
                    message = self._extract_error_message(response)
                    if self._is_url_property_mismatch(message):
                        if self.report:
                            self.report.log_warning(
                                f"URL Inspection 403: {page_url} | {message} | "
                                f"请确认页面 URL 与 GSC_SITE_URL={self.site_url} 完全一致"
                            )
                        return None
                    self._raise_gsc_permission_error(response)
                response.raise_for_status()
                payload = response.json()
                index_result = payload.get("inspectionResult", {}).get("indexStatusResult", {})
                status = map_gsc_index_status(
                    index_result.get("coverageState", ""),
                    index_result.get("verdict", ""),
                )
                if self.report:
                    self.report.log_api(
                        "GSC",
                        "urlInspection/index:inspect",
                        detail=f"page={page_url} status={status} coverage={index_result.get('coverageState', '')}",
                    )
                return status
            except requests.exceptions.RequestException as exc:
                last_error = exc
                logging.warning(
                    "GSC URL inspection failed (attempt %s/%s): %s",
                    attempt,
                    self.MAX_RETRIES,
                    exc,
                )
                if attempt < self.MAX_RETRIES:
                    time.sleep(2)
        if self.report:
            self.report.log_api(
                "GSC",
                "urlInspection/index:inspect",
                ok=False,
                detail=f"page={page_url} error={last_error}",
            )
        return None

    @staticmethod
    def _extract_error_message(response: requests.Response) -> str:
        try:
            payload = response.json()
            return payload.get("error", {}).get("message", response.text)
        except ValueError:
            return response.text

    @staticmethod
    def _is_url_property_mismatch(message: str) -> bool:
        lowered = message.lower()
        return (
            "do not own this site" in lowered
            or "not part of this property" in lowered
            or "inspected url" in lowered
        )

    def _query_search_analytics(self, body: dict[str, Any], label: str = "searchAnalytics/query") -> dict[str, Any]:
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
            "无法连接 Google Search Console API。请检查网络/VPN/代理，或在 .env 中设置 "
            "HTTPS_PROXY 后重试。"
        ) from last_error

    def _raise_gsc_permission_error(self, response: requests.Response) -> None:
        message = self._extract_error_message(response)
        if "has not been used" in message or "is disabled" in message:
            raise RuntimeError(
                "Google Search Console API 未启用。请打开 Google Cloud Console，"
                "在创建 OAuth 客户端的同一项目中启用 Search Console API，然后等待 1-2 分钟再重试。"
            ) from None

        raise RuntimeError(
            "Google Search Console 返回 403。"
            "请确认：1) 已在 Cloud Console 启用 Search Console API；"
            "2) 授权账号对该站点有权限；"
            f"3) GSC_SITE_URL 与 Search Console 中的站点地址完全一致。详情: {message}"
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
        self._overview_cache: dict[str, dict[str, Any]] = {}

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

    def preload_keyword_overview(self, keywords: list[str]) -> None:
        missing = [
            keyword
            for keyword in keywords
            if keyword.casefold() not in self.load_organic_rankings()
            and keyword.casefold() not in self._overview_cache
        ]
        if not missing:
            return

        chunk_size = 50
        for index in range(0, len(missing), chunk_size):
            chunk = missing[index : index + chunk_size]
            payload = self._request(
                "keywords-explorer/overview",
                {
                    "keywords": ",".join(chunk),
                    "country": self.config.ahrefs_target_country.lower(),
                    "select": "keyword,volume,difficulty",
                },
            )
            for item in payload.get("keywords", []):
                keyword = item.get("keyword")
                if keyword:
                    self._overview_cache[str(keyword).casefold()] = item

    def get_keyword_metrics(self, keyword: str) -> dict[str, Any]:
        ranking = self.load_organic_rankings().get(keyword.casefold())
        if ranking:
            return {
                "volume": ranking.get("volume"),
                "kd": ranking.get("keyword_difficulty"),
                "position": ranking.get("best_position"),
                "rank_change": format_rank_change(ranking.get("best_position_diff")),
            }

        overview = self._overview_cache.get(keyword.casefold())
        if overview is None:
            self.preload_keyword_overview([keyword])
            overview = self._overview_cache.get(keyword.casefold())

        if overview:
            return {
                "volume": overview.get("volume"),
                "kd": overview.get("difficulty"),
                "position": None,
                "rank_change": "未进Top100",
            }

        logging.warning("Ahrefs returned no data for keyword: %s", keyword)
        return {
            "volume": None,
            "kd": None,
            "position": None,
            "rank_change": "",
        }

    def get_domain_rating(self, domain: str) -> dict[str, Any]:
        target = normalize_domain(domain)
        if not target:
            return {"dr": None, "is_indexed": None}

        payload = self._request(
            "site-explorer/domain-rating",
            {
                "target": target,
                "date": self.report_date.isoformat(),
            },
        )
        rating = payload.get("domain_rating", {})
        is_indexed = self._is_backlink_live(target)
        if self.report:
            self.report.log_api(
                "Ahrefs",
                "site-explorer/domain-rating",
                detail=f"domain={target} dr={rating.get('domain_rating')} indexed={is_indexed}",
            )
        return {
            "dr": rating.get("domain_rating"),
            "is_indexed": is_indexed,
        }

    def get_dashboard_summary(self, tracked_keywords: list[str]) -> dict[str, Any]:
        rankings = self.load_organic_rankings()
        top10_count = 0
        top30_count = 0
        previous_top30_count = 0
        for keyword in tracked_keywords:
            ranking = rankings.get(keyword.casefold())
            if not ranking:
                continue
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

    def _is_backlink_live(self, referring_domain: str) -> bool | None:
        where = json.dumps(
            {"field": "root_name_source", "is": ["eq", referring_domain]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        payload = self._request(
            "site-explorer/all-backlinks",
            {
                "target": self.config.ahrefs_target_domain,
                "select": "is_lost",
                "where": where,
                "history": "live",
                "limit": 1,
            },
        )
        backlinks = payload.get("backlinks", [])
        if not backlinks:
            return False
        return not bool(backlinks[0].get("is_lost"))

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


def map_gsc_index_status(coverage_state: str, verdict: str) -> str:
    state = (coverage_state or "").lower()
    if verdict == "PASS" or "submitted and indexed" in state:
        return "已收录"
    if verdict == "FAIL" or "not indexed" in state:
        return "未收录"
    return "索引异常"


def build_dashboard_alert(
    gsc_summary: dict[str, Any],
    page_stats: dict[str, int],
    traffic_week_change: float | None,
) -> str:
    alerts: list[str] = []
    if traffic_week_change is not None and traffic_week_change <= -0.2:
        alerts.append("流量下跌")
    if page_stats.get("updated", 0) > 0 and page_stats.get("crawl_issues", 0) > 0:
        alerts.append("收录异常")
    return alerts[0] if alerts else "正常"


def sync_dashboard(
    config: Config,
    feishu: FeishuClient,
    gsc: GSCClient,
    ahrefs: AhrefsClient,
    tracked_keywords: list[str],
    page_stats: dict[str, int],
    report: SyncReport,
) -> None:
    data_date = get_target_date(config)
    gsc_summary = gsc.query_site_summary(data_date)
    ahrefs_summary = ahrefs.get_dashboard_summary(tracked_keywords)

    this_week_start = data_date - dt.timedelta(days=6)
    last_week_end = data_date - dt.timedelta(days=7)
    last_week_start = data_date - dt.timedelta(days=13)
    this_week_clicks = gsc.query_clicks_sum(this_week_start, data_date)
    last_week_clicks = gsc.query_clicks_sum(last_week_start, last_week_end)
    traffic_week_change = calc_ratio_change(this_week_clicks, last_week_clicks)

    fields: dict[str, Any] = {
        "日期": data_date,
        "自然点击（GSC）": gsc_summary["clicks"],
        "展示量（GSC）": gsc_summary["impressions"],
        "平均CTR": gsc_summary["ctr"],
        "全站平均排名": gsc_summary["position"],
        "核心词Top10数量": ahrefs_summary["top10_count"],
        "核心词Top30数量": ahrefs_summary["top30_count"],
        "今日新增RD（referring domain）": ahrefs_summary["new_referring_domains"],
        "网站总收录页面": page_stats.get("indexed_pages", 0),
        "抓取异常数量": page_stats.get("crawl_issues", 0),
        "异常预警": build_dashboard_alert(gsc_summary, page_stats, traffic_week_change),
    }
    if traffic_week_change is not None:
        fields["周环比流量"] = traffic_week_change
    if ahrefs_summary["top30_week_change"] is not None:
        fields["周环比Top30词"] = ahrefs_summary["top30_week_change"]

    fields = remove_none_values(fields)
    fields["日期"] = data_date
    fields["异常预警"] = build_dashboard_alert(gsc_summary, page_stats, traffic_week_change)

    feishu.upsert_record(
        table_id=config.feishu_table_dashboard_id,
        key_field="日期",
        key_value=data_date,
        fields=fields,
        table_label=TABLE_LABELS["dashboard"],
    )


def sync_keywords(config: Config, feishu: FeishuClient, ahrefs: AhrefsClient, report: SyncReport) -> list[str]:
    table = TABLE_LABELS["keywords"]
    records = feishu.list_records(config.feishu_table_keywords_id)
    if not records:
        report.log_skip(table, "表格无记录，请先在飞书手动添加关键词行（填写「关键词内容」）")
        return []

    keywords = [
        str(fields["关键词内容"])
        for record in records
        if (fields := record.get("fields", {})).get("关键词内容")
    ]
    if not keywords:
        report.log_skip(table, f"共 {len(records)} 行，但没有一行填写「关键词内容」")
        return []

    ahrefs.load_organic_rankings()
    ahrefs.preload_keyword_overview(keywords)
    updated = 0
    empty_keyword_rows = len(records) - len(keywords)
    for record in records:
        fields = record.get("fields", {})
        keyword = fields.get("关键词内容")
        if not keyword:
            continue

        metrics = ahrefs.get_keyword_metrics(str(keyword))
        update_fields = {"日期": ahrefs.report_date}
        update_fields.update(remove_none_values({
            "搜索量（月）": metrics["volume"],
            "KD难度": metrics["kd"],
            "当前排名": metrics["position"],
            "排名波动": metrics["rank_change"],
        }))
        feishu.update_record(
            config.feishu_table_keywords_id,
            record["record_id"],
            update_fields,
            table_label=table,
            key_value=keyword,
        )
        updated += 1

    if empty_keyword_rows:
        report.log_skip(
            table,
            f"{empty_keyword_rows} 行为空行（未填「关键词内容」），已跳过；已成功更新 {updated} 行",
        )
    elif updated == 0:
        report.log_skip(table, "没有可更新的关键词行")
    return keywords


def sync_pages(
    config: Config,
    feishu: FeishuClient,
    gsc: GSCClient,
    report: SyncReport,
) -> dict[str, int]:
    table = TABLE_LABELS["pages"]
    data_date = get_target_date(config)
    records = feishu.list_records(config.feishu_table_pages_id)
    if not records:
        report.log_skip(table, "表格无记录，请先在飞书手动添加页面行（填写「页面URL」）")
        return {"indexed_pages": 0, "crawl_issues": 0, "updated": 0}

    indexed_pages = 0
    crawl_issues = 0
    updated = 0
    empty_url_rows = 0
    for record in records:
        fields = record.get("fields", {})
        raw_url = normalize_feishu_url(fields.get("页面URL"))
        if not raw_url:
            empty_url_rows += 1
            continue

        page_url = normalize_page_url_for_gsc(raw_url, config.gsc_site_url)
        if not page_url_belongs_to_property(page_url, config.gsc_site_url):
            report.log_skip(
                table,
                f"record={record['record_id']} URL 不在 GSC 资源内: {raw_url} "
                f"(需与 {config.gsc_site_url} 一致，含 www/协议/路径)",
            )
            continue

        clicks = gsc.query_page_clicks(data_date, page_url)
        index_status = gsc.inspect_page_index_status(page_url)
        update_fields: dict[str, Any] = {
            "日期": data_date,
            "页面流量": clicks,
        }
        if index_status is not None:
            update_fields["收录状态"] = index_status
            if index_status == "已收录":
                indexed_pages += 1
            else:
                crawl_issues += 1
        else:
            report.log_skip(table, f"record={record['record_id']} 收录状态未检测: {page_url}")

        feishu.update_record(
            config.feishu_table_pages_id,
            record["record_id"],
            update_fields,
            table_label=table,
            key_value=page_url,
        )
        updated += 1

    if empty_url_rows:
        report.log_skip(
            table,
            f"{empty_url_rows} 行为空行（未填「页面URL」），已跳过；已成功更新 {updated} 行",
        )
    elif updated == 0:
        report.log_skip(table, "没有可更新的页面行")

    stats = {"indexed_pages": indexed_pages, "crawl_issues": crawl_issues, "updated": updated}
    report.log_api(
        "GSC",
        "page index summary",
        detail=f"indexed={indexed_pages} crawl_issues={crawl_issues} updated_pages={updated}",
    )
    return stats


def sync_backlinks(config: Config, feishu: FeishuClient, ahrefs: AhrefsClient, report: SyncReport) -> None:
    table = TABLE_LABELS["backlinks"]
    data_date = ahrefs.report_date
    records = feishu.list_records(config.feishu_table_backlinks_id)
    if not records:
        report.log_skip(table, "表格无记录，请先在飞书手动添加外链行（填写「外链来源域名」）")
        return

    updated = 0
    empty_domain_rows = 0
    for record in records:
        fields = record.get("fields", {})
        domain = normalize_domain(normalize_feishu_url(fields.get("外链来源域名")))
        if not domain:
            empty_domain_rows += 1
            continue

        metrics = ahrefs.get_domain_rating(domain)
        update_fields: dict[str, Any] = {"日期": data_date}
        update_fields.update(remove_none_values({
            "域名DR值": metrics["dr"],
        }))
        if metrics["is_indexed"] is True:
            update_fields["外链收录状态"] = "已收录"
        elif metrics["is_indexed"] is False:
            update_fields["外链收录状态"] = "未收录"

        feishu.update_record(
            config.feishu_table_backlinks_id,
            record["record_id"],
            update_fields,
            table_label=table,
            key_value=domain,
        )
        updated += 1

    if empty_domain_rows:
        report.log_skip(
            table,
            f"{empty_domain_rows} 行为空行（未填「外链来源域名」），已跳过；已成功更新 {updated} 行",
        )
    elif updated == 0:
        report.log_skip(table, "没有可更新的外链行")


def format_rank_change(diff: Any) -> str:
    if diff is None:
        return ""
    try:
        value = int(diff)
    except (TypeError, ValueError):
        return ""
    if value == 0:
        return "持平"
    if value < 0:
        return f"↑{abs(value)}"
    return f"↓{value}"


def normalize_domain(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if "://" in raw or raw.startswith("//"):
        hostname = urlparse(raw).netloc
    else:
        hostname = raw.split("/", 1)[0]
    return hostname.lower().removeprefix("www.")


def normalize_feishu_url(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("link") or value.get("text") or "").strip()
    if isinstance(value, list) and value:
        return normalize_feishu_url(value[0])
    return ""


def normalize_page_url_for_gsc(page_url: str, site_url: str) -> str:
    raw = page_url.strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        return raw
    base = site_url.rstrip("/")
    if raw.startswith("/"):
        return f"{base}{raw}"
    return f"{base}/{raw.lstrip('/')}"


def page_url_belongs_to_property(page_url: str, site_url: str) -> bool:
    if not page_url:
        return False
    if site_url.startswith("sc-domain:"):
        domain = site_url.removeprefix("sc-domain:").lower()
        host = urlparse(page_url).netloc.lower().removeprefix("www.")
        return host == domain or host.endswith(f".{domain}")
    prefix = site_url.rstrip("/").lower()
    normalized = page_url.rstrip("/").lower()
    return normalized.startswith(prefix)


def remove_none_values(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def main() -> None:
    setup_logging()
    logging.info("SEO Feishu data sync started")

    config = Config.load()
    report = SyncReport(started_at=dt.datetime.now(), data_date=get_target_date(config), config=config)
    feishu = FeishuClient(config, report)
    gsc = GSCClient(config, report)
    ahrefs = AhrefsClient(config, report)

    report.log_skip("SEO每日执行", "该表以人工填写为主，当前脚本不自动写入")
    report.log_skip("周绩效复盘", "该表以人工填写为主，当前脚本不自动写入")

    tracked_keywords = sync_keywords(config, feishu, ahrefs, report)
    page_stats = sync_pages(config, feishu, gsc, report)
    sync_dashboard(config, feishu, gsc, ahrefs, tracked_keywords, page_stats, report)
    sync_backlinks(config, feishu, ahrefs, report)

    report_path = report.save()
    logging.info("SEO Feishu data sync finished. Report: %s", report_path)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("SEO Feishu data sync failed")
        raise
