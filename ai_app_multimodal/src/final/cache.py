"""応答キャッシュ（セッション14の cache.py の写し）。同じ材料のリクエストには、LLM を呼ばずに前の結果を返す。"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta

from kondate.clock import Clock
from kondate.llm import Usage

KEY_VERSION = 1


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def cache_key(*, scope: str, kind: str, content_sha256: str, preprocess: dict,
              prompt: str, system: str | None, model: str, schema: dict | None) -> str:
    material = {
        "v": KEY_VERSION,
        "scope": scope,
        "kind": kind,
        "content_sha256": content_sha256,
        "preprocess": preprocess,
        "prompt": prompt,
        "system": system,
        "model": model,
        "schema_sha256": sha256_hex(canonical(schema)) if schema is not None else None,
    }
    return sha256_hex(canonical(material))


@dataclass(frozen=True)
class Entry:
    scope: str
    value: dict
    usage: Usage
    stored_at: datetime


class ResponseCache:
    def __init__(self, clock: Clock, max_entries: int = 256, ttl_seconds: int = 24 * 3600) -> None:
        self._clock = clock
        self.max_entries = max_entries
        self.ttl = timedelta(seconds=ttl_seconds)
        self._entries: OrderedDict[str, Entry] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> Entry | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if self._clock.now() - entry.stored_at >= self.ttl:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return entry

    def put(self, key: str, scope: str, value: dict, usage: Usage) -> None:
        self._entries[key] = Entry(scope, value, usage, self._clock.now())
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def forget(self, scope: str) -> int:
        keys = [k for k, e in self._entries.items() if e.scope == scope]
        for k in keys:
            del self._entries[k]
        return len(keys)
