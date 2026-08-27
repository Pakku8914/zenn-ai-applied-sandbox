"""KVキャッシュのメモリ量の見積もり（セッション3の参照実装）。

式だけでは身につかないので、必ず計算例と実測の突き合わせをセットで扱う。
"""

from __future__ import annotations

from dataclasses import dataclass

# Qwen2.5-0.5B-Instruct の構成（config.json より）
QWEN_05B = {"n_layers": 24, "n_kv_heads": 2, "head_dim": 64, "hidden": 896}
# 比較用（本書のサンドボックスでは動かさないが、規模感の計算に使う）
LLAMA_8B = {"n_layers": 32, "n_kv_heads": 8, "head_dim": 128, "hidden": 4096}


@dataclass(frozen=True)
class KVEstimate:
    per_token_bytes: int
    total_bytes: int
    seq_len: int
    batch: int

    @property
    def total_mb(self) -> float:
        return self.total_bytes / 1024 / 1024

    @property
    def per_token_kb(self) -> float:
        return self.per_token_bytes / 1024


def kv_cache_bytes(n_layers: int, n_kv_heads: int, head_dim: int, seq_len: int,
                   batch: int = 1, bytes_per_elem: int = 2) -> KVEstimate:
    """KVキャッシュのメモリ量。

        1トークンあたり = 層数 × KVヘッド数 × ヘッド次元 × 2（K と V）× 1要素のバイト数
        合計 = 1トークンあたり × 系列長 × 同時実行数

    bytes_per_elem は KVキャッシュの型。f16 なら 2、q8_0 相当なら 1。
    """
    per_token = n_layers * n_kv_heads * head_dim * 2 * bytes_per_elem
    return KVEstimate(per_token, per_token * seq_len * batch, seq_len, batch)


def max_concurrent(memory_bytes: int, seq_len: int, *, n_layers: int, n_kv_heads: int,
                   head_dim: int, bytes_per_elem: int = 2) -> int:
    """与えられたメモリで同時に何本の系列を持てるか。"""
    one = kv_cache_bytes(n_layers, n_kv_heads, head_dim, seq_len, 1, bytes_per_elem)
    return max(memory_bytes // one.total_bytes, 0)


def table(model: dict, seq_lens=(512, 2048, 8192), batches=(1, 2, 4, 8)) -> list[dict]:
    """章に載せる表を生成する。"""
    rows = []
    for seq_len in seq_lens:
        for batch in batches:
            est = kv_cache_bytes(model["n_layers"], model["n_kv_heads"], model["head_dim"],
                                 seq_len, batch)
            rows.append({"seq_len": seq_len, "batch": batch,
                         "per_token_kb": round(est.per_token_kb, 2),
                         "total_mb": round(est.total_mb, 1)})
    return rows
