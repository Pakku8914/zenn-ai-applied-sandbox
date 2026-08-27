#!/usr/bin/env python3
"""KVキャッシュのメモリ量を計算し、サーバの実測と突き合わせる（セッション3）。

式で出した見積もりと、コンテキスト長を変えたときの実際のメモリ使用量を比べる。
「式は合っているが実際はもっと使う」ことを確認するのが目的（実装のオーバーヘッド）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrakit.kvcache import LLAMA_8B, QWEN_05B, kv_cache_bytes, max_concurrent, table  # noqa: E402


def main() -> None:
    print("=== Qwen2.5-0.5B の構成 ===")
    for key, value in QWEN_05B.items():
        print(f"{key:<12}: {value}")

    est = kv_cache_bytes(QWEN_05B["n_layers"], QWEN_05B["n_kv_heads"],
                         QWEN_05B["head_dim"], seq_len=1, batch=1)
    print(f"\n1トークンあたりの KVキャッシュ: {est.per_token_bytes} バイト "
          f"（{est.per_token_kb:.2f} KB）")
    print("  計算: 層数 24 × KVヘッド 2 × ヘッド次元 64 × 2(K,V) × 2バイト(f16)")

    print("\n=== コンテキスト長 × 同時実行数（Qwen2.5-0.5B・f16）===")
    print(f"{'系列長':>8}{'同時実行':>10}{'合計(MB)':>12}")
    for row in table(QWEN_05B):
        print(f"{row['seq_len']:>8}{row['batch']:>10}{row['total_mb']:>12.1f}")

    print("\n=== 同じ計算を 8B 級モデルでやると ===")
    est8 = kv_cache_bytes(LLAMA_8B["n_layers"], LLAMA_8B["n_kv_heads"],
                          LLAMA_8B["head_dim"], seq_len=1, batch=1)
    print(f"1トークンあたり: {est8.per_token_kb:.2f} KB "
          f"（0.5B の {est8.per_token_bytes / est.per_token_bytes:.0f} 倍）")
    print(f"{'系列長':>8}{'同時実行':>10}{'合計(MB)':>12}")
    for row in table(LLAMA_8B, seq_lens=(2048, 8192), batches=(1, 8, 32)):
        print(f"{row['seq_len']:>8}{row['batch']:>10}{row['total_mb']:>12.1f}")

    print("\n=== 1GB の余裕で持てる同時実行数（系列長ごと）===")
    print(f"{'系列長':>8}{'0.5B':>8}{'8B級':>8}")
    for seq_len in (512, 2048, 8192):
        n_small = max_concurrent(1024**3, seq_len, **{k: v for k, v in QWEN_05B.items()
                                                      if k != "hidden"})
        n_big = max_concurrent(1024**3, seq_len, **{k: v for k, v in LLAMA_8B.items()
                                                    if k != "hidden"})
        print(f"{seq_len:>8}{n_small:>8}{n_big:>8}")

    print("\n※ ここまでは式による見積もり。実際の使用量は実装のオーバーヘッドで上回る。"
          "サーバ起動時のログ（KV cache size）と突き合わせること。")


if __name__ == "__main__":
    main()
