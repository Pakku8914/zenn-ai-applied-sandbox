#!/usr/bin/env python3
"""応答キャッシュのヒット率を入口の上限に翻訳する（復習2・問題5）。

セッション6（応答キャッシュ）とセッション4・5（飽和点と入口の上限）をつなぐ。

  入口で受ける rps × (1 − ヒット率) = 上流（推論サーバ）に届く rps

この1行から2つの向きの計算ができる。

  ①（順方向）ヒット率が h なら、上流の上限 C に対して入口は C ÷ (1 − h) まで開ける
  ②（逆方向）入口で R を受けたいなら、必要なヒット率は 1 − C ÷ R

**②の使い方には罠がある。** キャッシュは冷えるものなので（デプロイ直後・
TTL 切れ・無効化直後・新しい質問が来たとき）、ヒット率を前提に入口を開けると、
冷えた瞬間に上流が飽和する。冷えたときに何倍の入力が上流へ流れるかを必ず
併記すること。

  docker compose exec app python src/review02/cache_capacity.py

上流の上限 1.13 rps は 2026-08-15 実測（aarch64 / CPU 2コア / メモリ 5.8GB /
Python 3.12.13 / llama.cpp `-t 2`・Q4_K_M・スロット2・並列2）。
**ヒット率は読者が入れる仮定値であり、本書の実測値ではない。**
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.review01.capacity_chain import floor_at  # noqa: E402

CEILING_RPS = 1.13
"""上流の上限スループット（並列2 の実測 rps・2026-08-15）。"""

DEFAULT_HIT_RATES = (0.0, 0.2, 0.3, 0.5, 0.7)
"""感度分析で振るヒット率。**すべて仮定値**であり実測ではない。"""


def _check_hit_rate(hit_rate: float) -> None:
    if not 0.0 <= hit_rate < 1.0:
        raise ValueError("hit_rate は 0.0 以上 1.0 未満で指定してください"
                         "（1.0 は「上流を1回も呼ばない」なので意味がありません）")


def ceil_at(value: float, digits: int = 3) -> float:
    """切り上げ。必要なヒット率は切り上げないと足りなくなる。

    9桁で丸めてから切り上げるのは二進小数の誤差対策（`floor_at` と同じ理由）。
    """
    scale = 10 ** digits
    return math.ceil(round(value * scale, 9)) / scale


def upstream_rps(entry_rps: float, hit_rate: float) -> float:
    """入口で受けた rps のうち、上流に届く rps。"""
    _check_hit_rate(hit_rate)
    if entry_rps < 0:
        raise ValueError("entry_rps は 0 以上を指定してください")
    return entry_rps * (1.0 - hit_rate)


def entry_rps_allowed(ceiling_rps: float, hit_rate: float) -> float:
    """上流の上限を守りながら入口で受けられる rps（切り捨て）。

    四捨五入すると、全キーが上限まで使ったときに上流の処理能力を超える。
    """
    _check_hit_rate(hit_rate)
    if ceiling_rps <= 0:
        raise ValueError("ceiling_rps は正の数を指定してください")
    return floor_at(ceiling_rps / (1.0 - hit_rate), 2)


def rate_per_key(entry_rps: float, tenants: int) -> float:
    """キーあたりの `rate`（切り捨て）。合計が入口の上限を超えないようにする。"""
    if tenants < 1:
        raise ValueError("tenants は 1 以上を指定してください")
    return floor_at(entry_rps / tenants, 2)


def required_hit_rate(target_rps: float, ceiling_rps: float) -> float:
    """入口で target_rps を受けるために必要なヒット率（切り上げ）。

    返り値が 0 以下なら、キャッシュに頼らなくても上流だけで足りている。
    """
    if target_rps <= 0 or ceiling_rps <= 0:
        raise ValueError("target_rps と ceiling_rps は正の数を指定してください")
    return max(ceil_at(1.0 - ceiling_rps / target_rps, 3), 0.0)


def cold_multiplier(entry_rps: float, ceiling_rps: float) -> float:
    """キャッシュが冷えたとき、上流に届く入力が上限の何倍になるか（切り捨て）。

    1.0 を超えていたら、冷えた瞬間に飽和する設計である。
    """
    if ceiling_rps <= 0:
        raise ValueError("ceiling_rps は正の数を指定してください")
    return floor_at(entry_rps / ceiling_rps, 2)


def plan_markdown(ceiling_rps: float = CEILING_RPS, tenants: int = 3,
                  hit_rates: tuple[float, ...] = DEFAULT_HIT_RATES) -> str:
    """ヒット率を振った感度分析（Markdown）。"""
    lines = [
        "# 応答キャッシュのヒット率と入口の上限",
        "",
        f"- 上流の上限: {ceiling_rps:.2f} rps（並列2 の実測・2026-08-15 実測 / "
        "aarch64 / CPU 2コア / メモリ 5.8GB / Python 3.12.13 / llama.cpp `-t 2`）",
        f"- テナント数: {tenants}",
        "- ヒット率は**すべて仮定値**であり、本書の実測値ではありません",
        "",
        "| ヒット率（仮定） | 上流に届く割合 | 入口で受けられる rps | "
        "キーあたりの rate | 冷えたときの上流への倍率 |",
        "| --: | --: | --: | --: | --: |",
    ]
    for h in hit_rates:
        entry = entry_rps_allowed(ceiling_rps, h)
        lines.append(f"| {h:.2f} | {1.0 - h:.2f} | {entry:.2f} | "
                     f"{rate_per_key(entry, tenants):.2f} | "
                     f"{cold_multiplier(entry, ceiling_rps):.2f} 倍 |")
    lines += [
        "",
        "## 読み取れる関係",
        "",
        "- ヒット率を上げると入口を広く開けられる。増える量は "
        "`1 ÷ (1 − ヒット率)` 倍であり、比例ではない",
        "- 開けた入口は、キャッシュが冷えた瞬間にそのまま上流へ流れる。"
        "右端の倍率が 1.00 を超えている行は、冷えたら飽和する設計である",
        "- したがってヒット率を前提に入口を開けるなら、**冷えたときの縮退**"
        "（キューの上限・503 と Retry-After・階層を落とす）を先に用意する（S05）",
        "- 前方一致率（本書の実測 0.664 / 0.087）は応答キャッシュのヒット率では"
        "ない。前方一致はプリフィルを短くするだけで、上流の呼び出し回数は減らない（S06）",
    ]
    return "\n".join(lines)


def main() -> None:
    print(plan_markdown())
    print()
    for target in (2.0, 3.0):
        need = required_hit_rate(target, CEILING_RPS)
        print(f"入口で {target:.2f} rps を受けるのに必要なヒット率: "
              f"{need:.3f}（上流の上限 {CEILING_RPS:.2f} rps）")


if __name__ == "__main__":
    main()
