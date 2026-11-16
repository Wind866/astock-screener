"""A 股事件数据采集。

三类事件统一归一化为同一套字段，供前端筛选与飞书推送共用：

    holder       股东增减持（东方财富-高管持股-股东增减持）
    placement    定增 / 增发（东方财富-新股数据-全部增发）
    repurchase   股票回购（东方财富-股票回购）

设计原则：
1. 所有取数都包在 try/except 里，单个数据源失败不影响其它数据源；
2. 列名用"关键词模糊匹配"而不是硬编码，接口改版时能自动适配或优雅降级；
3. 数值统一换算为：股数(股)、金额(万元)、比例(%)。
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import re
from typing import Any

LOG = logging.getLogger("collectors")

TYPE_LABEL = {
    "increase": "增持",
    "decrease": "减持",
    "placement": "定增",
    "repurchase": "回购",
    "dividend": "分红",
}


# ---------------------------------------------------------------- 基础工具


def _ak():
    """延迟导入 akshare，便于在没有安装依赖时也能 import 本模块做单元测试。"""
    import akshare as ak  # noqa: PLC0415

    return ak


def _to_float(value: Any) -> float | None:
    """把 '1.23万' / '4.5%' / '--' / NaN 这类脏数据转成 float。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    text = str(value).strip().replace(",", "").replace("，", "")
    if text in {"", "-", "--", "—", "None", "nan", "NaN", "null"}:
        return None
    multiplier = 1.0
    if text.endswith("万"):
        multiplier, text = 1e4, text[:-1]
    elif text.endswith("亿"):
        multiplier, text = 1e8, text[:-1]
    elif text.endswith("%"):
        text = text[:-1]
    text = re.sub(r"[^\d.\-]", "", text)
    if text in {"", "-", "."}:
        return None
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _to_date(value: Any) -> str:
    """统一输出 YYYY-MM-DD，失败返回空串。"""
    if value is None:
        return ""
    text = str(value).strip()
    if text in {"", "-", "--", "NaT", "None", "nan"}:
        return ""
    match = re.match(r"(\d{4})[-/年]?(\d{1,2})[-/月]?(\d{1,2})", text)
    if not match:
        return ""
    year, month, day = match.groups()
    try:
        return dt.date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return ""


def _clean_code(value: Any) -> str:
    match = re.search(r"(\d{6})", str(value))
    return match.group(1) if match else ""


def board_of(code: str) -> str:
    if not code:
        return "其他"
    if code.startswith(("688", "689")):
        return "科创板"
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith(("600", "601", "603", "605")):
        return "沪市主板"
    if code.startswith(("000", "001", "002", "003")):
        return "深市主板"
    if code.startswith(("8", "4", "920")):
        return "北交所"
    return "其他"


def market_prefix(code: str) -> str:
    if code.startswith("6"):
        return "sh"
    if code.startswith(("0", "3")):
        return "sz"
    if code.startswith(("4", "8", "9")):
        return "bj"
    return "sh"


def _party_kind(name: str) -> str:
    """粗分股东类型，用于前端二次筛选。"""
    text = name or ""
    if any(key in text for key in ("有限公司", "集团", "控股", "投资", "基金", "资产管理", "合伙", "信托", "证券")):
        return "机构股东"
    if any(key in text for key in ("Limited", "Ltd", "Holding", "Capital", "Investment", "Fund", "Asset", "Inc", "Co.", "Company")):
        return "机构股东"
    if len(text) <= 4 and not any(key in text for key in ("公司", "银行", "大学")):
        return "个人股东"
    return "其他"


def _flatten_columns(df):
    """把东方财富常见的多级表头（如 ('持股变动信息','变动数量')）压平成 '持股变动信息-变动数量'。"""
    columns = []
    for col in df.columns:
        if isinstance(col, tuple):
            parts = [str(part).strip() for part in col if str(part).strip() and not str(part).startswith("Unnamed")]
            columns.append("-".join(parts))
        else:
            columns.append(str(col).strip())
    out = df.copy()
    out.columns = columns
    return out


def _pick(columns: list[str], *keywords: str, exclude: tuple[str, ...] = ()) -> str | None:
    """按关键词顺序找列：先找同时包含全部关键词的列，找不到再退化到首个关键词。"""
    for keyword in keywords:
        for col in columns:
            if all(k in col for k in keyword.split("&")) and not any(e in col for e in exclude):
                return col
    return None


