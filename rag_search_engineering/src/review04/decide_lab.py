#!/usr/bin/env python3
"""横断復習04：流行の道具（GraphRAG）を「測ってから入れる」判断を数字にする。

セッション14の実測をそのまま定数に写し、次の3つを計算する。

  1. 作ったエッジのうち、検索では届かない場所に架かっているのは何%か
  2. 代替案（事前構築ゼロの参照追跡）で何問解けるか
  3. その「3問中3問」を、偶然では起きないと言えるか（セッション2の少数サンプル）

グラフは作り直さない（`src/session14/build_graph.py` の出力を転記している）。

実行:  docker compose exec app python src/review04/decide_lab.py
"""

from __future__ import annotations

import math

# --- セッション14の実測（2026-08-15 / aarch64 / CPU 2コア / メモリ 5.8GB）---
NODES = 307              # 文書 301 + 部署 6
EDGES = 375
EDGE_TYPES: dict[str, int] = {"related": 156, "mentions": 216, "delegates_to": 3}
CROSS_THEME_EDGES = 3    # 主題（語彙のかたまり）をまたぐエッジ
EDGES_AFTER_TITLE_CHANGE = 372  # 参照先のタイトルを1件変えたあとのエッジ数

MULTIHOP_TOTAL = 3       # マルチホップ質問の件数
MULTIHOP: dict[str, int] = {
    "上位10件のみ": 0,
    "親子チャンク": 0,
    "グラフ1ホップ（delegates_to）": 3,
    "参照追跡（事前構築ゼロ）": 3,
}

# 「測っていない」欄。埋めないまま残すことがこの表の仕事
UNMEASURED: tuple[str, ...] = (
    "集約質問・全体要約の件数（判定データが無いので精度を出していない）",
    "本番コーパスでの主題またぎ比（0.8% は本書の合成コーパスの値）",
    "グラフを毎日更新したときの構築時間と失敗率",
    "参照追跡が増やす1リクエストのレイテンシ（追加の検索1ラウンド）",
)


def edge_type_total() -> int:
    """型別の内訳が合計と合うか。合わない表は読者にも自分にも嘘をつく。"""
    return sum(EDGE_TYPES.values())


def cross_theme_share() -> float:
    """検索では届かない場所に架かっているエッジの割合。"""
    return CROSS_THEME_EDGES / EDGES


def wasted_edges() -> int:
    """同じ主題の中に引いた（検索でも届く）エッジの数。"""
    return EDGES - CROSS_THEME_EDGES


def edges_lost_by_title_change() -> int:
    """タイトルを1件変えただけで静かに消えるエッジの数。"""
    return EDGES - EDGES_AFTER_TITLE_CHANGE


def binom_tail_ge(n: int, k: int, p: float = 0.5) -> float:
    """二項分布の上側確率 P(X >= k)。互角のときに k 勝以上する確率。"""
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def luck_probability(wins: int = MULTIHOP_TOTAL, n: int = MULTIHOP_TOTAL) -> float:
    """当てずっぽう（勝率50%）でも n 問中 wins 問に届いてしまう確率。"""
    return binom_tail_ge(n, wins, 0.5)


def alternatives_tie() -> bool:
    """グラフと代替案が同点かどうか。同点なら「入れない」が既定になる。"""
    return MULTIHOP["グラフ1ホップ（delegates_to）"] == MULTIHOP["参照追跡（事前構築ゼロ）"]


def decision_rows() -> list[tuple[str, str, str, str]]:
    """導入判断の表。（打ち手 / 解けた件数 / 事前コスト / 維持コスト）"""
    return [
        ("上位10件のみ（現状）", f"{MULTIHOP['上位10件のみ']}/{MULTIHOP_TOTAL}", "なし", "なし"),
        ("親子チャンク", f"{MULTIHOP['親子チャンク']}/{MULTIHOP_TOTAL}",
         "チャンク方式の変更（並行構築＋切り替え）", "小"),
        ("参照追跡（多段検索）", f"{MULTIHOP['参照追跡（事前構築ゼロ）']}/{MULTIHOP_TOTAL}",
         "委任表現の抽出ルールのみ", "小（検索1ラウンド増）"),
        ("参照グラフ（GraphRAG）", f"{MULTIHOP['グラフ1ホップ（delegates_to）']}/{MULTIHOP_TOTAL}",
         f"ノード{NODES}・エッジ{EDGES}の構築", "大（タイトル変更で静かに壊れる）"),
    ]


def verdict() -> tuple[str, list[str]]:
    """判断と、その根拠。根拠はすべて数字にひもづける。"""
    reasons = [
        f"{EDGES}本のうち検索で届かない場所に架かっているのは {CROSS_THEME_EDGES}本"
        f"（{cross_theme_share() * 100:.1f}%）。残り {wasted_edges()}本は作らなくても困らなかった",
        f"代替案（参照追跡）が同じ {MULTIHOP['参照追跡（事前構築ゼロ）']}/{MULTIHOP_TOTAL} に届く",
        f"タイトルを1件変えるだけでエッジが {EDGES} -> {EDGES_AFTER_TITLE_CHANGE} に減り、"
        "エラーは出ない（維持コストが人手に化ける）",
        f"ただし判断の母数は {MULTIHOP_TOTAL} 問しかない。当てずっぽうでも "
        f"{luck_probability() * 100:.1f}% の確率で同じ結果になる",
    ]
    return "入れない（参照追跡で代替する）", reasons


def main() -> None:
    print("=== 1. グラフの規模と内訳（セッション14の実測を転記）===")
    print(f"  ノード {NODES} / エッジ {EDGES}")
    for name, n in EDGE_TYPES.items():
        print(f"    {name:<13} {n:>4} 本")
    print(f"    合計          {edge_type_total():>4} 本（表の合計と一致: "
          f"{edge_type_total() == EDGES}）")
    print(f"  主題をまたぐエッジ: {CROSS_THEME_EDGES} / {EDGES} "
          f"= {cross_theme_share() * 100:.1f}%")

    print("\n=== 2. 打ち手ごとに何問解けたか（マルチホップ質問 3問）===")
    for move, solved, setup, upkeep in decision_rows():
        print(f"  {move:<24} {solved:<5} 事前 {setup:<34} 維持 {upkeep}")

    print("\n=== 3. 3問で判断することの危うさ（セッション2）===")
    print(f"  当てずっぽうで 3/3 に届く確率        : {luck_probability():.6f}")
    print(f"  互角の検索器が 10 問中 7 勝以上する確率: {binom_tail_ge(10, 7):.6f}")
    print(f"  互角の検索器が 20 問中 15 勝以上      : {binom_tail_ge(20, 15):.6f}")

    decision, reasons = verdict()
    print(f"\n=== 4. 判断: {decision} ===")
    for i, r in enumerate(reasons, start=1):
        print(f"  ({i}) {r}")

    print("\n=== 5. 測っていないこと（埋めないまま残す）===")
    for item in UNMEASURED:
        print(f"  - {item}")


if __name__ == "__main__":
    main()
