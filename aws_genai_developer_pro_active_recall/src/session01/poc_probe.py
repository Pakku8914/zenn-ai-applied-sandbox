#!/usr/bin/env python3
"""セッション1: PoC プローブ。

同じ質問を「資料を渡さない」「資料を1件渡す」の2条件で投げ、判定表を出す。
判定は 1. 必須条件（根拠提示率）→ 2. 性能条件（トークン・レイテンシ・コスト）の順。

    docker compose exec app python src/session01/poc_probe.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/workspace")

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

MODEL_ID = "amazon.nova-lite-v1:0"

# system は「役割の固定」に使う。ユーザー入力と混ぜない
SYSTEM_PROMPT = "あなたは社内ヘルプデスクの案内役です。資料に無いことは答えません。"

# 「根拠を提示できた」と機械判定するための印。
# 実務では引用（citations）の有無で判定するが、PoC ではこの程度の単純な
# 判定でも「資料に基づいて答えたか」を数えられる
GROUNDING_MARKER = "提供された資料によると"

# PoC の合格条件（本番へ進んでよいと言える線）。数字は要件から先に決めておく。
# 「動かしてから決める」と、都合のよい線に後付けで下げてしまう
CRITERIA = {
    "grounded_rate_min": 0.90,  # 根拠提示率（必須条件）
    "avg_latency_ms_max": 1500,  # 1件あたりの平均レイテンシ
    "usd_per_1k_max": 0.50,  # 1,000件あたりの推定コスト（USD）
}

# 質問と、その答えが書かれている社内文書の一文（fixtures/kb_corpus.json より）
QUESTIONS: list[tuple[str, str]] = [
    (
        "有給休暇の繰越上限は何日ですか。",
        "年次有給休暇の未消化分は翌年度に限り繰り越せますが、繰越上限は20日です。",
    ),
    (
        "在宅勤務は週に何日まで認められますか。",
        "在宅勤務は週3日を上限として認められます。",
    ),
    (
        "国内出張の宿泊費の上限はいくらですか。",
        "宿泊費の上限は国内出張が1泊15000円、海外出張が1泊25000円です。",
    ),
]


def ask(runtime, question: str, source: str | None) -> dict:
    """1問を投げ、回答と計測値をまとめて返す。

    `source` が None なら資料を渡さない（プロンプトのみ）。
    渡す場合は `<context>` で囲んで「ここが根拠だ」と明示する。
    """
    text = question if source is None else f"{question}\n<context>{source}</context>"
    response = runtime.converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": text}]}],
        inferenceConfig={"maxTokens": 300, "temperature": 0.0},
    )
    answer = response["output"]["message"]["content"][0]["text"]
    usage = response["usage"]
    return {
        "question": question,
        "answer": answer,
        "grounded": GROUNDING_MARKER in answer,
        "inputTokens": usage["inputTokens"],
        "outputTokens": usage["outputTokens"],
        "latencyMs": response["metrics"]["latencyMs"],
        "stopReason": response["stopReason"],
    }


def run(runtime, *, with_source: bool) -> list[dict]:
    """全問を1条件で実行する。"""
    return [ask(runtime, q, s if with_source else None) for q, s in QUESTIONS]


def summarize(results: list[dict]) -> dict:
    """PoC の判定に使う集計値を作る。"""
    n = len(results)
    grounded = sum(1 for r in results if r["grounded"])
    total_in = sum(r["inputTokens"] for r in results)
    total_out = sum(r["outputTokens"] for r in results)
    usd = catalog.cost_usd(MODEL_ID, total_in, total_out)
    return {
        "n": n,
        "grounded": grounded,
        "groundedRate": grounded / n,
        "avgInputTokens": total_in / n,
        "avgOutputTokens": total_out / n,
        "avgLatencyMs": sum(r["latencyMs"] for r in results) / n,
        "usdTotal": usd,
        "usdPer1k": usd / n * 1000,
    }


def judge(summary: dict) -> tuple[bool, str]:
    """(合格したか, 理由) を返す。必須条件 → 性能条件の順に見る。"""
    if summary["groundedRate"] < CRITERIA["grounded_rate_min"]:
        return False, "必須条件を満たさないため、トークンとレイテンシの計測は行いません"
    ng: list[str] = []
    if summary["avgLatencyMs"] > CRITERIA["avg_latency_ms_max"]:
        ng.append("平均レイテンシ超過")
    if summary["usdPer1k"] > CRITERIA["usd_per_1k_max"]:
        ng.append("コスト超過")
    if ng:
        return False, " / ".join(ng)
    return True, "根拠提示率・レイテンシ・コストのすべてが合格条件を満たしました"


def main() -> None:
    runtime = clients.bedrock_runtime()

    print("=== サンプル商事ヘルプデスク PoC プローブ ===")
    print(f"モデル: {MODEL_ID} / 質問{len(QUESTIONS)}件")

    # --- 条件A: プロンプトのみ ------------------------------------------------
    print()
    print("--- 条件A: プロンプトのみ（社内資料を渡さない） ---")
    plain = run(runtime, with_source=False)
    for i, r in enumerate(plain, start=1):
        mark = "○" if r["grounded"] else "×"
        print(f"[Q{i}] 根拠提示: {mark}  stopReason: {r['stopReason']}")
    sa = summarize(plain)
    print(f"  根拠提示率: {sa['grounded']}/{sa['n']} = {sa['groundedRate']:.0%}")
    ok_a, why_a = judge(sa)
    print(f"  判定: {'GO' if ok_a else 'NO-GO'}（{why_a}）")

    # --- 条件B: 社内資料を1件渡す --------------------------------------------
    print()
    print("--- 条件B: 社内資料を1件渡す（グラウンディングあり） ---")
    grounded = run(runtime, with_source=True)
    for i, r in enumerate(grounded, start=1):
        mark = "○" if r["grounded"] else "×"
        print(
            f"[Q{i}] 根拠提示: {mark}  "
            f"入力 {r['inputTokens']} tok  "
            f"出力 {r['outputTokens']} tok  "
            f"{r['latencyMs']} ms"
        )
    sb = summarize(grounded)
    print(f"  根拠提示率    : {sb['grounded']}/{sb['n']} = {sb['groundedRate']:.0%}")
    print(f"  平均入力      : {sb['avgInputTokens']:.1f} tok")
    print(f"  平均出力      : {sb['avgOutputTokens']:.1f} tok")
    print(f"  平均レイテンシ: {sb['avgLatencyMs']:.1f} ms")
    print(
        f"  推定コスト    : {sb['usdTotal']:.6f} USD（{sb['n']}件）"
        f" / {sb['usdPer1k']:.3f} USD（1,000件換算）"
    )
    ok_b, why_b = judge(sb)
    print(f"  判定: {'GO' if ok_b else 'NO-GO'}（{why_b}）")

    # --- 参考: 条件A の回答全文 ----------------------------------------------
    # ここに出る数値・日付は社内文書のどこにも存在しない。
    # 「もっともらしいが根拠がない」がハルシネーションの実物である
    print()
    print("--- 参考: 条件A で返ってきた回答（社内資料には存在しない内容です） ---")
    for i, r in enumerate(plain, start=1):
        print(f"[Q{i}] {r['question']}")
        print(f"      {r['answer']}")


if __name__ == "__main__":
    main()
