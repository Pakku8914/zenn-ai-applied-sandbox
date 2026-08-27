"""キャッシュ（セッション6の参照実装）。

`PrefixCache` と `ExactCache` はキャッシュキーに**権限を含めていない**。
セッション6で「キャッシュがテナントを跨ぐ」事故を再現させるための意図的な欠け。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field


def key_of(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    saved_ms: float = 0.0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def summary(self) -> str:
        return (f"ヒット {self.hits} / ミス {self.misses} "
                f"（ヒット率 {self.hit_rate:.3f}・短縮 {self.saved_ms / 1000:.1f}s）")


@dataclass
class ExactCache:
    """プロンプト全文が一致したときだけ返す。単純だがヒット率は低い。"""

    ttl_seconds: float = 300.0
    store: dict[str, tuple[float, str, float]] = field(default_factory=dict)
    stats: CacheStats = field(default_factory=CacheStats)

    def get(self, prompt: str) -> str | None:
        entry = self.store.get(key_of(prompt))
        if entry is None:
            self.stats.misses += 1
            return None
        stored_at, text, cost_ms = entry
        if time.time() - stored_at > self.ttl_seconds:
            self.store.pop(key_of(prompt), None)
            self.stats.misses += 1
            return None
        self.stats.hits += 1
        self.stats.saved_ms += cost_ms
        return text

    def put(self, prompt: str, text: str, cost_ms: float) -> None:
        self.store[key_of(prompt)] = (time.time(), text, cost_ms)

    def invalidate_all(self) -> None:
        self.store.clear()


@dataclass
class PrefixCache:
    """前方一致した長さを記録する。KVキャッシュの再利用が効く条件を可視化する。

    実際の KVキャッシュ再利用は推論サーバ側（llama.cpp の `cache_prompt`）が行う。
    ここでは「どれだけ前方が共有できているか」を測って設計判断に使う。
    """

    prefixes: list[str] = field(default_factory=list)

    def common_prefix_len(self, prompt: str) -> int:
        best = 0
        for known in self.prefixes:
            n = 0
            for a, b in zip(known, prompt):
                if a != b:
                    break
                n += 1
            best = max(best, n)
        return best

    def add(self, prompt: str) -> None:
        self.prefixes.append(prompt)

    def report(self, prompts: list[str]) -> dict:
        """プロンプト集の前方一致率を測る。"""
        self.prefixes.clear()
        shared: list[float] = []
        for prompt in prompts:
            n = self.common_prefix_len(prompt)
            shared.append(n / max(len(prompt), 1))
            self.add(prompt)
        return {"n": len(prompts),
                "mean_shared_ratio": sum(shared) / len(shared) if shared else 0.0,
                "max_shared_ratio": max(shared) if shared else 0.0}
