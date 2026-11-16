"""离线演示数据：没有网络 / 未安装 akshare 时也能完整预览界面与筛选逻辑。"""

from __future__ import annotations

import datetime as dt
import random

STOCKS = [
    ("600519", "贵州茅台", 1520.00), ("000858", "五粮液", 138.60), ("601318", "中国平安", 52.30),
    ("600036", "招商银行", 38.90), ("002594", "比亚迪", 246.80), ("300750", "宁德时代", 198.40),
    ("601899", "紫金矿业", 17.85), ("600900", "长江电力", 27.60), ("000333", "美的集团", 68.20),
    ("002415", "海康威视", 31.40), ("688981", "中芯国际", 82.50), ("688111", "金山办公", 268.00),
    ("300059", "东方财富", 22.10), ("601012", "隆基绿能", 18.30), ("600276", "恒瑞医药", 48.70),
    ("000651", "格力电器", 41.20), ("601166", "兴业银行", 19.40), ("600030", "中信证券", 26.80),
    ("002230", "科大讯飞", 52.90), ("300124", "汇川技术", 62.30), ("688036", "传音控股", 96.40),
    ("603259", "药明康德", 58.10), ("601888", "中国中免", 68.50), ("000001", "平安银行", 11.20),
    ("600887", "伊利股份", 28.40), ("002714", "牧原股份", 44.60), ("601088", "中国神华", 39.80),
    ("600028", "中国石化", 6.35), ("601668", "中国建筑", 5.80), ("600585", "海螺水泥", 24.30),
    ("002352", "顺丰控股", 38.20), ("300760", "迈瑞医疗", 268.50), ("688012", "中微公司", 168.20),
    ("603501", "韦尔股份", 108.60), ("601127", "赛力斯", 92.40), ("000725", "京东方A", 4.32),
    ("600104", "上汽集团", 15.60), ("601633", "长城汽车", 25.80), ("002050", "三花智控", 26.40),
    ("600690", "海尔智家", 26.90), ("601398", "工商银行", 6.12), ("601288", "农业银行", 5.28),
    ("601988", "中国银行", 5.05), ("600016", "民生银行", 4.18), ("000002", "万科A", 7.85),
    ("600048", "保利发展", 9.20), ("601601", "中国太保", 32.40), ("601628", "中国人寿", 36.70),
    ("600309", "万华化学", 76.30), ("002466", "天齐锂业", 38.60), ("300274", "阳光电源", 78.40),
    ("688599", "天合光能", 20.30), ("601138", "工业富联", 24.80), ("002475", "立讯精密", 42.30),
    ("300308", "中际旭创", 128.40), ("688041", "海光信息", 132.60), ("603986", "兆易创新", 108.30),
    ("000568", "泸州老窖", 142.80), ("600809", "山西汾酒", 196.40), ("002304", "洋河股份", 82.30),
    ("600588", "用友网络", 12.40), ("601360", "三六零", 9.85), ("002271", "东方雨虹", 12.80),
]

HOLDERS = [
    "香港中央结算有限公司", "中国证券金融股份有限公司", "全国社保基金一一三组合",
    "招商银行股份有限公司-兴全合润混合型证券投资基金", "中国工商银行-上证50交易型开放式指数证券投资基金",
    "王建国", "李明", "张伟", "陈晓东", "中信证券股份有限公司", "国泰君安证券股份有限公司",
    "上海高毅资产管理合伙企业(有限合伙)", "深圳市创新投资集团有限公司", "先进制造产业投资基金(有限合伙)",
]

STATUS_HOLDER = ["实施中", "实施完成", "已完成"]
STATUS_REPO = ["董事会预案", "股东大会通过", "实施中", "已完成"]
STATUS_DIV = ["董事会预案", "股东大会通过", "实施"]


def board_of(code: str) -> str:
    if code.startswith(("688", "689")):
        return "科创板"
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith(("600", "601", "603", "605")):
        return "沪市主板"
    if code.startswith(("000", "001", "002", "003")):
        return "深市主板"
    return "北交所"


