#!/usr/bin/env python3
"""改善の優先度を決める（影響クエリ数 × 実装コスト × 副作用リスク）。

  python src/session17/priority.py

Recall の改善幅（実測）とトラフィック（ログ）はデータから決まる。
実装コストと副作用リスクは**測れない**ので、チームの見積もりを入れる欄にしてある。
ここに置いてある cost_days は「例として置いた仮の値」であって実測値ではない。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from metrics import ANSWERABLE_TYPES, load_log  # noqa: E402

CURRENT_BASELINE = "bm25/fixed"


@dataclass(frozen=True)
class Action:
    """改善の打ち手1つ。効果は実測、コストと副作用は見積もり。"""

    action_id: str
    name: str
    baseline: str  # どの構成を基準に測った数字か
    target_types: tuple[str, ...]
    recall_before: float
    recall_after: float
    cost_days: float  # 仮の値。チームの見積もりに置き換える
    side_effect: str  # 低 / 中 / 高
    side_effect_note: str
    evidence: str


ACTIONS: tuple[Action, ...] = (
    Action("syn_query", "クエリ側の同義語展開", CURRENT_BASELINE, ("abbrev",),
           0.182, 0.873, 2.0, "中",
           "辞書の維持が要る。誤展開すると無関係な文書が混ざる",
           "Review01（bm25/fixed・2026-08-16 実測）"),
    Action("syn_index", "索引側の同義語展開", CURRENT_BASELINE, ("abbrev",),
           0.182, 0.765, 3.0, "低",
           "検索時のコストはゼロ。辞書を変えるたびに再索引が要る",
           "セッション5（bm25/fixed・2026-08-16 実測）"),
    Action("hybrid_minmax", "ハイブリッド検索 min-max(0.3:1.0)", CURRENT_BASELINE,
           ANSWERABLE_TYPES, 0.763, 0.797, 4.0, "中",
           "スコア尺度の正規化と重みの再調整が要る",
           "セッション8（2026-08-15 実測）"),
    Action("dense_rerank50", "密ベクトル検索＋リランク（候補50）", CURRENT_BASELINE,
           ANSWERABLE_TYPES, 0.763, 0.818, 5.0, "高",
           "候補50 の中央値 1,571ms。500ms の予算では候補12 前後が上限",
           "セッション9（2026-08-15 実測）"),
    Action("zero_hit_guide", "ゼロヒット時に言い換え候補を出す", CURRENT_BASELINE,
           ("unanswerable",), 0.0, 0.0, 1.0, "低",
           "Recall では効果が測れない。ゼロヒット後の離脱率で測る",
           "ログのゼロヒット 10 行（すべて回答不能クエリ）"),
    Action("rerank_only", "リランクだけ足す", "dense/fixed",
           ANSWERABLE_TYPES, 0.783, 0.818, 3.0, "高",
           "土俵違いの例。この数字は密ベクトル検索を基準に測ったもの",
           "セッション9（dense/fixed・2026-08-15 実測）"),
)


def traffic_rows(log: list[dict], types) -> int:
    wanted = set(types)
    return sum(1 for r in log if r["query_type"] in wanted)


def answerable_rows(log: list[dict]) -> int:
    """Recall を定義できる行数（回答不能クエリを除く）。"""
    return traffic_rows(log, ANSWERABLE_TYPES)


def expected_gain(log: list[dict], action: Action) -> float:
    """全体の Recall@10 をどれだけ押し上げるか（対象トラフィックの割合 × 改善幅）。"""
    if action.recall_after == action.recall_before:
        return 0.0
    share = traffic_rows(log, action.target_types) / answerable_rows(log)
    return share * (action.recall_after - action.recall_before)


def score(log: list[dict], action: Action) -> float:
    """コスト1人日あたりの期待改善量。"""
    return expected_gain(log, action) / action.cost_days


def check_baselines(actions=ACTIONS, current: str = CURRENT_BASELINE) -> list[str]:
    """いまの構成と違う基準で測られた打ち手を洗い出す。"""
    return [a.action_id for a in actions if a.baseline != current]


def rank(log: list[dict], actions=ACTIONS, *, key: str = "score",
         exclude_side_effects: tuple[str, ...] = (),
         current: str = CURRENT_BASELINE) -> list[Action]:
    """打ち手を並べる。土俵が違う数字が混ざっていたら止める。"""
    foreign = [a.action_id for a in actions if a.baseline != current]
    if foreign:
        raise ValueError(
            f"基準が違う打ち手が混ざっています: {foreign}。"
            f"いまの構成は {current} です。同じ基準で測り直すか、除いてから並べてください。"
        )
    if key not in ("score", "gain"):
        raise ValueError(f"未知の key です: {key}")
    target = [a for a in actions if a.side_effect not in exclude_side_effects]
    metric = score if key == "score" else expected_gain
    return sorted(target, key=lambda a: (-metric(log, a), a.action_id))


def comparable(actions=ACTIONS, current: str = CURRENT_BASELINE) -> tuple[Action, ...]:
    return tuple(a for a in actions if a.baseline == current)


def main() -> None:
    log = load_log()
    actions = comparable()

    print("=== 土俵の確認 ===")
    for action_id in check_baselines():
        base = next(a.baseline for a in ACTIONS if a.action_id == action_id)
        print(f"基準が違うので同じ表に並べない : {action_id}（{base} 基準）")

    print(f"\n=== 打ち手の候補（基準 {CURRENT_BASELINE}・ログ {len(log)} 行）===")
    for action in actions:
        rows = traffic_rows(log, action.target_types)
        print(f"[{action.action_id}] {action.name}")
        print(f"  対象 : {'+'.join(action.target_types)}（{rows} 行 / 全 {len(log)} 行）")
        print(f"  効果 : {action.recall_before:.3f} -> {action.recall_after:.3f}"
              f"（{action.evidence}）")
        print(f"  期待改善量 : {expected_gain(log, action):.4f}"
              f" / コスト {action.cost_days:.0f} 人日（仮）/ 副作用 {action.side_effect}")

    print("\n=== 期待改善量だけで並べる ===")
    for i, action in enumerate(rank(log, actions, key="gain"), start=1):
        print(f"{i}. {action.action_id} : {expected_gain(log, action):.4f}")

    print("\n=== コストで割って並べる ===")
    for i, action in enumerate(rank(log, actions, key="score"), start=1):
        print(f"{i}. {action.action_id} : {score(log, action):.4f}")

    print("\n=== 副作用「高」を外して並べる ===")
    for i, action in enumerate(
            rank(log, actions, key="score", exclude_side_effects=("高",)), start=1):
        print(f"{i}. {action.action_id} : {score(log, action):.4f}")


if __name__ == "__main__":
    main()
