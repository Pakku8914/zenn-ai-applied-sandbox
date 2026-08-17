#!/usr/bin/env python3
"""インデックス運用のコスト試算（計算・保存・更新）。

入力にする実測値は次の2つだけ（2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB）。
  - 埋め込み: 673 チャンクで 38.21 秒（tools/bench_embed.py）
  - 次元: 384（intfloat/multilingual-e5-small）
あとは掛け算と割り算なので、手元の環境の数字を入れれば自分の見積もりになる。

    python src/session16/cost_model.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402

DIM = 384  # ベクトルの次元
BYTES_PER_DIM = 4  # float32
EMBED_SECONDS_673 = 38.21  # 実測
BOOK_CHUNKS = 673
TARGET_CHUNKS = 100_000  # 本番想定
DAILY_CHANGE_RATE = 0.01  # 1日に書き換わる割合
INDEXING_THRESHOLD_KB = 10_000  # Qdrant の既定（単位は KB）

MIB = 1024 * 1024
SEC_PER_CHUNK = EMBED_SECONDS_673 / BOOK_CHUNKS


def summary() -> dict:
    """試算をまとめて返す（verify.py が同じ値を検査する）。"""
    vec_bytes = DIM * BYTES_PER_DIM
    book_vec_bytes = vec_bytes * BOOK_CHUNKS
    target_vec_bytes = vec_bytes * TARGET_CHUNKS
    chunks = chunk_all(load_docs(), "fixed", size=400, overlap=80)
    text_bytes = sum(len(c.text.encode("utf-8")) for c in chunks)
    full = SEC_PER_CHUNK * TARGET_CHUNKS
    daily = full * DAILY_CHANGE_RATE
    return {
        "vec_bytes": vec_bytes,
        "book_vec_kb": round(book_vec_bytes / 1024, 1),
        "target_vec_mib": round(target_vec_bytes / MIB, 1),
        "peak_vec_mib": round(2 * target_vec_bytes / MIB, 1),
        "threshold_chunks": int(INDEXING_THRESHOLD_KB * 1024 / vec_bytes),
        "n_chunks": len(chunks),
        "text_bytes": text_bytes,
        "text_ratio": round(text_bytes / book_vec_bytes, 2),
        "ms_per_chunk": round(SEC_PER_CHUNK * 1000, 1),
        "full_minutes": round(full / 60, 1),
        "daily_seconds": round(daily, 1),
        "ratio": round(full / daily, 1),
        "monthly_incremental_minutes": round(daily * 30 / 60, 1),
        "monthly_full_hours": round(full * 30 / 3600, 1),
    }


def main() -> None:
    s = summary()

    print("=== 1. 保存（ベクトル）===")
    print(f"  ベクトル1本            : {DIM} × {BYTES_PER_DIM} = {s['vec_bytes']:,} バイト")
    print(f"  本書の {BOOK_CHUNKS} チャンク    : {s['book_vec_kb']:,} KB")
    print(f"  {TARGET_CHUNKS:,} チャンク     : {s['target_vec_mib']:,} MiB")
    print(f"  並行構築中のピーク      : {s['peak_vec_mib']:,} MiB（新旧2本）")
    print(f"  HNSW が作られ始める規模 : {INDEXING_THRESHOLD_KB:,} KB ÷ {s['vec_bytes']:,} B "
          f"= 約 {s['threshold_chunks']:,} チャンク")
    print(f"  → 本書の {BOOK_CHUNKS} チャンクは {s['book_vec_kb']:,} KB しかないので"
          "しきい値に届かない")
    print("     （セッション7で見た「HNSW が1本も作られていない」の正体）")

    print("\n=== 2. 保存（本文のペイロード）===")
    print(f"  {s['n_chunks']} チャンクの本文 : {s['text_bytes']:,} バイト "
          f"= {s['text_bytes'] / 1024:,.1f} KB")
    print(f"  ベクトルとの比       : 本文が {s['text_ratio']} 倍")
    print("  ベクトルだけを見て容量を見積もると外す。本文もメタデータも索引に載る")

    print("\n=== 3. 計算（埋め込み）===")
    print(f"  1チャンクあたり        : {s['ms_per_chunk']} ms")
    print(f"  全再索引（{TARGET_CHUNKS:,}）  : {s['full_minutes']} 分")
    print(f"  日次1%の増分（{int(TARGET_CHUNKS * DAILY_CHANGE_RATE):,}） : "
          f"{s['daily_seconds']} 秒")
    print(f"  比                     : {s['ratio']} 倍")

    print("\n=== 4. 1か月（30日）回したら ===")
    print(f"  増分更新のみ           : {s['monthly_incremental_minutes']} 分 / 月")
    print(f"  毎日全再索引           : {s['monthly_full_hours']} 時間 / 月")
    print("  全再索引を日課にすると、CPU をほぼ埋め込みだけに使うことになる")


if __name__ == "__main__":
    main()
