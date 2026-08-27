#!/usr/bin/env python3
"""エッジに載るかを見積もる道具（セッション11）。

この章で扱う数値は3種類ある。**混ぜてはいけない。**

  ① 実測値   : reports/ の測定結果。測定条件つきで引用する（例: Q4_K_M の 379.4 MB）
  ② 物理計算 : 定数から計算できるもの（例: 光ファイバ中の伝搬速度から出す往復の下限）
  ③ 前提値   : 読者が自分の環境の値を入れるもの（端末のメモリ・通信単価・実行時メモリ）

見積もりの結論が変わるのは、たいてい ③ を置き間違えたときである。
どの数値が ③ なのかを常に自分で言えるようにしておくこと。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.kvcache import LLAMA_8B, QWEN_05B, kv_cache_bytes  # noqa: E402

MB = 1024 ** 2
GB = 1024 ** 3

# ② 物理計算の前提：光ファイバ中の信号の実効伝搬速度（真空中の光速の約 2/3）。
#    実測値ではない。実際の往復時間は経路の迂回とキューイングでこれを必ず上回る。
FIBER_KM_PER_S = 200_000

MODELS = {"qwen05b": QWEN_05B, "llama8b": LLAMA_8B}


def shape(name: str) -> dict:
    """kv_cache_bytes に渡せる形（hidden を除く）にする。"""
    return {k: v for k, v in MODELS[name].items() if k != "hidden"}


@dataclass(frozen=True)
class MemoryBudget:
    """③ 前提値。端末の物理メモリのうち、推論に使ってよい分を求める。"""

    total_mb: float          # 端末の物理メモリ
    os_reserved_mb: float    # OS が握っていて触れない分
    other_apps_mb: float     # 同時に動く他のアプリの分
    headroom: float = 0.2    # 余白（断片化・一時的な増加・将来のモデル更新のため）

    @property
    def available_mb(self) -> float:
        return max(self.total_mb - self.os_reserved_mb - self.other_apps_mb, 0.0)

    @property
    def limit_mb(self) -> float:
        """余白を残した上限。ここに収めるのが設計目標になる。"""
        return self.available_mb * (1.0 - self.headroom)


@dataclass(frozen=True)
class Footprint:
    """推論が使うメモリの内訳。3つ全部を足さないと必ず見積もりを外す。"""

    weights_mb: float    # ① 重み（GGUF/ONNX の実ファイルサイズ）
    kv_mb: float         # 計算値（KVキャッシュ。分類モデルなら 0）
    runtime_mb: float    # ③ 実行時の作業メモリ（ランタイム・中間結果）

    @property
    def total_mb(self) -> float:
        return self.weights_mb + self.kv_mb + self.runtime_mb


def kv_mb(name: str, seq_len: int, batch: int = 1, bytes_per_elem: int = 2) -> float:
    """KVキャッシュの MB。セッション3の式をそのまま端末に持ち込む。"""
    est = kv_cache_bytes(seq_len=seq_len, batch=batch,
                         bytes_per_elem=bytes_per_elem, **shape(name))
    return est.total_mb


def weights_mb(params: float, bytes_per_param: float) -> float:
    """重みの MB。bytes_per_param が 2 なら f16、1 なら 8bit、0.5 なら 4bit 相当。"""
    return params * bytes_per_param / MB


def fits(budget: MemoryBudget, fp: Footprint) -> tuple[bool, float]:
    """上限に収まるか。戻り値は (収まるか, 余白 MB)。余白が負なら超過量。"""
    return fp.total_mb <= budget.limit_mb, budget.limit_mb - fp.total_mb


def max_bytes_per_param(budget: MemoryBudget, params: float,
                        kv_mb_value: float, runtime_mb: float) -> float:
    """逆算：この予算に載せるには1パラメータ何バイトまで使えるか。

    0.125 バイト（＝1bit）を下回ったら、その規模のモデルは
    どんな量子化をしても載らない。**モデルを小さくするしかない。**
    """
    left_mb = budget.limit_mb - kv_mb_value - runtime_mb
    if left_mb <= 0 or params <= 0:
        return 0.0
    return left_mb * MB / params


def monthly_upload_gb(payload_bytes: float, per_hour: float, devices: int,
                      hours_per_day: float = 24.0, days: int = 30,
                      send_ratio: float = 1.0) -> float:
    """月間の上り転送量。send_ratio はエッジで一次判定して実際に送る割合。"""
    total = payload_bytes * per_hour * hours_per_day * days * devices * send_ratio
    return total / GB


def rtt_floor_ms(distance_km: float, km_per_s: float = FIBER_KM_PER_S) -> float:
    """往復の物理的下限（②物理計算）。距離 0 のエッジでは 0 になる。"""
    return distance_km * 2 / km_per_s * 1000