def _cell(row, columns: list[str], *keywords: str, exclude: tuple[str, ...] = ()) -> Any:
    col = _pick(columns, *keywords, exclude=exclude)
    return row.get(col) if col else None


# ---------------------------------------------------------------- 采集器


def collect_holder_changes(days: int = 90) -> tuple[list[dict], str]:
    """股东增减持：ak.stock_ggcg_em(symbol='全部')。"""
    ak = _ak()
    raw = ak.stock_ggcg_em(symbol="全部")
    df = _flatten_columns(raw)
    columns = list(df.columns)

    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    events: list[dict] = []

    for _, row in df.iterrows():
        code = _clean_code(_cell(row, columns, "代码&code", "代码"))
        if not code:
            continue
        announce = _to_date(_cell(row, columns, "公告日"))
        end_date = _to_date(_cell(row, columns, "变动截止日"))
        start_date = _to_date(_cell(row, columns, "变动开始日"))
        effective = announce or end_date or start_date
        if effective and effective < cutoff:
            continue

        direction_raw = str(_cell(row, columns, "增减") or "")
        shares_wan = _to_float(_cell(row, columns, "变动数量"))
        if shares_wan is None:
            shares_wan = _to_float(_cell(row, columns, "变动股数"))
        if shares_wan is None:
            continue
        shares = shares_wan * 1e4  # 单位：万股 -> 股

        direction = "increase" if ("增" in direction_raw or shares > 0) else "decrease"
        if "减" in direction_raw:
            direction = "decrease"

        price = _to_float(_cell(row, columns, "最新价"))
        amount = abs(shares) * price / 1e4 if price else None  # 万元

        party = str(_cell(row, columns, "股东名称") or "").strip()
        events.append(
            {
                "id": f"{direction}-{code}-{effective}-{party}-{int(shares)}",
                "type": direction,
                "code": code,
                "name": str(_cell(row, columns, "名称&name", "名称") or "").strip(),
                "board": board_of(code),
                "party": party or "—",
                "partyKind": _party_kind(party),
                "shares": abs(shares),
                "ratio": _to_float(_cell(row, columns, "占总股本比例", exclude=("变动后",))),
                "ratioLabel": "占总股本%",
                "amount": abs(amount) if amount is not None else None,
                "amountEstimated": True,
                "price": price,
                "changePct": _to_float(_cell(row, columns, "涨跌幅")),
                "startDate": start_date,
                "endDate": end_date,
                "announceDate": announce or end_date or start_date,
                "status": "已公告",
                "method": "集中竞价/大宗交易",
                "source": "东方财富·股东增减持",
            }
        )

    return events, f"{len(events)} 条（近 {days} 天）"


def collect_repurchases(days: int = 90) -> tuple[list[dict], str]:
    """股票回购：ak.stock_repurchase_em()。"""
    ak = _ak()
    df = _flatten_columns(ak.stock_repurchase_em())
    columns = list(df.columns)

    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    events: list[dict] = []

    for _, row in df.iterrows():
        code = _clean_code(_cell(row, columns, "股票代码", "代码"))
        if not code:
            continue
        announce = _to_date(_cell(row, columns, "最新公告日期", "公告日期", "公告日"))
        start_date = _to_date(_cell(row, columns, "回购起始时间", "起始时间"))
        effective = announce or start_date
        if effective and effective < cutoff:
            continue

        shares = _to_float(_cell(row, columns, "已回购股份数量"))
        amount_yuan = _to_float(_cell(row, columns, "已回购金额"))
        plan_low = _to_float(_cell(row, columns, "计划回购金额区间-下限"))
        plan_high = _to_float(_cell(row, columns, "计划回购金额区间-上限"))
        if amount_yuan is None and plan_high is None:
            continue

        amount_wan = amount_yuan / 1e4 if amount_yuan else (plan_high / 1e4 if plan_high else None)
        events.append(
            {
                "id": f"repurchase-{code}-{effective}",
                "type": "repurchase",
                "code": code,
                "name": str(_cell(row, columns, "股票简称", "名称") or "").strip(),
                "board": board_of(code),
                "party": "上市公司回购",
                "partyKind": "公司",
                "shares": shares,
                "ratio": _to_float(_cell(row, columns, "占公告前一日总股本比例-上限")),
                "ratioLabel": "占总股本%",
                "amount": amount_wan,
                "amountEstimated": amount_yuan is None,
                "price": _to_float(_cell(row, columns, "最新价")),
                "changePct": None,
                "startDate": start_date,
                "endDate": "",
                "announceDate": effective,
                "status": str(_cell(row, columns, "实施进度") or "进行中").strip(),
                "priceLow": _to_float(_cell(row, columns, "已回购股份价格区间-下限")),
                "priceHigh": _to_float(_cell(row, columns, "已回购股份价格区间-上限")),
                "planAmountLow": plan_low / 1e4 if plan_low else None,
                "planAmountHigh": plan_high / 1e4 if plan_high else None,
                "method": "二级市场回购",
                "source": "东方财富·股票回购",
            }
        )

    return events, f"{len(events)} 条（近 {days} 天）"


