#!/usr/bin/env python3
"""最初の1本。Converse API で基盤モデルを呼び、トークン数とコストを表示する。

同じ質問を「資料あり」「資料なし」の2通りで投げる。資料を渡さないと、
モデルはそれらしい数字を添えて作り話をする。この差が本教材の出発点になる。

    docker compose exec app python src/session00/hello_bedrock.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/workspace")

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

MODEL_ID = "amazon.nova-lite-v1:0"


QUESTION = "有給休暇の繰越上限は何日ですか。"
CONTEXT = (
    "<context>年次有給休暇の未消化分は翌年度に限り繰り越せますが、"
    "繰越上限は20日です。</context>"
)

CASES = (
    ("資料あり（<context> を渡す）", f"{QUESTION}\n{CONTEXT}"),
    ("資料なし（<context> を渡さない）", QUESTION),
)


def ask(runtime, prompt: str) -> dict:
    return runtime.converse(
        modelId=MODEL_ID,
        # system は「役割の固定」に使う。ユーザー入力と混ぜないことが
        # プロンプトインジェクション対策の第一歩になる
        system=[{"text": "あなたは社内ヘルプデスクの案内役です。資料に無いことは答えません。"}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 300, "temperature": 0.0},
    )


def main() -> None:
    runtime = clients.bedrock_runtime()

    for label, prompt in CASES:
        response = ask(runtime, prompt)
        text = response["output"]["message"]["content"][0]["text"]
        usage = response["usage"]
        cost = catalog.cost_usd(MODEL_ID, usage["inputTokens"], usage["outputTokens"])

        print(f"=== {label} ===")
        print("--- 回答 ---")
        print(text)
        print()
        print("--- 計測 ---")
        print(f"stopReason      : {response['stopReason']}")
        print(f"入力トークン     : {usage['inputTokens']}")
        print(f"出力トークン     : {usage['outputTokens']}")
        print(f"レイテンシ(ms)   : {response['metrics']['latencyMs']}")
        print(f"推定コスト(USD)  : {cost}")
        print()


if __name__ == "__main__":
    main()
