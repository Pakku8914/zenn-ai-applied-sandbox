#!/usr/bin/env python3
"""索引作成時間を実測値から見積もる（セッション6・問題4）。

埋め込みだけの時間で見積もると足りない。ベクトルDB への登録を含む
「索引作成全体」との比を掛けること。基準にする実測値は次の2つ。

  tools/bench_embed.py            : 673 チャンクの埋め込み        38.21 秒
  tools/eval_matrix.py (dense/fixed): 673 チャンクの索引作成全体   56.60 秒

いずれも 2026-08-15 / aarch64 / CPU 2コア / メモリ 5.8GB / Python 3.12.13 の実測値。
別の環境に持っていくときは、この2つを測り直してから使うこと。
"""

from __future__ import annotations

EMBED_SEC = 38.21  # 673 チャンクの埋め込みだけの時間
BUILD_SEC = 56.60  # 同じ 673 チャンクの索引作成全体（埋め込み + Qdrant 登録）
BASE_CHUNKS = 673
LOAD_SEC = 6.7  # モデルのロード（キャッシュ後・プロセスごとに1回）
SIZES = (673, 10_000, 100_000)


def main() -> None:
    per_chunk_sec = EMBED_SEC / BASE_CHUNKS
    overhead = BUILD_SEC / EMBED_SEC

    print("索引作成時間の見積もり"
          "（2026-08-15 実測 / aarch64 / CPU 2コア / multilingual-e5-small）")
    print(f"  基準: {BASE_CHUNKS} チャンクの埋め込み {EMBED_SEC:.2f} 秒 "
          f"= 1件あたり {per_chunk_sec * 1000:.1f} ms")
    print(f"        {BASE_CHUNKS} チャンクの索引作成 {BUILD_SEC:.1f} 秒 "
          f"= 埋め込みの {overhead:.2f} 倍")
    print()
    for n in SIZES:
        embed_min = n * per_chunk_sec / 60
        total_min = embed_min * overhead
        print(f"  {n:>9,} チャンク : 埋め込み {embed_min:>6.1f} 分"
              f" / 索引作成全体 {total_min:>6.1f} 分")
    print()
    print(f"モデルのロード {LOAD_SEC} 秒（プロセスごとに1回）は上記に含みません。")


if __name__ == "__main__":
    main()
