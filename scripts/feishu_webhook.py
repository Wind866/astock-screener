#!/usr/bin/env python3
"""飞书自定义机器人统一发送层：加签 / 重试 / 业务码校验（零第三方依赖）。

移植自 BIGApush 的 utils/feishu_webhook.py，同样是纯标准库实现。三个关键点：

1. **加签**：机器人开启「加签」后，不带 timestamp/sign 的请求会被拒（业务码 19021），
   但 HTTP 状态仍是 200 —— 只看 HTTP 会误判成功。
2. **业务码校验**：飞书返回 ``{"code":19021}`` 必须判失败，否则告警会在最需要它的时候静默哑掉。
3. **网络重试**：飞书偶发 502 / 连接重置，重试 2 次可救回大半。

环境变量约定（与 BIGApush 保持一致，同一个机器人可直接复用凭据）：
    FEISHU_WEBHOOK / FEISHU_SECRET   业务机器人
    ALERT_WEBHOOK  / ALERT_SECRET    独立告警机器人（配置后优先用于告警）
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

__all__ = [
    "gen_sign", "sign_payload", "post_json", "response_ok",
    "send_text", "send_payload", "resolve_credentials", "alert_text",
    "describe_rejection", "SIGN_HINT",
]

# 飞书自定义机器人业务码：0 / 缺失 视为成功；19021 加签失败；19024 关键词校验失败
SIGN_ERROR_CODE = 19021
KEYWORD_ERROR_CODE = 19024
SIGN_HINT = "19021 = 机器人开启了加签，但 FEISHU_SECRET / ALERT_SECRET 为空或不对"


def gen_sign(secret: str, timestamp: str) -> str:
    """飞书官方加签算法：HMAC-SHA256(key=f'{ts}\\n{secret}', msg=b'') → base64。"""
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def sign_payload(payload: dict, secret: str) -> dict:
    """返回带签名的新 payload；secret 为空时原样返回副本（机器人未开加签）。"""
    out = dict(payload)
    secret = (secret or "").strip()
    if secret:
        ts = str(int(time.time()))
        out["timestamp"] = ts
        out["sign"] = gen_sign(secret, ts)
    return out


def response_ok(result: Any) -> bool:
    """飞书响应是否真正受理。HTTP 200 不代表成功。"""
    if not isinstance(result, dict):
        return False
    code = result.get("code", result.get("StatusCode"))
    return code in (0, None)


def describe_rejection(result: Any) -> str:
    """把飞书业务码翻成能直接照做的提示；非加签/关键词错误返回空串。"""
    if not isinstance(result, dict):
        return ""
    code = result.get("code", result.get("StatusCode"))
    if code in (SIGN_ERROR_CODE, str(SIGN_ERROR_CODE)):
        return f"（{SIGN_HINT}）"
    if code in (KEYWORD_ERROR_CODE, str(KEYWORD_ERROR_CODE)):
        return "（19024 = 机器人开了「自定义关键词」校验，消息里没命中关键词）"
    return ""


def post_json(webhook: str, payload: dict, secret: str = "", timeout: float = 12, attempts: int = 2) -> dict:
    """POST 一个 JSON 并解析响应。

    - 网络异常 / 429 / 5xx：重试 ``attempts`` 次
    - 4xx（非 429）：立即抛错，重试无意义
    - 业务错误（HTTP 200 但 code != 0）：不重试，原样返回给调用方判断
    """
    webhook = (webhook or "").strip()
    if not webhook:
        raise ValueError("webhook 为空")
    body = json.dumps(sign_payload(payload, secret), ensure_ascii=False).encode("utf-8")
    last: Exception | None = None
    for i in range(max(1, attempts)):
        req = urllib.request.Request(
            webhook,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code != 429:
                raise
            last = exc
        except Exception as exc:  # noqa: BLE001 - 网络抖动统一重试
            last = exc
        if i + 1 < attempts:
            time.sleep(1.5 * (i + 1))
    assert last is not None
    raise last


def send_payload(payload: dict, webhook: str = "", secret: str = "", alert: bool = False, **kw) -> dict:
    """按需解析凭据后发送，返回飞书原始响应（调用方用 response_ok 判断）。"""
    hook, sec = resolve_credentials(alert=alert, webhook=webhook, secret=secret)
    return post_json(hook, payload, sec, **kw)


def send_text(text: str, webhook: str = "", secret: str = "", alert: bool = False, **kw) -> dict:
    return send_payload({"msg_type": "text", "content": {"text": text}}, webhook, secret, alert, **kw)


def alert_text(text: str) -> dict:
    """发到独立告警机器人；没配 ALERT_WEBHOOK 时回落业务机器人。"""
    return send_text(text, alert=True)


def resolve_credentials(alert: bool = False, webhook: str = "", secret: str = "") -> tuple[str, str]:
    """解析 webhook/secret：显式参数 > 告警机器人（仅 alert）> 业务机器人 > BIGA 兼容变量。"""
    if webhook:
        return webhook.strip(), (secret or "").strip()
    if alert:
        hook = os.environ.get("ALERT_WEBHOOK", "").strip()
        if hook:
            return hook, (os.environ.get("ALERT_SECRET") or os.environ.get("FEISHU_SECRET") or "").strip()
    return (
        os.environ.get("FEISHU_WEBHOOK", "").strip(),
        (os.environ.get("FEISHU_SECRET") or "").strip(),
    )
