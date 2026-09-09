#!/usr/bin/env python3
"""セッション15: LLM-as-a-Judge（別のモデルに採点させ、機械判定と突き合わせる）。

    docker compose exec app python src/session15/judge.py

採点役の設計で外せない約束は3つです。

    1. **生成役と別のモデルを使う**（自分の答案を自分で採点させない）
    2. 採点結果も**出力契約**にする（自由文の講評は集計できない）
    3. 機械で分かることは機械で決め、採点役は**減点だけ**に使う（拒否権を持たせない）

3つめが本章の要点です。引用の有無・引用の裏取りは機械で確実に判定できます。
その判定を採点役が覆せる設計にすると、「judge が合格と言ったから出した」という
説明のつかない出力が生まれます。ここでは機械判定を**拒否権（veto）**にします。

同梱モックの採点役は本当に採点していません（決定的な固定キーの JSON を返すだけ）。
そこで本ファイルは「本物の採点役に返させたい契約」を `JUDGE_SCHEMA` として示し、
実行はモックが返す3キーを薄い層で写して通します。**採点役が信用できるかどうかの
検証（judge の偏り・人間評価との一致）はセッション18の範囲**なので、ここでは
「機械判定との一致率を測るところまで」で止めます。
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "/workspace")
for _dir in ("session04", "session05", "session06", "session14", "session15"):
    sys.path.insert(0, f"/workspace/src/{_dir}")

from awskit import clients  # noqa: E402

import prompt_registry as registry  # noqa: E402  セッション6（構造化出力の契約検査）

import provenance  # noqa: E402  セッション14
import transparency  # noqa: E402  本章（裏取り）

# 生成役（Nova Lite）と採点役（Claude 3.5 Haiku）は必ず別にする
GENERATOR_MODEL = transparency.MODEL_ID
JUDGE_MODEL = "anthropic.claude-3-5-haiku-20241022-v1:0"

MAX_TOKENS = 300

# 差し替えて壊す用の、存在しない出典
FAKE_URI = "s3://sample-shoji-docs/hr/paid-leave-v9.md"

# **本物の採点役に返させたい契約**（理想形）。自由文ではなく機械可読にする
JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["grounded", "citationSupported", "score", "reason"],
    "properties": {
        "grounded": {"type": "boolean"},
        "citationSupported": {"type": "boolean"},
        "score": {"type": "number", "minimum": 1, "maximum": 5},
        "reason": {"type": "string", "minLength": 1},
    },
}

JUDGE_SYSTEM = (
    "# 役割\n"
    "あなたは社内ヘルプデスクの回答を採点する審査役です。回答を書いたモデルとは別の"
    "モデルとして、与えられた根拠だけを見て採点します。\n\n"
    "# 指示\n"
    "1. <answer> の各文が <evidence> の記述で支えられているかを確かめます。\n"
    "2. 支えられていない文が1つでもあれば不合格にします。\n"
    "3. 根拠に無い一般知識で補いません。\n"
    "4. 採点結果は JSON オブジェクト1件だけを出力します。前置きは書きません。\n\n"
    "# 出力形式\n"
    "キーは grounded / citationSupported / score / reason の4つです。"
)

# モックが返す固定キーを本章の採点軸に写す薄い層（実物では JUDGE_SCHEMA を直接読む）
VERDICT_OF = {"positive": "pass", "neutral": "borderline", "negative": "fail"}


class SelfGradingError(RuntimeError):
    """生成役と採点役が同じモデルになっている（採点が自己弁護になる）。"""


def assert_distinct_models(generator_model_id: str, judge_model_id: str) -> None:
    """同じモデルに自分の答案を採点させない。

    同一モデルは同じ誤りを同じ理由で正しいと判断します（自己一致バイアス）。
    採点役を分けるのは精度の話ではなく、**独立した観測を1つ増やす**ためです。
    """
    if generator_model_id == judge_model_id:
        raise SelfGradingError(
            f"生成役と採点役が同じモデルです: {judge_model_id}（別のモデルを指定してください）"
        )


def mechanical_verdict(
    *, answer: str, sources: str, citations: list[dict], allowed_uris: set[str]
) -> dict:
    """機械で確実に分かることだけで合否を出す（採点役より前に置く）。"""
    grounded = registry.GROUNDING_MARKER in answer
    support = transparency.support_ratio(answer, sources)
    unknown = [
        citation["uri"] for citation in citations if citation["uri"] not in allowed_uris
    ]
    passed = bool(citations) and grounded and support == 1.0 and not unknown
    return {
        "verdict": "pass" if passed else "fail",
        "grounded": grounded,
        "supportRatio": support,
        "citationCount": len(citations),
        "unknownCitations": unknown,
    }


def build_prompt(*, answer: str, evidence: str) -> str:
    """採点用のメッセージ。**`<context>` という札は使いません。**

    同梱モックは `<context>` を見つけると「資料から答える」経路に入るため、
    採点役に渡す材料は `<answer>` と `<evidence>` という別の札で囲みます。
    実 Bedrock でも、採点対象と根拠は別の札で囲んだ方が取り違えが起きません。
    """
    return (
        "<answer>\n"
        f"{answer}\n"
        "</answer>\n"
        "<evidence>\n"
        f"{evidence}\n"
        "</evidence>\n"
        "上の回答を採点し、結果を JSON で返してください。"
    )


def score_answer(runtime, *, answer: str, evidence: str, judge_model: str = JUDGE_MODEL) -> dict:
    """採点役を1回呼ぶ。温度0なので**同じ入力なら同じ採点**になる。"""
    assert_distinct_models(GENERATOR_MODEL, judge_model)
    response = runtime.converse(
        modelId=judge_model,
        system=[{"text": JUDGE_SYSTEM}],
        messages=[{"role": "user", "content": [{"text": build_prompt(answer=answer, evidence=evidence)}]}],
        inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.0},
    )
    text = registry.text_of(response)
    # 採点結果も契約検査にかける。**壊れた採点は集計に混ぜない**
    payload = registry.validate_contract(text)
    return {
        "judgeModelId": judge_model,
        "verdict": VERDICT_OF[payload["sentiment"]],
        "reason": payload["summary"],
        "labels": payload["keywords"],
    }


def build_cases(results: dict) -> list[dict]:
    """透明性の演習の結果から、採点対象の4件を組む（追加の生成はしない）。"""
    good = results["rai-001"]
    refused = results["rai-006"]
    fabricated = results["rai-005"]
    allowed = {citation["uri"] for citation in good["citations"]}
    tampered = [dict(citation) for citation in good["citations"]]
    tampered[0]["uri"] = FAKE_URI
    return [
        {
            "id": "j-01",
            "label": "引用付きで資料の文をそのまま引いた回答",
            "answer": good["answer"],
            "evidence": good["sources"],
            "citations": good["citations"],
            "allowedUris": allowed,
        },
        {
            "id": "j-02",
            "label": "資料に答えが無いと述べた回答",
            "answer": refused["answer"],
            "evidence": refused["sources"],
            "citations": refused["citations"],
            "allowedUris": {c["uri"] for c in refused["citations"]},
        },
        {
            "id": "j-03",
            "label": "検索を通さずに作った回答（引用なし）",
            "answer": fabricated["answer"],
            "evidence": good["sources"],
            "citations": [],
            "allowedUris": allowed,
        },
        {
            "id": "j-04",
            "label": "引用の URI を差し替えた回答",
            "answer": good["answer"],
            "evidence": good["sources"],
            "citations": tampered,
            "allowedUris": allowed,
        },
    ]


def review(runtime, cases: list[dict]) -> dict:
    """機械判定 → 採点役 → 最終判定（機械が不合格なら採点役は覆せない）。"""
    rows: list[dict] = []
    for case in cases:
        mechanical = mechanical_verdict(
            answer=case["answer"],
            sources=case["evidence"],
            citations=case["citations"],
            allowed_uris=case["allowedUris"],
        )
        judged = score_answer(runtime, answer=case["answer"], evidence=case["evidence"])
        final = (
            "pass"
            if mechanical["verdict"] == "pass" and judged["verdict"] == "pass"
            else "fail"
        )
        rows.append(
            {
                "id": case["id"],
                "label": case["label"],
                "mechanical": mechanical,
                "judge": judged,
                "final": final,
                # 採点役の合否が、機械判定の合否と一致したか
                "agreed": (judged["verdict"] == "pass") == (mechanical["verdict"] == "pass"),
            }
        )
    agreed = sum(1 for row in rows if row["agreed"])
    return {
        "generatorModelId": GENERATOR_MODEL,
        "judgeModelId": JUDGE_MODEL,
        "rows": rows,
        "total": len(rows),
        "agreed": agreed,
        "agreementRate": round(agreed / len(rows), 4) if rows else 0.0,
        "vetoed": [row["id"] for row in rows if row["mechanical"]["verdict"] == "fail"],
    }


def line(row: dict) -> str:
    return (
        f"{row['id']} 機械={row['mechanical']['verdict']:<5}"
        f" 裏取り={row['mechanical']['supportRatio']:<6}"
        f" 引用={row['mechanical']['citationCount']}"
        f" 採点役={row['judge']['verdict']:<10}"
        f" 最終={row['final']:<5} 一致={'○' if row['agreed'] else '×'}"
        f"  {row['label']}"
    )


def main() -> None:
    state = provenance.bootstrap()
    runtime = clients.bedrock_runtime()
    results = transparency.run_all(ddb=state["ddb"], s3=state["s3"])
    report = review(runtime, build_cases(results))

    print("=== 1. 採点役に返させたい契約（理想形） ===")
    print(json.dumps(JUDGE_SCHEMA, ensure_ascii=False))

    print()
    print(f"=== 2. 採点結果（生成役 {report['generatorModelId']} / 採点役 {report['judgeModelId']}） ===")
    for row in report["rows"]:
        print(" ", line(row))

    print()
    print("=== 3. 機械判定と採点役の一致率 ===")
    print(f"  一致 {report['agreed']}/{report['total']} = {report['agreementRate']}")
    print(f"  機械判定が拒否権を使った件: {report['vetoed']}")
    print("  ※ 同梱モックの採点役は採点していません（固定キーを返すだけ）。")
    print("     一致率が低いこと自体が「採点役をまだ信用してはいけない」という観測です。")

    print()
    print("=== 4. 自分に自分を採点させようとすると止まる ===")
    try:
        assert_distinct_models(GENERATOR_MODEL, GENERATOR_MODEL)
    except SelfGradingError as error:
        print(f"  SelfGradingError: {error}")


if __name__ == "__main__":
    main()
