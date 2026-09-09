"""障害注入とトークン集計。

実 AWS では再現しにくい事象（スロットリング、レイテンシ悪化、リージョン障害）を
**意図したタイミングで確実に起こす** ための仕組みです。
リトライ・指数バックオフ・サーキットブレーカー・フェイルオーバー・コスト監視の演習は、
「失敗が起きること」が前提なので、これが無いと章が成り立ちません。

制御は HTTP で行います（本文の演習では curl か boto3 の外側から叩きます）:

    POST /_mock/behavior  {"throttle_next": 2, "latency_ms": 300}
    POST /_mock/reset
    GET  /_mock/usage
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field

from . import catalog


@dataclass
class Behavior:
    # 次の N 回の呼び出しを ThrottlingException（HTTP 429）で失敗させる
    throttle_next: int = 0
    # 全呼び出しに加える擬似レイテンシ（ミリ秒）
    latency_ms: int = 0
    # このモデル ID への呼び出しだけを ServiceUnavailableException（503）にする
    unavailable_model: str | None = None
    # True の間、すべての呼び出しを ValidationException（400）にする
    force_validation_error: bool = False
    # 出力を必ず max_tokens で打ち切る（コンテキスト溢れの再現）
    force_max_tokens: bool = False
    # <context> が無いときに作り話をするか（False なら「分かりません」を返す）
    hallucinate_without_context: bool = True

    def to_api(self) -> dict:
        return asdict(self)


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    throttled: int = 0
    per_model: dict[str, dict[str, int]] = field(default_factory=dict)

    def record(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_read: int = 0,
        cache_write: int = 0,
    ) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_read_tokens += cache_read
        self.cache_write_tokens += cache_write
        slot = self.per_model.setdefault(
            model_id,
            {"calls": 0, "inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0},
        )
        slot["calls"] += 1
        slot["inputTokens"] += input_tokens
        slot["outputTokens"] += output_tokens
        slot["cacheReadTokens"] += cache_read

    def to_api(self) -> dict:
        models = {}
        total_usd = 0.0
        for model_id, slot in self.per_model.items():
            try:
                usd = catalog.cost_usd(
                    model_id, slot["inputTokens"], slot["outputTokens"]
                )
            except KeyError:
                usd = 0.0
            total_usd += usd
            models[model_id] = {**slot, "estimatedUsd": usd}
        return {
            "calls": self.calls,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "cacheReadTokens": self.cache_read_tokens,
            "cacheWriteTokens": self.cache_write_tokens,
            "throttled": self.throttled,
            "estimatedUsdTotal": round(total_usd, 6),
            "perModel": models,
        }


class State:
    """プロセス内の共有状態。uvicorn のワーカーは1つ（--workers 1）を前提とする。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.behavior = Behavior()
        self.usage = Usage()
        # プロンプトキャッシュの再現用。キャッシュ接頭辞のハッシュ → トークン数
        self.cache: dict[str, int] = {}

    def reset(self) -> None:
        with self._lock:
            self.behavior = Behavior()
            self.usage = Usage()
            self.cache = {}

    def update_behavior(self, patch: dict) -> Behavior:
        with self._lock:
            for key, value in patch.items():
                if hasattr(self.behavior, key):
                    setattr(self.behavior, key, value)
            return self.behavior

    def take_throttle(self) -> bool:
        """スロットリング枠が残っていれば1つ消費して True を返す。"""
        with self._lock:
            if self.behavior.throttle_next > 0:
                self.behavior.throttle_next -= 1
                self.usage.throttled += 1
                return True
            return False

    def cache_lookup(self, key: str, tokens: int) -> tuple[int, int]:
        """(キャッシュ読み込みトークン, キャッシュ書き込みトークン) を返す。"""
        with self._lock:
            if key in self.cache:
                return self.cache[key], 0
            self.cache[key] = tokens
            return 0, tokens


STATE = State()
