#!/usr/bin/env python3
"""セッション12: 敵対的テストの自動化（層ごとの遮断を数える）。

    docker compose exec app python src/session12/redteam.py

`attack_set.PROBES` を4層のパイプラインに流し、**どの層が何を止めたか**を数えます。
1回の実行で分かるのは次の4つです。

    1. 攻撃として作った入力を、どの層が止めたか
    2. 通るべき入力を、どこかの層が誤って止めていないか
    3. 遮断ではなく「無害化して通した」件数（正規化・PII 匿名化）
    4. 基盤モデル（FM）を実際に呼んだ件数（＝課金とレイテンシが発生した件数）

**指標としての設計（判定の妥当性・目標値・回帰の基準）はセッション18の範囲です。**
本章は「層ごとに何が起きたかを観察する」ところまでを扱います。
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session12")

import attack_set  # noqa: E402
import safety  # noqa: E402

LAYERS = ("L1", "L2", "L3", "L4")

# L1 が「直して通した」ことを表す修復名
L1_REPAIRS = {"nfkc", "boundary_tag", "whitespace"}


def run(pipeline: safety.SafetyPipeline | None = None, probes=None) -> dict:
    """検査セットを流して集計を返す。**副作用は基盤モデルの呼び出しだけ。**"""
    pipeline = pipeline or safety.SafetyPipeline()
    probes = probes or attack_set.PROBES

    outcomes: dict[str, safety.Outcome] = {}
    mismatches: list[str] = []
    for probe in probes:
        outcome = pipeline.handle(probe.text)
        outcomes[probe.probe_id] = outcome
        if outcome.layer != probe.expect:
            mismatches.append(
                f"{probe.probe_id}: 宣言 {probe.expect} / 実測 {outcome.layer}"
                f"（{outcome.reason}）"
            )

    blocked = {
        layer: sum(1 for o in outcomes.values() if o.decision == "block" and o.layer == layer)
        for layer in LAYERS
    }
    reached: dict[str, int] = {}
    remaining = len(probes)
    for layer in LAYERS:
        reached[layer] = remaining
        remaining -= blocked[layer]

    attack = [p for p in probes if p.kind == "attack"]
    benign = [p for p in probes if p.kind == "benign"]
    return {
        "total": len(probes),
        "reached": reached,
        "blocked": blocked,
        "allowed": sum(1 for o in outcomes.values() if o.decision == "allow"),
        "attackTotal": len(attack),
        "attackBlocked": sum(
            1 for p in attack if outcomes[p.probe_id].decision == "block"
        ),
        "benignTotal": len(benign),
        "benignPassed": sum(
            1 for p in benign if outcomes[p.probe_id].decision == "allow"
        ),
        "overBlocked": [
            p.probe_id for p in benign if outcomes[p.probe_id].decision == "block"
        ],
        "repairedAtL1": sum(
            1 for o in outcomes.values() if L1_REPAIRS & set(o.repairs)
        ),
        "piiAnonymized": sum(
            1 for o in outcomes.values() if "pii_anonymized" in o.repairs
        ),
        "modelCalls": sum(1 for o in outcomes.values() if o.model_called),
        "mismatches": mismatches,
        "outcomes": outcomes,
    }


def report(summary: dict) -> None:
    print(f"=== 検査セット {summary['total']} 件を4層に流す ===")
    print(f"  攻撃として作った入力: {summary['attackTotal']} 件")
    print(f"  通るべき入力: {summary['benignTotal']} 件")
    print()
    print("=== 層ごとに何を止めたか ===")
    for layer in LAYERS:
        reached = summary["reached"][layer]
        blocked = summary["blocked"][layer]
        print(f"  {layer}: 到達 {reached} / 遮断 {blocked} / 通過 {reached - blocked}")
    print()
    print("=== 結果 ===")
    print(f"  攻撃の遮断: {summary['attackBlocked']} / {summary['attackTotal']}")
    print(f"  通るべき入力の通過: {summary['benignPassed']} / {summary['benignTotal']}")
    # 過剰遮断は「どの層が・なぜ」まで出す。原因が違えば対策も違う
    for probe_id in summary["overBlocked"]:
        outcome = summary["outcomes"][probe_id]
        print(
            f"  過剰遮断: {probe_id} {outcome.layer} {outcome.reason}"
            f"（{attack_set.by_id(probe_id).text}）"
        )
    print(f"  L1 で無害化して通した: {summary['repairedAtL1']} 件")
    print(f"  L2 で PII を匿名化した: {summary['piiAnonymized']} 件")
    print(f"  基盤モデルを呼んだ: {summary['modelCalls']} / {summary['total']} 件")
    print(f"  宣言と実測の食い違い: {len(summary['mismatches'])} 件")
    for line in summary["mismatches"]:
        print(f"    - {line}")


def details(summary: dict) -> None:
    """1件ずつの結末。原因を追うときだけ使う（既定では表示しない）。"""
    for probe in attack_set.PROBES:
        outcome = summary["outcomes"][probe.probe_id]
        print(
            f"  {probe.probe_id} {probe.kind:<6} {outcome.layer:<5}"
            f" {outcome.reason:<34} {probe.note}"
        )


def main() -> None:
    summary = run()
    report(summary)
    if "--detail" in sys.argv:
        print()
        print("=== 1件ずつの結末 ===")
        details(summary)


if __name__ == "__main__":
    main()
