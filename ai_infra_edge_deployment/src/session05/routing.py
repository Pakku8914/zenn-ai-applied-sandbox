#!/usr/bin/env python3
"""モデル階層への振り分け（セッション5）。

「全部を一番大きいモデルに送る」をやめるための判定を、純粋な関数として書く。
どの階層が速いかは**測って決める**。本書のサンドボックスでは Q8_0 が f16 の
2.1 倍速く、より小さい Q4_K_M より速かった（セッション3の実測）。
「小さいほうが速い」という思い込みで階層を組むと外れる。

  docker compose exec app python src/session05/routing.py
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    """振り分け先の1階層。

    measured_* は**実測した値だけ**を入れる。測っていないものは None のまま
    にしておく（推定値を書くと、後で実測と区別できなくなる）。
    """

    name: str
    model_file: str
    max_prompt_tokens: int
    max_output_tokens: int
    measured_ttft_p50_ms: float | None = None
    measured_tps: float | None = None


# 2026-08-15 実測（スロット1・コンテキスト1024・max_tokens=48・20リクエスト・並列1・
# aarch64 / CPU 2コア / メモリ 5.8GB / llama.cpp `-t 2`）。
# 入力の上限 960 は「1スロット 1024 − 出力用の予約 64」（セッション4）。
FAST = Tier("fast", "qwen05b-q8_0.gguf", max_prompt_tokens=960, max_output_tokens=64,
            measured_ttft_p50_ms=61.0, measured_tps=63.0)
QUALITY = Tier("quality", "qwen05b-f16.gguf", max_prompt_tokens=960, max_output_tokens=256,
               measured_ttft_p50_ms=124.0, measured_tps=30.0)
TIERS: tuple[Tier, ...] = (FAST, QUALITY)


@dataclass(frozen=True)
class Route:
    """振り分けの結果。

    degraded    : 品質を落として通したか（記録しないと後から説明できない）
    status_code : 0 なら振り分けた。413 は受ける前に断った
    """

    tier: str
    max_tokens: int
    degraded: bool
    reason: str
    status_code: int = 0


def route(prompt_tokens: int, requested_max_tokens: int, *,
          priority: str = "interactive", upstream_degraded: bool = False,
          tiers: Sequence[Tier] = TIERS) -> Route:
    """どの階層へ流すかを決める。判定の順序が方針そのものである。

    1. どの階層にも収まらない長さは、受ける前に断る（413）
    2. 上流が不調なら速い階層へ落として出力も切り詰める（縮退）
    3. 急がない要求（batch）は速い階層で十分
    4. 長い出力が必要なものだけ品質階層へ
    5. それ以外は既定＝測って速かった階層
    """
    fast, quality = tiers[0], tiers[-1]
    longest = max(t.max_prompt_tokens for t in tiers)
    if prompt_tokens <= 0 or requested_max_tokens <= 0:
        return Route("-", 0, False, "入力と出力はどちらも 1 トークン以上が必要", 400)
    if prompt_tokens > longest:
        return Route("-", 0, False,
                     f"入力が長すぎる（{prompt_tokens} > {longest}）", 413)
    if upstream_degraded:
        return Route(fast.name, min(requested_max_tokens, fast.max_output_tokens), True,
                     "上流が不調なので速い階層に落として出力も切り詰める")
    if priority == "batch":
        return Route(fast.name, min(requested_max_tokens, fast.max_output_tokens), True,
                     "急がない要求は速い階層で十分")
    if (requested_max_tokens > fast.max_output_tokens
            or prompt_tokens > fast.max_prompt_tokens):
        return Route(quality.name, min(requested_max_tokens, quality.max_output_tokens),
                     False, "長い出力が要るので品質階層へ")
    return Route(fast.name, min(requested_max_tokens, fast.max_output_tokens), False,
                 "既定は測って速かった階層")


CASES: tuple[tuple[int, int, str, bool], ...] = (
    (200, 64, "interactive", False),
    (200, 200, "interactive", False),
    (200, 200, "batch", False),
    (200, 64, "interactive", True),
    (1200, 64, "interactive", False),
)


def routing_table(cases: Sequence[tuple[int, int, str, bool]] = CASES) -> str:
    """引き継げる形（Markdown の表）で振り分け方針を書き出す。"""
    lines = ["| 入力 | 要求出力 | 優先度 | 上流 | 階層 | max_tokens | 縮退 | 理由 |",
             "| --: | --: | :--- | :--- | :--- | --: | :-: | :--- |"]
    for prompt_tokens, want, priority, degraded in cases:
        r = route(prompt_tokens, want, priority=priority, upstream_degraded=degraded)
        tier = r.tier if r.status_code == 0 else str(r.status_code)
        lines.append(f"| {prompt_tokens} | {want} | {priority} | "
                     f"{'不調' if degraded else '正常'} | {tier} | {r.max_tokens} | "
                     f"{'あり' if r.degraded else '-'} | {r.reason} |")
    return "\n".join(lines)


if __name__ == "__main__":
    print("=== 階層（2026-08-15 実測・スロット1・ctx1024・max_tokens=48・並列1）===")
    for t in TIERS:
        print(f"{t.name:<8}: {t.model_file:<20} "
              f"TTFT p50 {t.measured_ttft_p50_ms:.0f} ms / {t.measured_tps:.1f} tok/s "
              f"/ 出力上限 {t.max_output_tokens}")
    print()
    print("=== 振り分け表 ===")
    print(routing_table())
