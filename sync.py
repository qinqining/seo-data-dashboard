from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

try:
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    Request = None
    service_account = None
    Credentials = None
    build = None
    InstalledAppFlow = None


ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


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
    feishu_table_daily_log_id: str
    feishu_table_weekly_review_id: str
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
            feishu_table_daily_log_id=env_required("FEISHU_TABLE_DAILY_LOG_ID"),
            feishu_table_weekly_review_id=env_required("FEISHU_TABLE_WEEKLY_REVIEW_ID"),
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


def env_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


class FeishuClient:
    def __init__(self, config: Config):
        self.config = config
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

    def create_record(self, table_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        url = (
            f"{self.base_url}/bitable/v1/apps/"
            f"{self.config.feishu_base_app_token}/tables/{table_id}/records"
        )
        return self._request("POST", url, json={"fields": fields})

    def update_record(self, table_id: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        url = (
            f"{self.base_url}/bitable/v1/apps/"
            f"{self.config.feishu_base_app_token}/tables/{table_id}/records/{record_id}"
        )
        return self._request("PUT", url, json={"fields": fields})

    def upsert_record(self, table_id: str, key_field: str, key_value: Any, fields: dict[str, Any]) -> None:
        existing = self.find_record_by_field(table_id, key_field, key_value)
        if existing:
            self.update_record(table_id, existing["record_id"], fields)
            logging.info("Updated Feishu record table=%s key=%s", table_id, key_value)
        else:
            self.create_record(table_id, fields)
            logging.info("Created Feishu record table=%s key=%s", table_id, key_value)

    def find_record_by_field(self, table_id: str, key_field: str, key_value: Any) -> dict[str, Any] | None:
        for record in self.list_records(table_id):
            fields = record.get("fields", {})
            if fields.get(key_field) == key_value:
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

    def __init__(self, config: Config):
        self.config = config
        self.service = self._build_service()

    def _build_service(self) -> Any:
        if build is None:
            raise RuntimeError("Google API dependencies are not installed.")

        if self.config.google_auth_mode == "service_account":
            credentials = self._load_service_account_credentials()
        elif self.config.google_auth_mode == "oauth":
            credentials = self._load_oauth_credentials()
        else:
            raise RuntimeError(f"Unsupported GOOGLE_AUTH_MODE: {self.config.google_auth_mode}")

        return build("searchconsole", "v1", credentials=credentials)

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
        result = (
            self.service.searchanalytics()
            .query(siteUrl=self.config.gsc_site_url, body=body)
            .execute()
        )
        rows = result.get("rows", [])
        if not rows:
            return {
                "clicks": 0,
                "impressions": 0,
                "ctr": 0,
                "position": 0,
            }
        row = rows[0]
        return {
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": row.get("ctr", 0),
            "position": row.get("position", 0),
        }

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
        result = (
            self.service.searchanalytics()
            .query(siteUrl=self.config.gsc_site_url, body=body)
            .execute()
        )
        rows = result.get("rows", [])
        return int(rows[0].get("clicks", 0)) if rows else 0


class AhrefsClient:
    def __init__(self, config: Config):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.config.ahrefs_api_token}",
                "Accept": "application/json",
            }
        )

    def get_keyword_metrics(self, keyword: str) -> dict[str, Any]:
        logging.info("Ahrefs keyword metrics placeholder: %s", keyword)
        return {
            "volume": None,
            "kd": None,
            "position": None,
            "rank_change": "",
        }

    def get_domain_rating(self, domain: str) -> dict[str, Any]:
        logging.info("Ahrefs domain rating placeholder: %s", domain)
        return {
            "dr": None,
            "is_indexed": None,
        }

    def get_dashboard_summary(self) -> dict[str, Any]:
        logging.info("Ahrefs dashboard summary placeholder")
        return {
            "top10_count": None,
            "top30_count": None,
            "new_referring_domains": None,
        }


