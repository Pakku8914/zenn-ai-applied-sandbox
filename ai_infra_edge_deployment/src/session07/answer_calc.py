#!/usr/bin/env python3
"""練習問題1・3・4・9 の計算部分の解答（セッション7）。

  docker compose exec app python src/session07/answer_calc.py

サイズは実測値（2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB）。
時間はすべて見積りであり、入力（帯域・ディスク・プロセス起動）は仮定値である。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session07.imageplan import (  # noqa: E402
    APP_IMAGE_MB, BAKED, FETCH, GGUF_MB, METHOD_NAMES, METHOD_ORDER,
    SAMPLE_CONTEXT, VOLUME, Assumptions, build_context, image_mb, read_patterns,
    registry_stored_mb, rollout_traffic_mb, startup_cost, startup_table,
)

HERE = Path(__file__).resolve().parent
REPLICAS = 10


def problem1() -> None:
    print("=== 問題1: 焼いたときのサイズと転送量（10レプリカ）===")
    print("| 形式 | 焼いたイメージ | 重みを外したイメージ "
          "| 差し替えの転送（焼く） | 同（ボリューム） |")
    print("| :--- | --: | --: | --: | --: |")
    for name, mb in GGUF_MB.items():
        baked = rollout_traffic_mb(BAKED, replicas=REPLICAS, changed="weights",
                                   weights_mb=mb)
        volume = rollout_traffic_mb(VOLUME, replicas=REPLICAS, changed="weights",
                                    weights_mb=mb)
        print(f"| {name} | {image_mb(BAKED, mb):.1f} MB | "
              f"{image_mb(VOLUME, mb):.1f} MB | {baked:.1f} MB | {volume:.1f} MB |")
    code_only = " / ".join(
        f"{METHOD_NAMES[m]} "
        f"{rollout_traffic_mb(m, replicas=REPLICAS, changed='code', weights_mb=GGUF_MB['q4_k_m']):.1f} MB"
        for m in METHOD_ORDER)
    print(f"コードだけの変更: {code_only}")


def problem3() -> None:
    print("\n=== 問題3: ビルドコンテキスト ===")
    patterns = read_patterns((HERE / "dockerignore.example").read_text(encoding="utf-8"))
    keep = "!models/gguf/qwen05b-q4_k_m.gguf"
    cases = [
        ("除外のみ", patterns),
        ("! で1本を送り返す", [*patterns, keep]),
        ("! を除外より前に書く", [keep, *patterns]),
    ]
    for label, pats in cases:
        ctx = build_context(SAMPLE_CONTEXT, pats)
        print(f"{label}: 送る {ctx.sent_mb:.1f} MB / 除く {ctx.excluded_mb:.1f} MB")


def problem4() -> None:
    skewed = Assumptions(registry_mbps=30.0, object_store_mbps=200.0)
    weights = GGUF_MB["q4_k_m"]
    print("\n=== 問題4: 起動時間の内訳"
          "（レジストリ 30MB/s・オブジェクトストレージ 200MB/s・cold）===")
    print(startup_table([startup_cost(m, weights, skewed) for m in METHOD_ORDER]))
    warm = " / ".join(
        f"{METHOD_NAMES[m]} "
        f"{startup_cost(m, weights, skewed, image_cached=True).total_ms:.1f} ms"
        for m in METHOD_ORDER)
    print(f"warm: {warm}")
    print("順序が入れ替わる条件: オブジェクトストレージの帯域 > レジストリの帯域")


def problem9() -> None:
    weights = GGUF_MB["q4_k_m"]
    stored_baked = registry_stored_mb(BAKED, platforms=2, weights_mb=weights)
    stored_volume = registry_stored_mb(VOLUME, platforms=2, weights_mb=weights)
    naive = image_mb(BAKED, weights) * 2
    print("\n=== 問題9: マルチアーキ（2 platform・Q4_K_M）===")
    print(f"レジストリ占有  : 焼く {stored_baked:.1f} MB / "
          f"ボリューム {stored_volume:.1f} MB（単純に2倍すると {naive:.1f} MB）")
    print(f"ノード1台の pull: 焼く {image_mb(BAKED, weights):.1f} MB / "
          f"ボリューム {image_mb(VOLUME, weights):.1f} MB"
          f"（方式③は別経路で {weights:.1f} MB）")
    print(f"重みはアーキ非依存なので、{METHOD_NAMES[VOLUME]}でも"
          f"{METHOD_NAMES[FETCH]}でも platform を増やしても重みは増えない")


def main() -> int:
    problem1()
    problem3()
    problem4()
    problem9()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
