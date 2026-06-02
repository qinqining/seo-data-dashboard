"""Print Google OAuth fields from token.json for Mingdao connection setup."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "token.json"


def main() -> None:
    if not TOKEN_FILE.exists():
        print(f"未找到 {TOKEN_FILE}，请先运行 sync.py 完成 Google 授权。")
        raise SystemExit(1)

    data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    fields = ("client_id", "client_secret", "refresh_token")
    print("复制以下值到明道云 GSC 连接参数（勾选「隐藏」）：\n")
    for name in fields:
        value = data.get(name, "")
        if not value:
            print(f"  {name}: （缺失）")
            continue
        masked = value[:6] + "..." + value[-4:] if len(value) > 12 else "(太短)"
        print(f"  {name}: {masked}")
    print("\n完整值请直接打开 token.json 复制（勿发到聊天/工单）。")
    print("GSC 站点 URL 用 .env 里的 GSC_SITE_URL（一行，含 https://）。")


if __name__ == "__main__":
    main()
