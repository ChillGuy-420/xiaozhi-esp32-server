"""Log patcher for isolated mode. Values are removed; they are not written."""

from __future__ import annotations

import re
import threading

_lock = threading.Lock()
_secrets: set[str] = set()
_active = False

_BEARER = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_HEADER_ASSIGN = re.compile(
    r"(?i)(authorization|device-credential|api_key|access_token|secret_key|mqtt_signature_key)"
    r"(\s*[:=]\s*)(\S+)"
)
_CONTENT_HINTS = (
    "识别文本",
    "大模型收到用户消息",
    "语音生成成功",
    "语音生成失败",
    "conn - Headers",
    "OTA请求头",
    "OTA请求数据",
    "LLM 处理出错",
    "解析到说话人信息",
    "发送第一段语音",
    "发送音频消息",
)


def activate(secrets: set[str] | None = None) -> None:
    global _active
    with _lock:
        _active = True
        if secrets:
            _secrets.update(s for s in secrets if isinstance(s, str) and len(s) >= 8)


def add_secrets(secrets: set[str]) -> None:
    with _lock:
        _secrets.update(s for s in secrets if isinstance(s, str) and len(s) >= 8)


def is_active() -> bool:
    return _active


def redact_text(message: str) -> str:
    if not _active or not message:
        return message
    redacted = message
    with _lock:
        secrets = list(_secrets)
    for secret in secrets:
        if secret and secret in redacted:
            redacted = redacted.replace(secret, "[redacted]")
    redacted = _BEARER.sub("Bearer [redacted]", redacted)
    redacted = _HEADER_ASSIGN.sub(r"\1\2[redacted]", redacted)
    if any(hint in message for hint in _CONTENT_HINTS):
        return "[isolated] redacted content log"
    if redacted != message:
        return "[isolated] redacted sensitive log"
    return message


def patcher(record: dict) -> None:
    if not _active:
        return
    message = record.get("message")
    if isinstance(message, str):
        record["message"] = redact_text(message)
