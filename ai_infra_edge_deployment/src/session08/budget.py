#!/usr/bin/env python3
"""推論 Pod の予算計算（セッション8）。

マニフェストに書く数字（`requests.memory` / `startupProbe` の猶予 /
`terminationGracePeriodSeconds`）を、手で決めずに**式から出す**ための道具。
手で決めた数字を直接書くと、モデルやコンテキスト長を変えたときに直し忘れる。

扱うのは4つ。

- メモリ要求：重み ＋ KVキャッシュ ＋ 上乗せ
- 起動の猶予：`startupProbe` の予算 ≧ 起動の見積り
- 停止の猶予：`terminationGracePeriodSeconds` ≧ preStop ＋ 生成の最長 ＋ 余裕
- ロールアウト：`maxSurge` と `maxUnavailable` から所要時間と余剰容量

**時間の数値は仮定である。** 起動の見積りはセッション7の `Assumptions` を
そのまま引き継ぐ（レジストリ帯域・ディスク読み出しなどは自分の環境で測って
置き換える）。ここで確かめたいのは絶対値ではなく「設定した猶予 > 見積り」と
いう大小関係である。

サイズは本書の実測値（2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB /
Python 3.12.13）を使う。本書のサイズは `st_size / 1024 / 1024` で出しているので、
Kubernetes の `Mi`（1024 基準）と同じ基準で読める。`M`（1000 基準）とは 4.9%
ずれるので、マニフェストでは必ず `Mi` / `Gi` を使う。
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.kvcache import LLAMA_8B, QWEN_05B, kv_cache_bytes  # noqa: E402
from src.session07.imageplan import (  # noqa: E402
    BAKED, FETCH, GGUF_MB, METHOD_NAMES, VOLUME, Assumptions, startup_cost,
)

MIB = 1024 * 1024
GIB = 1024 * 1024 * 1024

TTFT_P50_MS = 155.0
"""TTFT p50 の実測（2026-08-15 / Q4_K_M・スロット2・コンテキスト2048・並列1）。

