#!/usr/bin/env python3
"""把当天事件摘要推送到飞书群机器人（自定义 webhook）。

用法：
    export FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"
    export FEISHU_SECRET=""            # 可选：机器人开了签名校验时必填
    export PAGE_URL="https://xxx.github.io/astock-screener/"
    python scripts/notify_feishu.py            # 正式推送
    python scripts/notify_feishu.py --dry-run  # 只打印卡片不发送
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "latest.json"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

TYPE_LABEL = {"increase": "增持", "decrease": "减持", "placement": "定增", "repurchase": "回购", "dividend": "分红"}
TYPE_EMOJI = {"increase": "🔴", "decrease": "🟢", "placement": "🟠", "repurchase": "🔵", "dividend": "🟣"}


def sign(secret: str, timestamp: int) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def fmt_amount(wan) -> str:
    if wan is None:
        return "—"
    if wan >= 10000:
        return f"{wan / 10000:.2f}亿"
    if wan >= 1:
        return f"{wan:,.0f}万"
    return f"{wan:.1f}万"


def top_lines(events: list[dict], limit: int) -> str:
    """按金额取 top，输出 markdown 行。"""
    ranked = sorted(
        events,
        key=lambda e: (e.get("amount") if e.get("amount") is not None else -1),
        reverse=True,
    )[:limit]
    if not ranked:
        return "今日无相关事件"
    lines = []
    for e in ranked:
        amount = e.get("amount")
        text = f"**{e['code']} {e['name']}** {fmt_amount(amount)}"
        if e["type"] == "dividend":
            text += f" · {e.get('qtyText', '')}"
            if e.get("dividendYield") is not None:
                text += f" · 股息率 {e['dividendYield']:.2f}%"
        elif e.get("ratio") is not None:
            text += f" · 占总股本 {e['ratio']:.2f}%"
        if e.get("party") and e["type"] in ("increase", "decrease"):
            text += f" · {e['party'][:16]}"
        lines.append(text)
    return "\n".join(lines)


def build_card(data: dict) -> dict:
    today = data.get("tradeDate", "")
    stats = data.get("stats", {})
    by_type = stats.get("byType", {})
    limit = int(CONFIG.get("feishu", {}).get("maxItemsPerSection", 6))

    net = stats.get("netIncrease", 0)
    summary = (
        f"**📊 事件总览**（近 {data.get('lookbackDays', '—')} 天窗口 · 涉及 **{stats.get('stocks', 0)}** 只个股）\n"
        f"🔴 增持 {by_type.get('increase', {}).get('count', 0)} 条 · {fmt_amount(by_type.get('increase', {}).get('amount'))}　"
        f"🟢 减持 {by_type.get('decrease', {}).get('count', 0)} 条 · {fmt_amount(by_type.get('decrease', {}).get('amount'))}\n"
        f"🟠 定增 {by_type.get('placement', {}).get('count', 0)} 单 · {fmt_amount(by_type.get('placement', {}).get('amount'))}　"
        f"🔵 回购 {by_type.get('repurchase', {}).get('count', 0)} 条 · {fmt_amount(by_type.get('repurchase', {}).get('amount'))}\n"
        f"🟣 分红 {by_type.get('dividend', {}).get('count', 0)} 条 · {fmt_amount(by_type.get('dividend', {}).get('amount'))}\n"
        f"**净方向：{'增持' if net >= 0 else '减持'} {fmt_amount(abs(net))}**"
    )

    events = data.get("events", [])
    by = {}
    for e in events:
        by.setdefault(e["type"], []).append(e)

    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": summary}}, {"tag": "hr"}]

    section_titles = {
        "increase": "🔥 增持金额 TOP",
        "decrease": "📉 减持金额 TOP",
        "placement": "🧧 定增募资 TOP",
        "repurchase": "💰 回购金额 TOP",
        "dividend": "🎁 分红方案 TOP",
    }
    for key in ("increase", "decrease", "placement", "repurchase", "dividend"):
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**{section_titles[key]}**\n{top_lines(by.get(key, []), limit)}"},
            }
        )

    # 数据源健康
    src_lines = []
    for s in data.get("sources", []):
        mark = "✅" if s["status"] == "ok" else "⚠️"
        src_lines.append(f"{mark} {s['name']}")
    elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": "数据源：" + " / ".join(src_lines) + " · 金额为披露或估算值，仅供参考，不构成投资建议"}]})

    page_url = os.environ.get("PAGE_URL") or CONFIG.get("feishu", {}).get("pageUrl") or ""
    if page_url:
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🖥 打开交互筛选器"},
                        "type": "primary",
                        "url": page_url,
                    }
                ],
            }
        )

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "indigo",
            "title": {"tag": "plain_text", "content": f"📈 A股事件雷达 · {today}"},
        },
        "elements": elements,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="不实际发送，仅打印卡片")
    parser.add_argument("--file", default=None, help="指定数据文件（默认 data/latest.json）")
    args = parser.parse_args()

    data_path = Path(args.file) if args.file else DATA_FILE
    if not data_path.exists():
        print(f"❌ 数据文件不存在：{data_path}，请先运行 fetch_data.py", file=sys.stderr)
        return 1
    data = json.loads(data_path.read_text(encoding="utf-8"))

    card = build_card(data)
    payload: dict = {"msg_type": "interactive", "card": card}

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])
        print("\n---- 卡片文本预览 ----")
        for element in card["elements"]:
            if element.get("tag") == "div":
                print(element["text"]["content"])
                print()
        return 0

    webhook = os.environ.get("FEISHU_WEBHOOK") or ""
    secret = os.environ.get("FEISHU_SECRET") or ""
    if not webhook:
        print("❌ 未配置 FEISHU_WEBHOOK 环境变量", file=sys.stderr)
        return 1

    import requests  # noqa: PLC0415

    if secret:
        timestamp = int(time.time())
        payload["timestamp"] = str(timestamp)
        payload["sign"] = sign(secret, timestamp)

    resp = requests.post(webhook, json=payload, timeout=15)
    result = resp.json()
    if result.get("code") in (0, None) and result.get("msg") in ("success", None):
        print(f"✅ 飞书推送成功：{result}")
        return 0
    print(f"❌ 飞书推送失败：{result}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
