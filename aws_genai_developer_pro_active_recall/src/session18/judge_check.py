#!/usr/bin/env python3
"""セッション18: 採点役（LLM-as-a-Judge）を信じてよい範囲を決める。

    docker compose exec app python src/session18/judge_check.py

セッション15で作った採点役（`src/session15/judge.py`）を**そのまま**使います。本章が足すのは
「その採点役を信じてよいか」を決める手順です。手順は3つだけです。

    1. 機械で確実に分かる判定（引用の有無・引用の裏取り）を**正解**として置く
    2. 採点役の判定と突き合わせ、**食い違った件を数える**
    3. 一致率がしきい値を下回る採点役の判定は、**品質ゲートに使わない**

3のしきい値は精度の話ではなく責任の話です。「採点役が合格と言ったから出した」を
説明として通さないために、ゲートは機械判定だけで組みます（採点役は減点材料に使う）。

**機械判定にも限界があります。** 機械判定は「引用付きで答えたか」しか見ないので、
**断るのが正解の件も不合格**にします。だから機械判定を唯一の正解にはできません。
限界を数えておくのが本章の仕事です。
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/workspace")
for _dir in ("session04", "session05", "session06", "session14", "session15", "session18"):
    sys.path.insert(0, f"/workspace/src/{_dir}")

from awskit import clients  # noqa: E402

import judge  # noqa: E402  セッション15（別モデルの採点役・機械判定の拒否権）

import eval_dataset as dataset  # noqa: E402
import eval_harness as harness  # noqa: E402

# 採点役の判定をゲートに使ってよい最低の一致率。**下回るなら使わない**
TRUST_MIN_AGREEMENT = 0.9


def cases_from(generation: dict) -> list[dict]:
    """生成の評価の結果を、そのまま採点対象にする（追加の生成はしない）。"""
    return [
        {
            "id": row["id"],
            "answer": row["answer"],
            "evidence": row["sources"],
            "citations": row["citations"],
            "allowedUris": {citation["uri"] for citation in row["citations"]},
            # 断るのが正解の件か（機械判定の限界を数えるために持つ）
            "refusalIsCorrect": row["docId"] is None,
            "behaviourOk": row["ok"],
        }
        for row in generation["rows"]
    ]


def review(runtime, cases: list[dict]) -> dict:
    """機械判定 → 採点役 → 最終判定（機械が不合格なら採点役は覆せない）。"""
    rows: list[dict] = []
    for case in cases:
        mechanical = judge.mechanical_verdict(
            answer=case["answer"],
            sources=case["evidence"],
            citations=case["citations"],
            allowed_uris=case["allowedUris"],
        )
        judged = judge.score_answer(runtime, answer=case["answer"], evidence=case["evidence"])
        machine_pass = mechanical["verdict"] == "pass"
        judge_pass = judged["verdict"] == "pass"
        rows.append(
            {
                "id": case["id"],
                "mechanical": mechanical["verdict"],
                "judge": judged["verdict"],
                # 機械判定の拒否権。採点役が合格と言っても機械が不合格なら不合格
                "final": "pass" if (machine_pass and judge_pass) else "fail",
                "agreed": machine_pass == judge_pass,
                "refusalIsCorrect": case["refusalIsCorrect"],
                "behaviourOk": case["behaviourOk"],
            }
        )
    total = len(rows) or 1
    agreed = sum(1 for row in rows if row["agreed"])
    return {
        "generatorModelId": judge.GENERATOR_MODEL,
        "judgeModelId": judge.JUDGE_MODEL,
        "rows": rows,
        "total": len(rows),
        "agreed": agreed,
        "agreementRate": round(agreed / total, 4),
        "mechanicalPass": [row["id"] for row in rows if row["mechanical"] == "pass"],
        "mechanicalFail": [row["id"] for row in rows if row["mechanical"] != "pass"],
        # 機械判定が不合格にしたが、挙動としては正しい件（＝機械判定の限界）
        "mechanicalBlindSpots": [
            row["id"] for row in rows if row["mechanical"] != "pass" and row["behaviourOk"]
        ],
        "disagreed": [row["id"] for row in rows if not row["agreed"]],
        "vetoed": [row["id"] for row in rows if row["mechanical"] != "pass"],
    }


def veto_respected(report: dict) -> bool:
    """機械判定が不合格の件が、最終判定でも必ず不合格になっているか。"""
    return all(row["final"] == "fail" for row in report["rows"] if row["mechanical"] != "pass")


def usable_in_gate(report: dict, *, minimum: float = TRUST_MIN_AGREEMENT) -> bool:
    """採点役の判定を品質ゲートに使ってよいか。**一致率で決める。**"""
    return report["agreementRate"] >= minimum


def main() -> None:
    harness.reset_mock()
    runtime = clients.bedrock_runtime()
    agent = clients.agent_runtime()
    generation = harness.evaluate_generation(runtime, agent, dataset.rows())
    cases = cases_from(generation)
    report = review(runtime, cases)
    again = judge.score_answer(
        runtime, answer=cases[0]["answer"], evidence=cases[0]["evidence"]
    )

    print("=== 6. 採点役（LLM-as-a-Judge）の妥当性 ===")
    print(
        f"  生成役 {report['generatorModelId']} / 採点役 {report['judgeModelId']}（必ず別モデル）"
    )
    print(
        f"  対象 {report['total']} 件 / 採点役の呼び出し {report['total'] + 1} 回"
        "（再現性の確認 1 回を含む）"
    )
    first = report["rows"][0]
    print(f"  同じ入力なら同じ採点になる: {again['verdict'] == first['judge']}")
    print(f"  機械判定が不合格なら採点役は覆せない（拒否権）: {veto_respected(report)}")
    print(
        f"  機械判定の内訳: 合格 {len(report['mechanicalPass'])} 件 /"
        f" 不合格 {len(report['mechanicalFail'])} 件"
    )
    print(
        f"  そのうち {len(report['mechanicalBlindSpots'])} 件は「断るのが正解」の件"
        "（機械判定は引用付きで答えたかしか見ない）"
    )
    print(
        f"  信じてよい範囲: 一致率が {TRUST_MIN_AGREEMENT} を下回る採点役の判定は"
        "品質ゲートに使わない"
    )
    print("  同梱モックの採点役は採点していない（固定キーを返す）ため、この環境では常にゲート外です")

    print()
    print("=== 7. 参考: 一致率の実測（この値は本文に載せません） ===")
    print(f"  一致 {report['agreed']}/{report['total']} = {report['agreementRate']}")
    print(f"  食い違った件: {report['disagreed']}")
    print(f"  ゲートに使ってよいか: {usable_in_gate(report)}")
    print("  モックの採点役は採点していないので、この値は採点役の品質ではありません。")
    print("  実環境では、人が採点した数十件を正解にして同じ表を作り、しきい値で判断します。")


if __name__ == "__main__":
    main()