絶対値は実行ごとに 2 倍程度ぶれる。停止の予算は「この程度の桁」で見積もり、
余裕を足して使う。
"""

TPOT_P50_MS = 19.19
"""TPOT p50 の実測（同条件）。1トークン生成するのにかかった時間。"""


# ---------------------------------------------------------------------------
# メモリ要求
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Overhead:
    """重みと KVキャッシュ以外に必要なメモリ。**すべて仮定である。**

    - `margin`：重み＋KVキャッシュに対する余裕（断片化・一時バッファ）
    - `fixed_mib`：プロセス・ランタイム・計算バッファの固定分

    自分の環境で `kubectl top pod`（あるいは `docker stats`）を見て置き換える。
    ここに入れる値は「安全側に倒すためのつまみ」であって、実測ではない。
    """

    margin: float = 0.20
    fixed_mib: float = 256.0


@dataclass(frozen=True)
class MemoryBudget:
    """メモリ要求の内訳。"""

    weights_mib: float
    kv_mib: float
    overhead: Overhead = field(default_factory=Overhead)

    @property
    def base_mib(self) -> float:
        """重み ＋ KVキャッシュ。ここを忘れると同時実行を上げた瞬間に殺される。"""
        return self.weights_mib + self.kv_mib

    @property
    def required_mib(self) -> float:
        return self.base_mib * (1.0 + self.overhead.margin) + self.overhead.fixed_mib

    @property
    def required_bytes(self) -> float:
        return self.required_mib * MIB

    def rounded_mib(self, step: float = 64.0) -> int:
        """マニフェストに書く値。切り上げる（切り下げると足りなくなる）。"""
        if step <= 0:
            raise ValueError("step は正の数を指定してください")
        return int(math.ceil(self.required_mib / step) * step)

    def quantity(self, step: float = 64.0) -> str:
        """Kubernetes の数量表記。`Mi` を使う（`M` は 1000 基準で 4.9% 小さい）。"""
        return f"{self.rounded_mib(step)}Mi"

    def explain(self) -> str:
        return (f"({self.weights_mib:.1f} + {self.kv_mib:.1f}) × "
                f"{1.0 + self.overhead.margin:.2f} + {self.overhead.fixed_mib:.1f} "
                f"= {self.required_mib:.1f} MiB → {self.quantity()}")


def kv_mib(ctx_total: int, model: dict | None = None, bytes_per_elem: int = 2) -> float:
    """KVキャッシュの合計（MiB）。

    llama.cpp の `-c` は**全スロットの合計**なので、`-c 2048 -np 2` なら
    1スロット 1024 で合計は 2048 トークンぶんになる（セッション3・4の実測）。
    つまり合計 KVキャッシュは `-c` の値だけで決まり、`-np` を増やしても
    合計は変わらない（1本あたりが短くなる）。
    """
    if ctx_total <= 0:
        return 0.0
    m = model or QWEN_05B
    est = kv_cache_bytes(m["n_layers"], m["n_kv_heads"], m["head_dim"],
                         ctx_total, 1, bytes_per_elem)
    return est.total_bytes / MIB


def weights_mib_for(model_path: str) -> float | None:
    """モデルのファイル名から重みのサイズ（MiB）を引く。

    本書の実測値（f16 948.1 / Q8_0 506.5 / Q4_K_M 379.4 MiB）を使う。
    知らないファイル名なら None を返す（検査側が「分からない」と報告する）。
    """
    name = str(model_path).lower()
    for key in sorted(GGUF_MB, key=len, reverse=True):
        if key in name:
            return GGUF_MB[key]
    return None


def budget_for(model_path: str, ctx_total: int,
               overhead: Overhead | None = None) -> MemoryBudget | None:
    """モデルのパスと `-c` の値からメモリ要求を組み立てる。"""
    weights = weights_mib_for(model_path)
    if weights is None:
        return None
    return MemoryBudget(weights, kv_mib(ctx_total), overhead or Overhead())


def budget_for_8b(weights_mib: float, ctx_total: int,
                  overhead: Overhead | None = None) -> MemoryBudget:
    """8B 級（層32・KVヘッド8・ヘッド次元128）で同じ式を使う。

    重みのサイズは**読者が入れる仮定**である（本書は 8B を動かしていない）。
    KVキャッシュは 1トークン 128.00 KB で、0.5B の 11 倍になる（セッション3）。
    """
    return MemoryBudget(weights_mib, kv_mib(ctx_total, LLAMA_8B),
                        overhead or Overhead())


# ---------------------------------------------------------------------------
# Probe の予算
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeSpec:
    """Probe の設定値。既定値は Kubernetes の既定に合わせてある。"""

    initial_delay_s: float = 0.0
    period_s: float = 10.0
    failure_threshold: int = 3
    timeout_s: float = 1.0
    path: str | None = None
    kind: str = "unknown"

    @property
    def budget_s(self) -> float:
        """失敗が確定するまでの猶予（秒）。

        最初の実行が `initialDelaySeconds`、以降 `periodSeconds` ごとなので、
        `failureThreshold` 回目の失敗は
        `initialDelaySeconds + periodSeconds × (failureThreshold − 1)` に起きる。
        タイムアウトぶんは足さない（**安全側に小さく数える**）。
        """
        return self.initial_delay_s + self.period_s * max(self.failure_threshold - 1, 0)

    def describe(self) -> str:
        return (f"{self.initial_delay_s:.0f} + {self.period_s:.0f} × "
                f"{max(self.failure_threshold - 1, 0)} = {self.budget_s:.1f} 秒")


# ---------------------------------------------------------------------------
# 起動・停止・ロールアウト
# ---------------------------------------------------------------------------


def startup_seconds(method: str, weights_mib: float,
                    assumptions: Assumptions | None = None, *,
                    image_cached: bool = False) -> float:
    """コールドスタートの見積り（秒）。セッション7の内訳をそのまま使う。

    `method` は `BAKED`（イメージに焼く）／`VOLUME`（すでにある）／
    `FETCH`（起動時に取得）。**この値は仮定の積み上げであって実測ではない。**
    """
    cost = startup_cost(method, weights_mib, assumptions, image_cached=image_cached)
    return cost.total_ms / 1000.0


def startup_breakdown(method: str, weights_mib: float,
                      assumptions: Assumptions | None = None) -> dict[str, float]:
    """起動見積りの内訳（秒）。章の表とレビュー時の説明に使う。"""
    c = startup_cost(method, weights_mib, assumptions)
    return {"イメージ取得": c.pull_ms / 1000.0, "プロセス起動": c.start_ms / 1000.0,
            "重み取得": c.fetch_ms / 1000.0, "モデルロード": c.load_ms / 1000.0,
            "ウォームアップ": c.warmup_ms / 1000.0, "合計": c.total_ms / 1000.0}


def max_request_seconds(max_tokens: int, ttft_ms: float = TTFT_P50_MS,
                        tpot_ms: float = TPOT_P50_MS) -> float:
    """1リクエストが最長どれだけ走るか（秒）。

    TTFT ＋ TPOT × 生成トークン数。既定値は本書の実測（2026-08-15）だが、
    **絶対値は実行ごとにぶれる**ので、停止の予算には必ず余裕を足す。
    """
    if max_tokens < 0:
        raise ValueError("max_tokens は 0 以上を指定してください")
    return (ttft_ms + tpot_ms * max_tokens) / 1000.0


def grace_required_s(prestop_s: float, request_s: float,
                     margin_s: float = 5.0) -> float:
    """`terminationGracePeriodSeconds` に必要な秒数。

    preStop の待ちは猶予の**内側**で消費される。つまり
    `preStop の待ち ＋ 生成の最長 ＋ 余裕` が猶予に収まっていなければ、
    生成中のリクエストが SIGKILL で切られる。
    """
    return prestop_s + request_s + margin_s


def rollout_waves(replicas: int, max_surge: int, max_unavailable: int = 0) -> int:
    """ロールアウトが何波に分かれるか。

    同時に置き換えられる数は `maxSurge + maxUnavailable` に律速される
    （`maxUnavailable: 0` なら `maxSurge` の数だけ新しい Pod を先に立てる）。
    endpoints の伝播や preStop の待ちはこの見積りに含めていない。
    """
    if replicas <= 0:
        raise ValueError("replicas は 1 以上を指定してください")
    parallel = max_surge + max_unavailable
    if parallel <= 0:
        raise ValueError("maxSurge と maxUnavailable の両方を 0 にすると進みません")
    return math.ceil(replicas / parallel)


def rollout_seconds(replicas: int, max_surge: int, startup_s: float,
                    max_unavailable: int = 0) -> float:
    """ロールアウトの所要時間の見積り（秒）。1波ごとに起動を待つ。"""
    return rollout_waves(replicas, max_surge, max_unavailable) * startup_s


def surge_memory_mib(max_surge: int, request_mib: float) -> float:
    """`maxSurge` のあいだ余分に必要になるメモリ（MiB）。

    `maxUnavailable: 0` は「古い Pod を落とさない」ので、その分の容量を
    クラスタ側に用意しておかないと新しい Pod が Pending のままになる。
    """
    return max_surge * request_mib


def method_label(method: str) -> str:
    return METHOD_NAMES.get(method, method)


__all__ = [
    "BAKED", "FETCH", "VOLUME", "GIB", "MIB", "Assumptions", "MemoryBudget",
    "Overhead", "ProbeSpec", "TPOT_P50_MS", "TTFT_P50_MS", "budget_for",
    "budget_for_8b", "grace_required_s", "kv_mib", "max_request_seconds",
    "method_label", "rollout_seconds", "rollout_waves", "startup_breakdown",
    "startup_seconds", "surge_memory_mib", "weights_mib_for",
]
