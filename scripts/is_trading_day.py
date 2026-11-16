#!/usr/bin/env python3
"""交易日预检：非交易日直接跳过采集与推送，别在假期推昨天的榜单。

判断顺序：
    1. akshare 交易日历（tool_trade_date_hist_sina，缓存到 .cache/trade_cal.json）
    2. 日历取不到 → 退化为「周一至周五算交易日」，并打印降级提示（不让网络抖动卡死流程）

输出 ``is_trading=true|false``，同时写入 ``$GITHUB_OUTPUT``。
配合 ``--force`` 可强制视为交易日（调试用）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "trade_cal.json"


def _emit(is_trading: bool, reason: str) -> None:
    print(f"[交易日] {reason} → is_trading={'true' if is_trading else 'false'}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        try:
            with open(out, "a", encoding="utf-8") as fp:
                fp.write(f"is_trading={'true' if is_trading else 'false'}\n")
        except OSError:
            pass


def _from_cache(today: str) -> bool | None:
    if not CACHE.exists():
        return None
    try:
        days = set(json.loads(CACHE.read_text(encoding="utf-8")).get("days", []))
    except (json.JSONDecodeError, OSError):
        return None
    return today in days if days else None


def _from_akshare() -> set[str] | None:
    try:
        import akshare as ak  # noqa: PLC0415
    except ImportError:
        return None

    # akshare 1.20.45 起把 tool_trade_date_hist_sina 改名为 calendar_trade_date_hist_sina，
    # 新名优先、旧名兜底，两边都试一遍免得跟着版本走。
    frame = None
    for name in ("calendar_trade_date_hist_sina", "tool_trade_date_hist_sina"):
        fn = getattr(ak, name, None)
        if fn is None:
            continue
        try:
            frame = fn()
            break
        except Exception as exc:  # noqa: BLE001 - 数据源不可用时降级
            print(f"[交易日] {name} 获取失败：{str(exc)[:120]}")

    if frame is None or getattr(frame, "empty", True):
        return None

    # 列名可能随版本变化（trade_date / 交易日期），取第一个像日期的列
    column = next(
        (c for c in frame.columns if "date" in str(c).lower() or "日期" in str(c)),
        frame.columns[0],
    )
    days = {str(v)[:10] for v in frame[column].tolist()}
    if not days:
        return None
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"days": sorted(days)}, ensure_ascii=False), encoding="utf-8")
    return days


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="", help="指定日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--force", action="store_true", help="强制视为交易日")
    args = parser.parse_args()

    today = args.date or dt.date.today().isoformat()
    if args.force:
        _emit(True, "FORCE 强制运行")
        return 0

    weekday = dt.date.fromisoformat(today).weekday()
    if weekday >= 5:
        _emit(False, f"{today} 是周末")
        return 0

    cached = _from_cache(today)
    if cached is not None:
        _emit(cached, f"{today} 命中本地交易日历")
        return 0

    days = _from_akshare()
    if days is not None:
        _emit(today in days, f"{today} 来自 akshare 交易日历（{len(days)} 个交易日）")
        return 0

    _emit(True, f"{today} 日历不可用，按工作日放行（降级）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