def build_demo_events(seed: int = 20261116, days: int = 70) -> list[dict]:
    rng = random.Random(seed)
    today = dt.date.today()
    events: list[dict] = []

    def day(offset_max: int) -> str:
        return (today - dt.timedelta(days=rng.randint(0, offset_max))).isoformat()

    # 股东增减持
    for _ in range(88):
        code, name, price = rng.choice(STOCKS)
        direction = "increase" if rng.random() < 0.42 else "decrease"
        # 先定金额量级，再按股价折算股数，避免高价股出现天量金额
        target_wan = rng.choice([rng.uniform(300, 5000), rng.uniform(5000, 50000), rng.uniform(50000, 200000)])
        shares = target_wan * 1e4 / price
        holder = rng.choice(HOLDERS)
        amount = round(shares * price / 1e4, 1)
        announce = day(days)
        events.append({
            "id": f"{direction}-{code}-{announce}-{holder}-{int(shares)}",
            "type": direction, "code": code, "name": name, "board": board_of(code),
            "party": holder,
            "partyKind": "机构股东" if any(k in holder for k in ("公司", "基金", "合伙", "组合")) else "个人股东",
            "shares": shares, "ratio": round(shares / 1e9 * 100, 3), "ratioLabel": "占总股本%",
            "amount": amount, "amountEstimated": True, "price": price,
            "changePct": round(rng.uniform(-6, 6), 2),
            "startDate": announce, "endDate": announce, "announceDate": announce,
            "status": rng.choice(STATUS_HOLDER), "method": rng.choice(["集中竞价", "大宗交易", "协议转让"]),
            "source": "演示数据",
        })

    # 定增
    for _ in range(26):
        code, name, price = rng.choice(STOCKS)
        issue = day(days)
        issue_price = round(price * rng.uniform(0.62, 0.92), 2)
        target_wan = rng.uniform(10000, 400000)  # 1 亿 ~ 40 亿
        shares = target_wan * 1e4 / issue_price
        events.append({
            "id": f"placement-{code}-{issue}-{int(shares)}",
            "type": "placement", "code": code, "name": name, "board": board_of(code),
            "party": rng.choice(["控股股东及一致行动人", "公募基金组合", "产业投资者", "境外机构投资者"]),
            "partyKind": "机构股东", "shares": shares, "ratio": round(shares / 1e9 * 100, 3),
            "ratioLabel": "占总股本%", "amount": round(shares * issue_price / 1e4, 1),
            "amountEstimated": False, "price": issue_price, "changePct": None,
            "startDate": issue, "endDate": "", "announceDate": issue, "status": "已发行",
            "premium": round((issue_price / price - 1) * 100, 2),
            "method": "定向增发", "source": "演示数据",
        })

    # 回购
    for _ in range(30):
        code, name, price = rng.choice(STOCKS)
        announce = day(days)
        plan_high = round(rng.uniform(2000, 90000), 1)
        done = round(plan_high * rng.uniform(0, 1), 1)
        events.append({
            "id": f"repurchase-{code}-{announce}",
            "type": "repurchase", "code": code, "name": name, "board": board_of(code),
            "party": "上市公司回购", "partyKind": "公司",
            "shares": int(done * 1e4 / price) if price else None, "ratio": round(rng.uniform(0.2, 3.2), 2),
            "ratioLabel": "占总股本%", "amount": done, "amountEstimated": False,
            "price": price, "changePct": round(rng.uniform(-5, 5), 2),
            "startDate": announce, "endDate": "", "announceDate": announce,
            "status": rng.choice(STATUS_REPO),
            "priceLow": round(price * 0.85, 2), "priceHigh": round(price * 1.05, 2),
            "planAmountLow": round(plan_high * 0.5, 1), "planAmountHigh": plan_high,
            "method": "二级市场回购", "source": "演示数据",
        })

    # 分红
    for _ in range(46):
        code, name, price = rng.choice(STOCKS)
        announce = day(days)
        yield_pct = rng.choice([0.6, 1.2, 1.8, 2.4, 3.0, 3.8, 5.2])
        per_10 = round(price * yield_pct / 100 * 10, 2)
        bonus = rng.choice([0, 0, 0, 0, 1, 2, 3])
        transfer = rng.choice([0, 0, 0, 0, 2, 4])
        # 用总市值反推股本，避免"高价股 + 巨股本"的失真组合
        market_cap = rng.uniform(3e9, 1e11)
        total_share = market_cap / price
        parts = [f"10派{per_10:g}元"]
        if bonus:
            parts.append(f"10送{bonus}股")
        if transfer:
            parts.append(f"10转{transfer}股")
        events.append({
            "id": f"dividend-{code}-{announce}-{per_10}",
            "type": "dividend", "code": code, "name": name, "board": board_of(code),
            "party": "／".join(parts), "partyKind": "公司", "shares": None, "qtyText": "／".join(parts),
            "ratio": yield_pct, "ratioLabel": "股息率%",
            "amount": round(per_10 / 10 * total_share / 1e4, 1), "amountEstimated": True,
            "price": price, "changePct": round(rng.uniform(-3, 3), 2),
            "startDate": announce, "endDate": "", "announceDate": announce,
            "status": rng.choice(STATUS_DIV),
            "dividendPer10": per_10, "bonusPer10": bonus, "transferPer10": transfer,
            "dividendYield": yield_pct, "exDate": announce, "recordDate": announce,
            "reportPeriod": "20260630", "method": "现金分红/送转", "source": "演示数据",
        })

    events.sort(key=lambda e: (e["announceDate"], e.get("amount") or 0), reverse=True)
    return events
