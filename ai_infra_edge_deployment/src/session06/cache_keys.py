#!/usr/bin/env python3
"""キャッシュキーの設計（セッション6）。

`infrakit/cache.py` の `ExactCache` は鍵にプロンプト全文しか含めていない
（教材の題材として意図的に残した欠け）。ここでは「誰の・どのモデルの・
どの条件での・どの資料バージョンでの答えか」まで鍵に含める。

鍵に入れ忘れたものが、そのまま事故の形になる:
    テナントを入れ忘れる  -> 他社の答えが返る
    可視範囲を入れ忘れる  -> 機密資料に基づく答えが一般社員に返る
    モデルを入れ忘れる    -> モデルを差し替えても古い答えが返る
    資料版を入れ忘れる    -> 規程が改訂されても古い答えが返る
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from infrakit.cache import CacheStats, key_of

# 鍵の項目区切り。プロンプト本文に出てこない制御文字を使う
FIELD_SEP = "\x1f"
PROMPT_SEP = "\x1e"


@dataclass(frozen=True)
class CacheScope:
    """キャッシュを分ける境界（スコープ）。

    「同じ答えを返してよい範囲」を1つの値にまとめたもの。
    frozen にしてあるのは、いったん作った鍵の材料を後から書き換えないため。
    """

    tenant_id: str
    visibility: frozenset[str]
    model: str = "qwen05b-q4_k_m.gguf"
    max_tokens: int = 64
    temperature: float = 0.0
    corpus_version: str = "2026-08-15"

    def fingerprint(self) -> str:
        """スコープを1本の文字列にする。ログに出しても中身が読める形にしておく。"""
        return FIELD_SEP.join([
            f"tenant={self.tenant_id}",
            "visibility=" + ",".join(sorted(self.visibility)),
            f"model={self.model}",
            f"max_tokens={self.max_tokens}",
            f"temperature={self.temperature:.2f}",
            f"corpus={self.corpus_version}",
        ])

    @property
    def cacheable(self) -> bool:
        """温度が 0 でなければ答えは毎回変わる。キャッシュしてはいけない。"""
        return self.temperature == 0.0


def unsafe_key(prompt: str) -> str:
    """プロンプト全文だけを鍵にする（`ExactCache` と同じ）。

    誰が聞いても同じ鍵になるため、テナントと権限を跨いで答えが共有される。
    """
    return key_of(prompt)


def scoped_key(scope: CacheScope, prompt: str) -> str:
    """スコープとプロンプトを合わせて鍵にする。"""
    return key_of(scope.fingerprint() + PROMPT_SEP + prompt)


@dataclass
class Entry:
    """キャッシュの1件。消すための情報（誰の・どの版か）も一緒に持つ。"""

    stored_at: float
    text: str
    cost_ms: float
    tenant_id: str
    corpus_version: str


@dataclass
class ScopedCache:
    """スコープ付きの完全一致キャッシュ。

    `ExactCache` との違いは2つだけ。
      1. 鍵にスコープを含める（跨がない）
      2. 消せる（テナント単位・資料バージョン単位で捨てられる）
    """

    ttl_seconds: float = 300.0
    store: dict[str, Entry] = field(default_factory=dict)
    stats: CacheStats = field(default_factory=CacheStats)
    skipped: int = 0

    def get(self, scope: CacheScope, prompt: str) -> str | None:
        if not scope.cacheable:
            # 温度が 0 でないリクエストは、そもそもキャッシュの対象にしない
            self.skipped += 1
            return None
        key = scoped_key(scope, prompt)
        entry = self.store.get(key)
        if entry is None:
            self.stats.misses += 1
            return None
        if time.time() - entry.stored_at > self.ttl_seconds:
            self.store.pop(key, None)
            self.stats.misses += 1
            return None
        self.stats.hits += 1
        self.stats.saved_ms += entry.cost_ms
        return entry.text

    def put(self, scope: CacheScope, prompt: str, text: str, cost_ms: float) -> None:
        if not scope.cacheable:
            self.skipped += 1
            return
        self.store[scoped_key(scope, prompt)] = Entry(
            stored_at=time.time(), text=text, cost_ms=cost_ms,
            tenant_id=scope.tenant_id, corpus_version=scope.corpus_version)

    def invalidate_tenant(self, tenant_id: str) -> int:
        """1テナント分だけ捨てる。「この会社の答えだけ消して」に応えられる形。"""
        doomed = [k for k, e in self.store.items() if e.tenant_id == tenant_id]
        for key in doomed:
            self.store.pop(key, None)
        return len(doomed)

    def invalidate_stale(self, current_version: str) -> int:
        """現行の資料バージョン以外を捨てる。改訂のたびに呼ぶ。"""
        doomed = [k for k, e in self.store.items() if e.corpus_version != current_version]
        for key in doomed:
            self.store.pop(key, None)
        return len(doomed)

    def invalidate_all(self) -> int:
        n = len(self.store)
        self.store.clear()
        return n

    def report_markdown(self) -> str:
        """引き継げる形の観測結果。ヒット率だけでなく件数と節約時間も残す。"""
        return "\n".join([
            "| 指標 | 値 |",
            "| :--- | --: |",
            f"| ヒット | {self.stats.hits} |",
            f"| ミス | {self.stats.misses} |",
            f"| ヒット率 | {self.stats.hit_rate:.3f} |",
            f"| 節約できた推論時間 | {self.stats.saved_ms / 1000:.1f} s |",
            f"| キャッシュ対象外（温度が0でない） | {self.skipped} |",
            f"| 保持しているキー数 | {len(self.store)} |",
        ])
