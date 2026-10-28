"""Security helpers for MCC remote management."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from typing import Any

SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|pwd|token|secret|access[_-]?token|refresh[_-]?token|client[_-]?secret|session)",
    re.IGNORECASE,
)

SECRET_VALUE_RE = re.compile(
    r"(?im)^([\w.\-]*(?:password|passwd|pwd|token|secret|access_token|refresh_token|client_secret)[\w.\-]*\s*[:=]\s*)(.*)$"
)

# ⚠️ 2026-10-20 审查修复（中等·脱敏覆盖不全）：
#   SECRET_VALUE_RE 只匹配「行首 key: value / key=value」，以下真实场景全部漏网：
#     · `Password: xxx`（空格分隔，非冒号等号）—— MCC/服务端常见输出
#     · `> say login MyPass123`（终端回显，口令在命令参数里）
#     · `https://host/api?token=abc&x=1`（URL 内嵌 token）
#   新增两条正则，与 SECRET_VALUE_RE 一起在 mask_text 里依次应用。
SECRET_SPACE_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|access[_-]?token)\b"
    r"(\s*[:=]?\s+)(\S{3,})"
)
SECRET_URL_PARAM_RE = re.compile(
    r"(?i)([?&](?:token|access_token|refresh_token|key|secret|api[_-]?key|password)=)([^&\s#]+)"
)


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def mask_secret(value: str, keep: int = 3) -> str:
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "******"
    return f"{value[:keep]}******{value[-keep:]}"


def protect_secret(value: str | None) -> str | None:
    if not value:
        return None
    from vmtools_next.config import get_config

    key = get_config().server.secret_key.encode("utf-8")
    nonce = secrets.token_bytes(16)
    payload = value.encode("utf-8")
    digest = hmac.new(key, nonce + payload, hashlib.sha256).digest()
    return "v1:" + base64.urlsafe_b64encode(nonce + digest + payload).decode("ascii")


def reveal_secret(value: str | None) -> str | None:
    if not value:
        return None
    if not value.startswith("v1:"):
        return value
    from vmtools_next.config import get_config

    try:
        raw = base64.urlsafe_b64decode(value[3:].encode("ascii"))
        nonce, digest, payload = raw[:16], raw[16:48], raw[48:]
        key = get_config().server.secret_key.encode("utf-8")
        expected = hmac.new(key, nonce + payload, hashlib.sha256).digest()
        if not hmac.compare_digest(digest, expected):
            return None
        return payload.decode("utf-8")
    except Exception:
        return None


def mask_text(text: str) -> str:
    """Mask common key=value / key: value / URL-param secrets in text logs/configs.

    ⚠️ 2026-10-20 审查修复（中等·脱敏覆盖不全）：除原有的行首 `key: value`，
    额外覆盖「空格分隔」与「URL 查询参数」两种真实形态（见上方正则注释）。
    """
    if not text:
        return text

    def repl(match: re.Match[str]) -> str:
        return f"{match.group(1)}******"

    text = SECRET_VALUE_RE.sub(repl, text)
    # URL 查询参数（?token=xxx / &key=xxx）
    text = SECRET_URL_PARAM_RE.sub(lambda m: f"{m.group(1)}******", text)
    # 空格分隔（Password: xxx / password xxx）
    text = SECRET_SPACE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}******", text)
    return text


def mask_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "******" if SENSITIVE_KEY_RE.search(str(key)) else mask_mapping(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_mapping(item) for item in value]
    return value


def dumps_masked(value: Any) -> str:
    return json.dumps(mask_mapping(value), ensure_ascii=False, default=str)
