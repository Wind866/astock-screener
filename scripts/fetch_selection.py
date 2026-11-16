#!/usr/bin/env python3
"""拉取 BIGApush 的收盘选股结果，供事件表做「选股 × 事件」交叉。

数据链路：
    BIGApush 收盘选股 → SQLite stock_selection_record → export_selection.py
    → exports/selection-latest.json（提交到 BIGApush 仓库）
    → 本脚本拉 raw 地址 → 写进 data/latest.json 的 selection 字段 → 前端标注

取不到不报错：没有选股池时前端自动隐藏该维度，事件表照常工作。

用法：
    python scripts/fetch_selection.py             # 单独跑，看识别结果
    python scripts/fetch_selection.py --file xx.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOCAL_OVERRIDE = ROOT / "data" / "extra" / "selection.json"

DEFAULT_SOURCE = "https://raw.githubusercontent.com/Wind866/BIGApush/main/exports/selection-latest.json"
DATE_RE = re.compile(r"(20\d{2})[-/]?(\d{1,2})[-/]?(\d{1,2})")


def _pick(row: dict, *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, "", "-"):
            return row[name]
    lowered = {str(k).lower(): v for k, v in row.items()}
    for name in names:
        if name.lower() in lowered and lowered[name.lower()] not in (None, "", "-"):
            return lowered[name.lower()]
    return None


def _code(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or "").split(".")[0])
    return digits.zfill(6)[-6:] if digits else ""


def _date(value: Any) -> str:
    text = str(value or "")
    match = DATE_RE.search(text)
    if not match:
        return ""
    y, m, d = (int(g) for g in match.groups())
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return ""


def _strategies(row: dict) -> list[str]:
    raw = _pick(row, "strategies", "strategy_names", "strategy", "strategy_name", "策略", "选股策略")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        return [s.strip() for s in re.split(r"[,，+、;/\s]+", raw) if s.strip()]
    return []


def _flatten(node: Any) -> list[dict]:
    if isinstance(node, list):
        out = []
        for item in node:
            out.extend(_flatten(item))
        return out
    if isinstance(node, dict):
        for key in ("picks", "items", "rows", "data", "list", "records"):
            if isinstance(node.get(key), list):
                return _flatten(node[key])
        if _code(_pick(node, "code", "stock_code", "股票代码")):  # 单行
            return [node]
        out = []
        for value in node.values():
            if isinstance(value, (list, dict)):
                out.extend(_flatten(value))
        return out
    return []


def normalize(raw: Any, days: int = 15) -> dict | None:
    rows = _flatten(raw)
    if not rows:
        return None

    today = dt.date.today()
    cutoff = (today - dt.timedelta(days=days)).isoformat()
    picks: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for row in rows:
        code = _code(_pick(row, "code", "stock_code", "股票代码", "证券代码", "symbol"))
        if not code:
            continue
        date = _date(_pick(row, "selection_date", "date", "选入日期", "trade_date", "announceDate"))
        if not date:
            date = today.isoformat()
        if date < cutoff:
            continue
        if (code, date) in seen:
            continue
        seen.add((code, date))

        strategies = _strategies(row)
        score = _pick(row, "score", "评分", "综合评分")
        picks.append(
            {
                "code": code,
                "name": str(_pick(row, "name", "stock_name", "股票名称", "股票简称") or code).strip(),
                "date": date,
                "strategies": strategies,
                "strategyCount": int(_pick(row, "strategy_count", "strategyCount", "命中策略个数") or len(strategies) or 1),
                "score": float(score) if isinstance(score, (int, float)) else None,
                "rank": _pick(row, "rank_position", "rank", "排名"),
                "price": _pick(row, "selection_price", "price", "选入价格", "最新价"),
                "industry": _pick(row, "industry", "行业", "所属行业"),
                "sector": _pick(row, "sector", "板块", "所属板块"),
            }
        )

    if not picks:
        return None

    picks.sort(key=lambda p: (p["date"], -(p.get("rank") or 999)), reverse=True)
    return {
        "asOf": max(p["date"] for p in picks),
        "count": len(picks),
        "stocks": len({p["code"] for p in picks}),
        "picks": picks,
    }


def load_selection(source: str | None = None, days: int = 15, timeout: float = 12) -> dict | None:
    """本地 data/extra/selection.json 优先（离线/联调），否则拉远程 raw。"""
    if LOCAL_OVERRIDE.exists():
        try:
            return normalize(json.loads(LOCAL_OVERRIDE.read_text(encoding="utf-8")), days)
        except (json.JSONDecodeError, OSError):
            pass

    url = (source or "").strip() or DEFAULT_SOURCE
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "astock-screener/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - 拉不到就静默降级
        print(f"[选股池] 拉取失败（{url}）：{str(exc)[:100]}")
        return None

    result = normalize(raw, days)
    if result:
        result["source"] = "BIGApush"
        result["url"] = url
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=None, help="本地 JSON 文件")
    parser.add_argument("--url", default=None)
    parser.add_argument("--days", type=int, default=15)
    args = parser.parse_args()

    if args.file:
        data = normalize(json.loads(Path(args.file).read_text(encoding="utf-8")), args.days)
    else:
        data = load_selection(args.url, args.days)

    if not data:
        print("没有可用的选股数据（前端会隐藏该维度）")
        return 0
    print(f"选股池：{data['stocks']} 只 / {data['count']} 条记录，最新 {data['asOf']}")
    for pick in data["picks"][:8]:
        print(f"  {pick['date']} {pick['code']} {pick['name']} 评分={pick['score']} 策略={','.join(pick['strategies']) or '—'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