def collect_placements(days: int = 90) -> tuple[list[dict], str]:
    """定增 / 增发：ak.stock_qbzf_em()。"""
    ak = _ak()
    df = _flatten_columns(ak.stock_qbzf_em())
    columns = list(df.columns)
    LOG.info("增发明细列名: %s", columns)

    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    events: list[dict] = []

    for _, row in df.iterrows():
        code = _clean_code(_cell(row, columns, "股票代码", "代码"))
        if not code:
            continue
        issue_date = _to_date(_cell(row, columns, "发行日期", "上市日期", "增发上市日"))
        if issue_date and issue_date < cutoff:
            continue

        price = _to_float(_cell(row, columns, "增发价格", "发行价格"))
        shares_raw = _to_float(_cell(row, columns, "增发数量", "发行数量", "发行总数", "增发总数"))
        if shares_raw is None:
            continue
        # 增发数量单位可能是"万股"也可能是"股"，按数量级判断
        shares = shares_raw * 1e4 if shares_raw < 1e6 else shares_raw
        if shares <= 0:
            shares = abs(shares)

        # 募集资金字段不同来源单位不一（元/万元/亿元），按量级判断
        amount_wan = None
        raised = _to_float(_cell(row, columns, "募集资金", "实际募资", "募资总额"))
        if raised is not None:
            if raised >= 1e6:  # 单位：元
                amount_wan = raised / 1e4
            elif raised >= 100:  # 单位：万元
                amount_wan = raised
            else:  # 单位：亿元
                amount_wan = raised * 1e4
        if amount_wan is None and price:
            amount_wan = shares * price / 1e4  # 万元

        method = str(_cell(row, columns, "发行方式") or "定向增发").strip()
        events.append(
            {
                "id": f"placement-{code}-{issue_date}-{int(shares)}",
                "type": "placement",
                "code": code,
                "name": str(_cell(row, columns, "股票名称", "股票简称", "名称") or "").strip(),
                "board": board_of(code),
                "party": str(_cell(row, columns, "发行对象") or "定增认购方").strip() or "定增认购方",
                "partyKind": "机构股东",
                "shares": shares,
                "ratio": None,
                "ratioLabel": "占总股本%",
                "amount": amount_wan,
                "amountEstimated": False,
                "price": price,
                "changePct": None,
                "startDate": issue_date,
                "endDate": "",
                "announceDate": issue_date,
                "status": "已发行",
                "method": method or "定向增发",
                "lockup": _to_float(_cell(row, columns, "锁定期")),
                "source": "东方财富·增发",
            }
        )

    return events, f"{len(events)} 条（近 {days} 天）"


# ---------------------------------------------------------------- 分红


def _recent_report_dates(count: int = 5) -> list[str]:
    """最近若干个报告期（0331/0630/0930/1231），按时间倒序。"""
    today = dt.date.today()
    dates: list[str] = []
    year, quarter = today.year, (today.month - 1) // 3
    for _ in range(count):
        year, quarter = (year, quarter - 1) if quarter > 0 else (year - 1, 3)
        month_day = {0: "0331", 1: "0630", 2: "0930", 3: "1231"}[quarter]
        dates.append(f"{year}{month_day}")
    return dates


