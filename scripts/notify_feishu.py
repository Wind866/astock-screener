#!/usr/bin/env python3
"""把当天事件摘要推送到飞书群机器人（自定义 webhook）。

用法：
    export FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"
    export FEISHU_SECRET=""            # 可选：机器人开了签名校验时必填
    export PAGE_URL="https://xxx.github.io/astock-screener/"   # 也可用统一名 PAGES_URL
    python scripts/notify_feishu.py            # 正式推送
    python scripts/notify_feishu.py --dry-run  # 只打印卡片不发送
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import feishu_webhook  # noqa: E402
import push_ledger  # noqa: E402

DATA_FILE = ROOT / "data" / "latest.json"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

TYPE_LABEL = {"increase": "增持", "decrease": "减持", "placement": "定增", "repurchase": "回购", "dividend": "分红"}
TYPE_EMOJI = {"increase": "🔴", "decrease": "🟢", "placement": "🟠", "repurchase": "🔵", "dividend": "🟣"}


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

    # 数据日期不是今天就打警告，避免把昨天的榜单当成今日行情（BIGApush 同口径）
    stale = ""
    if today and today != dt.date.today().isoformat():
        stale = " ⚠️非当日"

    net = stats.get("netIncrease", 0)
    new_events = (data.get("delta") or {}).get("newEvents")
    new_text = f" · 较上次新增 **{new_events}** 条" if new_events else ""
    summary = (
        f"**📊 事件总览**（近 {data.get('lookbackDays', '—')} 天窗口 · 涉及 **{stats.get('stocks', 0)}** 只个股{new_text}）\n"
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

    page_url = (
        os.environ.get("PAGES_URL")
        or os.environ.get("PAGE_URL")  # 旧名，保持兼容
        or CONFIG.get("feishu", {}).get("pageUrl")
        or ""
    )
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
            "title": {"tag": "plain_text", "content": f"📈 A股事件雷达 · 数据截至 {today}{stale}"},
        },
        "elements": elements,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="不实际发送，仅打印卡片")
    parser.add_argument("--file", default=None, help="指定数据文件（默认 data/latest.json）")
    parser.add_argument("--slot", default="2033", help="档期时刻 HHMM（默认 2033 = 20:33 收盘后），用于台账判重")
    parser.add_argument("--edition", default="", help="档期日期，默认今天")
    parser.add_argument("--force", action="store_true", help="忽略台账强制推送")
    parser.add_argument("--no-ledger", action="store_true", help="不读也不写台账（纯手动调试）")
    args = parser.parse_args()

    edition = args.edition or dt.date.today().isoformat()
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

    # 台账判重：同一天同一档期推过就不再推（多档 cron 兜底的去重）
    if not args.no_ledger and not args.force:
        hit = push_ledger.find("daily.yml", edition, args.slot)
        if hit:
            print(f"[ledger] {edition} slot={args.slot} 已推过（{hit.get('ts')} / run {hit.get('run_id') or '—'}），跳过")
            return 0

    webhook, secret = feishu_webhook.resolve_credentials()
    if not webhook:
        print("❌ 未配置 FEISHU_WEBHOOK 环境变量", file=sys.stderr)
        return 1

    try:
        result = feishu_webhook.post_json(webhook, payload, secret)
    except Exception as exc:  # noqa: BLE001 - 网络层失败
        print(f"❌ 飞书推送网络异常：{exc}", file=sys.stderr)
        return 1

    if not feishu_webhook.response_ok(result):
        print(f"❌ 飞书推送失败：{result}{feishu_webhook.describe_rejection(result)}", file=sys.stderr)
        return 1

    print(f"✅ 飞书推送成功：{result}")
    if not args.no_ledger:
        push_ledger.record("daily.yml", edition, args.slot, note=f"{len(data.get('events', []))} 条事件")
        print(f"[ledger] 已记账 {edition} slot={args.slot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
