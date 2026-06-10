"""
SEO sync: pull GSC + Ahrefs and write to Mingdao worksheets.

Run via run_sync.bat (about once per week).
Writes: SEO 自动数据看板、站点关键词库、页面管理表、GSC Top 查询/页面明细。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlparse

import requests
from dotenv import load_dotenv

from keyword_grading import (
    KeywordGradeDetail,
    format_grading_summary_lines,
    grade_keyword,
    normalize_ahrefs_cpc,
    should_auto_write_priority,
)

try:
    from google.auth import exceptions as google_auth_exceptions
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    google_auth_exceptions = None
    AuthorizedSession = None
    Request = None
    service_account = None
    Credentials = None
    InstalledAppFlow = None

# 443/SSL 等瞬时网络错误：整站重试 + OAuth 刷新重试（避免第 1 站失败导致后 4 站未跑）
GOOGLE_CREDENTIAL_MAX_ATTEMPTS = 5
GOOGLE_CREDENTIAL_RETRY_SECONDS = 4
SITE_SYNC_MAX_ATTEMPTS = 3
SITE_SYNC_RETRY_SECONDS = 5


ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
REPORT_DIR = ROOT / "reports"
CACHE_DIR = ROOT / "cache"
OPTIONS_FILE = ROOT / "config" / "mingdao_options.json"
SITES_FILE = ROOT / "config" / "sites.json"
WORKSHEETS_FILE = ROOT / "config" / "mingdao_worksheets.json"
LOG_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

load_dotenv(ROOT / ".env")


def apply_proxy_env() -> None:
    """Load optional proxy vars from .env (Google 默认不强制走 HTTPS_PROXY)。"""
    for key in ("MINGDAO_PROXY", "AHREFS_PROXY", "GOOGLE_PROXY", "NO_PROXY"):
        value = os.getenv(key, "").strip()
        if value:
            os.environ[key] = value


def parse_proxy_value(value: str) -> dict[str, str]:
    raw = value.strip()
    if not raw or raw.lower() in {"none", "direct", "off", "false", "0", "tun"}:
        return {}
    return {"http": raw, "https": raw}


def get_google_proxies() -> dict[str, str]:
    """仅当 .env 显式设置 GOOGLE_PROXY 时才手动指定；否则走系统代理（Clash 全局/规则）。"""
    explicit = (os.getenv("GOOGLE_PROXY") or "").strip()
    if explicit:
        return parse_proxy_value(explicit)
    if os.getenv("GOOGLE_USE_HTTPS_PROXY", "").lower() in {"1", "true", "yes"}:
        http = (os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or "").strip()
        if http:
            return {"http": http, "https": http}
    return {}


def configure_google_session(session: requests.Session) -> None:
    google_proxy = get_google_proxies()
    if google_proxy:
        session.trust_env = False
        session.proxies.update(google_proxy)
        logging.info("Google API proxy (manual): %s", google_proxy["https"])
    else:
        # 无 TUN 时：Clash 全局/智能 +「系统代理」即可（与上周飞书同步相同思路）
        session.trust_env = True
        session.proxies.clear()
        logging.info("Google API proxy: system (Clash 全局/规则，请开启系统代理)")


def get_mingdao_proxies() -> dict[str, str]:
    return parse_proxy_value(os.getenv("MINGDAO_PROXY", ""))


apply_proxy_env()

DASHBOARD_LABEL = "SEO自动数据看板"
KEYWORDS_LABEL = "站点关键词库"
PAGES_LABEL = "页面管理表"
GSC_TOP_QUERIES_LABEL = "GSC Top 查询明细"
GSC_TOP_PAGES_LABEL = "GSC Top 页面明细"


def format_sync_command(argv: list[str] | None = None) -> str:
    argv = argv or sys.argv
    args = argv[1:]
    if Path(argv[0]).name == "sync.py":
        return "run_sync.bat " + " ".join(args)
    return " ".join(argv)


@dataclass
class SyncReport:
    started_at: dt.datetime
    data_date: dt.date
    config: "Config"
    command_line: str = ""
    tables: SyncTables | None = None
    api_calls: list[str] | None = None
    writes: list[str] | None = None
    skips: list[str] | None = None
    warnings: list[str] | None = None
    keyword_grading_lines: list[str] | None = None
    site_outcomes: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        self.api_calls = []
        self.writes = []
        self.skips = []
        self.warnings = []
        self.keyword_grading_lines = []
        self.site_outcomes = []

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

    def record_site_outcome(self, site_key: str, *, ok: bool, error: str = "") -> None:
        self.site_outcomes.append({"site": site_key, "ok": ok, "error": error})

    def add_keyword_grading_report(self, lines: list[str]) -> None:
        self.keyword_grading_lines.extend(lines)

    def _write_count_for_table(self, table_label: str) -> tuple[int, int]:
        creates = updates = 0
        needle = f"[WRITE] {table_label} "
        for line in self.writes:
            if not line.startswith(needle):
                continue
            if " create " in line:
                creates += 1
            elif " update " in line or " enrich " in line:
                updates += 1
        return creates, updates

    def _mingdao_writes_summary(self, tables: SyncTables) -> str:
        """按本次实际跑的模块汇总写入次数（未跑的表不出现在括号里）。"""
        base = f"Mingdao writes: {len(self.writes)} total"
        parts: list[str] = []
        module_tables: list[tuple[bool, str, str]] = [
            (tables.dashboard, DASHBOARD_LABEL, "看板"),
            (tables.keywords, "站点关键词库", "关键词"),
            (tables.pages, PAGES_LABEL, "页面"),
            (tables.gsc_top_queries, GSC_TOP_QUERIES_LABEL, "GSC查询"),
            (tables.gsc_top_pages, GSC_TOP_PAGES_LABEL, "GSC页面"),
        ]
        for enabled, label, short in module_tables:
            if not enabled:
                continue
            creates, updates = self._write_count_for_table(label)
            parts.append(f"{short} create {creates} / update {updates}")
        if parts:
            return f"{base} ({'; '.join(parts)})"
        return base

    def _dashboard_rows_for_site(self, site_key: str) -> int:
        prefix = f"key={site_key}@"
        return sum(
            1 for line in self.writes if line.startswith(f"[WRITE] {DASHBOARD_LABEL}") and prefix in line
        )

    def render_summary(self, finished_at: dt.datetime) -> list[str]:
        elapsed = max(0, (finished_at - self.started_at).total_seconds())
        tables = self.tables or SyncTables()
        failed = [o for o in self.site_outcomes if not o["ok"]]
        succeeded = [o for o in self.site_outcomes if o["ok"]]
        api_fail = sum(1 for line in self.api_calls if "[API][FAIL]" in line)

        if not self.site_outcomes:
            overall = "测试/未跑站点"
        elif failed and not succeeded:
            overall = "失败"
        elif failed:
            overall = "部分成功"
        elif self.warnings or api_fail:
            overall = "全部完成（有警告）"
        else:
            overall = "全部成功"

        modules: list[str] = []
        if tables.dashboard:
            modules.append("看板")
        if tables.keywords:
            modules.append("关键词")
        if tables.pages:
            modules.append("页面")
        if tables.gsc_top_queries:
            modules.append("GSC查询")
        if tables.gsc_top_pages:
            modules.append("GSC页面")
        module_text = "、".join(modules) if modules else "(无)"

        dash_create, dash_update = self._write_count_for_table(DASHBOARD_LABEL)
        expected_dash = (
            len(self.config.sites) * self.config.dashboard_sync_days if tables.dashboard else 0
        )
        gsc_top_enabled = tables.gsc_top_queries or tables.gsc_top_pages

        lines = [
            "",
            "Summary 总结",
            "-" * 60,
            f"Overall       : {overall}",
            f"Duration      : {elapsed:.0f}s",
            f"Sync modules  : {module_text}",
            f"Anchor date   : {self.data_date.isoformat()}",
        ]
        if tables.dashboard:
            lines.append(
                f"Dashboard win : {self.config.dashboard_sync_days} days ending on anchor"
            )
        if gsc_top_enabled:
            lines.append(
                f"GSC Top win   : {self.config.dashboard_sync_days} days ending on anchor "
                f"(查询/页面各写锚点−{self.config.dashboard_sync_days - 1} … 锚点)"
            )
        lines.extend(
            [
                self._mingdao_writes_summary(tables),
                f"Warnings      : {len(self.warnings)}",
                f"API failures  : {api_fail}",
            ]
        )
        if tables.dashboard and expected_dash:
            lines.append(f"Dashboard rows: {dash_create + dash_update} written / {expected_dash} expected")

        if self.site_outcomes:
            lines.append("Per site:")
            for outcome in self.site_outcomes:
                site_key = outcome["site"]
                if outcome["ok"]:
                    detail = f"OK"
                    if tables.dashboard:
                        rows = self._dashboard_rows_for_site(site_key)
                        detail += f", 看板 {rows}/{self.config.dashboard_sync_days} 行"
                    lines.append(f"  - {site_key}: {detail}")
                else:
                    err = outcome.get("error") or "unknown error"
                    short = err.replace("\n", " ")[:120]
                    lines.append(f"  - {site_key}: FAIL — {short}")

        return lines

    def save(self) -> Path:
        finished_at = dt.datetime.now()
        report_path = REPORT_DIR / f"sync-report-{self.started_at.strftime('%Y%m%d-%H%M%S')}.txt"
        summary_lines = self.render_summary(finished_at)
        tables = self.tables or SyncTables()
        gsc_top_enabled = tables.gsc_top_queries or tables.gsc_top_pages
        header_lines: list[str] = []
        if self.command_line:
            header_lines.append(f"Command : {self.command_line}")
        header_lines.extend(
            [
            "SEO Mingdao Sync Report",
            "=" * 60,
            ]
        )
        header_lines.extend(
            [
                f"Started : {self.started_at.isoformat(sep=' ', timespec='seconds')}",
                f"Finished: {finished_at.isoformat(sep=' ', timespec='seconds')}",
                f"Anchor date : {self.data_date.isoformat()}",
            ]
        )
        if tables.dashboard:
            header_lines.append(
                f"Dashboard   : {self.config.dashboard_sync_days} days ending on anchor"
            )
        if gsc_top_enabled:
            header_lines.append(
                f"GSC Top     : {self.config.dashboard_sync_days} days ending on anchor"
            )
        header_lines.append(f"Sites     : {', '.join(site.key for site in self.config.sites)}")
        lines = header_lines
        if self.warnings:
            lines.extend(["", f"Warnings ({len(self.warnings)})", "-" * 60])
            lines.extend(self.warnings)
        lines.extend(summary_lines)
        lines.extend(
            [
                "",
                f"API calls ({len(self.api_calls)})",
                "-" * 60,
            ]
        )
        lines.extend(self.api_calls or ["(none)"])
        overall_line = next((ln for ln in summary_lines if ln.startswith("Overall")), "Overall: ?")
        logging.info(
            "Sync summary: %s | writes=%s warnings=%s",
            overall_line.split(":", 1)[-1].strip(),
            len(self.writes),
            len(self.warnings),
        )
        lines.extend(["", f"Mingdao writes ({len(self.writes)})", "-" * 60])
        lines.extend(self.writes or ["(none)"])
        lines.extend(["", f"Skipped ({len(self.skips)})", "-" * 60])
        lines.extend(self.skips or ["(none)"])
        if self.keyword_grading_lines:
            lines.extend(
                [
                    "",
                    f"Keyword grading ({len(self.keyword_grading_lines)} lines)",
                    "-" * 60,
                ]
            )
            lines.extend(self.keyword_grading_lines)
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
    top1_3: str
    top4_10: str
    top11_20: str
    top21_100: str
    backlinks: str
    weekly_avg_position: str | None
    site_dr: str | None
    indexed: str
    issues: str
    alert: str
    traffic_wow: str


# GSC query 平均排名分档（看板四档搜索词数）
RANK_BUCKET_SPECS: tuple[tuple[str, str, int, int], ...] = (
    ("GSC Top1-3 搜索词数", "top1_3", 1, 3),
    ("GSC Top4-10 搜索词数", "top4_10", 4, 10),
    ("GSC Top11-20 搜索词数", "top11_20", 11, 20),
    ("GSC Top21-100 搜索词数", "top21_100", 21, 100),
)

@dataclass(frozen=True)
class SiteConfig:
    key: str
    gsc_site_url: str
    ahrefs_domain: str
    homepage_url: str
    gsc_top_countries: tuple[str, ...] | None = None


@dataclass(frozen=True)
class WorksheetTableConfig:
    worksheet_id: str
    fields: dict[str, str]
    site_option_keys: dict[str, str]
    option_keys: dict[str, dict[str, str]]


@dataclass(frozen=True)
class WorksheetsConfig:
    keywords: WorksheetTableConfig
    pages: WorksheetTableConfig
    gsc_top_queries: WorksheetTableConfig
    gsc_top_pages: WorksheetTableConfig


@dataclass
class PageSyncStats:
    indexed_count: int = 0
    issues_count: int = 0
    updated: int = 0
    created: int = 0
    seeded_from_gsc: int = 0
    seeded_from_ahrefs: int = 0
    skipped_empty_url: int = 0
    skipped_missing_row: int = 0
    skipped_update_error: int = 0


@dataclass
class SyncTables:
    keywords: bool = True
    pages: bool = True
    dashboard: bool = True
    gsc_top_queries: bool = True
    gsc_top_pages: bool = True
    gsc_top_queries_enrich: bool = True
    gsc_top_queries_enrich_only: bool = False
    dashboard_gsc_buckets_only: bool = False


def sync_needs_gsc(tables: SyncTables) -> bool:
    return (
        tables.pages
        or tables.dashboard
        or (tables.gsc_top_queries and not tables.gsc_top_queries_enrich_only)
        or tables.gsc_top_pages
    )


@dataclass(frozen=True)
class Config:
    mingdao_app_key: str
    mingdao_sign: str
    mingdao_api_base: str
    mingdao_request_timeout: int
    mingdao_worksheet_dashboard: str
    dashboard_fields: DashboardFieldIds
    sites: tuple[SiteConfig, ...]
    site_option_keys: dict[str, str]
    alert_option_keys: dict[str, str]
    keyword_intent_option_keys: dict[str, str]
    keyword_priority_option_keys: dict[str, str]
    google_auth_mode: str
    google_credentials_file: str
    google_client_secret_file: str
    google_token_file: str
    ahrefs_api_token: str
    ahrefs_target_country: str
    ahrefs_aggregate_countries: tuple[str, ...]
    ahrefs_aggregate_max_countries: int
    worksheets: WorksheetsConfig
    data_delay_days: int
    dashboard_sync_days: int
    cache_enabled: bool
    cache_ttl_hours: int
    gsc_recent_refresh_days: int
    gsc_top_queries_limit: int
    gsc_top_pages_limit: int
    pages_gsc_import_limit: int
    page_import_min_impressions: int
    pages_ahrefs_import_limit: int
    pages_ahrefs_import_min_traffic: int
    gsc_top_queries_enrich_countries: tuple[str, ...]
    gsc_top_queries_enrich_mode: str
    gsc_top_queries_enrich_limit: int
    dashboard_gsc_query_limit: int

    @classmethod
    def load(cls, *, site_filter: list[str] | None = None) -> "Config":
        load_dotenv(ROOT / ".env")
        apply_proxy_env()
        options = load_mingdao_options()
        env_filter = os.getenv("SYNC_SITES", "").strip()
        if site_filter is None and env_filter:
            site_filter = [part.strip() for part in env_filter.split(",") if part.strip()]
        return cls(
            mingdao_app_key=env_required("MINGDAO_APP_KEY"),
            mingdao_sign=env_required("MINGDAO_SIGN"),
            mingdao_api_base=os.getenv("MINGDAO_API_BASE", "https://api.mingdao.com/v2/open/worksheet").rstrip("/"),
            mingdao_request_timeout=int(os.getenv("MINGDAO_REQUEST_TIMEOUT", "120")),
            mingdao_worksheet_dashboard=env_required("MINGDAO_WORKSHEET_DASHBOARD"),
            dashboard_fields=DashboardFieldIds(
                date=env_required("MINGDAO_FIELD_DASH_DATE"),
                site=env_required("MINGDAO_FIELD_DASH_SITE"),
                clicks=env_required("MINGDAO_FIELD_DASH_CLICKS"),
                impressions=env_required("MINGDAO_FIELD_DASH_IMPRESSIONS"),
                ctr=env_required("MINGDAO_FIELD_DASH_CTR"),
                position=env_required("MINGDAO_FIELD_DASH_POSITION"),
                top1_3=env_required("MINGDAO_FIELD_DASH_TOP1_3"),
                top4_10=env_required("MINGDAO_FIELD_DASH_TOP4_10"),
                top11_20=env_required("MINGDAO_FIELD_DASH_TOP11_20"),
                top21_100=env_required("MINGDAO_FIELD_DASH_TOP21_100"),
                backlinks=_env_dashboard_field(
                    "MINGDAO_FIELD_DASH_BACKLINKS",
                    "MINGDAO_FIELD_DASH_RD_DELTA",
                ),
                weekly_avg_position=os.getenv("MINGDAO_FIELD_DASH_WEEKLY_AVG_POSITION", "").strip() or None,
                site_dr=(
                    os.getenv("MINGDAO_FIELD_DASH_SITE_DR", "").strip()
                    or os.getenv("本站DR", "").strip()
                    or None
                ),
                indexed=env_required("MINGDAO_FIELD_DASH_INDEXED"),
                issues=env_required("MINGDAO_FIELD_DASH_ISSUES"),
                alert=env_required("MINGDAO_FIELD_DASH_ALERT"),
                traffic_wow=env_required("MINGDAO_FIELD_DASH_TRAFFIC_WOW"),
            ),
            sites=tuple(load_sites(site_filter)),
            site_option_keys=options["sites"],
            alert_option_keys=options["alerts"],
            keyword_intent_option_keys=options["keyword_intent_option_keys"],
            keyword_priority_option_keys=options["keyword_priority_option_keys"],
            google_auth_mode=os.getenv("GOOGLE_AUTH_MODE", "oauth").lower(),
            google_credentials_file=os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json"),
            google_client_secret_file=os.getenv("GOOGLE_CLIENT_SECRET_FILE", "client_secret.json"),
            google_token_file=os.getenv("GOOGLE_TOKEN_FILE", "token.json"),
            ahrefs_api_token=env_required("AHREFS_API_TOKEN"),
            ahrefs_target_country=os.getenv("AHREFS_TARGET_COUNTRY", "all").strip().lower(),
            ahrefs_aggregate_countries=tuple(
                parse_country_list(os.getenv("AHREFS_AGGREGATE_COUNTRIES", ""))
            ),
            ahrefs_aggregate_max_countries=int(os.getenv("AHREFS_AGGREGATE_MAX_COUNTRIES", "0")),
            worksheets=load_worksheets_config(),
            data_delay_days=int(os.getenv("DATA_DELAY_DAYS", "3")),
            dashboard_sync_days=int(os.getenv("DASHBOARD_SYNC_DAYS", "7")),
            cache_enabled=os.getenv("CACHE_ENABLED", "1").lower() not in {"0", "false", "no", "off"},
            cache_ttl_hours=int(os.getenv("CACHE_TTL_HOURS", "12")),
            gsc_recent_refresh_days=int(os.getenv("GSC_RECENT_REFRESH_DAYS", "2")),
            gsc_top_queries_limit=int(os.getenv("GSC_TOP_QUERIES_LIMIT", "1000")),
            gsc_top_pages_limit=int(os.getenv("GSC_TOP_PAGES_LIMIT", "1000")),
            pages_gsc_import_limit=int(
                os.getenv("PAGES_GSC_IMPORT_LIMIT", os.getenv("GSC_TOP_PAGES_LIMIT", "1000"))
            ),
            page_import_min_impressions=int(os.getenv("PAGE_IMPORT_MIN_IMPRESSIONS", "1")),
            pages_ahrefs_import_limit=int(
                os.getenv(
                    "PAGES_AHREFS_IMPORT_LIMIT",
                    os.getenv("PAGES_GSC_IMPORT_LIMIT", "1000"),
                )
            ),
            pages_ahrefs_import_min_traffic=int(os.getenv("PAGES_AHREFS_IMPORT_MIN_TRAFFIC", "0")),
            gsc_top_queries_enrich_countries=tuple(
                code.lower()
                for code in parse_country_list(
                    os.getenv("GSC_TOP_QUERIES_ENRICH_COUNTRIES", "")
                )
            ),
            gsc_top_queries_enrich_mode=os.getenv(
                "GSC_TOP_QUERIES_ENRICH_MODE", "clicks_gt_zero"
            ).strip().lower(),
            gsc_top_queries_enrich_limit=int(os.getenv("GSC_TOP_QUERIES_ENRICH_LIMIT", "500")),
            dashboard_gsc_query_limit=int(os.getenv("DASHBOARD_GSC_QUERY_LIMIT", "1000")),
        )

    def site_option_key(self, site_key: str) -> str:
        key = self.site_option_keys.get(site_key)
        if not key:
            known = ", ".join(sorted(self.site_option_keys))
            raise RuntimeError(f"Unknown site {site_key!r}. Known: {known}")
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
    priority_keys = {
        k: v
        for k, v in dict(payload.get("keyword_priority_option_keys", {})).items()
        if v
    }
    return {
        "sites": payload["sites"],
        "alerts": payload["alerts"],
        "keyword_intent_option_keys": dict(payload.get("keyword_intent_option_keys", {})),
        "keyword_priority_option_keys": priority_keys,
    }


def load_worksheet_table(raw: dict[str, Any]) -> WorksheetTableConfig:
    option_keys: dict[str, dict[str, str]] = {}
    for key in (
        "index_status_option_keys",
        "dofollow_option_keys",
        "link_status_option_keys",
        "country_option_keys",
    ):
        if key in raw:
            option_keys[key.removesuffix("_option_keys")] = dict(raw[key])
    return WorksheetTableConfig(
        worksheet_id=str(raw["worksheet_id"]),
        fields=dict(raw["fields"]),
        site_option_keys=dict(raw["site_option_keys"]),
        option_keys=option_keys,
    )


KEYWORD_FIELD_ENV_KEYS: dict[str, str] = {
    "site": "MINGDAO_FIELD_KEYWORD_SITE",
    "cpc": "MINGDAO_FIELD_KEYWORD_CPC",
    "value_score": "MINGDAO_FIELD_KEYWORD_VALUE_SCORE",
}

GSC_TOP_QUERIES_FIELD_ENV_KEYS: dict[str, str] = {
    "data_date": "MINGDAO_FIELD_GSC_QUERY_DATA_DATE",
    "site": "MINGDAO_FIELD_GSC_QUERY_SITE",
    "keyword": "MINGDAO_FIELD_GSC_QUERY_KEYWORD",
    "country": "MINGDAO_FIELD_GSC_QUERY_COUNTRY",
    "clicks": "MINGDAO_FIELD_GSC_QUERY_CLICKS",
    "impressions": "MINGDAO_FIELD_GSC_QUERY_IMPRESSIONS",
    "ctr": "MINGDAO_FIELD_GSC_QUERY_CTR",
    "position": "MINGDAO_FIELD_GSC_QUERY_POSITION",
    "ahrefs_volume": "MINGDAO_FIELD_GSC_QUERY_AHREFS_VOLUME",
    "ahrefs_kd": "MINGDAO_FIELD_GSC_QUERY_AHREFS_KD",
    "ahrefs_cpc": "MINGDAO_FIELD_GSC_QUERY_AHREFS_CPC",
}

# Ahrefs keywords-explorer 不支持的国家（GSC alpha-3）；enrich 跳过、不请求 overview
GSC_ENRICH_SKIP_COUNTRIES: frozenset[str] = frozenset({"irn"})

# GSC ISO 3166-1 alpha-3（小写）→ Ahrefs keywords-explorer 国家码（alpha-2）
# 与 config/mingdao_worksheets.json → gsc_top_queries.country_option_keys 对齐；zzz 无映射
GSC_COUNTRY_TO_AHREFS: dict[str, str] = {
    "ago": "ao",
    "alb": "al",
    "are": "ae",
    "arg": "ar",
    "arm": "am",
    "aus": "au",
    "aut": "at",
    "aze": "az",
    "bgr": "bg",
    "bhr": "bh",
    "bfa": "bf",
    "bgd": "bd",
    "bel": "be",
    "ben": "bj",
    "bih": "ba",
    "blr": "by",
    "blz": "bz",
    "bol": "bo",
    "bra": "br",
    "brb": "bb",
    "brn": "bn",
    "btn": "bt",
    "bwa": "bw",
    "can": "ca",
    "che": "ch",
    "chl": "cl",
    "chn": "cn",
    "civ": "ci",
    "cmr": "cm",
    "cod": "cd",
    "col": "co",
    "cri": "cr",
    "cyp": "cy",
    "cze": "cz",
    "deu": "de",
    "dnk": "dk",
    "dom": "do",
    "dza": "dz",
    "ecu": "ec",
    "egy": "eg",
    "esp": "es",
    "eth": "et",
    "fin": "fi",
    "fji": "fj",
    "fra": "fr",
    "gbr": "gb",
    "geo": "ge",
    "gha": "gh",
    "glp": "gp",
    "gnb": "gw",
    "grc": "gr",
    "gtm": "gt",
    "guy": "gy",
    "hkg": "hk",
    "hnd": "hn",
    "hrv": "hr",
    "hun": "hu",
    "idn": "id",
    "ind": "in",
    "irl": "ie",
    "irq": "iq",
    "isr": "il",
    "ita": "it",
    "jam": "jm",
    "jor": "jo",
    "jpn": "jp",
    "kaz": "kz",
    "ken": "ke",
    "khm": "kh",
    "kna": "kn",
    "kor": "kr",
    "kwt": "kw",
    "lbn": "lb",
    "lby": "ly",
    "lka": "lk",
    "ltu": "lt",
    "lux": "lu",
    "lva": "lv",
    "lie": "li",
    "mar": "ma",
    "maf": "mf",
    "mda": "md",
    "mdg": "mg",
    "mdv": "mv",
    "mex": "mx",
    "mkd": "mk",
    "mlt": "mt",
    "mmr": "mm",
    "mng": "mn",
    "mus": "mu",
    "mys": "my",
    "nam": "na",
    "nga": "ng",
    "nic": "ni",
    "nld": "nl",
    "nor": "no",
    "npl": "np",
    "nzl": "nz",
    "omn": "om",
    "pak": "pk",
    "pan": "pa",
    "per": "pe",
    "phl": "ph",
    "png": "pg",
    "pol": "pl",
    "pri": "us",
    "prt": "pt",
    "pse": "ps",
    "pry": "py",
    "pyf": "pf",
    "qat": "qa",
    "rou": "ro",
    "rus": "ru",
    "rwa": "rw",
    "sau": "sa",
    "sgp": "sg",
    "slv": "sv",
    "srb": "rs",
    "ssd": "ss",
    "svk": "sk",
    "svn": "si",
    "swz": "sz",
    "syr": "sy",
    "tha": "th",
    "tto": "tt",
    "tun": "tn",
    "tur": "tr",
    "twn": "tw",
    "tza": "tz",
    "uga": "ug",
    "ukr": "ua",
    "ury": "uy",
    "usa": "us",
    "uzb": "uz",
    "ven": "ve",
    "vnm": "vn",
    "xkk": "xk",
    "zaf": "za",
}

GSC_TOP_QUERIES_OVERVIEW_BATCH_SIZE = 50

GSC_TOP_PAGES_FIELD_ENV_KEYS: dict[str, str] = {
    "data_date": "MINGDAO_FIELD_GSC_PAGE_DATA_DATE",
    "site": "MINGDAO_FIELD_GSC_PAGE_SITE",
    "country": "MINGDAO_FIELD_GSC_PAGE_COUNTRY",
    "page_url": "MINGDAO_FIELD_GSC_PAGE_URL",
    "clicks": "MINGDAO_FIELD_GSC_PAGE_CLICKS",
    "impressions": "MINGDAO_FIELD_GSC_PAGE_IMPRESSIONS",
    "ctr": "MINGDAO_FIELD_GSC_PAGE_CTR",
    "position": "MINGDAO_FIELD_GSC_PAGE_POSITION",
}

PAGES_FIELD_ENV_KEYS: dict[str, str] = {
    "site": "MINGDAO_FIELD_PAGE_SITE",
    "page_url": "MINGDAO_FIELD_PAGE_URL",
    "ahrefs_first_seen": "MINGDAO_FIELD_PAGE_AHREFS_FIRST_SEEN",
    "word_count": "MINGDAO_FIELD_PAGE_WORD_COUNT",
    "primary_keyword": "MINGDAO_FIELD_PAGE_PRIMARY_KEYWORD",
    "primary_keyword_volume": "MINGDAO_FIELD_PAGE_PRIMARY_KEYWORD_VOLUME",
    "index_status": "MINGDAO_FIELD_PAGE_INDEX_STATUS",
    "clicks": "MINGDAO_FIELD_PAGE_CLICKS",
    "impressions": "MINGDAO_FIELD_PAGE_IMPRESSIONS",
    "ctr": "MINGDAO_FIELD_PAGE_CTR",
    "position": "MINGDAO_FIELD_PAGE_POSITION",
    "data_date": "MINGDAO_FIELD_PAGE_DATA_DATE",
    "ur": "MINGDAO_FIELD_PAGE_UR",
    "global_dr": "MINGDAO_FIELD_PAGE_GLOBAL_DR",
    "ahrefs_traffic": "MINGDAO_FIELD_PAGE_AHREFS_TRAFFIC",
    "ahrefs_value": "MINGDAO_FIELD_PAGE_AHREFS_VALUE",
    "keyword_count": "MINGDAO_FIELD_PAGE_KEYWORD_COUNT",
}

# 兼容 .env 里用明道云列名（中文）作键的旧写法
PAGES_FIELD_CHINESE_ENV_KEYS: dict[str, str] = {
    "site": "独立站",
    "page_url": "页面 URL",
    "ahrefs_first_seen": "发布日期",
    "word_count": "页面字数",
    "primary_keyword": "主关键词",
    "primary_keyword_volume": "主词搜索量",
    "index_status": "收录状态",
    "clicks": "GSC点击",
    "impressions": "GSC展示量",
    "ctr": "GSC平均CTR",
    "position": "GSC平均排名",
    "data_date": "数据日期",
    "ur": "URL权重UR",
    "global_dr": "全球排名DR",
    "ahrefs_traffic": "Ahrefs月流量",
    "ahrefs_value": "Ahrefs流量价值",
    "keyword_count": "排名关键词数",
}


def apply_field_env_overrides(fields: dict[str, str], env_keys: dict[str, str]) -> dict[str, str]:
    merged = dict(fields)
    for logical, env_key in env_keys.items():
        value = os.getenv(env_key, "").strip()
        if value:
            merged[logical] = value
    return merged


def apply_page_field_env_overrides(fields: dict[str, str]) -> dict[str, str]:
    """页面管理表：MINGDAO_FIELD_PAGE_* 覆盖 json；中文列名键作兜底。"""
    merged = apply_field_env_overrides(fields, PAGES_FIELD_ENV_KEYS)
    for logical, chinese_key in PAGES_FIELD_CHINESE_ENV_KEYS.items():
        if merged.get(logical):
            continue
        value = os.getenv(chinese_key, "").strip()
        if value:
            merged[logical] = value
    legacy_traffic = os.getenv("traffic", "").strip() or os.getenv("页面流量", "").strip()
    if legacy_traffic and not merged.get("clicks"):
        merged["clicks"] = legacy_traffic
    return merged


def apply_keyword_field_env_overrides(fields: dict[str, str]) -> dict[str, str]:
    """关键词表可选列：.env 覆盖 mingdao_worksheets.json（与看板 MINGDAO_FIELD_DASH_* 一致）。"""
    merged = apply_field_env_overrides(fields, KEYWORD_FIELD_ENV_KEYS)
    cpc = os.getenv("CPC", "").strip()
    if cpc and "cpc" not in KEYWORD_FIELD_ENV_KEYS:
        merged["cpc"] = cpc
    if cpc and not os.getenv("MINGDAO_FIELD_KEYWORD_CPC", "").strip():
        merged["cpc"] = cpc
    return merged


def apply_worksheet_env_overrides(raw: dict[str, Any], *, worksheet_env: str, field_env: dict[str, str]) -> dict[str, Any]:
    merged = dict(raw)
    worksheet_id = os.getenv(worksheet_env, "").strip()
    if worksheet_id:
        merged["worksheet_id"] = worksheet_id
    merged["fields"] = apply_field_env_overrides(dict(merged["fields"]), field_env)
    return merged


def load_worksheets_config() -> WorksheetsConfig:
    if not WORKSHEETS_FILE.exists():
        raise RuntimeError(f"Missing {WORKSHEETS_FILE}")
    payload = json.loads(WORKSHEETS_FILE.read_text(encoding="utf-8"))
    keywords_raw = dict(payload["keywords"])
    keywords_raw["fields"] = apply_keyword_field_env_overrides(dict(keywords_raw["fields"]))
    gsc_queries_raw = apply_worksheet_env_overrides(
        payload["gsc_top_queries"],
        worksheet_env="MINGDAO_WORKSHEET_GSC_TOP_QUERIES",
        field_env=GSC_TOP_QUERIES_FIELD_ENV_KEYS,
    )
    gsc_pages_raw = apply_worksheet_env_overrides(
        payload["gsc_top_pages"],
        worksheet_env="MINGDAO_WORKSHEET_GSC_TOP_PAGES",
        field_env=GSC_TOP_PAGES_FIELD_ENV_KEYS,
    )
    pages_raw = dict(payload["pages"])
    pages_raw["fields"] = apply_page_field_env_overrides(dict(pages_raw["fields"]))
    worksheet_id = (
        os.getenv("MINGDAO_WORKSHEET_PAGES", "").strip()
        or os.getenv("页面管理表", "").strip()
    )
    if worksheet_id:
        pages_raw["worksheet_id"] = worksheet_id
    return WorksheetsConfig(
        keywords=load_worksheet_table(keywords_raw),
        pages=load_worksheet_table(pages_raw),
        gsc_top_queries=load_worksheet_table(gsc_queries_raw),
        gsc_top_pages=load_worksheet_table(gsc_pages_raw),
    )


def worksheet_site_option(table: WorksheetTableConfig, site_key: str) -> str:
    key = table.site_option_keys.get(site_key)
    if not key:
        known = ", ".join(sorted(table.site_option_keys))
        raise RuntimeError(f"Unknown site {site_key!r} in worksheet config. Known: {known}")
    return key


def row_control_value(row: dict[str, Any], control_id: str) -> str:
    value = row.get(control_id, "")
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


def build_site_filter(control_id: str, site_option_key: str) -> dict[str, Any]:
    return {
        "controlId": control_id,
        "dataType": MingdaoClient.SELECT_TYPE,
        "spliceType": 1,
        "filterType": 2,
        "values": [site_option_key],
    }


def format_rank_change(item: dict[str, Any]) -> str:
    position = item.get("best_position")
    diff = item.get("best_position_diff")
    if position is None:
        return "未进Top100"
    if diff is None or diff == 0:
        return "持平"
    diff_int = int(diff)
    if diff_int < 0:
        return f"↑{abs(diff_int)}"
    return f"↓{diff_int}"


def map_gsc_index_status(payload: dict[str, Any]) -> str:
    index = payload.get("inspectionResult", {}).get("indexStatusResult", {})
    verdict = str(index.get("verdict", "")).upper()
    coverage = str(index.get("coverageState", "")).lower()
    if verdict == "PASS" or "indexed" in coverage:
        return "已收录"
    if verdict in {"FAIL", "PARTIAL"} or "error" in coverage or "redirect" in coverage:
        return "索引异常"
    return "未收录"


def parse_ahrefs_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    if "T" in text:
        return text.split("T", 1)[0]
    return text[:10] if len(text) >= 10 else text


def normalize_page_url(url: str) -> str:
    return url.strip().rstrip("/")


def normalize_page_url_for_gsc(url: str) -> str:
    """GSC URL Inspection / 页面维度查询需要完整 https URL。"""
    raw = url.strip()
    if not raw:
        return ""
    if not raw.startswith("http://") and not raw.startswith("https://"):
        raw = f"https://{raw}"
    return raw.rstrip("/") + "/"


def page_url_lookup_keys(page_url: str) -> list[str]:
    """GSC / Ahrefs URL 字符串变体，用于索引匹配。"""
    raw = page_url.strip()
    if not raw:
        return []
    candidates = [
        raw,
        raw.rstrip("/"),
        raw.rstrip("/") + "/",
        normalize_page_url_for_gsc(raw),
    ]
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = parsed.netloc.lower()
    path = parsed.path or "/"
    if host.startswith("www."):
        candidates.append(f"https://{host.removeprefix('www.')}{path}")
        candidates.append(f"https://{host.removeprefix('www.')}{path.rstrip('/')}/")
    elif host:
        candidates.append(f"https://www.{host}{path}")
        candidates.append(f"https://www.{host}{path.rstrip('/')}/")
    seen: set[str] = set()
    keys: list[str] = []
    for candidate in candidates:
        key = normalize_page_url(candidate)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def resolve_page_index_entry(index: dict[str, Any], page_url: str) -> dict[str, Any] | None:
    for key in page_url_lookup_keys(page_url):
        item = index.get(key)
        if item is not None:
            return item
    return None


def normalize_ahrefs_usd(value: Any) -> float:
    """Ahrefs 金额字段常为 USD 美分，转为美元。"""
    amount = float(value)
    if amount >= 100:
        return round(amount / 100, 2)
    return round(amount, 2)


def normalize_gsc_site_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if raw.startswith("sc-domain:"):
        return raw
    if not raw.startswith("http://") and not raw.startswith("https://"):
        raw = f"https://{raw}"
    return raw


def parse_country_list(value: str) -> list[str]:
    return [part.strip().lower() for part in value.split(",") if part.strip()]


def gsc_top_country_scope_label(site: SiteConfig) -> str:
    if not site.gsc_top_countries:
        return "all"
    return ",".join(site.gsc_top_countries)


def gsc_top_country_allowed(site: SiteConfig, country_code: str) -> bool:
    if not site.gsc_top_countries:
        return True
    return country_code.lower() in site.gsc_top_countries


def gsc_country_to_ahrefs(country_code: str) -> str | None:
    code = country_code.strip().lower()
    if not code:
        return None
    mapped = GSC_COUNTRY_TO_AHREFS.get(code)
    if mapped:
        return mapped
    if len(code) == 2:
        return code
    return None


def parse_mingdao_number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def gsc_top_queries_enrich_fields_ready(table: WorksheetTableConfig) -> bool:
    return all(
        table.fields.get(key)
        for key in ("ahrefs_volume", "ahrefs_kd", "ahrefs_cpc")
    )


def select_gsc_top_query_enrich_targets(
    groups: dict[tuple[str, str], dict[str, Any]],
    *,
    enrich_countries: tuple[str, ...],
    mode: str,
    limit: int,
) -> list[tuple[str, str, int, list[str]]]:
    allowed = {code.lower() for code in enrich_countries}
    items: list[tuple[str, str, int, list[str]]] = []
    for (keyword, country), data in groups.items():
        if allowed and country.lower() not in allowed:
            continue
        total_clicks = int(data.get("total_clicks") or 0)
        if mode == "clicks_gt_zero" and total_clicks <= 0:
            continue
        row_ids = list(data.get("row_ids") or [])
        if not row_ids:
            continue
        items.append((keyword, country, total_clicks, row_ids))
    items.sort(key=lambda item: item[2], reverse=True)
    if limit > 0:
        items = items[:limit]
    return items


def load_sites(site_filter: list[str] | None = None) -> list[SiteConfig]:
    if not SITES_FILE.exists():
        raise RuntimeError(f"Missing {SITES_FILE}")
    payload = json.loads(SITES_FILE.read_text(encoding="utf-8"))
    sites: list[SiteConfig] = []
    for item in payload.get("sites", []):
        key = str(item["key"]).strip()
        if site_filter and key not in site_filter:
            continue
        gsc_url = normalize_gsc_site_url(str(item["gsc_site_url"]))
        homepage = str(item.get("homepage_url", "")).strip()
        if not homepage:
            homepage = gsc_url if gsc_url.startswith("https://") else f"https://{normalize_ahrefs_domain(str(item['ahrefs_domain']))}/"
        raw_countries = item.get("gsc_top_countries")
        if raw_countries:
            gsc_top_countries = tuple(
                part.strip().lower()
                for part in raw_countries
                if str(part).strip()
            ) or None
        else:
            gsc_top_countries = None
        sites.append(
            SiteConfig(
                key=key,
                gsc_site_url=gsc_url,
                ahrefs_domain=normalize_ahrefs_domain(str(item["ahrefs_domain"])),
                homepage_url=homepage,
                gsc_top_countries=gsc_top_countries,
            )
        )
    if not sites:
        raise RuntimeError("No sites to sync. Check config/sites.json or SYNC_SITES filter.")
    return sites


def merge_organic_ranking(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    existing_pos = existing.get("best_position")
    incoming_pos = incoming.get("best_position")
    if existing_pos is None:
        return incoming
    if incoming_pos is None:
        return existing
    if incoming_pos < existing_pos:
        return incoming
    return existing


def env_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _env_dashboard_field(primary: str, *legacy_names: str) -> str:
    for name in (primary, *legacy_names):
        value = os.getenv(name, "").strip()
        if value:
            return value
    known = ", ".join((primary, *legacy_names))
    raise RuntimeError(f"Missing required env var (one of): {known}")


def normalize_ahrefs_domain(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if "://" in raw:
        host = urlparse(raw).netloc
    else:
        host = raw.split("/", 1)[0]
    return host.lower().removeprefix("www.")


def get_sync_anchor_date(config: Config) -> dt.date:
    """GSC 数据可用性锚点：today - DATA_DELAY_DAYS（建议 3，覆盖 1–3 天延迟）。"""
    return dt.date.today() - dt.timedelta(days=config.data_delay_days)


def resolve_sync_anchor_date(config: Config, override: str | None) -> dt.date:
    if override:
        return dt.date.fromisoformat(override.strip())
    return get_sync_anchor_date(config)


def get_target_date(config: Config, *, anchor_override: str | None = None) -> dt.date:
    return resolve_sync_anchor_date(config, anchor_override)


def calc_weekly_avg_position(daily_data: dict[dt.date, dict[str, Any]]) -> float | None:
    """同步窗口内（通常 7 天）全站加权平均排名的算术平均，供看板「周平均排名」。"""
    if not daily_data:
        return None
    positions = [float(day.get("position") or 0) for day in daily_data.values()]
    return round(sum(positions) / len(positions), 1)


def get_dashboard_dates(config: Config, *, anchor: dt.date | None = None) -> list[dt.date]:
    anchor = anchor or get_sync_anchor_date(config)
    start = anchor - dt.timedelta(days=config.dashboard_sync_days - 1)
    dates: list[dt.date] = []
    current = start
    while current <= anchor:
        dates.append(current)
        current += dt.timedelta(days=1)
    return dates


def empty_gsc_summary() -> dict[str, Any]:
    return {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0}


def is_provisional_gsc_zero(summary: dict[str, Any], date_value: dt.date, config: Config) -> bool:
    """ clicks/impressions 均为 0 且日期仍在 GSC 可能补数的窗口内 → 下次 sync 应重拉。"""
    clicks = int(summary.get("clicks") or 0)
    impressions = int(summary.get("impressions") or 0)
    if clicks > 0 or impressions > 0:
        return False
    days_since = (dt.date.today() - date_value).days
    return days_since <= config.data_delay_days + config.gsc_recent_refresh_days


class SyncCache:
    """本地 JSON 缓存：避免重复 GSC 请求；对仍为 0 的近期日期自动失效。"""

    def __init__(self, *, enabled: bool = True):
        self.enabled = enabled
        self.gsc_dir = CACHE_DIR / "gsc"
        if enabled:
            self.gsc_dir.mkdir(parents=True, exist_ok=True)

    def _gsc_path(self, site_key: str) -> Path:
        return self.gsc_dir / f"{site_key}.json"

    def load_gsc_site(self, site_key: str) -> dict[str, Any]:
        if not self.enabled:
            return {"days": {}}
        path = self._gsc_path(site_key)
        if not path.exists():
            return {"days": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def save_gsc_site(self, site_key: str, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        self._gsc_path(site_key).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_gsc_day(self, site_key: str, date_value: dt.date) -> dict[str, Any] | None:
        return self.load_gsc_site(site_key).get("days", {}).get(date_value.isoformat())

    def merge_gsc_days(self, site_key: str, days: dict[str, dict[str, Any]]) -> None:
        if not self.enabled:
            return
        payload = self.load_gsc_site(site_key)
        payload.setdefault("days", {}).update(days)
        payload["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
        self.save_gsc_site(site_key, payload)

    def needs_gsc_fetch(
        self,
        site_key: str,
        date_value: dt.date,
        config: Config,
        *,
        force: bool,
    ) -> bool:
        if force or not self.enabled:
            return True
        cached = self.get_gsc_day(site_key, date_value)
        if cached is None:
            return True
        if is_provisional_gsc_zero(cached, date_value, config):
            return True
        fetched_at = cached.get("fetched_at", "")
        if not fetched_at:
            return True
        try:
            ts = dt.datetime.fromisoformat(fetched_at)
        except ValueError:
            return True
        age_hours = (dt.datetime.now() - ts).total_seconds() / 3600
        return age_hours >= config.cache_ttl_hours


def fetch_gsc_daily_summaries(
    gsc: "GSCClient",
    site: SiteConfig,
    config: Config,
    cache: SyncCache,
    report: SyncReport,
    *,
    anchor: dt.date | None = None,
    force_refresh: bool = False,
) -> dict[dt.date, dict[str, Any]]:
    dates = get_dashboard_dates(config, anchor=anchor)
    start, end = dates[0], dates[-1]
    needs_fetch = any(
        cache.needs_gsc_fetch(site.key, day, config, force=force_refresh) for day in dates
    )

    if needs_fetch:
        batch = gsc.query_daily_summaries(start, end)
        fetched_at = dt.datetime.now().isoformat(timespec="seconds")
        to_save: dict[str, dict[str, Any]] = {}
        for day in dates:
            summary = batch.get(day, empty_gsc_summary())
            to_save[day.isoformat()] = {**summary, "fetched_at": fetched_at}
        cache.merge_gsc_days(site.key, to_save)
        report.log_api("cache", "gsc refresh", detail=f"site={site.key} range={start}..{end} days={len(dates)}")
    else:
        report.log_api("cache", "gsc hit", detail=f"site={site.key} range={start}..{end}")

    result: dict[dt.date, dict[str, Any]] = {}
    for day in dates:
        cached = cache.get_gsc_day(site.key, day)
        result[day] = cached if cached else empty_gsc_summary()
    return result


class MingdaoClient:
    DATE_TYPE = 15
    SELECT_TYPE = 11
    NUMBER_TYPE = 6

    def __init__(self, config: Config, report: SyncReport | None = None):
        self.config = config
        self.report = report
        self.request_timeout = max(30, config.mingdao_request_timeout)
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        mingdao_proxy = get_mingdao_proxies()
        if mingdao_proxy:
            self.session.proxies.update(mingdao_proxy)
            self.session.trust_env = False

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.config.mingdao_api_base}/{endpoint.lstrip('/')}"
        body = {
            "appKey": self.config.mingdao_app_key,
            "sign": self.config.mingdao_sign,
            **payload,
        }
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                resp = self.session.post(url, json=body, timeout=self.request_timeout)
                resp.raise_for_status()
                data = resp.json()
                ok = data.get("success") is True or data.get("error_code") == 1
                if not ok:
                    if self.report:
                        preview = json.dumps(
                            {k: v for k, v in payload.items() if k not in {"sign"}},
                            ensure_ascii=False,
                        )[:500]
                        self.report.log_api("Mingdao", endpoint, ok=False, detail=f"{data} payload={preview}")
                    raise RuntimeError(f"Mingdao API error ({endpoint}): {data}")
                return data
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_error = exc
                if attempt < 3:
                    logging.warning(
                        "Mingdao %s timeout/connection (attempt %s/3), retry in 5s: %s",
                        endpoint,
                        attempt,
                        exc,
                    )
                    time.sleep(5)
                    continue
                raise
        raise RuntimeError(f"Mingdao API failed ({endpoint}): {last_error}") from last_error

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
        page_index: int = 1,
        log_api: bool = True,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "worksheetId": worksheet_id,
            "pageSize": page_size,
            "pageIndex": page_index,
            "listType": 0,
        }
        if filters:
            payload["filters"] = filters

        data = self._post("getFilterRows", payload)
        rows = data.get("data", {}).get("rows", [])
        if self.report and log_api:
            self.report.log_api(
                "Mingdao",
                "getFilterRows",
                detail=f"worksheet={worksheet_id} page={page_index} rows={len(rows)}",
            )
        return rows

    def list_all_rows(
        self,
        worksheet_id: str,
        *,
        filters: list[dict[str, Any]] | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        all_rows: list[dict[str, Any]] = []
        page_index = 1
        while True:
            rows = self.list_rows(
                worksheet_id,
                filters=filters,
                page_size=page_size,
                page_index=page_index,
                log_api=page_index == 1,
            )
            if not rows:
                break
            all_rows.extend(rows)
            if len(rows) < page_size:
                break
            page_index += 1
        return all_rows

    def find_dashboard_row(self, data_date: dt.date, site_option_key: str) -> dict[str, Any] | None:
        fields = self.config.dashboard_fields
        filters = [
            {
                "controlId": fields.date,
                "dataType": self.DATE_TYPE,
                "spliceType": 1,
                "filterType": 2,
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
        if not controls:
            raise RuntimeError("Mingdao addRow: controls 为空，请检查字段映射与数据")

        # addRows 批量接口要求 rows=[[{controlId,value},...]]；addRow 单条用 controls
        data = self._post(
            "addRow",
            {
                "worksheetId": worksheet_id,
                "controls": controls,
                "triggerWorkflow": False,
            },
        )
        row_id = data.get("data")
        if self.report:
            self.report.log_api(
                "Mingdao",
                "addRow",
                detail=f"rowId={row_id} fields={len(controls)}",
            )
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

    def delete_row(
        self,
        worksheet_id: str,
        row_id: str,
        *,
        thorough_delete: bool = False,
        trigger_workflow: bool = False,
    ) -> None:
        self._post(
            "deleteRow",
            {
                "worksheetId": worksheet_id,
                "rowId": row_id,
                "triggerWorkflow": trigger_workflow,
                "ThoroughDelete": thorough_delete,
            },
        )
        if self.report:
            self.report.log_api(
                "Mingdao",
                "deleteRow",
                detail=f"rowId={row_id} thorough={thorough_delete}",
            )

    def upsert_dashboard(self, data_date: dt.date, logical_fields: dict[str, Any], site_key: str) -> None:
        site_option = self.config.site_option_key(site_key)
        controls = build_dashboard_controls(self.config, logical_fields, site_key)

        if self.report:
            self.report.log_api(
                "Mingdao",
                "build controls",
                detail=f"count={len(controls)} site={site_key} date={data_date.isoformat()}",
            )
            if not controls:
                self.report.log_skip(DASHBOARD_LABEL, "controls 为空，未调用写入 API")

        if not controls:
            raise RuntimeError("明道云写入失败：未生成任何字段数据（controls 为空）")

        existing = self.find_dashboard_row(data_date, site_option)
        key = f"{site_key}@{data_date.isoformat()}"
        if existing:
            row_id = existing["rowid"]
            self.edit_row(self.config.mingdao_worksheet_dashboard, row_id, controls)
            if self.report:
                self.report.log_write(DASHBOARD_LABEL, "update", key, logical_fields)
        else:
            self.add_row(self.config.mingdao_worksheet_dashboard, controls)
            if self.report:
                self.report.log_write(DASHBOARD_LABEL, "create", key, logical_fields)


def build_dashboard_controls(config: Config, logical_fields: dict[str, Any], site_key: str) -> list[dict[str, str]]:
    fields = config.dashboard_fields
    mapping = {
        "日期": fields.date,
        "独立站": fields.site,
        "自然点击": fields.clicks,
        "展示量": fields.impressions,
        "平均CTR": fields.ctr,
        "全站加权平均排名": fields.position,
        "GSC Top1-3 搜索词数": fields.top1_3,
        "GSC Top4-10 搜索词数": fields.top4_10,
        "GSC Top11-20 搜索词数": fields.top11_20,
        "GSC Top21-100 搜索词数": fields.top21_100,
        "Backlinks变化": fields.backlinks,
        "已监控URL收录数": fields.indexed,
        "已监控URL异常数": fields.issues,
        "异常预警": fields.alert,
        "周环比流量": fields.traffic_wow,
    }
    if fields.weekly_avg_position:
        mapping["周平均排名"] = fields.weekly_avg_position
    if fields.site_dr:
        mapping["本站DR"] = fields.site_dr

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
            controls.append({"controlId": control_id, "value": config.site_option_key(site_key)})
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


def format_mingdao_decimal(value: Any, *, places: int = 2) -> str:
    """明道云数值列固定小数位（如 CPC、价值分）。"""
    return f"{float(value):.{places}f}"


def is_transient_network_error(exc: BaseException) -> bool:
    """OAuth / GSC / 明道云 常见的可重试网络错误（含读超时、443 SSL EOF）。"""
    if isinstance(
        exc,
        (
            requests.exceptions.SSLError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ),
    ):
        return True
    if google_auth_exceptions and isinstance(exc, google_auth_exceptions.TransportError):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        response = exc.response
        if response is not None and response.status_code in {429, 500, 502, 503, 504}:
            return True
    cause = exc.__cause__
    if cause is not None and cause is not exc:
        return is_transient_network_error(cause)
    return False


def load_service_account_credentials(config: Config) -> Any:
    if service_account is None:
        raise RuntimeError("Google service account dependency is not installed.")
    credentials_path = ROOT / config.google_credentials_file
    if not credentials_path.exists():
        raise RuntimeError(f"Google credentials file not found: {credentials_path}")
    return service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=GSCClient.SCOPES,
    )


def load_oauth_credentials(config: Config) -> Any:
    if Credentials is None or Request is None or InstalledAppFlow is None:
        raise RuntimeError("Google OAuth dependencies are not installed.")

    token_path = ROOT / config.google_token_file
    client_secret_path = ROOT / config.google_client_secret_file
    credentials = None

    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(token_path, GSCClient.SCOPES)

    if credentials and credentials.expired and credentials.refresh_token:
        last_error: Exception | None = None
        for attempt in range(1, GOOGLE_CREDENTIAL_MAX_ATTEMPTS + 1):
            try:
                refresh_session = requests.Session()
                configure_google_session(refresh_session)
                credentials.refresh(Request(session=refresh_session))
                token_path.write_text(credentials.to_json(), encoding="utf-8")
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                if not is_transient_network_error(exc) or attempt >= GOOGLE_CREDENTIAL_MAX_ATTEMPTS:
                    raise
                delay = GOOGLE_CREDENTIAL_RETRY_SECONDS * attempt
                logging.warning(
                    "Google OAuth token refresh failed (attempt %s/%s), retry in %ss: %s",
                    attempt,
                    GOOGLE_CREDENTIAL_MAX_ATTEMPTS,
                    delay,
                    exc,
                )
                time.sleep(delay)
        if last_error:
            raise last_error

    if not credentials or not credentials.valid:
        if not client_secret_path.exists():
            raise RuntimeError(f"Google OAuth client secret file not found: {client_secret_path}")
        if not get_google_proxies():
            logging.info(
                "Google OAuth 使用系统代理；请确认 Clash 已开启「系统代理」，全局或智能模式均可。"
            )
        logging.info("Opening browser for Google OAuth. Complete login to create token.json.")
        flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, GSCClient.SCOPES)
        credentials = flow.run_local_server(port=0)
        token_path.write_text(credentials.to_json(), encoding="utf-8")

    return credentials


def load_google_credentials_with_retry(config: Config) -> Any:
    """整次 sync 只加载/刷新一次 Google 凭据，避免每站重复打 oauth2.googleapis.com。"""
    last_error: Exception | None = None
    for attempt in range(1, GOOGLE_CREDENTIAL_MAX_ATTEMPTS + 1):
        try:
            if config.google_auth_mode == "service_account":
                return load_service_account_credentials(config)
            if config.google_auth_mode == "oauth":
                return load_oauth_credentials(config)
            raise RuntimeError(f"Unsupported GOOGLE_AUTH_MODE: {config.google_auth_mode}")
        except Exception as exc:
            last_error = exc
            if not is_transient_network_error(exc) or attempt >= GOOGLE_CREDENTIAL_MAX_ATTEMPTS:
                raise
            delay = GOOGLE_CREDENTIAL_RETRY_SECONDS * attempt
            logging.warning(
                "Google credentials load failed (attempt %s/%s), retry in %ss: %s",
                attempt,
                GOOGLE_CREDENTIAL_MAX_ATTEMPTS,
                delay,
                exc,
            )
            time.sleep(delay)
    if last_error:
        raise last_error
    raise RuntimeError("Google credentials load failed")


class GSCClient:
    SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
    API_BASE = "https://searchconsole.googleapis.com/webmasters/v3"
    REQUEST_TIMEOUT = (15, 45)
    MAX_RETRIES = 3

    def __init__(
        self,
        config: Config,
        report: SyncReport | None = None,
        *,
        site_url: str,
        credentials: Any | None = None,
    ):
        if AuthorizedSession is None or Request is None:
            raise RuntimeError("Google API dependencies are not installed.")

        self.config = config
        self.report = report
        self.site_url = site_url
        if credentials is None:
            credentials = load_google_credentials_with_retry(config)
        self.session = AuthorizedSession(credentials)
        configure_google_session(self.session)

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
                    f"site={self.site_url} date={date_value.isoformat()} clicks={summary['clicks']} "
                    f"impressions={summary['impressions']} ctr={summary['ctr']} "
                    f"position={summary['position']}"
                ),
            )
        return summary

    def query_daily_summaries(
        self,
        start_date: dt.date,
        end_date: dt.date,
    ) -> dict[dt.date, dict[str, Any]]:
        body = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "dimensions": ["date"],
            "rowLimit": 25000,
        }
        result = self._query_search_analytics(body)
        by_date: dict[dt.date, dict[str, Any]] = {}
        for row in result.get("rows", []):
            keys = row.get("keys", [])
            if not keys:
                continue
            day = dt.date.fromisoformat(str(keys[0]))
            by_date[day] = {
                "clicks": int(row.get("clicks", 0)),
                "impressions": int(row.get("impressions", 0)),
                "ctr": float(row.get("ctr", 0)),
                "position": float(row.get("position", 0)),
            }
        if self.report:
            self.report.log_api(
                "GSC",
                "searchAnalytics/query (daily batch)",
                detail=(
                    f"site={self.site_url} range={start_date.isoformat()}..{end_date.isoformat()} "
                    f"days={len(by_date)}"
                ),
            )
        return by_date

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
                detail=f"site={self.site_url} range={start_date.isoformat()}..{end_date.isoformat()} clicks={clicks}",
            )
        return clicks

    def query_page_clicks(self, page_url: str, date_value: dt.date) -> int:
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
        result = self._query_search_analytics(body)
        rows = result.get("rows", [])
        clicks = int(rows[0].get("clicks", 0)) if rows else 0
        if self.report:
            self.report.log_api(
                "GSC",
                "searchAnalytics/query (page clicks)",
                detail=f"site={self.site_url} page={page_url} date={date_value.isoformat()} clicks={clicks}",
            )
        return clicks

    def query_dimension_rows(
        self,
        date_value: dt.date,
        dimensions: list[str],
        *,
        row_limit: int = 1000,
        label: str = "searchAnalytics/query",
        country_filter: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """按 dimensions 拉 Top 行（默认按点击降序），支持分页至 row_limit。"""
        rows_out: list[dict[str, Any]] = []
        start_row = 0
        batch_size = min(25000, max(1, row_limit))
        allowed_countries: set[str] | None = None
        if country_filter:
            allowed_countries = {code.lower() for code in country_filter}

        while len(rows_out) < row_limit:
            body: dict[str, Any] = {
                "startDate": date_value.isoformat(),
                "endDate": date_value.isoformat(),
                "dimensions": dimensions,
                "rowLimit": min(batch_size, row_limit - len(rows_out)),
                "startRow": start_row,
            }
            if country_filter and len(country_filter) == 1:
                body["dimensionFilterGroups"] = [
                    {
                        "filters": [
                            {
                                "dimension": "country",
                                "expression": country_filter[0].lower(),
                            }
                        ]
                    }
                ]
            result = self._query_search_analytics(body)
            batch = result.get("rows", [])
            if not batch:
                break
            for row in batch:
                keys = row.get("keys", [])
                if len(keys) != len(dimensions):
                    continue
                if allowed_countries and "country" in dimensions:
                    country_idx = dimensions.index("country")
                    country_code = str(keys[country_idx]).strip().lower()
                    if country_code not in allowed_countries:
                        continue
                item = {
                    "keys": keys,
                    "clicks": int(row.get("clicks", 0)),
                    "impressions": int(row.get("impressions", 0)),
                    "ctr": float(row.get("ctr", 0)),
                    "position": float(row.get("position", 0)),
                }
                rows_out.append(item)
                if len(rows_out) >= row_limit:
                    break
            if len(batch) < body["rowLimit"]:
                break
            start_row += len(batch)

        if self.report:
            country_note = f" countries={','.join(country_filter)}" if country_filter else " countries=all"
            self.report.log_api(
                "GSC",
                label,
                detail=(
                    f"site={self.site_url} date={date_value.isoformat()} "
                    f"dimensions={dimensions} rows={len(rows_out)} limit={row_limit}{country_note}"
                ),
            )
        return rows_out

    def inspect_page_url(self, page_url: str) -> str:
        url = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
        body = {"inspectionUrl": page_url, "siteUrl": self.site_url}
        last_error: Exception | None = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = self.session.post(url, json=body, timeout=self.REQUEST_TIMEOUT)
                if response.status_code == 403:
                    self._raise_gsc_permission_error(response)
                response.raise_for_status()
                payload = response.json()
                status = map_gsc_index_status(payload)
                if self.report:
                    self.report.log_api(
                        "GSC",
                        "urlInspection/index:inspect",
                        detail=f"site={self.site_url} page={page_url} status={status}",
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
            self.report.log_warning(
                f"GSC URL Inspection 失败，按未收录处理: site={self.site_url} page={page_url} err={last_error}"
            )
        return "未收录"

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
            "无法连接 Google Search Console API。"
            "请确认：1) Clash 已开全局或智能模式，并开启「系统代理」；"
            "2) .env 不要设置 HTTPS_PROXY（改用系统代理，与上周飞书同步相同）；"
            "3) GSC_SITE_URL 与 Search Console 资源一致。"
            f" 原始错误: {last_error}"
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
            f"请确认 config/sites.json 中该站的 gsc_site_url 与 Search Console 资源完全一致"
            f"（URL 前缀或 sc-domain:xxx.com）。详情: {message}"
        ) from None


class AhrefsClient:
    BASE_URL = "https://api.ahrefs.com/v3"

    def __init__(
        self,
        config: Config,
        report: SyncReport | None = None,
        *,
        target_domain: str,
        site_key: str = "",
        report_date: dt.date | None = None,
    ):
        self.config = config
        self.report = report
        self.target_domain = normalize_ahrefs_domain(target_domain)
        self.site_key = site_key
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.config.ahrefs_api_token}",
                "Accept": "application/json",
            }
        )
        self.report_date = report_date or get_sync_anchor_date(config)
        self.compare_date = self.report_date - dt.timedelta(days=7)
        self._rankings_by_date: dict[str, dict[str, dict[str, Any]]] = {}
        self._domain_rating_by_date: dict[str, float | None] = {}
        self._top_pages_index: dict[str, dict[str, Any]] | None = None
        self._top_pages_index_date: dt.date | None = None
        self._crawled_pages_index: dict[str, dict[str, Any]] | None = None
        self._landing_keyword_stats: dict[str, dict[str, Any]] | None = None
        self._landing_keyword_stats_date: dt.date | None = None
        self._url_metrics_cache: dict[str, dict[str, Any]] = {}
        self._keyword_overview_cache: dict[tuple[str, str], dict[str, Any]] = {}

    def fetch_keywords_overview(
        self,
        ahrefs_country: str,
        keywords: list[str],
    ) -> dict[str, dict[str, Any]]:
        """keywords-explorer/overview；键为 keyword casefold。"""
        country = ahrefs_country.strip().lower()
        pending = [kw for kw in keywords if kw and kw.strip()]
        results: dict[str, dict[str, Any]] = {}
        if not pending:
            return results

        uncached: list[str] = []
        for keyword in pending:
            cache_key = (country, keyword.casefold())
            cached = self._keyword_overview_cache.get(cache_key)
            if cached is not None:
                results[keyword.casefold()] = cached
            else:
                uncached.append(keyword)

        for offset in range(0, len(uncached), GSC_TOP_QUERIES_OVERVIEW_BATCH_SIZE):
            batch = uncached[offset : offset + GSC_TOP_QUERIES_OVERVIEW_BATCH_SIZE]
            try:
                payload = self._request(
                    "keywords-explorer/overview",
                    {
                        "country": country,
                        "keywords": ",".join(batch),
                        "select": "keyword,volume,difficulty,cpc",
                    },
                )
            except (requests.HTTPError, RuntimeError) as exc:
                if self.report:
                    self.report.log_warning(
                        f"{self.site_key} overview 批次失败 country={country} "
                        f"batch={len(batch)} err={exc}"
                    )
                continue

            rows = payload.get("keywords")
            if not isinstance(rows, list):
                rows = []
            if self.report:
                self.report.log_api(
                    "Ahrefs",
                    "keywords-explorer/overview (gsc top enrich)",
                    detail=(
                        f"site={self.site_key} country={country} "
                        f"requested={len(batch)} returned={len(rows)}"
                    ),
                )

            returned_keys: set[str] = set()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                keyword = str(row.get("keyword") or "").strip()
                if not keyword:
                    continue
                key = keyword.casefold()
                returned_keys.add(key)
                metrics = {
                    "volume": row.get("volume"),
                    "kd": row.get("difficulty"),
                    "cpc": row.get("cpc"),
                }
                self._keyword_overview_cache[(country, key)] = metrics
                results[key] = metrics

            for keyword in batch:
                key = keyword.casefold()
                if key in returned_keys:
                    continue
                empty: dict[str, Any] = {}
                self._keyword_overview_cache[(country, key)] = empty
                results[key] = empty

            if offset + GSC_TOP_QUERIES_OVERVIEW_BATCH_SIZE < len(uncached):
                time.sleep(0.25)

        return results

    def load_organic_rankings(self) -> dict[str, dict[str, Any]]:
        """锚点日有机词（关键词同步等沿用）。"""
        return self.load_organic_rankings_for_date(self.report_date)

    def load_organic_rankings_for_date(self, report_date: dt.date) -> dict[str, dict[str, Any]]:
        cache_key = report_date.isoformat()
        cached = self._rankings_by_date.get(cache_key)
        if cached is not None:
            return cached

        compare_date = report_date - dt.timedelta(days=7)
        if self._is_aggregate_all():
            rankings, countries = self._load_organic_rankings_all_countries(
                report_date, compare_date
            )
            detail = (
                f"site={self.site_key} target={self.target_domain} date={report_date.isoformat()} "
                f"compared={compare_date.isoformat()} countries={len(countries)} "
                f"count={len(rankings)} mode=aggregate"
            )
        else:
            rankings = self._load_organic_rankings_for_country(
                self.config.ahrefs_target_country,
                report_date=report_date,
                compare_date=compare_date,
            )
            detail = (
                f"site={self.site_key} target={self.target_domain} date={report_date.isoformat()} "
                f"compared={compare_date.isoformat()} country={self.config.ahrefs_target_country} "
                f"count={len(rankings)}"
            )

        self._rankings_by_date[cache_key] = rankings
        logging.info(
            "Loaded %s organic keywords from Ahrefs for %s",
            len(rankings),
            report_date.isoformat(),
        )
        if self.report:
            self.report.log_api("Ahrefs", "site-explorer/organic-keywords", detail=detail)
        return rankings

    def _is_aggregate_all(self) -> bool:
        return self.config.ahrefs_target_country == "all"

    def _load_organic_rankings_for_country(
        self,
        country: str,
        *,
        report_date: dt.date,
        compare_date: dt.date,
    ) -> dict[str, dict[str, Any]]:
        payload = self._request(
            "site-explorer/organic-keywords",
            {
                "target": self.target_domain,
                "country": country.lower(),
                "date": report_date.isoformat(),
                "date_compared": compare_date.isoformat(),
                "select": (
                    "keyword,volume,keyword_difficulty,cpc,"
                    "is_transactional,is_commercial,is_navigational,is_branded,is_local,is_informational,"
                    "best_position,best_position_prev,best_position_diff,best_position_url"
                ),
                "limit": 1000,
            },
        )
        rankings: dict[str, dict[str, Any]] = {}
        for item in payload.get("keywords", []):
            keyword = item.get("keyword")
            if keyword:
                rankings[str(keyword).casefold()] = item
        return rankings

    def _resolve_aggregate_countries(self, report_date: dt.date) -> list[str]:
        if self.config.ahrefs_aggregate_countries:
            return list(self.config.ahrefs_aggregate_countries)

        payload = self._request(
            "site-explorer/metrics-by-country",
            {
                "target": self.target_domain,
                "date": report_date.isoformat(),
                "select": "country,org_keywords,org_traffic",
            },
        )
        rows = [row for row in payload.get("metrics", []) if (row.get("org_keywords") or 0) > 0]
        rows.sort(key=lambda row: (row.get("org_traffic") or 0), reverse=True)
        max_countries = self.config.ahrefs_aggregate_max_countries
        if max_countries > 0:
            rows = rows[:max_countries]
        countries = [str(row["country"]).lower() for row in rows]
        if not countries:
            logging.warning(
                "Ahrefs aggregate: no countries with organic keywords for %s; fallback to us",
                self.target_domain,
            )
            return ["us"]
        logging.info(
            "Ahrefs aggregate countries for %s: %s",
            self.target_domain,
            ",".join(countries),
        )
        return countries

    def _load_organic_rankings_all_countries(
        self,
        report_date: dt.date,
        compare_date: dt.date,
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        countries = self._resolve_aggregate_countries(report_date)
        merged: dict[str, dict[str, Any]] = {}
        for country in countries:
            country_rankings = self._load_organic_rankings_for_country(
                country,
                report_date=report_date,
                compare_date=compare_date,
            )
            for key, item in country_rankings.items():
                existing = merged.get(key)
                if existing is None:
                    merged[key] = item
                else:
                    merged[key] = merge_organic_ranking(existing, item)
        return merged, countries

    def get_dashboard_summary(self) -> dict[str, Any]:
        """锚点日汇总：Backlinks 净值（四档词数、本站 DR 改由看板按日拉取）。"""
        new_rd = self._get_refdomains_delta()
        summary: dict[str, Any] = {
            "new_referring_domains": new_rd,
        }
        if self.report:
            self.report.log_api(
                "Ahrefs",
                "dashboard summary",
                detail=(
                    f"site={self.site_key} date={self.report_date.isoformat()} "
                    f"backlinks={new_rd}"
                ),
            )
        return summary

    def get_domain_rating_for_date(self, report_date: dt.date) -> float | None:
        """指定日的 Ahrefs 全站 Domain Rating（看板 7 日窗口每日各写一行）。"""
        cache_key = report_date.isoformat()
        if cache_key in self._domain_rating_by_date:
            return self._domain_rating_by_date[cache_key]
        dr = self._fetch_domain_rating(report_date)
        self._domain_rating_by_date[cache_key] = dr
        return dr

    def _fetch_domain_rating(self, report_date: dt.date) -> float | None:
        payload = self._request(
            "site-explorer/domain-rating",
            {
                "target": self.target_domain,
                "date": report_date.isoformat(),
            },
        )
        dr_block = payload.get("domain_rating")
        if isinstance(dr_block, dict):
            raw = dr_block.get("domain_rating")
        else:
            raw = dr_block
        if raw is None:
            dr = None
        else:
            dr = round(float(raw), 1)
        if self.report:
            self.report.log_api(
                "Ahrefs",
                "site-explorer/domain-rating",
                detail=(
                    f"site={self.site_key} target={self.target_domain} "
                    f"date={report_date.isoformat()} dr={dr}"
                ),
            )
        return dr

    def _get_refdomains_delta(self) -> int | None:
        start_date = self.report_date - dt.timedelta(days=7)
        payload = self._request(
            "site-explorer/refdomains-history",
            {
                "target": self.target_domain,
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
                detail=f"site={self.site_key} range={start_date.isoformat()}..{self.report_date.isoformat()} delta={delta}",
            )
        return delta

    def prepare_page_sync_caches(self, report_date: dt.date) -> None:
        """页面管理表：预拉 Ahrefs 索引（top-pages 用于 URL 发现 + 字段补全）。"""
        self._ensure_top_pages_index(report_date)
        self._ensure_crawled_pages_index()
        self._ensure_landing_keyword_stats(report_date)

    def _ensure_top_pages_index(self, report_date: dt.date) -> dict[str, dict[str, Any]]:
        if self._top_pages_index is not None and self._top_pages_index_date == report_date:
            return self._top_pages_index
        params: dict[str, Any] = {
            "target": self.target_domain,
            "date": report_date.isoformat(),
            "select": (
                "url,page_type,ur,sum_traffic,value,keywords,"
                "top_keyword,top_keyword_volume"
            ),
            "limit": self.config.pages_ahrefs_import_limit,
        }
        if not self._is_aggregate_all():
            params["country"] = self.config.ahrefs_target_country
        try:
            payload = self._request("site-explorer/top-pages", params)
        except requests.HTTPError as exc:
            # 无快照 / 套餐限制等：降级为空索引，其余 Ahrefs 源仍可补数
            if self.report:
                detail = str(exc)
                if exc.response is not None:
                    detail = f"{exc.response.status_code} {exc.response.text[:300]}"
                self.report.log_warning(
                    f"{self.site_key} top-pages 索引拉取失败，跳过: {detail}"
                )
            self._top_pages_index = {}
            self._top_pages_index_date = report_date
            return {}
        index: dict[str, dict[str, Any]] = {}
        for item in payload.get("pages", []):
            raw_url = str(item.get("url") or item.get("raw_url") or "").strip()
            if not raw_url:
                continue
            index[normalize_page_url(raw_url)] = item
        self._top_pages_index = index
        self._top_pages_index_date = report_date
        if self.report:
            self.report.log_api(
                "Ahrefs",
                "site-explorer/top-pages (page import/enrich)",
                detail=f"site={self.site_key} date={report_date.isoformat()} urls={len(index)}",
            )
        return index

    def _ensure_crawled_pages_index(self) -> dict[str, dict[str, Any]]:
        if self._crawled_pages_index is not None:
            return self._crawled_pages_index
        try:
            payload = self._request(
                "site-explorer/crawled-pages",
                {
                    "target": self.target_domain,
                    "select": "url,url_rating,first_seen,title,http_code",
                    "limit": 1000,
                },
            )
        except requests.HTTPError as exc:
            if self.report:
                detail = str(exc)
                if exc.response is not None:
                    detail = f"{exc.response.status_code} {exc.response.text[:300]}"
                self.report.log_warning(
                    f"{self.site_key} crawled-pages 索引拉取失败，跳过: {detail}"
                )
            self._crawled_pages_index = {}
            return {}
        index: dict[str, dict[str, Any]] = {}
        for item in payload.get("pages", []):
            raw_url = str(item.get("url") or "").strip()
            if not raw_url:
                continue
            index[normalize_page_url(raw_url)] = item
        self._crawled_pages_index = index
        if self.report:
            self.report.log_api(
                "Ahrefs",
                "site-explorer/crawled-pages (page enrich)",
                detail=f"site={self.site_key} urls={len(index)}",
            )
        return index

    def _ensure_landing_keyword_stats(self, report_date: dt.date) -> dict[str, dict[str, Any]]:
        if (
            self._landing_keyword_stats is not None
            and self._landing_keyword_stats_date == report_date
        ):
            return self._landing_keyword_stats
        rankings = self.load_organic_rankings_for_date(report_date)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in rankings.values():
            landing = str(item.get("best_position_url") or "").strip()
            if not landing:
                continue
            grouped.setdefault(normalize_page_url(landing), []).append(item)
        stats: dict[str, dict[str, Any]] = {}
        for url_key, items in grouped.items():
            best = max(items, key=lambda row: int(row.get("volume") or 0))
            stats[url_key] = {
                "keyword_count": len(items),
                "primary_keyword": best.get("keyword"),
                "primary_keyword_volume": best.get("volume"),
            }
        self._landing_keyword_stats = stats
        self._landing_keyword_stats_date = report_date
        if self.report:
            self.report.log_api(
                "Ahrefs",
                "organic-keywords landing stats",
                detail=f"site={self.site_key} date={report_date.isoformat()} urls={len(stats)}",
            )
        return stats

    def _fetch_url_metrics(self, page_url: str, report_date: dt.date) -> dict[str, Any]:
        cache_key = f"{normalize_page_url(page_url)}@{report_date.isoformat()}"
        cached = self._url_metrics_cache.get(cache_key)
        if cached is not None:
            return cached
        params: dict[str, Any] = {
            "target": page_url,
            "date": report_date.isoformat(),
        }
        if not self._is_aggregate_all():
            params["country"] = self.config.ahrefs_target_country
        try:
            payload = self._request("site-explorer/metrics", params)
        except (requests.HTTPError, RuntimeError) as exc:
            metrics: dict[str, Any] = {}
            self._url_metrics_cache[cache_key] = metrics
            if self.report:
                self.report.log_warning(
                    f"{self.site_key} url metrics 失败，跳过: url={page_url} err={exc}"
                )
            return metrics
        metrics = payload.get("metrics")
        if not isinstance(metrics, dict):
            metrics = payload if isinstance(payload, dict) else {}
        self._url_metrics_cache[cache_key] = metrics
        if self.report:
            self.report.log_api(
                "Ahrefs",
                "site-explorer/metrics (page)",
                detail=(
                    f"site={self.site_key} url={page_url} "
                    f"org_traffic={metrics.get('org_traffic')} "
                    f"org_keywords={metrics.get('org_keywords')}"
                ),
            )
        return metrics

    def get_page_ahrefs_metrics(self, page_url: str, report_date: dt.date) -> dict[str, Any]:
        self.prepare_page_sync_caches(report_date)
        out: dict[str, Any] = {}
        top_item = resolve_page_index_entry(self._top_pages_index or {}, page_url)
        if top_item:
            if top_item.get("ur") is not None:
                out["ur"] = round(float(top_item["ur"]), 1)
            if top_item.get("keywords") is not None:
                out["keyword_count"] = int(top_item["keywords"])
            if top_item.get("top_keyword"):
                out["primary_keyword"] = str(top_item["top_keyword"])
            if top_item.get("top_keyword_volume") is not None:
                out["primary_keyword_volume"] = int(top_item["top_keyword_volume"])
            if top_item.get("sum_traffic") is not None:
                out["ahrefs_traffic"] = int(top_item["sum_traffic"])
            if top_item.get("value") is not None:
                out["ahrefs_value"] = normalize_ahrefs_usd(top_item["value"])

        crawled = resolve_page_index_entry(self._crawled_pages_index or {}, page_url)
        if crawled:
            if out.get("ur") is None and crawled.get("url_rating") is not None:
                out["ur"] = round(float(crawled["url_rating"]), 1)
            first_seen = parse_ahrefs_date(crawled.get("first_seen"))
            if first_seen:
                out["ahrefs_first_seen"] = first_seen

        landing = resolve_page_index_entry(self._landing_keyword_stats or {}, page_url)
        if landing:
            if not out.get("primary_keyword") and landing.get("primary_keyword"):
                out["primary_keyword"] = str(landing["primary_keyword"])
            if out.get("primary_keyword_volume") is None and landing.get("primary_keyword_volume") is not None:
                out["primary_keyword_volume"] = int(landing["primary_keyword_volume"])
            if out.get("keyword_count") is None and landing.get("keyword_count") is not None:
                out["keyword_count"] = int(landing["keyword_count"])

        need_metrics = (
            out.get("ahrefs_traffic") is None
            or out.get("keyword_count") is None
            or out.get("ahrefs_value") is None
        )
        if need_metrics:
            metrics = self._fetch_url_metrics(page_url, report_date)
            if out.get("ahrefs_traffic") is None and metrics.get("org_traffic") is not None:
                out["ahrefs_traffic"] = int(metrics["org_traffic"])
            if out.get("keyword_count") is None and metrics.get("org_keywords") is not None:
                out["keyword_count"] = int(metrics["org_keywords"])
            if out.get("ahrefs_value") is None and metrics.get("org_cost") is not None:
                out["ahrefs_value"] = normalize_ahrefs_usd(metrics["org_cost"])

        site_dr = self.get_domain_rating_for_date(report_date)
        if site_dr is not None:
            out["global_dr"] = site_dr

        return out

    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        resp = self.session.get(url, params=params, timeout=60)
        if not resp.ok:
            body = resp.text[:500]
            if self.report:
                self.report.log_api("Ahrefs", path, ok=False, detail=f"{resp.status_code} {body}")
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


def position_in_rank_bucket(position: Any, low: int, high: int) -> bool:
    if position is None:
        return False
    try:
        rank = int(position)
    except (TypeError, ValueError):
        return False
    return low <= rank <= high


def count_rank_buckets(
    rankings: dict[str, dict[str, Any]],
    *,
    position_field: str = "best_position",
) -> dict[str, int]:
    counts = {key: 0 for _label, key, _lo, _hi in RANK_BUCKET_SPECS}
    for ranking in rankings.values():
        position = ranking.get(position_field)
        for _label, key, low, high in RANK_BUCKET_SPECS:
            if position_in_rank_bucket(position, low, high):
                counts[key] += 1
    return counts


def count_gsc_query_rank_buckets(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {key: 0 for _label, key, _lo, _hi in RANK_BUCKET_SPECS}
    for item in rows:
        position = item.get("position")
        for _label, key, low, high in RANK_BUCKET_SPECS:
            if position_in_rank_bucket(position, low, high):
                counts[key] += 1
                break
    return counts


def fetch_gsc_query_rows_for_date(
    gsc: GSCClient,
    config: Config,
    data_date: dt.date,
    *,
    report: SyncReport | None = None,
    site_key: str = "",
) -> list[dict[str, Any]]:
    """GSC query 维、全国家合计（不按 country 拆分）。"""
    return gsc.query_dimension_rows(
        data_date,
        ["query"],
        row_limit=config.dashboard_gsc_query_limit,
        label="searchAnalytics/query (dashboard buckets)",
    )


def load_gsc_query_rows_by_dates(
    gsc: GSCClient,
    config: Config,
    dates: Iterable[dt.date],
    *,
    report: SyncReport,
    site_key: str,
    store: dict[dt.date, list[dict[str, Any]]] | None = None,
) -> dict[dt.date, list[dict[str, Any]]]:
    bucket = store if store is not None else {}
    for data_date in dates:
        if data_date in bucket:
            continue
        rows = fetch_gsc_query_rows_for_date(
            gsc,
            config,
            data_date,
            report=report,
            site_key=site_key,
        )
        bucket[data_date] = rows
        report.log_api(
            "sync",
            f"gsc dashboard buckets ({site_key})",
            detail=(
                f"date={data_date.isoformat()} queries={len(rows)} "
                f"limit={config.dashboard_gsc_query_limit}"
            ),
        )
    return bucket


def gsc_rank_bucket_fields_for_date(
    query_by_date: dict[dt.date, list[dict[str, Any]]],
    data_date: dt.date,
) -> dict[str, Any]:
    counts = count_gsc_query_rank_buckets(query_by_date.get(data_date, []))
    return rank_bucket_logical_fields(counts)


def rank_bucket_logical_fields(bucket_counts: dict[str, int]) -> dict[str, Any]:
    """看板：GSC 四档搜索词数（当日 query 维、全国家合计）。"""
    return {label: bucket_counts[key] for label, key, _lo, _hi in RANK_BUCKET_SPECS}


def build_dashboard_alert(traffic_week_change: float | None) -> str:
    if traffic_week_change is not None and traffic_week_change <= -0.2:
        return "流量下跌"
    return "正常"


def resolve_priority_option_key(
    label: str,
    priority_keys: dict[str, str],
    *,
    report: SyncReport | None = None,
) -> str | None:
    key = priority_keys.get(label)
    if key:
        return key
    if label == "P3":
        fallback = priority_keys.get("未分级")
        if report:
            report.log_warning(
                "明道云「优先级」尚无 P3 选项，P3 词已记为未分级；请在表中增加 P3 后更新 keyword_priority_option_keys"
            )
        return fallback
    return None


def build_keyword_controls(
    table: WorksheetTableConfig,
    *,
    site_option_key: str,
    data_date: dt.date,
    keyword: str,
    item: dict[str, Any],
    intent_option_keys: dict[str, str],
    priority_option_keys: dict[str, str],
    write_priority: bool,
    report: SyncReport | None = None,
    grade: KeywordGradeDetail | None = None,
) -> list[dict[str, str]]:
    fields = table.fields
    controls = [
        {"controlId": fields["site"], "value": site_option_key},
        {"controlId": fields["keyword"], "value": keyword},
        {"controlId": fields["data_date"], "value": format_mingdao_date(data_date)},
        {"controlId": fields["rank_change"], "value": format_rank_change(item)},
    ]
    volume = item.get("volume")
    if volume is not None:
        controls.append({"controlId": fields["volume"], "value": format_mingdao_number(volume)})
    kd = item.get("keyword_difficulty")
    if kd is not None:
        controls.append({"controlId": fields["kd"], "value": format_mingdao_number(kd)})
    cpc_raw = item.get("cpc")
    cpc_usd = normalize_ahrefs_cpc(cpc_raw)
    cpc_field = fields.get("cpc")
    if cpc_field and cpc_usd is not None:
        controls.append({"controlId": cpc_field, "value": format_mingdao_decimal(cpc_usd, places=2)})
    rank = item.get("best_position")
    if rank is not None:
        controls.append({"controlId": fields["rank"], "value": format_mingdao_number(rank)})
    landing = item.get("best_position_url")
    if landing:
        controls.append({"controlId": fields["landing_url"], "value": str(landing)})

    if grade is None:
        grade = grade_keyword(
            keyword=keyword,
            item=item,
            volume=volume,
            kd=kd,
            cpc=cpc_raw,
            rank=rank,
            write_priority=write_priority,
        )
    intent_field = fields.get("search_intent")
    if grade.intent and intent_field:
        intent_key = intent_option_keys.get(grade.intent)
        if intent_key:
            controls.append({"controlId": intent_field, "value": intent_key})

    if write_priority and grade.final_priority:
        priority_field = fields.get("priority")
        if priority_field:
            priority_key = resolve_priority_option_key(
                grade.final_priority,
                priority_option_keys,
                report=report,
            )
            if priority_key:
                controls.append({"controlId": priority_field, "value": priority_key})

    value_score_field = fields.get("value_score")
    if value_score_field and grade.value_score is not None:
        controls.append(
            {"controlId": value_score_field, "value": format_mingdao_decimal(grade.value_score, places=2)}
        )

    return controls


def build_page_controls(
    table: WorksheetTableConfig,
    *,
    data_date: dt.date,
    index_status: str,
    metrics: dict[str, Any],
) -> list[dict[str, str]]:
    fields = table.fields
    index_keys = table.option_keys.get("index_status", {})
    index_key = index_keys.get(index_status)
    if not index_key:
        raise RuntimeError(f"Unknown index status {index_status!r}")
    controls: list[dict[str, str]] = [
        {"controlId": fields["index_status"], "value": index_key},
        {"controlId": fields["data_date"], "value": format_mingdao_date(data_date)},
    ]
    clicks_field = fields.get("traffic") or fields.get("clicks")
    if clicks_field:
        controls.append(
            {"controlId": clicks_field, "value": format_mingdao_number(int(metrics.get("clicks") or 0))}
        )
    impressions_field = fields.get("impressions")
    if impressions_field and metrics.get("impressions") is not None:
        controls.append(
            {
                "controlId": impressions_field,
                "value": format_mingdao_number(int(metrics["impressions"])),
            }
        )
    ctr_field = fields.get("ctr")
    if ctr_field and metrics.get("ctr") is not None:
        controls.append({"controlId": ctr_field, "value": format_mingdao_number(float(metrics["ctr"]))})
    position_field = fields.get("position")
    if position_field and metrics.get("position") is not None:
        controls.append(
            {
                "controlId": position_field,
                "value": format_mingdao_number(round(float(metrics["position"]), 1)),
            }
        )
    word_count_field = fields.get("word_count")
    if word_count_field and metrics.get("word_count") is not None:
        controls.append(
            {
                "controlId": word_count_field,
                "value": format_mingdao_number(int(metrics["word_count"])),
            }
        )

    text_field_map = {
        "primary_keyword": lambda v: str(v),
    }
    for field_key, formatter in text_field_map.items():
        field_id = fields.get(field_key)
        value = metrics.get(field_key)
        if field_id and value:
            controls.append({"controlId": field_id, "value": formatter(value)})

    date_field = fields.get("ahrefs_first_seen")
    first_seen = metrics.get("ahrefs_first_seen")
    if date_field and first_seen:
        controls.append({"controlId": date_field, "value": format_mingdao_date(first_seen)})

    number_field_map = {
        "ur": lambda v: format_mingdao_number(round(float(v), 1)),
        "primary_keyword_volume": lambda v: format_mingdao_number(int(v)),
        "keyword_count": lambda v: format_mingdao_number(int(v)),
        "ahrefs_traffic": lambda v: format_mingdao_number(int(v)),
        "global_dr": lambda v: format_mingdao_number(round(float(v), 1)),
    }
    for field_key, formatter in number_field_map.items():
        field_id = fields.get(field_key)
        value = metrics.get(field_key)
        if field_id and value is not None:
            controls.append({"controlId": field_id, "value": formatter(value)})

    value_field = fields.get("ahrefs_value")
    if value_field and metrics.get("ahrefs_value") is not None:
        controls.append(
            {
                "controlId": value_field,
                "value": format_mingdao_decimal(float(metrics["ahrefs_value"]), places=2),
            }
        )
    return controls


def fetch_gsc_page_metrics_by_url(
    gsc: GSCClient,
    config: Config,
    data_date: dt.date,
    *,
    report: SyncReport | None = None,
    site_key: str = "",
) -> dict[str, dict[str, Any]]:
    """锚点日 GSC page 维度汇总（全国家合计），键为 normalize_page_url。"""
    api_rows = gsc.query_dimension_rows(
        data_date,
        ["page"],
        row_limit=config.pages_gsc_import_limit,
        label="searchAnalytics/query (pages import)",
    )
    by_url: dict[str, dict[str, Any]] = {}
    for item in api_rows:
        keys = item.get("keys", [])
        if not keys:
            continue
        raw_url = str(keys[0]).strip()
        if not raw_url:
            continue
        key = normalize_page_url(raw_url)
        by_url[key] = {
            "page_url": raw_url,
            "clicks": int(item.get("clicks") or 0),
            "impressions": int(item.get("impressions") or 0),
            "ctr": float(item.get("ctr") or 0),
            "position": float(item.get("position") or 0),
        }
    if report:
        report.log_api(
            "sync",
            f"gsc pages batch ({site_key})",
            detail=f"date={data_date.isoformat()} urls={len(by_url)} limit={config.pages_gsc_import_limit}",
        )
    return by_url


def seed_page_rows_from_ahrefs_top_pages(
    ahrefs: AhrefsClient,
    mingdao: MingdaoClient,
    table: WorksheetTableConfig,
    report: SyncReport,
    site: SiteConfig,
    data_date: dt.date,
    *,
    site_option: str,
    known_urls: set[str],
    import_limit: int,
    min_traffic: int,
) -> int:
    """从 Ahrefs top-pages 批量新建行：按 sum_traffic 降序，表中尚无的 URL。"""
    index = ahrefs._top_pages_index or {}
    items = sorted(
        index.items(),
        key=lambda kv: int(kv[1].get("sum_traffic") or 0),
        reverse=True,
    )
    created = 0
    for url_key, item in items:
        if created >= import_limit:
            break
        traffic = int(item.get("sum_traffic") or 0)
        if traffic < min_traffic:
            continue
        if url_key in known_urls:
            continue
        page_url = str(item.get("url") or item.get("raw_url") or url_key).strip()
        if not page_url:
            continue
        controls = build_page_seed_controls(
            table,
            site_option_key=site_option,
            page_url=page_url,
            data_date=data_date,
        )
        mingdao.add_row(table.worksheet_id, controls)
        known_urls.add(url_key)
        created += 1
        report.log_write(
            PAGES_LABEL,
            "create",
            site.key,
            {
                "页面URL": page_url,
                "独立站": site.key,
                "Ahrefs月流量": traffic,
            },
        )
    if created:
        report.log_api(
            "sync",
            f"pages ahrefs import ({site.key})",
            detail=(
                f"date={data_date.isoformat()} created={created} "
                f"limit={import_limit} min_traffic={min_traffic} "
                f"top_pages_index={len(index)}"
            ),
        )
    return created


def seed_page_rows_from_gsc(
    mingdao: MingdaoClient,
    table: WorksheetTableConfig,
    report: SyncReport,
    site: SiteConfig,
    data_date: dt.date,
    *,
    site_option: str,
    metrics_by_url: dict[str, dict[str, Any]],
    known_urls: set[str],
    min_impressions: int,
) -> int:
    """从 GSC 批量结果新建行：仅 impressions >= min_impressions 且表中尚无的 URL。"""
    created = 0
    for key, metrics in metrics_by_url.items():
        if metrics["impressions"] < min_impressions:
            continue
        if key in known_urls:
            continue
        page_url = metrics["page_url"]
        controls = build_page_seed_controls(
            table,
            site_option_key=site_option,
            page_url=page_url,
            data_date=data_date,
        )
        mingdao.add_row(table.worksheet_id, controls)
        known_urls.add(key)
        created += 1
        report.log_write(
            PAGES_LABEL,
            "create",
            site.key,
            {"页面URL": page_url, "独立站": site.key, "GSC展示量": metrics["impressions"]},
        )
    if created:
        report.log_api(
            "sync",
            f"pages gsc import ({site.key})",
            detail=f"date={data_date.isoformat()} created={created} min_impressions={min_impressions}",
        )
    return created


def sync_keywords(
    config: Config,
    mingdao: MingdaoClient,
    ahrefs: AhrefsClient,
    report: SyncReport,
    site: SiteConfig,
    data_date: dt.date,
) -> None:
    table = config.worksheets.keywords
    site_option = worksheet_site_option(table, site.key)
    rankings = ahrefs.load_organic_rankings()
    filters = [build_site_filter(table.fields["site"], site_option)]
    existing_rows = mingdao.list_all_rows(table.worksheet_id, filters=filters)
    priority_field = table.fields.get("priority", "")
    row_index: dict[str, tuple[str, str]] = {}
    for row in existing_rows:
        keyword_val = row_control_value(row, table.fields["keyword"])
        if not keyword_val:
            continue
        existing_priority = row_control_value(row, priority_field) if priority_field else ""
        row_index[keyword_val.casefold()] = (row["rowid"], existing_priority)

    created = 0
    updated = 0
    priority_skipped_manual = 0
    grade_details: list[KeywordGradeDetail] = []

    for item in rankings.values():
        keyword = item.get("keyword")
        if not keyword:
            continue
        keyword_text = str(keyword)
        lookup = keyword_text.casefold()
        row_id, existing_priority = row_index.get(lookup, (None, ""))
        write_priority = should_auto_write_priority(
            existing_priority,
            priority_keys=config.keyword_priority_option_keys,
        )
        if row_id and not write_priority:
            priority_skipped_manual += 1

        grade = grade_keyword(
            keyword=keyword_text,
            item=item,
            volume=item.get("volume"),
            kd=item.get("keyword_difficulty"),
            cpc=item.get("cpc"),
            rank=item.get("best_position"),
            write_priority=write_priority,
        )
        grade_details.append(grade)

        controls = build_keyword_controls(
            table,
            site_option_key=site_option,
            data_date=data_date,
            keyword=keyword_text,
            item=item,
            intent_option_keys=config.keyword_intent_option_keys,
            priority_option_keys=config.keyword_priority_option_keys,
            write_priority=write_priority,
            report=report,
            grade=grade,
        )

        if row_id:
            mingdao.edit_row(table.worksheet_id, row_id, controls)
            updated += 1
        else:
            mingdao.add_row(table.worksheet_id, controls)
            created += 1

    priority_written = sum(1 for d in grade_details if d.write_priority)
    priority_counts: dict[str, int] = {}
    for d in grade_details:
        if d.write_priority:
            priority_counts[d.final_priority] = priority_counts.get(d.final_priority, 0) + 1

    report.log_api(
        "sync",
        f"keywords ({site.key})",
        detail=(
            f"created={created} updated={updated} total={len(rankings)} "
            f"priority_auto={priority_written} priority_skip_manual={priority_skipped_manual}"
        ),
    )
    if not rankings:
        report.log_skip(
            KEYWORDS_LABEL,
            f"{site.key} Ahrefs US 市场 date={data_date} 返回 0 条排名词（站点在美国 Google 可能暂无 Top100 词）",
        )

    summary_lines = format_grading_summary_lines(
        site.key,
        data_date.isoformat(),
        grade_details,
        created=created,
        updated=updated,
        priority_skipped_manual=priority_skipped_manual,
    )
    report.add_keyword_grading_report(summary_lines)

    write_stats: dict[str, Any] = {
        "新建": created,
        "更新": updated,
        "API词数": len(rankings),
        "数据日期": data_date.isoformat(),
        "自动写优先级": priority_written,
        "保留人工优先级": priority_skipped_manual,
    }
    if priority_counts:
        write_stats["建议优先级分布"] = priority_counts
    report.log_write(KEYWORDS_LABEL, "sync", site.key, write_stats)


def build_page_seed_controls(
    table: WorksheetTableConfig,
    *,
    site_option_key: str,
    page_url: str,
    data_date: dt.date,
) -> list[dict[str, str]]:
    fields = table.fields
    return [
        {"controlId": fields["site"], "value": site_option_key},
        {"controlId": fields["page_url"], "value": page_url},
        {"controlId": fields["data_date"], "value": format_mingdao_date(data_date)},
    ]


def ensure_site_homepage_row(
    mingdao: MingdaoClient,
    table: WorksheetTableConfig,
    report: SyncReport,
    site: SiteConfig,
    data_date: dt.date,
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """每站保证有一条首页 URL（config/sites.json → homepage_url）。"""
    site_option = worksheet_site_option(table, site.key)
    homepage = normalize_page_url(site.homepage_url)
    has_homepage = any(
        normalize_page_url(row_control_value(row, table.fields["page_url"])) == homepage
        for row in rows
        if row_control_value(row, table.fields["page_url"])
    )
    if has_homepage:
        return rows, False

    controls = build_page_seed_controls(
        table,
        site_option_key=site_option,
        page_url=site.homepage_url,
        data_date=data_date,
    )
    mingdao.add_row(table.worksheet_id, controls)
    report.log_write(
        PAGES_LABEL,
        "create",
        site.key,
        {"页面URL": site.homepage_url, "独立站": site.key},
    )
    report.log_api(
        "sync",
        f"pages seed homepage ({site.key})",
        detail=f"url={site.homepage_url}",
    )
    filters = [build_site_filter(table.fields["site"], site_option)]
    return mingdao.list_all_rows(table.worksheet_id, filters=filters), True


def clear_pages_worksheet(
    config: Config,
    mingdao: MingdaoClient,
    report: SyncReport,
    *,
    site_keys: list[str] | None = None,
    dry_run: bool = False,
    thorough_delete: bool = False,
) -> dict[str, int]:
    """删除页面管理表行。site_keys 为空时删全表所有行；否则按独立站删。"""
    table = config.worksheets.pages
    stats = {"listed": 0, "deleted": 0, "failed": 0, "skipped": 0}

    if site_keys:
        targets = [site for site in config.sites if site.key in site_keys]
        unknown = sorted(set(site_keys) - {site.key for site in targets})
        if unknown:
            raise RuntimeError(f"未知站点: {', '.join(unknown)}")
    else:
        targets = []

    row_batches: list[tuple[str, list[dict[str, Any]]]] = []
    if targets:
        for site in targets:
            site_option = worksheet_site_option(table, site.key)
            filters = [build_site_filter(table.fields["site"], site_option)]
            rows = mingdao.list_all_rows(table.worksheet_id, filters=filters)
            row_batches.append((site.key, rows))
    else:
        rows = mingdao.list_all_rows(table.worksheet_id)
        row_batches.append(("all", rows))

    for scope, rows in row_batches:
        stats["listed"] += len(rows)
        report.log_api(
            "sync",
            f"clear pages {'preview' if dry_run else 'delete'} ({scope})",
            detail=f"rows={len(rows)} dry_run={dry_run} thorough={thorough_delete}",
        )
        if dry_run:
            continue
        for row in rows:
            row_id = str(row.get("rowid") or "").strip()
            if not row_id:
                stats["skipped"] += 1
                continue
            page_url = row_control_value(row, table.fields.get("page_url", ""))
            try:
                mingdao.delete_row(
                    table.worksheet_id,
                    row_id,
                    thorough_delete=thorough_delete,
                    trigger_workflow=False,
                )
                stats["deleted"] += 1
                report.log_write(
                    PAGES_LABEL,
                    "delete",
                    scope,
                    {"rowId": row_id, "页面URL": page_url or "(empty)"},
                )
            except Exception as exc:
                stats["failed"] += 1
                report.log_warning(
                    f"页面管理表删除失败 scope={scope} rowId={row_id} url={page_url}: {exc}"
                )
            time.sleep(0.05)

    return stats


def run_clear_pages(
    *,
    site_filter: list[str] | None = None,
    dry_run: bool = False,
    thorough_delete: bool = False,
    command_line: str = "",
) -> None:
    setup_logging()
    config = Config.load(site_filter=None)
    report = SyncReport(
        started_at=dt.datetime.now(),
        data_date=resolve_sync_anchor_date(config, None),
        config=config,
        command_line=command_line or format_sync_command(),
    )
    mingdao = MingdaoClient(config, report)
    mingdao.test_connection()

    stats = clear_pages_worksheet(
        config,
        mingdao,
        report,
        site_keys=site_filter,
        dry_run=dry_run,
        thorough_delete=thorough_delete,
    )
    scope = ",".join(site_filter) if site_filter else "all"
    logging.info(
        "Clear pages (%s): listed=%s deleted=%s failed=%s skipped=%s dry_run=%s",
        scope,
        stats["listed"],
        stats["deleted"],
        stats["failed"],
        stats["skipped"],
        dry_run,
    )
    report.save()


def sync_pages(
    config: Config,
    mingdao: MingdaoClient,
    gsc: GSCClient,
    ahrefs: AhrefsClient,
    report: SyncReport,
    site: SiteConfig,
    data_date: dt.date,
) -> PageSyncStats:
    table = config.worksheets.pages
    site_option = worksheet_site_option(table, site.key)
    filters = [build_site_filter(table.fields["site"], site_option)]
    rows = mingdao.list_all_rows(table.worksheet_id, filters=filters)
    rows, homepage_created = ensure_site_homepage_row(mingdao, table, report, site, data_date, rows)
    stats = PageSyncStats(created=1 if homepage_created else 0)

    known_urls: set[str] = set()
    for row in rows:
        page_url = row_control_value(row, table.fields["page_url"])
        if page_url:
            known_urls.add(normalize_page_url(page_url))

    metrics_by_url = fetch_gsc_page_metrics_by_url(
        gsc, config, data_date, report=report, site_key=site.key
    )

    ahrefs.prepare_page_sync_caches(data_date)
    stats.seeded_from_ahrefs = seed_page_rows_from_ahrefs_top_pages(
        ahrefs,
        mingdao,
        table,
        report,
        site,
        data_date,
        site_option=site_option,
        known_urls=known_urls,
        import_limit=config.pages_ahrefs_import_limit,
        min_traffic=config.pages_ahrefs_import_min_traffic,
    )
    stats.created += stats.seeded_from_ahrefs

    if stats.seeded_from_ahrefs:
        rows = mingdao.list_all_rows(table.worksheet_id, filters=filters)

    for row in rows:
        page_url = row_control_value(row, table.fields["page_url"])
        if not page_url:
            stats.skipped_empty_url += 1
            report.log_skip(PAGES_LABEL, f"{site.key} 空页面URL rowId={row.get('rowid')}")
            continue

        try:
            gsc_url = normalize_page_url_for_gsc(page_url)
            if gsc_url != page_url and gsc_url.rstrip("/") != page_url.rstrip("/"):
                report.log_api(
                    "sync",
                    f"page url normalized ({site.key})",
                    detail=f"{page_url!r} -> {gsc_url!r}",
                )

            metrics: dict[str, Any] = {}
            for lookup_key in page_url_lookup_keys(page_url):
                hit = metrics_by_url.get(lookup_key)
                if hit:
                    metrics = dict(hit)
                    break
            if not metrics:
                metrics = {
                    "clicks": gsc.query_page_clicks(gsc_url, data_date),
                    "impressions": 0,
                    "ctr": 0,
                    "position": 0,
                }
            metrics.update(ahrefs.get_page_ahrefs_metrics(page_url, data_date))
            index_status = gsc.inspect_page_url(gsc_url)
            controls = build_page_controls(
                table,
                data_date=data_date,
                index_status=index_status,
                metrics=metrics,
            )
            mingdao.edit_row(table.worksheet_id, row["rowid"], controls)
        except RuntimeError as exc:
            if "10007" in str(exc):
                stats.skipped_missing_row += 1
                report.log_skip(
                    PAGES_LABEL,
                    f"{site.key} 行已删除 rowId={row.get('rowid')} url={page_url}",
                )
                continue
            stats.skipped_update_error += 1
            report.log_warning(f"{site.key} 页面更新失败 rowId={row.get('rowid')} url={page_url}: {exc}")
            continue
        stats.updated += 1
        if index_status == "已收录":
            stats.indexed_count += 1
        else:
            stats.issues_count += 1
        report.log_write(
            PAGES_LABEL,
            "update",
            normalize_page_url(page_url),
            {
                "收录状态": index_status,
                "GSC点击": metrics.get("clicks"),
                "GSC展示量": metrics.get("impressions"),
                "主关键词": metrics.get("primary_keyword"),
                "排名关键词数": metrics.get("keyword_count"),
                "全球排名DR": metrics.get("global_dr"),
            },
        )

    report.log_api(
        "sync",
        f"pages ({site.key})",
        detail=(
            f"created={stats.created} ahrefs_import={stats.seeded_from_ahrefs} "
            f"updated={stats.updated} "
            f"indexed={stats.indexed_count} issues={stats.issues_count} "
            f"skipped_empty={stats.skipped_empty_url} skipped_missing={stats.skipped_missing_row} "
            f"skipped_error={stats.skipped_update_error} "
            f"ahrefs_limit={config.pages_ahrefs_import_limit} "
            f"min_traffic={config.pages_ahrefs_import_min_traffic} "
            f"homepage={site.homepage_url}"
        ),
    )
    return stats


def worksheet_country_option(table: WorksheetTableConfig, country_code: str) -> str | None:
    code = country_code.strip().lower()
    country_keys = table.option_keys.get("country", {})
    return country_keys.get(code)


def invert_option_keys(option_keys: dict[str, str]) -> dict[str, str]:
    return {value: key for key, value in option_keys.items()}


def resolve_country_code(raw: str, country_key_to_code: dict[str, str]) -> str:
    text = raw.strip()
    if not text:
        return ""
    if text in country_key_to_code:
        return country_key_to_code[text].lower()
    return text.lower()


def format_skipped_countries(skipped: Counter[str]) -> str:
    return ", ".join(f"{code}×{count}" for code, count in sorted(skipped.items()))


def log_missing_country_warning(
    report: SyncReport,
    *,
    site_key: str,
    table_label: str,
    skipped: Counter[str],
) -> None:
    if not skipped:
        return
    codes = format_skipped_countries(skipped)
    report.log_warning(
        f"{site_key} {table_label} 缺少国家单选选项，跳过 {sum(skipped.values())} 行: {codes} "
        f"（请在明道云建选项并写入 mingdao_worksheets.json country_option_keys）"
    )


def build_date_filter(control_id: str, data_date: dt.date) -> dict[str, Any]:
    return {
        "controlId": control_id,
        "dataType": MingdaoClient.DATE_TYPE,
        "spliceType": 1,
        "filterType": 2,
        "value": data_date.isoformat(),
    }


def load_worksheet_rows_in_date_window(
    mingdao: MingdaoClient,
    table: WorksheetTableConfig,
    *,
    site_option: str,
    dates: list[dt.date],
) -> list[dict[str, Any]]:
    """明道云 getFilterRows 对日期字段等值筛选不可靠；按独立站拉全量后在内存按数据日期过滤。"""
    site_filters = [build_site_filter(table.fields["site"], site_option)]
    all_rows = mingdao.list_all_rows(table.worksheet_id, filters=site_filters)
    if not dates:
        return all_rows
    date_set = {day.isoformat() for day in dates}
    data_date_field = table.fields.get("data_date")
    if not data_date_field:
        return all_rows
    return [
        row
        for row in all_rows
        if row_control_value(row, data_date_field) in date_set
    ]


def build_gsc_metric_controls(fields: dict[str, str], row: dict[str, Any]) -> list[dict[str, str]]:
    controls: list[dict[str, str]] = [
        {"controlId": fields["clicks"], "value": format_mingdao_number(row["clicks"])},
        {"controlId": fields["impressions"], "value": format_mingdao_number(row["impressions"])},
        {"controlId": fields["ctr"], "value": format_mingdao_number(row["ctr"])},
    ]
    position = row.get("position")
    if position is not None:
        controls.append(
            {"controlId": fields["position"], "value": format_mingdao_number(round(float(position), 1))}
        )
    return controls


def build_gsc_top_query_controls(
    table: WorksheetTableConfig,
    *,
    site_option_key: str,
    data_date: dt.date,
    keyword: str,
    country_option_key: str,
    metrics: dict[str, Any],
) -> list[dict[str, str]]:
    fields = table.fields
    controls = [
        {"controlId": fields["data_date"], "value": format_mingdao_date(data_date)},
        {"controlId": fields["site"], "value": site_option_key},
        {"controlId": fields["keyword"], "value": keyword},
        {"controlId": fields["country"], "value": country_option_key},
    ]
    controls.extend(build_gsc_metric_controls(fields, metrics))
    return controls


def build_gsc_top_page_controls(
    table: WorksheetTableConfig,
    *,
    site_option_key: str,
    data_date: dt.date,
    page_url: str,
    country_option_key: str,
    metrics: dict[str, Any],
) -> list[dict[str, str]]:
    fields = table.fields
    controls = [
        {"controlId": fields["data_date"], "value": format_mingdao_date(data_date)},
        {"controlId": fields["site"], "value": site_option_key},
        {"controlId": fields["page_url"], "value": page_url},
        {"controlId": fields["country"], "value": country_option_key},
    ]
    controls.extend(build_gsc_metric_controls(fields, metrics))
    return controls


def sync_gsc_top_queries(
    config: Config,
    mingdao: MingdaoClient,
    gsc: GSCClient,
    report: SyncReport,
    site: SiteConfig,
    anchor: dt.date,
) -> None:
    table = config.worksheets.gsc_top_queries
    site_option = worksheet_site_option(table, site.key)
    country_key_to_code = invert_option_keys(table.option_keys.get("country", {}))
    dates = get_dashboard_dates(config, anchor=anchor)
    window_rows = load_worksheet_rows_in_date_window(
        mingdao,
        table,
        site_option=site_option,
        dates=dates,
    )
    row_index_by_date: dict[dt.date, dict[tuple[str, str], str]] = {
        day: {} for day in dates
    }
    for row in window_rows:
        raw_date = row_control_value(row, table.fields["data_date"])
        try:
            data_date = dt.date.fromisoformat(raw_date)
        except ValueError:
            continue
        if data_date not in row_index_by_date:
            continue
        keyword = row_control_value(row, table.fields["keyword"])
        country_code = resolve_country_code(
            row_control_value(row, table.fields["country"]),
            country_key_to_code,
        )
        if keyword and country_code:
            row_index_by_date[data_date][(keyword, country_code)] = row["rowid"]

    created = 0
    updated = 0
    api_total = 0
    skipped_zero_clicks = 0
    skipped_countries: Counter[str] = Counter()

    for data_date in dates:
        row_index = row_index_by_date[data_date]

        api_rows = gsc.query_dimension_rows(
            data_date,
            ["query", "country"],
            row_limit=config.gsc_top_queries_limit,
            label="searchAnalytics/query (top queries)",
            country_filter=site.gsc_top_countries,
        )
        api_total += len(api_rows)

        for item in api_rows:
            if int(item.get("clicks") or 0) <= 0:
                skipped_zero_clicks += 1
                continue
            keys = item.get("keys", [])
            if len(keys) < 2:
                continue
            keyword = str(keys[0]).strip()
            country_code = str(keys[1]).strip().lower()
            if not keyword:
                continue
            if not gsc_top_country_allowed(site, country_code):
                continue
            country_option = worksheet_country_option(table, country_code)
            if not country_option:
                skipped_countries[country_code] += 1
                continue

            metrics = {
                "clicks": item["clicks"],
                "impressions": item["impressions"],
                "ctr": item["ctr"],
                "position": item["position"],
            }
            controls = build_gsc_top_query_controls(
                table,
                site_option_key=site_option,
                data_date=data_date,
                keyword=keyword,
                country_option_key=country_option,
                metrics=metrics,
            )
            lookup = (keyword, country_code)
            row_id = row_index.get(lookup)
            if row_id:
                mingdao.edit_row(table.worksheet_id, row_id, controls)
                updated += 1
            else:
                mingdao.add_row(table.worksheet_id, controls)
                created += 1

    log_missing_country_warning(
        report, site_key=site.key, table_label="GSC Top 查询", skipped=skipped_countries
    )
    report.log_api(
        "sync",
        f"gsc top queries ({site.key})",
        detail=(
            f"range={dates[0].isoformat()}..{dates[-1].isoformat()} days={len(dates)} "
            f"countries={gsc_top_country_scope_label(site)} "
            f"api={api_total} created={created} updated={updated} "
            f"skip_zero_clicks={skipped_zero_clicks} "
            f"skip_country={sum(skipped_countries.values())}"
            + (f" missing={format_skipped_countries(skipped_countries)}" if skipped_countries else "")
        ),
    )
    write_stats: dict[str, Any] = {
        "新建": created,
        "更新": updated,
        "API返回": api_total,
        "国家范围": gsc_top_country_scope_label(site),
        "跳过0点击": skipped_zero_clicks,
        "跳过国家行数": sum(skipped_countries.values()),
        "数据窗口": f"{dates[0].isoformat()}..{dates[-1].isoformat()}",
    }
    if skipped_countries:
        write_stats["缺少国家选项"] = dict(sorted(skipped_countries.items()))
    report.log_write(GSC_TOP_QUERIES_LABEL, "sync", site.key, write_stats)


def build_gsc_top_query_enrich_controls(
    table: WorksheetTableConfig,
    metrics: dict[str, Any],
) -> list[dict[str, str]]:
    fields = table.fields
    controls: list[dict[str, str]] = []
    volume_field = fields.get("ahrefs_volume")
    volume = metrics.get("volume")
    if volume_field and volume is not None:
        controls.append(
            {"controlId": volume_field, "value": format_mingdao_number(int(volume))}
        )
    kd_field = fields.get("ahrefs_kd")
    kd = metrics.get("kd")
    if kd_field and kd is not None:
        controls.append({"controlId": kd_field, "value": format_mingdao_number(kd)})
    cpc_field = fields.get("ahrefs_cpc")
    cpc_usd = normalize_ahrefs_cpc(metrics.get("cpc"))
    if cpc_field and cpc_usd is not None:
        controls.append(
            {"controlId": cpc_field, "value": format_mingdao_decimal(cpc_usd, places=2)}
        )
    return controls


def enrich_gsc_top_queries(
    config: Config,
    mingdao: MingdaoClient,
    ahrefs: AhrefsClient,
    report: SyncReport,
    site: SiteConfig,
    anchor: dt.date,
) -> None:
    table = config.worksheets.gsc_top_queries
    if not gsc_top_queries_enrich_fields_ready(table):
        report.log_skip(
            GSC_TOP_QUERIES_LABEL,
            f"{site.key} enrich 跳过：未配置 Ahrefs 三列 controlId "
            f"(MINGDAO_FIELD_GSC_QUERY_AHREFS_VOLUME/KD/CPC)",
        )
        return

    site_option = worksheet_site_option(table, site.key)
    country_key_to_code = invert_option_keys(table.option_keys.get("country", {}))
    dates = get_dashboard_dates(config, anchor=anchor)
    clicks_field = table.fields.get("clicks")
    if not clicks_field:
        report.log_skip(GSC_TOP_QUERIES_LABEL, f"{site.key} enrich 跳过：缺少 clicks 字段")
        return

    window_rows = load_worksheet_rows_in_date_window(
        mingdao,
        table,
        site_option=site_option,
        dates=dates,
    )
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row in window_rows:
        keyword = row_control_value(row, table.fields["keyword"])
        country_code = resolve_country_code(
            row_control_value(row, table.fields["country"]),
            country_key_to_code,
        )
        row_id = row.get("rowid")
        if not keyword or not country_code or not row_id:
            continue
        lookup = (keyword, country_code)
        bucket = groups.setdefault(
            lookup,
            {"total_clicks": 0, "row_ids": []},
        )
        bucket["total_clicks"] += int(parse_mingdao_number(row_control_value(row, clicks_field)))
        bucket["row_ids"].append(str(row_id))

    report.log_api(
        "sync",
        f"gsc top queries enrich load ({site.key})",
        detail=(
            f"range={dates[0].isoformat()}..{dates[-1].isoformat()} "
            f"window_rows={len(window_rows)} groups={len(groups)}"
        ),
    )

    targets = select_gsc_top_query_enrich_targets(
        groups,
        enrich_countries=config.gsc_top_queries_enrich_countries,
        mode=config.gsc_top_queries_enrich_mode,
        limit=config.gsc_top_queries_enrich_limit,
    )
    if not targets:
        report.log_skip(
            GSC_TOP_QUERIES_LABEL,
            f"{site.key} enrich 无目标 "
            f"(countries={','.join(config.gsc_top_queries_enrich_countries) or 'all'} "
            f"mode={config.gsc_top_queries_enrich_mode})",
        )
        return

    overview_by_country: dict[str, dict[str, dict[str, Any]]] = {}
    country_keywords: dict[str, list[str]] = {}
    skipped_enrich_countries: Counter[str] = Counter()
    for keyword, country, _clicks, _row_ids in targets:
        if country in GSC_ENRICH_SKIP_COUNTRIES:
            skipped_enrich_countries[country] += 1
            continue
        ahrefs_country = gsc_country_to_ahrefs(country)
        if not ahrefs_country:
            report.log_warning(
                f"{site.key} enrich 跳过未知国家映射: gsc={country!r} keyword={keyword!r}"
            )
            continue
        country_keywords.setdefault(ahrefs_country, []).append(keyword)

    api_keywords = 0
    for ahrefs_country, keywords in country_keywords.items():
        unique_keywords = list(dict.fromkeys(keywords))
        api_keywords += len(unique_keywords)
        overview_by_country[ahrefs_country] = ahrefs.fetch_keywords_overview(
            ahrefs_country,
            unique_keywords,
        )

    enriched_rows = 0
    skipped_no_metrics = 0
    for keyword, country, total_clicks, row_ids in targets:
        if country in GSC_ENRICH_SKIP_COUNTRIES:
            continue
        ahrefs_country = gsc_country_to_ahrefs(country)
        if not ahrefs_country:
            continue
        metrics = overview_by_country.get(ahrefs_country, {}).get(keyword.casefold())
        if not metrics:
            skipped_no_metrics += 1
            continue
        controls = build_gsc_top_query_enrich_controls(table, metrics)
        if not controls:
            skipped_no_metrics += 1
            continue
        logical = {
            "Ahrefs搜索量": metrics.get("volume"),
            "Ahrefs KD": metrics.get("kd"),
            "Ahrefs CPC": normalize_ahrefs_cpc(metrics.get("cpc")),
        }
        for row_id in row_ids:
            mingdao.edit_row(table.worksheet_id, row_id, controls)
            enriched_rows += 1
        report.log_write(
            GSC_TOP_QUERIES_LABEL,
            "enrich",
            f"{keyword}@{country}",
            {**logical, "7日点击": total_clicks, "rows": len(row_ids)},
        )

    report.log_api(
        "sync",
        f"gsc top queries enrich ({site.key})",
        detail=(
            f"range={dates[0].isoformat()}..{dates[-1].isoformat()} "
            f"countries={','.join(config.gsc_top_queries_enrich_countries)} "
            f"mode={config.gsc_top_queries_enrich_mode} "
            f"limit={config.gsc_top_queries_enrich_limit} "
            f"targets={len(targets)} overview_keywords={api_keywords} "
            f"rows_written={enriched_rows} skipped_no_metrics={skipped_no_metrics}"
            + (
                f" skip_enrich_country={sum(skipped_enrich_countries.values())}"
                f" ({format_skipped_countries(skipped_enrich_countries)})"
                if skipped_enrich_countries
                else ""
            )
        ),
    )


def sync_gsc_top_pages(
    config: Config,
    mingdao: MingdaoClient,
    gsc: GSCClient,
    report: SyncReport,
    site: SiteConfig,
    anchor: dt.date,
) -> None:
    table = config.worksheets.gsc_top_pages
    site_option = worksheet_site_option(table, site.key)
    country_key_to_code = invert_option_keys(table.option_keys.get("country", {}))
    dates = get_dashboard_dates(config, anchor=anchor)
    window_rows = load_worksheet_rows_in_date_window(
        mingdao,
        table,
        site_option=site_option,
        dates=dates,
    )
    row_index_by_date: dict[dt.date, dict[tuple[str, str], str]] = {
        day: {} for day in dates
    }
    for row in window_rows:
        raw_date = row_control_value(row, table.fields["data_date"])
        try:
            data_date = dt.date.fromisoformat(raw_date)
        except ValueError:
            continue
        if data_date not in row_index_by_date:
            continue
        page_url = row_control_value(row, table.fields["page_url"])
        country_code = resolve_country_code(
            row_control_value(row, table.fields["country"]),
            country_key_to_code,
        )
        if page_url and country_code:
            row_index_by_date[data_date][(normalize_page_url(page_url), country_code)] = row["rowid"]

    created = 0
    updated = 0
    api_total = 0
    skipped_zero_clicks = 0
    skipped_countries: Counter[str] = Counter()

    for data_date in dates:
        row_index = row_index_by_date[data_date]

        api_rows = gsc.query_dimension_rows(
            data_date,
            ["page", "country"],
            row_limit=config.gsc_top_pages_limit,
            label="searchAnalytics/query (top pages)",
            country_filter=site.gsc_top_countries,
        )
        api_total += len(api_rows)

        for item in api_rows:
            if int(item.get("clicks") or 0) <= 0:
                skipped_zero_clicks += 1
                continue
            keys = item.get("keys", [])
            if len(keys) < 2:
                continue
            page_url = str(keys[0]).strip()
            country_code = str(keys[1]).strip().lower()
            if not page_url:
                continue
            if not gsc_top_country_allowed(site, country_code):
                continue
            country_option = worksheet_country_option(table, country_code)
            if not country_option:
                skipped_countries[country_code] += 1
                continue

            metrics = {
                "clicks": item["clicks"],
                "impressions": item["impressions"],
                "ctr": item["ctr"],
                "position": item["position"],
            }
            controls = build_gsc_top_page_controls(
                table,
                site_option_key=site_option,
                data_date=data_date,
                page_url=page_url,
                country_option_key=country_option,
                metrics=metrics,
            )
            lookup = (normalize_page_url(page_url), country_code)
            row_id = row_index.get(lookup)
            if row_id:
                mingdao.edit_row(table.worksheet_id, row_id, controls)
                updated += 1
            else:
                mingdao.add_row(table.worksheet_id, controls)
                created += 1

    log_missing_country_warning(
        report, site_key=site.key, table_label="GSC Top 页面", skipped=skipped_countries
    )
    report.log_api(
        "sync",
        f"gsc top pages ({site.key})",
        detail=(
            f"range={dates[0].isoformat()}..{dates[-1].isoformat()} days={len(dates)} "
            f"countries={gsc_top_country_scope_label(site)} "
            f"api={api_total} created={created} updated={updated} "
            f"skip_zero_clicks={skipped_zero_clicks} "
            f"skip_country={sum(skipped_countries.values())}"
            + (f" missing={format_skipped_countries(skipped_countries)}" if skipped_countries else "")
        ),
    )
    write_stats: dict[str, Any] = {
        "新建": created,
        "更新": updated,
        "API返回": api_total,
        "国家范围": gsc_top_country_scope_label(site),
        "跳过0点击": skipped_zero_clicks,
        "跳过国家行数": sum(skipped_countries.values()),
        "数据窗口": f"{dates[0].isoformat()}..{dates[-1].isoformat()}",
    }
    if skipped_countries:
        write_stats["缺少国家选项"] = dict(sorted(skipped_countries.items()))
    report.log_write(GSC_TOP_PAGES_LABEL, "sync", site.key, write_stats)


def sync_dashboard_gsc_query_buckets(
    config: Config,
    mingdao: MingdaoClient,
    gsc: GSCClient,
    report: SyncReport,
    site: SiteConfig,
    *,
    anchor: dt.date,
) -> None:
    """仅写入看板 GSC 四档搜索词数（不覆盖其它看板列）。"""
    dates = get_dashboard_dates(config, anchor=anchor)
    query_by_date = load_gsc_query_rows_by_dates(
        gsc,
        config,
        dates,
        report=report,
        site_key=site.key,
    )

    for data_date in dates:
        fields: dict[str, Any] = {
            "日期": data_date,
            "独立站": site.key,
            **gsc_rank_bucket_fields_for_date(query_by_date, data_date),
        }
        report.log_api(
            "sync",
            f"dashboard gsc buckets ({site.key})",
            detail=format_fields_for_report(fields),
        )
        mingdao.upsert_dashboard(data_date, fields, site.key)


def sync_dashboard(
    config: Config,
    mingdao: MingdaoClient,
    gsc: GSCClient,
    ahrefs: AhrefsClient,
    report: SyncReport,
    site: SiteConfig,
    cache: SyncCache,
    *,
    anchor: dt.date,
    page_stats: PageSyncStats | None = None,
    force_refresh: bool = False,
) -> None:
    page_stats = page_stats or PageSyncStats()
    daily_data = fetch_gsc_daily_summaries(
        gsc, site, config, cache, report, anchor=anchor, force_refresh=force_refresh
    )
    ahrefs_anchor_summary = ahrefs.get_dashboard_summary()

    this_week_start = anchor - dt.timedelta(days=6)
    last_week_end = anchor - dt.timedelta(days=7)
    last_week_start = anchor - dt.timedelta(days=13)
    this_week_clicks = gsc.query_clicks_sum(this_week_start, anchor)
    last_week_clicks = gsc.query_clicks_sum(last_week_start, last_week_end)
    traffic_week_change = calc_ratio_change(this_week_clicks, last_week_clicks)
    weekly_avg_rank = calc_weekly_avg_position(daily_data)

    dates = list(daily_data.keys())
    query_by_date = load_gsc_query_rows_by_dates(
        gsc,
        config,
        dates,
        report=report,
        site_key=site.key,
    )

    for data_date, gsc_summary in daily_data.items():
        fields: dict[str, Any] = {
            "日期": data_date,
            "独立站": site.key,
            "自然点击": int(gsc_summary.get("clicks") or 0),
            "展示量": int(gsc_summary.get("impressions") or 0),
            "平均CTR": float(gsc_summary.get("ctr") or 0),
            "全站加权平均排名": round(float(gsc_summary.get("position") or 0), 1),
            **gsc_rank_bucket_fields_for_date(query_by_date, data_date),
        }

        if config.dashboard_fields.site_dr:
            site_dr = ahrefs.get_domain_rating_for_date(data_date)
            if site_dr is not None:
                fields["本站DR"] = site_dr

        if data_date == anchor:
            fields.update(
                {
                    "Backlinks变化": ahrefs_anchor_summary["new_referring_domains"],
                    "已监控URL收录数": page_stats.indexed_count,
                    "已监控URL异常数": page_stats.issues_count,
                    "异常预警": build_dashboard_alert(traffic_week_change),
                }
            )
            if weekly_avg_rank is not None and config.dashboard_fields.weekly_avg_position:
                fields["周平均排名"] = weekly_avg_rank
            if traffic_week_change is not None:
                fields["周环比流量"] = round(traffic_week_change, 4)

        if is_provisional_gsc_zero(gsc_summary, data_date, config):
            report.log_warning(
                f"{site.key} {data_date.isoformat()} GSC 仍为 0，可能尚未出数；"
                f"可稍后重跑 sync（缓存会在 {config.data_delay_days}+{config.gsc_recent_refresh_days} 天内自动重拉）"
            )

        report.log_api(
            "sync",
            f"dashboard payload ({site.key})",
            detail=format_fields_for_report(fields),
        )
        mingdao.upsert_dashboard(data_date, fields, site.key)


def sync_site(
    config: Config,
    mingdao: MingdaoClient,
    gsc: GSCClient | None,
    ahrefs: AhrefsClient,
    report: SyncReport,
    site: SiteConfig,
    cache: SyncCache,
    *,
    anchor: dt.date,
    tables: SyncTables | None = None,
    force_refresh: bool = False,
) -> None:
    tables = tables or SyncTables()
    page_stats = PageSyncStats()

    if tables.keywords:
        sync_keywords(config, mingdao, ahrefs, report, site, anchor)
    if tables.pages:
        if gsc is None:
            raise RuntimeError("GSC client required for 页面管理表")
        page_stats = sync_pages(config, mingdao, gsc, ahrefs, report, site, anchor)
    if tables.gsc_top_queries:
        if not tables.gsc_top_queries_enrich_only:
            if gsc is None:
                raise RuntimeError("GSC client required for GSC Top 查询明细")
            sync_gsc_top_queries(config, mingdao, gsc, report, site, anchor)
        if tables.gsc_top_queries_enrich:
            enrich_gsc_top_queries(config, mingdao, ahrefs, report, site, anchor)
    if tables.gsc_top_pages:
        if gsc is None:
            raise RuntimeError("GSC client required for GSC Top 页面明细")
        sync_gsc_top_pages(config, mingdao, gsc, report, site, anchor)
    if tables.dashboard:
        if gsc is None:
            raise RuntimeError("GSC client required for SEO 自动数据看板")
        if tables.dashboard_gsc_buckets_only:
            sync_dashboard_gsc_query_buckets(
                config,
                mingdao,
                gsc,
                report,
                site,
                anchor=anchor,
            )
        else:
            sync_dashboard(
                config,
                mingdao,
                gsc,
                ahrefs,
                report,
                site,
                cache,
                anchor=anchor,
                page_stats=page_stats,
                force_refresh=force_refresh,
            )


def run_sync(
    *,
    test_mingdao_only: bool = False,
    site_filter: list[str] | None = None,
    force_refresh: bool = False,
    tables: SyncTables | None = None,
    anchor_date: str | None = None,
    command_line: str = "",
) -> Path:
    setup_logging()
    logging.info("SEO Mingdao data sync started")

    config = Config.load(site_filter=site_filter)
    cache = SyncCache(enabled=config.cache_enabled)
    anchor = resolve_sync_anchor_date(config, anchor_date)
    dates = get_dashboard_dates(config, anchor=anchor)
    tables = tables or SyncTables()
    report = SyncReport(
        started_at=dt.datetime.now(),
        data_date=anchor,
        config=config,
        command_line=command_line or format_sync_command(),
        tables=tables,
    )
    mingdao = MingdaoClient(config, report)

    logging.info(
        "Sync window: %s .. %s (%s days), anchor=%s, cache=%s",
        dates[0].isoformat(),
        dates[-1].isoformat(),
        len(dates),
        anchor.isoformat(),
        "on" if config.cache_enabled else "off",
    )

    mingdao.test_connection()

    if test_mingdao_only:
        report.log_skip("sync", "test-mingdao-only: skipped GSC/Ahrefs write")
        return report.save()

    google_credentials: Any | None = None
    if sync_needs_gsc(tables):
        try:
            google_credentials = load_google_credentials_with_retry(config)
            logging.info(
                "Google credentials ready (auth=%s); reused for all %s site(s)",
                config.google_auth_mode,
                len(config.sites),
            )
        except Exception as exc:
            report.log_warning(f"Google credentials unavailable, GSC steps will retry per site: {exc}")
            logging.exception("Google credentials load failed")
    else:
        logging.info("Skipping Google credentials (no pages/dashboard in this run)")

    for site in config.sites:
        logging.info("Syncing site: %s (GSC=%s, Ahrefs=%s)", site.key, site.gsc_site_url, site.ahrefs_domain)
        site_ok = False
        last_error: Exception | None = None
        for attempt in range(1, SITE_SYNC_MAX_ATTEMPTS + 1):
            try:
                gsc: GSCClient | None = None
                if sync_needs_gsc(tables):
                    gsc = GSCClient(
                        config,
                        report,
                        site_url=site.gsc_site_url,
                        credentials=google_credentials,
                    )
                ahrefs = AhrefsClient(
                    config,
                    report,
                    target_domain=site.ahrefs_domain,
                    site_key=site.key,
                    report_date=anchor,
                )
                sync_site(
                    config,
                    mingdao,
                    gsc,
                    ahrefs,
                    report,
                    site,
                    cache,
                    anchor=anchor,
                    tables=tables,
                    force_refresh=force_refresh,
                )
                site_ok = True
                if attempt > 1:
                    logging.info("%s sync succeeded on attempt %s/%s", site.key, attempt, SITE_SYNC_MAX_ATTEMPTS)
                break
            except Exception as exc:
                last_error = exc
                if is_transient_network_error(exc) and attempt < SITE_SYNC_MAX_ATTEMPTS:
                    delay = SITE_SYNC_RETRY_SECONDS * attempt
                    logging.warning(
                        "%s sync failed (attempt %s/%s), retry in %ss: %s",
                        site.key,
                        attempt,
                        SITE_SYNC_MAX_ATTEMPTS,
                        delay,
                        exc,
                    )
                    report.log_warning(
                        f"{site.key} transient error (attempt {attempt}/{SITE_SYNC_MAX_ATTEMPTS}), "
                        f"retry in {delay}s: {exc}"
                    )
                    if google_credentials is None and config.google_auth_mode == "oauth":
                        try:
                            google_credentials = load_google_credentials_with_retry(config)
                            logging.info("Google credentials reloaded after transient failure")
                        except Exception as cred_exc:
                            logging.warning("Google credentials reload failed: %s", cred_exc)
                    time.sleep(delay)
                    continue
                report.log_warning(f"{site.key} sync failed: {exc}")
                logging.exception("Site sync failed: %s", site.key)
                break
        if not site_ok and last_error is not None:
            logging.error("%s skipped after %s attempt(s)", site.key, SITE_SYNC_MAX_ATTEMPTS)
        report.record_site_outcome(
            site.key,
            ok=site_ok,
            error="" if site_ok else str(last_error or "sync failed"),
        )

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
    parser.add_argument(
        "--site",
        action="append",
        dest="sites",
        metavar="SITE",
        help="Sync only this site key (repeatable). Default: all sites in config/sites.json",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore local GSC cache and re-fetch all dashboard dates",
    )
    parser.add_argument(
        "--skip-keywords",
        action="store_true",
        help="Skip 站点关键词库",
    )
    parser.add_argument(
        "--skip-pages",
        action="store_true",
        help="Skip 页面管理表",
    )
    parser.add_argument(
        "--skip-dashboard",
        action="store_true",
        help="Skip SEO 自动数据看板",
    )
    parser.add_argument(
        "--skip-gsc-top-queries",
        action="store_true",
        help="Skip GSC Top 查询明细",
    )
    parser.add_argument(
        "--skip-gsc-top-pages",
        action="store_true",
        help="Skip GSC Top 页面明细",
    )
    parser.add_argument(
        "--skip-gsc-top-queries-enrich",
        action="store_true",
        help="Skip GSC Top 查询 Ahrefs overview 补数（Volume/KD/CPC）",
    )
    parser.add_argument(
        "--only-gsc-top-queries-enrich",
        action="store_true",
        help="仅补 GSC Top 查询 Ahrefs 三列，不重拉 GSC",
    )
    parser.add_argument(
        "--only-dashboard-gsc-buckets",
        action="store_true",
        help="仅同步 SEO 自动数据看板的 GSC 四档搜索词数（不跑其它表/看板列）",
    )
    parser.add_argument(
        "--anchor-date",
        metavar="YYYY-MM-DD",
        help="覆盖锚点日（Ahrefs date、关键词/页面数据日期；例 2026-05-30）",
    )
    parser.add_argument(
        "--clear-pages",
        action="store_true",
        help="删除页面管理表现有数据行（危险操作；须配合 --yes 或 --clear-pages-dry-run）",
    )
    parser.add_argument(
        "--clear-pages-dry-run",
        action="store_true",
        help="仅统计页面管理表将删除的行数，不实际删除",
    )
    parser.add_argument(
        "--clear-pages-thorough",
        action="store_true",
        help="彻底删除（不进明道云回收站，不可恢复）",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认 destructive 操作（与 --clear-pages 同用）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.clear_pages:
        if not args.yes and not args.clear_pages_dry_run:
            raise SystemExit(
                "删除页面管理表行须加 --yes 确认，或先用 --clear-pages-dry-run 预览行数"
            )
        if args.clear_pages_dry_run and args.yes:
            logging.info("同时指定 dry-run 与 --yes：仅预览，不删除")
        run_clear_pages(
            site_filter=args.sites,
            dry_run=args.clear_pages_dry_run,
            thorough_delete=args.clear_pages_thorough,
            command_line=format_sync_command(),
        )
        return
    if args.only_gsc_top_queries_enrich and args.skip_gsc_top_queries:
        raise SystemExit("--only-gsc-top-queries-enrich 与 --skip-gsc-top-queries 不能同时使用")
    if args.only_dashboard_gsc_buckets and args.skip_dashboard:
        raise SystemExit("--only-dashboard-gsc-buckets 与 --skip-dashboard 不能同时使用")
    if args.only_gsc_top_queries_enrich and args.only_dashboard_gsc_buckets:
        raise SystemExit("--only-gsc-top-queries-enrich 与 --only-dashboard-gsc-buckets 不能同时使用")
    if args.only_gsc_top_queries_enrich:
        tables = SyncTables(
            keywords=False,
            pages=False,
            dashboard=False,
            gsc_top_queries=True,
            gsc_top_pages=False,
            gsc_top_queries_enrich=True,
            gsc_top_queries_enrich_only=True,
        )
    elif args.only_dashboard_gsc_buckets:
        tables = SyncTables(
            keywords=False,
            pages=False,
            dashboard=True,
            gsc_top_queries=False,
            gsc_top_pages=False,
            gsc_top_queries_enrich=False,
            dashboard_gsc_buckets_only=True,
        )
    else:
        tables = SyncTables(
            keywords=not args.skip_keywords,
            pages=not args.skip_pages,
            dashboard=not args.skip_dashboard,
            gsc_top_queries=not args.skip_gsc_top_queries,
            gsc_top_pages=not args.skip_gsc_top_pages,
            gsc_top_queries_enrich=(
                not args.skip_gsc_top_queries_enrich and not args.skip_gsc_top_queries
            ),
        )
    run_sync(
        test_mingdao_only=args.test_mingdao_only,
        site_filter=args.sites,
        force_refresh=args.refresh,
        tables=tables,
        anchor_date=args.anchor_date,
        command_line=format_sync_command(),
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("SEO Mingdao data sync failed")
        raise