def collect_dividends(days: int = 90) -> tuple[list[dict], str]:
    """分红送配：ak.stock_fhps_em(date=报告期)，按最近几个报告期合并。"""
    ak = _ak()
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    today = dt.date.today().isoformat()
    events: list[dict] = []
    used: list[str] = []

    for report_date in _recent_report_dates(5):
        try:
            raw = ak.stock_fhps_em(date=report_date)
        except Exception as exc:  # noqa: BLE001
            LOG.info("分红报告期 %s 获取失败: %s", report_date, exc)
            continue
        if raw is None or len(raw) == 0:
            continue
        used.append(report_date)
        df = _flatten_columns(raw)
        columns = list(df.columns)

        for _, row in df.iterrows():
            code = _clean_code(_cell(row, columns, "代码&code", "代码"))
            if not code:
                continue
            announce = _to_date(_cell(row, columns, "最新公告日期", "预案公告日", "公告日期"))
            ex_date = _to_date(_cell(row, columns, "除权除息日"))
            record_date = _to_date(_cell(row, columns, "股权登记日"))
            if (announce and announce < cutoff) and (ex_date and ex_date < today):
                continue

            per_10 = _to_float(_cell(row, columns, "现金分红比例", "派息比例", "派现比例"))
            bonus = _to_float(_cell(row, columns, "送股比例", "送转总比例"))
            transfer = _to_float(_cell(row, columns, "转股比例"))
            total_share = _to_float(_cell(row, columns, "总股本"))
            yield_pct = _to_float(_cell(row, columns, "股息率"))
            if yield_pct is not None and yield_pct < 1:  # 接口返回小数（0.085 = 8.5%）
                yield_pct *= 100

            if per_10 is None and bonus is None and transfer is None:
                continue

            amount_wan = None
            if per_10 and total_share:
                amount_wan = per_10 / 10 * total_share / 1e4  # 万元

            plan_text = []
            if per_10:
                plan_text.append(f"10派{per_10:g}元")
            if bonus:
                plan_text.append(f"10送{bonus:g}股")
            if transfer:
                plan_text.append(f"10转{transfer:g}股")

            events.append(
                {
                    "id": f"dividend-{code}-{report_date}-{per_10}-{bonus}-{transfer}",
                    "type": "dividend",
                    "code": code,
                    "name": str(_cell(row, columns, "名称&name", "名称") or "").strip(),
                    "board": board_of(code),
                    "party": "／".join(plan_text) if plan_text else "分红方案",
                    "partyKind": "公司",
                    "shares": None,
                    "qtyText": "／".join(plan_text) if plan_text else "—",
                    "ratio": yield_pct,
                    "ratioLabel": "股息率%",
                    "amount": amount_wan,
                    "amountEstimated": amount_wan is not None,
                    "price": _to_float(_cell(row, columns, "最新价")),
                    "changePct": None,
                    "startDate": ex_date,
                    "endDate": "",
                    "announceDate": announce or ex_date or record_date,
                    "status": str(_cell(row, columns, "方案进度") or "预案").strip(),
                    "dividendPer10": per_10,
                    "bonusPer10": bonus,
                    "transferPer10": transfer,
                    "dividendYield": yield_pct,
                    "exDate": ex_date,
                    "recordDate": record_date,
                    "reportPeriod": report_date,
                    "method": "现金分红/送转",
                    "source": "东方财富·分红送配",
                }
            )

    LOG.info("分红使用报告期: %s", used)
    return events, f"{len(events)} 条（报告期 {','.join(used) or '无'}）"


# ---------------------------------------------------------------- 聚合


COLLECTORS = {
    "holder": collect_holder_changes,
    "placement": collect_placements,
    "repurchase": collect_repurchases,
    "dividend": collect_dividends,
}


def collect_all(config: dict) -> tuple[list[dict], list[dict]]:
    """按配置执行采集，返回 (events, source_status)。"""
    days = int(config.get("lookbackDays", 90))
    enabled = config.get("sources", {})
    events: list[dict] = []
    status: list[dict] = []

    for key, fn in COLLECTORS.items():
        name = {
            "holder": "股东增减持",
            "placement": "定增/增发",
            "repurchase": "股票回购",
            "dividend": "分红送配",
        }[key]
        if not enabled.get(key, True):
            status.append({"name": name, "status": "skipped", "count": 0, "message": "配置中已关闭"})
            continue
        try:
            items, message = fn(days=days)
        except Exception as exc:  # noqa: BLE001 - 数据源不稳定，必须降级而不是崩掉
            LOG.warning("采集 %s 失败: %s", name, exc)
            status.append({"name": name, "status": "error", "count": 0, "message": str(exc)[:200]})
            continue
        events.extend(items)
        status.append({"name": name, "status": "ok", "count": len(items), "message": message})

    # 按类型过滤最小金额
    min_amount = float(config.get("minAmountWan", 0) or 0)
    if min_amount > 0:
        events = [e for e in events if (e.get("amount") or 0) >= min_amount]

    return events, status
