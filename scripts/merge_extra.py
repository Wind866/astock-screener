#!/usr/bin/env python3
"""把外部项目（旧仓库）里的 JSON 数据并入事件表。

设计目标：不改旧项目一行代码，把它的输出文件丢进 data/extra/ 就能出现在筛选器里。

用法：
    python scripts/merge_extra.py                       # 合并 data/extra/ 下所有 *.json
    python scripts/merge_extra.py --path ../ledger.json # 合并单个文件
    python scripts/merge_extra.py --dry-run             # 只看识别结果，不写文件
    python scripts/merge_extra.py --amount-unit yuan    # 金额字段是"元"而非"万元"

识别能力：
    * 结构：顶层数组 / {"events"|"items"|"rows"|"data"|"list": [...]} / {"2026-11-14": [...]}
    * 字段：中英文别名模糊匹配（代码/名称/股东/数量/金额/占比/公告日期…）
    * 类型：优先取 type 字段，否则用中英文关键词推断（增持/减持/定增/回购/分红）
    * 单位：金额默认按「万元」，占比默认按「百分数」，可命令行覆盖
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from collectors import board_of  # noqa: E402

EXTRA_DIR = ROOT / "data" / "extra"

# ---------------------------------------------------------------- 字段别名
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "code": ("股票代码", "证券代码", "代码", "code", "symbol", "ts_code", "stock_code", "ticker"),
    "name": ("股票名称", "股票简称", "证券简称", "名称", "name", "stock_name", "short_name"),
    "party": ("股东名称", "股东", "变动主体", "增持主体", "减持主体", "holder", "party", "shareholder", "subject"),
    "type": ("事件类型", "类型", "type", "category", "event_type", "kind"),
    "shares": ("变动数量", "增持数量", "减持数量", "成交数量", "数量", "股数", "shares", "volume", "change_shares", "num"),
    "amount": ("变动金额", "成交金额", "金额", "amount", "value", "turnover", "change_amount"),
    "ratio": ("占总股本比例", "占流通股比例", "变动比例", "比例", "占比", "ratio", "pct", "percent", "change_ratio"),
    "announceDate": ("公告日期", "公告日", "发布日期", "日期", "announce_date", "announceDate", "date", "trade_date", "pub_date"),
    "startDate": ("变动开始", "开始日期", "起始日期", "start_date", "begin_date"),
    "endDate": ("变动截止", "截止日期", "结束日期", "end_date"),
    "price": ("成交均价", "均价", "价格", "股价", "price", "avg_price", "close"),
    "changePct": ("涨跌幅", "当日涨跌幅", "change_pct", "pct_chg", "changePct"),
    "status": ("进度", "状态", "状态说明", "status", "stage"),
    "method": ("变动方式", "方式", "method", "way"),
    "note": ("备注", "说明", "摘要", "标题", "内容", "remark", "note", "title", "summary", "content"),
    "qtyText": ("分红方案", "方案", "派息方案", "plan"),
    "dividendYield": ("股息率", "dividend_yield", "yield"),
}

TYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("increase", ("增持", "increase", "add", "buy")),
    ("decrease", ("减持", "decrease", "reduce", "sell")),
    ("placement", ("定增", "增发", "非公开", "placement", "private placement", "issue")),
    ("repurchase", ("回购", "repurchase", "buyback")),
    ("dividend", ("分红", "派息", "送转", "权益分派", "dividend", "bonus")),
)
TYPE_LABEL = {"increase": "增持", "decrease": "减持", "placement": "定增", "repurchase": "回购", "dividend": "分红"}

DATE_RE = re.compile(r"(20\d{2})[-/年.]?(\d{1,2})[-/月.]?(\d{1,2})")


# ---------------------------------------------------------------- 小工具
def _norm_key(key: str) -> str:
    return re.sub(r"[\s_\-()（）%％:：]", "", str(key)).lower()


def _pick(row: dict, field: str) -> Any:
    """按别名模糊命中取值。"""
    target_norm = {_norm_key(k) for k in (field,)}
    for alias in FIELD_ALIASES.get(field, ()):
        a = _norm_key(alias)
        for key, value in row.items():
            nk = _norm_key(key)
            if nk == a or (len(a) >= 3 and a in nk):
                if value not in (None, "", "-", "—", "--", "None", "nan"):
                    return value
    # 兜底：精确等于字段名
    for key, value in row.items():
        if _norm_key(key) in target_norm and value not in (None, "", "-"):
            return value
    return None


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if value != value else float(value)  # NaN 过滤
    text = str(value).strip().replace(",", "").replace("%", "").replace("％", "")
    if not text or text in {"-", "—", "--", "None", "nan", "NaN"}:
        return None
    multiplier = 1.0
    for unit, mult in (("万亿", 1e12), ("亿", 1e8), ("万", 1e4)):
        if unit in text:
            multiplier = mult
            text = text.replace(unit, "")
            break
    text = re.sub(r"[^\d.\-+]", "", text)
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _norm_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return ""
    match = DATE_RE.search(text)
    if match:
        y, m, d = (int(g) for g in match.groups())
        try:
            return dt.date(y, m, d).isoformat()
        except ValueError:
            return ""
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return ""


def _norm_code(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    digits = re.sub(r"\D", "", text.split(".")[0])
    return digits.zfill(6)[-6:] if digits else ""


def _to_amount(value: Any, unit: str = "wan") -> float | None:
    """金额统一换算成「万元」。字符串自带 亿/万/元 后缀时按绝对金额处理。"""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        num = float(value)
        has_suffix = False
    else:
        text = str(value).strip()
        num = _to_float(text)
        if num is None:
            return None
        has_suffix = bool(re.search(r"(万亿|亿|万|元)", text))
    if has_suffix:  # 已带单位 → _to_float 已折算成元
        return num / 1e4
    if unit == "yuan":
        return num / 1e4
    if unit == "auto" and abs(num) > 5e6:
        return num / 1e4
    return num


def _infer_type(row: dict, hint: str = "") -> str:
    raw = str(_pick(row, "type") or "")
    raw_l = raw.lower()
    for key, words in TYPE_KEYWORDS:
        if raw_l in {k for k in (key, TYPE_LABEL[key])} or raw_l in words:
            return key
    text = " ".join(
        str(row.get(k) or "") for k in row if isinstance(row.get(k), (str, int, float))
    ).lower()
    for key, words in TYPE_KEYWORDS:
        if any(word.lower() in text for word in words) or any(word.lower() in raw_l for word in words):
            return key
    if hint:
        hint_l = hint.lower()
        for key, words in TYPE_KEYWORDS:
            if hint_l in {key, TYPE_LABEL[key].lower()} or any(w.lower() in hint_l for w in words):
                return key
    return ""


def _flatten(node: Any, hint: str = "") -> list[dict]:
    """把任意 JSON 结构摊平成 [dict, ...]，顺带记下容器名作为类型提示（如 {"dividends": [...]}）。"""
    out: list[dict] = []
    if isinstance(node, list):
        for item in node:
            out.extend(_flatten(item, hint))
    elif isinstance(node, dict):
        dict_values = [v for v in node.values() if isinstance(v, (list, dict))]
        looks_like_row = _norm_code(_pick(node, "code")) != "" and len(node) <= 40
        if looks_like_row:
            row = dict(node)
            if hint:
                row["__hint__"] = hint
            out.append(row)
        elif dict_values:
            for key, value in node.items():
                # 日期分组的字典也走这里，key 不会是类型，无副作用
                out.extend(_flatten(value, hint or str(key)))
    return out


def _load_files(paths: list[Path]) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    used: list[str] = []
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"   ✗ 跳过 {path.name}：{exc}")
            continue
        found = _flatten(raw)
        if found:
            used.append(path.name)
            rows.extend(found)
    return rows, used


# ---------------------------------------------------------------- 归一化
def to_event(row: dict, amount_unit: str = "wan") -> dict | None:
    code = _norm_code(_pick(row, "code"))
    if not code:
        return None
    hint = str(row.get("__hint__") or "")
    etype = _infer_type(row, hint)
    if not etype:
        return None

    name = str(_pick(row, "name") or "").strip() or code
    party = str(_pick(row, "party") or "").strip()
    note = str(_pick(row, "note") or "").strip()

    shares = _to_float(_pick(row, "shares"))
    amount = _to_amount(_pick(row, "amount"), amount_unit)

    price = _to_float(_pick(row, "price"))
    ratio = _to_float(_pick(row, "ratio"))
    yield_val = _to_float(_pick(row, "dividendYield"))
    if yield_val is None and etype == "dividend" and ratio is not None:
        yield_val = ratio
    if yield_val is not None and 0 < yield_val < 1:
        yield_val = round(yield_val * 100, 4)  # 小数 → 百分数

    announce = _norm_date(_pick(row, "announceDate")) or dt.date.today().isoformat()
    start = _norm_date(_pick(row, "startDate"))
    end = _norm_date(_pick(row, "endDate"))

    if etype in {"increase", "decrease"}:
        default_party = "股东"
        ratio_label = "占总股本%"
    elif etype == "repurchase":
        default_party = "上市公司回购"
        ratio_label = "占总股本%"
    elif etype == "dividend":
        default_party = note or str(_pick(row, "qtyText") or "分红方案")
        ratio_label = "股息率%"
    else:
        default_party = "定增认购方"
        ratio_label = "占总股本%"

    digest = hashlib.md5(
        f"{etype}|{code}|{announce}|{party}|{shares}|{amount}".encode("utf-8")
    ).hexdigest()[:10]

    event = {
        "id": f"ext-{etype}-{code}-{digest}",
        "type": etype,
        "code": code,
        "name": name,
        "board": board_of(code),
        "party": party or default_party,
        "partyKind": "公司" if etype in {"repurchase", "dividend"} else "机构股东",
        "shares": abs(shares) if shares is not None else None,
        "ratio": ratio,
        "ratioLabel": ratio_label,
        "amount": abs(amount) if amount is not None else None,
        "amountEstimated": amount is None and shares is not None and price is not None,
        "price": price,
        "changePct": _to_float(_pick(row, "changePct")),
        "startDate": start,
        "endDate": end,
        "announceDate": announce,
        "status": str(_pick(row, "status") or "外部数据"),
        "method": str(_pick(row, "method") or ""),
        "source": "外部项目",
        "external": True,
    }
    if amount is None and event["shares"] and price:
        event["amount"] = round(event["shares"] * price / 1e4, 2)
    if etype == "dividend":
        event["dividendYield"] = yield_val
        event["qtyText"] = note or str(_pick(row, "qtyText") or "")
    if note and etype != "dividend":
        event["note"] = note[:120]
    return event


# ---------------------------------------------------------------- 合并写回
def load_extra_events(amount_unit: str = "wan") -> tuple[list[dict], list[str]]:
    """供 fetch_data.py 调用：读取 data/extra/ 下全部 JSON 并归一化。"""
    if not EXTRA_DIR.exists():
        return [], []
    files = sorted(p for p in EXTRA_DIR.glob("*.json") if p.is_file())
    if not files:
        return [], []
    rows, used = _load_files(files)
    events = [ev for ev in (to_event(r, amount_unit) for r in rows) if ev]
    return events, used


def merge_into_payload(extra: list[dict], sources_used: list[str]) -> dict:
    from fetch_data import DATA_DIR, load_previous, summarize, write_payload  # noqa: PLC0415

    payload = load_previous()
    if not payload:
        raise SystemExit("没有 data/latest.json，请先跑 python scripts/fetch_data.py")

    existing = {e["id"] for e in payload["events"]}
    added = [e for e in extra if e["id"] not in existing]
    events = payload["events"] + added
    events.sort(key=lambda e: (e.get("announceDate") or "", e.get("amount") or 0), reverse=True)

    payload["events"] = events
    payload["stats"] = summarize(events)
    payload["sources"] = payload.get("sources", []) + [
        {
            "name": "外部项目",
            "status": "ok" if added else "skipped",
            "count": len(added),
            "message": f"{'、'.join(sources_used)} 合并 {len(added)} 条（去重后）",
        }
    ]
    payload["generatedAt"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    write_payload(payload)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return {"added": len(added), "total": len(events), "skipped": len(extra) - len(added)}


def main() -> int:
    parser = argparse.ArgumentParser(description="把外部 JSON 并入事件表")
    parser.add_argument("--path", nargs="*", help="文件或目录，默认 data/extra/")
    parser.add_argument("--amount-unit", default="wan", choices=["wan", "yuan", "auto"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    targets: list[Path] = []
    if args.path:
        for p in args.path:
            path = Path(p)
            targets.extend(sorted(path.glob("*.json")) if path.is_dir() else [path])
    elif EXTRA_DIR.exists():
        targets = sorted(EXTRA_DIR.glob("*.json"))

    if not targets:
        print(f"data/extra/ 下没有 JSON 文件。把旧项目的输出（如 ledger.json）复制进去再运行：")
        print(f"  {EXTRA_DIR}")
        return 0

    rows, used = _load_files(targets)
    events = [ev for ev in (to_event(r, args.amount_unit) for r in rows) if ev]
    print(f"读取 {len(used)} 个文件，识别 {len(rows)} 行 → 归一化 {len(events)} 条事件")
    print(f"  来源：{'、'.join(used)}")
    for key in ("increase", "decrease", "placement", "repurchase", "dividend"):
        subset = [e for e in events if e["type"] == key]
        if subset:
            amount = sum(e.get("amount") or 0 for e in subset)
            print(f"  {TYPE_LABEL[key]:<3} {len(subset):>4} 条  金额 {amount:>12,.0f} 万元")
    for e in events[:5]:
        print(f"   · {e['announceDate']} {e['code']} {e['name']} {TYPE_LABEL[e['type']]} {e['party']}")

    if args.dry_run:
        print("dry-run：未写入。")
        return 0

    result = merge_into_payload(events, used)
    print(f"✅ 合并完成：新增 {result['added']} 条（重复 {result['skipped']}），表内共 {result['total']} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
