"""監査ログ（Python 版）

出力先は既定で stderr です。stdout は JSON-RPC の通信路なので絶対に使いません。
TypeScript 版 node/src/session15/audit-log.ts とレコード構造・参照値の桁数を
揃えています（2 言語のログを同じ集計器で処理できるようにするため）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

REDACTED = "[REDACTED]"
MAX_FIELD_LENGTH = 200

#: トークンらしい文字列。既知の秘密値を知らなくても網に掛ける（最後の砦）
SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def scrub_secrets(text: str, known: Iterable[str] = ()) -> str:
    out = text
    for secret in known:
        # 短い値を置換対象にすると、無関係な文字列まで [REDACTED] になる
        if len(secret) >= 8:
            out = out.replace(secret, REDACTED)
    for pattern in SECRET_PATTERNS:
        out = pattern.sub(REDACTED, out)
    return out


def flatten_control_chars(value: str) -> str:
    """制御文字を空白へ。改行が残ると値でログ 1 行を偽造できる"""
    return "".join(
        " " if ord(character) <= 0x1F or ord(character) == 0x7F else character
        for character in value
    )


def scrub_field(value: str, known: Iterable[str] = ()) -> str:
    flattened = flatten_control_chars(scrub_secrets(value, known)).strip()
    if len(flattened) > MAX_FIELD_LENGTH:
        return flattened[:MAX_FIELD_LENGTH] + "…"
    return flattened


class AuditLogger:
    def __init__(
        self,
        *,
        server: str,
        tenant_id: str,
        subject_id: str,
        session_id: str,
        pepper: str,
        clock: Callable[[], int] | None = None,
        sink: Callable[[str], None] | None = None,
        known_secrets: Iterable[str] = (),
    ) -> None:
        self._server = server
        self._tenant_id = tenant_id
        self._subject_id = subject_id
        self._session_id = session_id
        self._pepper = pepper
        self._clock = clock or (lambda: int(datetime.now(tz=UTC).timestamp() * 1000))
        self._sink = sink or (lambda line: print(line, file=sys.stderr))
        self._known = tuple(known_secrets)

    def hash(self, value: str) -> str:
        """生値の代わりに載せる参照値。ペッパー付き HMAC の先頭 16 桁"""
        digest = hmac.new(self._pepper.encode(), value.encode(), hashlib.sha256)
        return digest.hexdigest()[:16]

    def write(
        self,
        *,
        event: str,
        target: str,
        outcome: str,
        params: Mapping[str, Any] | None = None,
        reason: str | None = None,
        result_count: int | None = None,
        findings: Iterable[str] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        scrubbed: dict[str, Any] = {}
        for key, value in (params or {}).items():
            scrubbed[key] = scrub_field(value, self._known) if isinstance(value, str) else value

        record: dict[str, Any] = {
            "ts": self._timestamp(),
            "server": self._server,
            "tenantId": self._tenant_id,
            "subject": self.hash(self._subject_id),
            "sessionRef": self.hash(self._session_id),
            "event": event,
            "target": scrub_field(target, self._known),
            "outcome": outcome,
            "params": scrubbed,
        }
        if reason is not None:
            record["reason"] = scrub_field(reason, self._known)
        if result_count is not None:
            record["resultCount"] = result_count
        if findings is not None:
            record["findings"] = list(findings)
        if duration_ms is not None:
            record["durationMs"] = duration_ms

        # json.dumps は改行をエスケープするので 1 レコードが必ず 1 行になる
        self._sink(json.dumps(record, ensure_ascii=False))

    def _timestamp(self) -> str:
        moment = datetime.fromtimestamp(self._clock() / 1000, tz=UTC)
        return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")
