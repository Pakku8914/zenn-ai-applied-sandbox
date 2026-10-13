"""応答キャッシュ：同じ材料のリクエストには、LLM を呼ばずに前の結果を返す。

プロンプトキャッシュ（セッション6）は API の側で「同じ接頭辞を読み直す料金」を下げる仕組みで、呼び出しは毎回起きる。
応答キャッシュはアプリの側で「呼び出しそのもの」を省く。キーは「何を同じとみなすか」を全部入れて作る。
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta

from kondate.clock import Clock
from kondate.llm import Usage

KEY_VERSION = 1  # キーの作り方を変えたら上げる（古い作り方のキーと混ざらないように）


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: object) -> bytes:
    """辞書のキーの順番に左右されない JSON のバイト列（同じ中身なら必ず同じバイト列になる）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def cache_key(*, scope: str, kind: str, content_sha256: str, preprocess: dict,
              prompt: str, system: str | None, model: str, schema: dict | None) -> str:
    material = {
        "v": KEY_VERSION,
        "scope": scope,                    # 誰の結果か（既定は利用者 ID。利用者をまたいで共有しない）
        "kind": kind,                      # どの機能か（fridge_scan / document_ask）
        "content_sha256": content_sha256,  # 送られてきたファイルのバイト列の SHA256
        "preprocess": preprocess,          # 前処理の設定（縮小の上限・JPEG の品質・送るページ）
        "prompt": prompt,                  # 指示の文（質問）
        "system": system,
        "model": model,                    # settings.llm_model（モデルが変われば答えも変わる）
        "schema_sha256": sha256_hex(canonical(schema)) if schema is not None else None,  # 構造化出力の形
    }
    return sha256_hex(canonical(material))


@dataclass(frozen=True)
class Entry:
    scope: str
    value: dict          # 応答の本体（usage を除いたもの）
    usage: Usage         # 最初に作ったときの利用量（参考。命中したリクエストの利用量には足さない）
    stored_at: datetime


class ResponseCache:
    """プロセス内メモリの応答キャッシュ。件数の上限（古いものから追い出す）と保持時間を持つ。"""

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
            del self._entries[key]           # 期限切れは消してから「無い」と答える
            return None
        self._entries.move_to_end(key)       # 最近使ったものを後ろへ（追い出されにくくする）
        return entry

    def put(self, key: str, scope: str, value: dict, usage: Usage) -> None:
        self._entries[key] = Entry(scope, value, usage, self._clock.now())
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)  # いちばん長く使われていないものを追い出す

    def forget(self, scope: str) -> int:
        """その利用者の結果をすべて消す（DELETE /api/me/data から呼ぶ）。消した件数を返す。"""
        keys = [k for k, e in self._entries.items() if e.scope == scope]
        for k in keys:
            del self._entries[k]
        return len(keys)
