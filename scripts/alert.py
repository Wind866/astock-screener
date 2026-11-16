#!/usr/bin/env python3
"""失败告警：发到独立告警机器人（ALERT_WEBHOOK 优先），没配则回落业务机器人。

工作流里失败时调用：
    python scripts/alert.py "⚠️ 每日采集任务失败" || true

凭据全部走环境变量，且业务/告警机器人「加签要么都开、要么都不开」——
只开一半会出现「告警静默」，这是 BIGApush 里踩过的坑。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import feishu_webhook  # noqa: E402


def main() -> int:
    message = sys.argv[1] if len(sys.argv) > 1 else "⚠️ 任务运行失败"
    run_url = ""
    if os.environ.get("GITHUB_RUN_ID"):
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        run_url = f"{server}/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"

    text = message if not run_url else f"{message}\n查看日志：{run_url}"
    hook, secret = feishu_webhook.resolve_credentials(alert=True)
    if not hook:
        print(f"[告警] 未配置 FEISHU_WEBHOOK / ALERT_WEBHOOK，仅打印：{text}")
        return 0

    try:
        result = feishu_webhook.post_json(hook, {"msg_type": "text", "content": {"text": text}}, secret)
    except Exception as exc:  # noqa: BLE001 - 告警失败不能反过来炸掉工作流
        print(f"[告警] 发送异常：{exc}")
        return 0

    if feishu_webhook.response_ok(result):
        print(f"[告警] 已发送：{text}")
    else:
        print(f"[告警] 发送被拒：{result}{feishu_webhook.describe_rejection(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
