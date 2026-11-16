"""CI 守护测试：webhook 泄露扫描 + 数据/归一化回归。

跑法（零第三方依赖，不需要 pytest）：
    python -m unittest discover -s tests -v

借鉴 BIGApush 的 tests/test_smoke.py::test_no_real_webhook_committed：
公开仓库里一旦提交真实 webhook，任何人拿到都能往你的群里发消息，而且爬虫抓得很快。
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

WEBHOOK_RE = re.compile(r"https://open\.feishu\.cn/open-apis/bot/v2/hook/[0-9a-zA-Z\-]{8,}")
PLACEHOLDER_HINTS = ("xxxx", "your", "example", "placeholder", "<", "***")

SKIP_DIRS = {".git", "__pycache__", ".cache", ".venv", "venv", "node_modules"}


def _iter_files() -> list[Path]:
    out = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in {".png", ".jpg", ".zip", ".db", ".pyc"}:
            continue
        out.append(path)
    return out


class TestNoRealWebhook(unittest.TestCase):
    def test_no_real_webhook_committed(self):
        hits = []
        for path in _iter_files():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in WEBHOOK_RE.findall(text):
                token = match.rsplit("/", 1)[-1].lower()
                if any(hint in token for hint in PLACEHOLDER_HINTS):
                    continue  # 文档里的占位符
                hits.append(f"{path.relative_to(ROOT)}: {match}")
        self.assertEqual(hits, [], "检测到疑似真实飞书 webhook，请立刻重置机器人并改用 Secrets：\n" + "\n".join(hits))


class TestDataShape(unittest.TestCase):
    def test_latest_payload(self):
        path = ROOT / "data" / "latest.json"
        if not path.exists():
            self.skipTest("data/latest.json 尚未生成")
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in ("generatedAt", "tradeDate", "stats", "events"):
            self.assertIn(key, data)
        self.assertIsInstance(data["events"], list)
        required = {"id", "type", "code", "name", "announceDate", "source"}
        for event in data["events"][:200]:
            self.assertLessEqual(required, set(event), f"事件缺字段：{event.get('id')}")
            self.assertEqual(len(event["code"]), 6, f"代码格式异常：{event}")
            self.assertIn(event["type"], {"increase", "decrease", "placement", "repurchase", "dividend"})

    def test_event_ids_unique(self):
        path = ROOT / "data" / "latest.json"
        if not path.exists():
            self.skipTest("data/latest.json 尚未生成")
        events = json.loads(path.read_text(encoding="utf-8"))["events"]
        ids = [e["id"] for e in events]
        self.assertEqual(len(ids), len(set(ids)), "事件 id 有重复，去重逻辑失效")

    def test_latest_js_matches_json(self):
        js = ROOT / "data" / "latest.js"
        if not js.exists():
            self.skipTest("data/latest.js 尚未生成")
        text = js.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("window.ASTOCK_DATA = "), "latest.js 格式不对，file:// 打开会失败")


class TestMergeExtra(unittest.TestCase):
    """外部数据归一化回归：这是接旧项目数据的入口，字段映射错了会静默丢数据。"""

    def test_field_aliases(self):
        import merge_extra  # noqa: PLC0415

        row = {
            "股票代码": "600519",
            "股票简称": "贵州茅台",
            "股东名称": "某集团",
            "变动数量": 120000,
            "变动金额": "3.5亿元",
            "公告日期": "20261113",
            "行动": "增持",
        }
        event = merge_extra.to_event(row)
        self.assertIsNotNone(event)
        self.assertEqual(event["type"], "increase")
        self.assertEqual(event["code"], "600519")
        self.assertEqual(event["announceDate"], "2026-11-13")
        self.assertAlmostEqual(event["amount"], 35000.0, places=2)  # 3.5 亿元 = 35000 万元

    def test_type_inference_and_skip(self):
        import merge_extra  # noqa: PLC0415

        self.assertEqual(merge_extra.to_event({"code": "002594", "name": "比亚迪", "type": "回购"})["type"], "repurchase")
        self.assertEqual(merge_extra.to_event({"code": "601398", "name": "工行", "type": "分红"})["type"], "dividend")
        self.assertIsNone(merge_extra.to_event({"name": "没有代码"}), "无股票代码的行应被忽略")

    def test_dividend_yield_normalized(self):
        import merge_extra  # noqa: PLC0415

        event = merge_extra.to_event({"code": "601398", "name": "工行", "type": "分红", "股息率": 0.0287})
        self.assertAlmostEqual(event["dividendYield"], 2.87, places=2)


class TestFeishuLayer(unittest.TestCase):
    def test_signature(self):
        import feishu_webhook  # noqa: PLC0415

        payload = {"msg_type": "text", "content": {"text": "hi"}}
        unsigned = feishu_webhook.sign_payload(payload, "")
        self.assertNotIn("sign", unsigned)
        signed = feishu_webhook.sign_payload(payload, "secret")
        self.assertIn("sign", signed)
        self.assertIn("timestamp", signed)

    def test_response_ok(self):
        import feishu_webhook  # noqa: PLC0415

        self.assertTrue(feishu_webhook.response_ok({"code": 0}))
        self.assertFalse(feishu_webhook.response_ok({"code": 19021}), "19021 必须判失败，否则告警静默")
        self.assertTrue("19021" in feishu_webhook.describe_rejection({"code": 19021}))


class TestWorkflows(unittest.TestCase):
    """工作流写坏了只会在 GitHub 上才报错，本地先拦一道。"""

    def test_workflows_parse(self):
        try:
            import yaml  # noqa: PLC0415
        except ImportError:
            self.skipTest("未安装 pyyaml")
        files = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        self.assertTrue(files, "没有找到工作流文件")
        for path in files:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertIn("jobs", data, f"{path.name} 缺少 jobs")
            for job in data["jobs"].values():
                self.assertTrue(job.get("steps"), f"{path.name} 有 job 没有 steps")

    def test_daily_has_fallback_slots(self):
        try:
            import yaml  # noqa: PLC0415
        except ImportError:
            self.skipTest("未安装 pyyaml")
        data = yaml.safe_load((ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8"))
        crons = [item["cron"] for item in data[True]["schedule"]]
        self.assertGreaterEqual(len(crons), 3, "兜底档太少：GitHub cron 延迟 4h+ 时会漏推")
        names = [step.get("name", "") for step in data["jobs"]["collect"]["steps"]]
        self.assertIn("台账判重（同档期只推一次）", names)
        self.assertIn("失败告警", names)


if __name__ == "__main__":
    unittest.main()
