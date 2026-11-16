#!/usr/bin/env python3
"""采集 A 股五类事件并生成前端数据文件。

用法：
    python scripts/fetch_data.py            # 真实数据
    python scripts/fetch_data.py --demo     # 离线演示数据
    python scripts/fetch_data.py --days 30  # 覆盖回看天数

产出：
    data/latest.json   给 API / 飞书脚本用
    data/latest.js     `window.ASTOCK_DATA = {...}`，让 index.html 直接 file:// 也能打开
    data/history/YYYY-MM-DD.json  每日快照（用于回溯与"新增事件"对比）
    data/history/index.json       快照索引
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from collectors import collect_all  # noqa: E402

DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
TYPE_ORDER = ["increase", "decrease", "placement", "repurchase", "dividend"]
TYPE_LABEL = {
    "increase": "增持",
    "decrease": "减持",
    "placement": "定增",
    "repurchase": "回购",
    "dividend": "分红",
}


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")


def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def summarize(events: list[dict]) -> dict:
    by_type = {}
    for key in TYPE_ORDER:
        subset = [e for e in events if e["type"] == key]
        by_type[key] = {
            "label": TYPE_LABEL[key],
            "count": len(subset),
            "amount": round(sum(e.get("amount") or 0 for e in subset), 1),
            "stocks": len({e["code"] for e in subset}),
        }
    stocks = len({e["code"] for e in events})
    increase_amt = by_type["increase"]["amount"]
    decrease_amt = by_type["decrease"]["amount"]
    return {
        "total": len(events),
        "stocks": stocks,
        "byType": by_type,
        "netIncrease": round(increase_amt - decrease_amt, 1),
        "topCodes": [
            {"code": code, "name": name, "count": count}
            for code, name, count in _top_codes(events)
        ],
    }


def _top_codes(events: list[dict], limit: int = 6) -> list[tuple[str, str, int]]:
    counter: dict[str, dict] = {}
    for event in events:
        item = counter.setdefault(event["code"], {"name": event["name"], "count": 0})
        item["count"] += 1
    ordered = sorted(counter.items(), key=lambda kv: kv[1]["count"], reverse=True)[:limit]
    return [(code, info["name"], info["count"]) for code, info in ordered]


def write_payload(payload: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (DATA_DIR / "latest.json").write_text(text, encoding="utf-8")
    (DATA_DIR / "latest.js").write_text(f"window.ASTOCK_DATA = {text};\n", encoding="utf-8")

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = payload["tradeDate"]
    (HISTORY_DIR / f"{stamp}.json").write_text(text, encoding="utf-8")

    snapshots = sorted((p.stem for p in HISTORY_DIR.glob("*.json") if p.stem.isdigit()), reverse=True)
    (HISTORY_DIR / "index.json").write_text(
        json.dumps({"dates": snapshots[:180]}, ensure_ascii=False), encoding="utf-8"
    )
    # 只保留最近 180 份快照
    for stale in snapshots[180:]:
        (HISTORY_DIR / f"{stale}.json").unlink(missing_ok=True)


def load_previous() -> dict | None:
    path = DATA_DIR / "latest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="生成离线演示数据")
    parser.add_argument("--days", type=int, default=None, help="覆盖 config 中的回看天数")
    args = parser.parse_args()
    setup_logging()

    config = load_config()
    if args.days:
        config["lookbackDays"] = args.days

    previous = load_previous()

    if args.demo:
        from demo_data import build_demo_events  # noqa: PLC0415

        events = build_demo_events()
        sources = [{"name": "演示数据", "status": "demo", "count": len(events), "message": "离线样例，非真实行情"}]
        data_mode = "demo"
    else:
        events, sources = collect_all(config)
        data_mode = "live" if any(s["status"] == "ok" for s in sources) else "degraded"
        # 合并旧项目 / 外部来源的数据（data/extra/*.json），失败不影响主流程
        try:
            from merge_extra import load_extra_events  # noqa: PLC0415

            extra_events, extra_files = load_extra_events(config.get("extraAmountUnit", "wan"))
            if extra_events:
                events.extend(extra_events)
                sources.append(
                    {
                        "name": "外部项目",
                        "status": "ok",
                        "count": len(extra_events),
                        "message": f"{'、'.join(extra_files)} 合并 {len(extra_events)} 条",
                    }
                )
        except Exception as exc:  # noqa: BLE001
            sources.append({"name": "外部项目", "status": "error", "count": 0, "message": str(exc)[:120]})

    # 按 id 去重，避免采集源与外部数据重复
    deduped: dict[str, dict] = {}
    for event in events:
        deduped.setdefault(event["id"], event)
    events = list(deduped.values())

    events.sort(key=lambda e: (e.get("announceDate") or "", e.get("amount") or 0), reverse=True)
    events = events[: int(config.get("maxEvents", 2000))]

    today = dt.date.today().isoformat()
    prev_ids = {e["id"] for e in (previous or {}).get("events", [])}
    new_count = len([e for e in events if e["id"] not in prev_ids]) if prev_ids else 0

    payload = {
        "generatedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "tradeDate": today,
        "dataMode": data_mode,
        "lookbackDays": config.get("lookbackDays"),
        "sources": sources,
        "stats": summarize(events),
        "delta": {"newEvents": new_count, "previousTradeDate": (previous or {}).get("tradeDate")},
        "events": events,
    }
    write_payload(payload)

    stats = payload["stats"]
    print(f"✅ 写入 {len(events)} 条事件（{data_mode}），覆盖 {stats['stocks']} 只个股")
    for key in TYPE_ORDER:
        info = stats["byType"][key]
        print(f"   {info['label']:<3} {info['count']:>5} 条  金额 {info['amount']:>12,.0f} 万元")
    for item in sources:
        flag = {"ok": "✓", "error": "✗", "skipped": "-", "demo": "·"}.get(item["status"], "?")
        print(f"   [{flag}] {item['name']}: {item['message']}")
    return 0 if events else 1


if __name__ == "__main__":
    raise SystemExit(main())