def sync_dashboard(config: Config, feishu: FeishuClient, gsc: GSCClient, ahrefs: AhrefsClient) -> None:
    target_date = dt.date.today() - dt.timedelta(days=config.data_delay_days)
    gsc_summary = gsc.query_site_summary(target_date)
    ahrefs_summary = ahrefs.get_dashboard_summary()

    fields = {
        "日期": target_date.isoformat(),
        "自然点击（GSC）": gsc_summary["clicks"],
        "展示量（GSC）": gsc_summary["impressions"],
        "平均CTR": gsc_summary["ctr"],
        "全站平均排名": gsc_summary["position"],
        "核心词Top10数量": ahrefs_summary["top10_count"],
        "核心词Top30数量": ahrefs_summary["top30_count"],
        "今日新增RD（referring domain）": ahrefs_summary["new_referring_domains"],
        "异常预警": "正常",
    }

    feishu.upsert_record(
        table_id=config.feishu_table_dashboard_id,
        key_field="日期",
        key_value=target_date.isoformat(),
        fields=fields,
    )


def sync_keywords(config: Config, feishu: FeishuClient, ahrefs: AhrefsClient) -> None:
    records = feishu.list_records(config.feishu_table_keywords_id)
    for record in records:
        fields = record.get("fields", {})
        keyword = fields.get("关键词内容")
        if not keyword:
            continue

        metrics = ahrefs.get_keyword_metrics(str(keyword))
        update_fields = {
            "搜索量（月）": metrics["volume"],
            "KD难度": metrics["kd"],
            "当前排名": metrics["position"],
            "排名波动": metrics["rank_change"],
        }
        update_fields = remove_none_values(update_fields)
        if update_fields:
            feishu.update_record(
                config.feishu_table_keywords_id,
                record["record_id"],
                update_fields,
            )


def sync_pages(config: Config, feishu: FeishuClient, gsc: GSCClient) -> None:
    target_date = dt.date.today() - dt.timedelta(days=config.data_delay_days)
    records = feishu.list_records(config.feishu_table_pages_id)
    for record in records:
        fields = record.get("fields", {})
        page_url = normalize_feishu_url(fields.get("页面URL"))
        if not page_url:
            continue

        clicks = gsc.query_page_clicks(target_date, page_url)
        feishu.update_record(
            config.feishu_table_pages_id,
            record["record_id"],
            {
                "页面流量": clicks,
            },
        )


def sync_backlinks(config: Config, feishu: FeishuClient, ahrefs: AhrefsClient) -> None:
    records = feishu.list_records(config.feishu_table_backlinks_id)
    for record in records:
        fields = record.get("fields", {})
        domain = normalize_feishu_url(fields.get("外链来源域名"))
        if not domain:
            continue

        metrics = ahrefs.get_domain_rating(domain)
        update_fields = {
            "域名DR值": metrics["dr"],
            "外链收录状态": "已收录" if metrics["is_indexed"] else None,
        }
        update_fields = remove_none_values(update_fields)
        if update_fields:
            feishu.update_record(
                config.feishu_table_backlinks_id,
                record["record_id"],
                update_fields,
            )


def normalize_feishu_url(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("link") or value.get("text") or "").strip()
    if isinstance(value, list) and value:
        return normalize_feishu_url(value[0])
    return ""


def remove_none_values(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def main() -> None:
    setup_logging()
    logging.info("SEO Feishu data sync started")

    config = Config.load()
    feishu = FeishuClient(config)
    gsc = GSCClient(config)
    ahrefs = AhrefsClient(config)

    sync_dashboard(config, feishu, gsc, ahrefs)
    sync_keywords(config, feishu, ahrefs)
    sync_pages(config, feishu, gsc)
    sync_backlinks(config, feishu, ahrefs)

    logging.info("SEO Feishu data sync finished")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("SEO Feishu data sync failed")
        raise
