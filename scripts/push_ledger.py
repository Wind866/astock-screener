#!/usr/bin/env python3
"""推送幂等台账：同一档期只推一次，多档 cron 兜底不刷屏。

GitHub 的 schedule 实测会延迟 4h 以上、偶有整档丢弃，所以每个业务档位都铺多个
cron 时间点兜底。代价是「补档」会重复推送同一个档期 —— 台账就是干这个的：
按 ``workflow + edition + slot`` 判重，推成功了才记账（失败不记，留给下一档重试）。

台账格式对齐 BIGApush 的 ``.push-state/ledger.json``，两个仓库看起来是同一套东西。

用法：
    python scripts/push_ledger.py --check  --workflow daily.yml --slot 16   # 判断是否该推
    python scripts/push_ledger.py --record --workflow daily.yml --slot 16   # 推成功后记账
    python scripts/push_ledger.py --show                                     # 查看台账
    python scripts/push_ledger.py --check ... --force                        # 强制视为该推

``--check`` 会输出 ``should_push=true|false``，若检测到 ``$GITHUB_OUTPUT`` 会同时写入该变量，
workflow 里可直接 ``if: steps.ledger.outputs.should_push == 'true'``。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / ".push-state" / "ledger.json"


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def load() -> dict:
    if not LEDGER.exists():
        return {"version": 1, "updated_at": "", "records": []}
    try:
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "updated_at": "", "records": []}
    data.setdefault("records", [])
    return data


def save(data: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now()
    data["records"] = data["records"][-200:]  # 只留最近 200 条，避免无限膨胀
    LEDGER.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find(workflow: str, edition: str, slot: str) -> dict | None:
    for rec in load()["records"]:
        if rec.get("workflow") == workflow and rec.get("edition") == edition and str(rec.get("slot", "")) == str(slot):
            return rec
    return None


def record(workflow: str, edition: str, slot: str, run_id: str = "", note: str = "") -> dict:
    data = load()
    rec = {
        "workflow": workflow,
        "edition": edition,
        "slot": str(slot),
        "run_id": run_id or os.environ.get("GITHUB_RUN_ID", ""),
        "ts": _now(),
    }
    if note:
        rec["note"] = note
    data["records"] = [r for r in data["records"] if not (
        r.get("workflow") == workflow and r.get("edition") == edition and str(r.get("slot", "")) == str(slot)
    )]
    data["records"].append(rec)
    save(data)
    return rec


def _emit(should_push: bool, reason: str, edition: str) -> None:
    print(f"[ledger] {reason} · edition={edition} · should_push={'true' if should_push else 'false'}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        try:
            with open(out, "a", encoding="utf-8") as fp:
                fp.write(f"should_push={'true' if should_push else 'false'}\n")
                fp.write(f"edition={edition}\n")
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="推送幂等台账")
    parser.add_argument("--check", action="store_true", help="判断该档期是否该推送")
    parser.add_argument("--record", action="store_true", help="记录一次成功推送")
    parser.add_argument("--show", action="store_true", help="打印台账")
    parser.add_argument("--workflow", default="daily.yml")
    parser.add_argument("--slot", default="16", help="档期小时，如 16（收盘后）")
    parser.add_argument("--edition", default="", help="档期日期，默认今天")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--note", default="")
    parser.add_argument("--force", action="store_true", help="强制视为该推 / 强制记账")
    args = parser.parse_args()

    edition = args.edition or dt.date.today().isoformat()

    if args.show:
        data = load()
        print(f"台账：{LEDGER}（{len(data['records'])} 条，更新于 {data.get('updated_at') or '—'}）")
        for rec in data["records"][-12:]:
            print(f"  {rec.get('ts')}  {rec.get('workflow')}  {rec.get('edition')}  slot={rec.get('slot')}  run={rec.get('run_id')}")
        return 0

    if args.record:
        rec = record(args.workflow, edition, args.slot, args.run_id, args.note)
        print(f"[ledger] 已记账：{rec}")
        return 0

    if args.check:
        if args.force:
            _emit(True, "FORCE 强制推送", edition)
            return 0
        hit = find(args.workflow, edition, args.slot)
        if hit:
            _emit(False, f"本档期已推过（{hit.get('ts')} / run {hit.get('run_id') or '—'}）", edition)
        else:
            _emit(True, "本档期未推送", edition)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
