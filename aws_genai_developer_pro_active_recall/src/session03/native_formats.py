#!/usr/bin/env python3
"""セッション3: モデル固有のネイティブ形式と Converse API の比較。

同じ質問を Anthropic 形式 / Nova 形式 / Meta 形式の3通りで `InvokeModel` に投げ、
「リクエストの形」「テキストの取り出し方」「トークン数のキー名」「停止理由の値」が
モデルごとに違うことを出力します。そのうえで同じ3モデルを Converse API で呼び、
差が消えることを確認します。

    docker compose exec app python src/session03/native_formats.py
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "/workspace")

from awskit import clients  # noqa: E402

# 3形式に共通で投げる入力。<context> を付けているので、
# どのモデルも「資料に基づいた同じ答え」を返す（差はレスポンスの形だけになる）
QUESTION = (
    "有給休暇の繰越上限は何日ですか。\n"
    "<context>年次有給休暇の未消化分は翌年度に限り繰り越せますが、"
    "繰越上限は20日です。</context>"
)

MAX_TOKENS = 300

# 形式ごとに使うモデル ID（すべて bedrock_mock/catalog.py にある ID）
MODELS: dict[str, str] = {
    "anthropic": "anthropic.claude-3-5-haiku-20241022-v1:0",
    "nova": "amazon.nova-lite-v1:0",
    "meta": "meta.llama3-3-70b-instruct-v1:0",
}

# 「どこを読めばよいか」の一覧。ネイティブ形式を使う限り、
# この表がコードのどこかに必ず現れる（＝Converse に寄せると消える表）
SHAPE: dict[str, dict[str, str]] = {
    "anthropic": {
        "maxTokensKey": "max_tokens",
        "textPath": "content[0].text",
        "inputTokensKey": "usage.input_tokens",
        "stopKey": "stop_reason",
    },
    "nova": {
        "maxTokensKey": "inferenceConfig.maxTokens",
        "textPath": "output.message.content[0].text",
        "inputTokensKey": "usage.inputTokens",
        "stopKey": "stopReason",
    },
    "meta": {
        "maxTokensKey": "max_gen_len",
        "textPath": "generation",
        "inputTokensKey": "prompt_token_count",
        "stopKey": "stop_reason",
    },
}


def build_body(family: str, text: str, max_tokens: int = MAX_TOKENS) -> dict:
    """モデル固有のリクエスト本体を組み立てる。

    ここが「モデルを差し替えるとコードを書き換える羽目になる」箇所です。
    上限トークンのキー名も、メッセージの入れ方も、3形式で一致していません。
    """
    if family == "anthropic":
        return {
            # 実 Bedrock では必須。付けないと ValidationException になる
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "messages": [{"role": "user", "content": [{"type": "text", "text": text}]}],
        }
    if family == "nova":
        return {
            "messages": [{"role": "user", "content": [{"text": text}]}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.0},
        }
    if family == "meta":
        # Meta 系は messages 配列を取らず、1本の文字列を渡す。
        # 実 Bedrock の Llama では特殊トークン付きのテンプレートを自分で組む必要がある
        return {"prompt": text, "max_gen_len": max_tokens, "temperature": 0.0}
    raise ValueError(f"未対応の形式です: {family}")


def parse_payload(family: str, payload: dict) -> dict:
    """モデル固有のレスポンスから、共通の形へ詰め替える（自作アダプタ）。"""
    if family == "anthropic":
        return {
            "text": payload["content"][0]["text"],
            "inputTokens": payload["usage"]["input_tokens"],
            "outputTokens": payload["usage"]["output_tokens"],
            "stopReason": payload["stop_reason"],
        }
    if family == "nova":
        return {
            "text": payload["output"]["message"]["content"][0]["text"],
            "inputTokens": payload["usage"]["inputTokens"],
            "outputTokens": payload["usage"]["outputTokens"],
            "stopReason": payload["stopReason"],
        }
    if family == "meta":
        return {
            "text": payload["generation"],
            "inputTokens": payload["prompt_token_count"],
            "outputTokens": payload["generation_token_count"],
            "stopReason": payload["stop_reason"],
        }
    raise ValueError(f"未対応の形式です: {family}")


def invoke_native(runtime, family: str, text: str = QUESTION) -> tuple[dict, dict]:
    """`InvokeModel` をネイティブ形式で呼ぶ。(共通形へ詰め替えた結果, 生の payload) を返す。"""
    response = runtime.invoke_model(
        modelId=MODELS[family],
        contentType="application/json",
        accept="application/json",
        body=json.dumps(build_body(family, text), ensure_ascii=False),
    )
    payload = json.loads(response["body"].read())
    parsed = parse_payload(family, payload)
    # InvokeModel はレイテンシを本体に入れず、レスポンスヘッダだけに入れる
    headers = response["ResponseMetadata"]["HTTPHeaders"]
    parsed["latencyMs"] = int(headers.get("x-amzn-bedrock-invocation-latency", -1))
    return parsed, payload


def invoke_converse(runtime, model_id: str, text: str = QUESTION) -> dict:
    """Converse API で呼ぶ。モデル ID が変わっても引数の形は変わらない。"""
    response = runtime.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": text}]}],
        inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.0},
    )
    return {
        "text": response["output"]["message"]["content"][0]["text"],
        "inputTokens": response["usage"]["inputTokens"],
        "outputTokens": response["usage"]["outputTokens"],
        "stopReason": response["stopReason"],
        # Converse は本体に計測値を持つ。ヘッダを読む必要がない
        "latencyMs": response["metrics"]["latencyMs"],
    }


def main() -> None:
    runtime = clients.bedrock_runtime()

    print("=== 1. ネイティブ形式（InvokeModel）で同じ質問を3通り投げる ===")
    natives: dict[str, dict] = {}
    for family in ("anthropic", "nova", "meta"):
        parsed, payload = invoke_native(runtime, family)
        natives[family] = parsed
        shape = SHAPE[family]
        print(f"\n[{family}] modelId: {MODELS[family]}")
        print(f"  上限トークンのキー : {shape['maxTokensKey']}")
        print(f"  テキストの位置     : {shape['textPath']}")
        print(f"  入力トークンのキー : {shape['inputTokensKey']}")
        print(f"  停止理由           : {shape['stopKey']} = {parsed['stopReason']}")
        print(f"  トップレベルのキー : {sorted(payload.keys())}")
        print(
            f"  入力 {parsed['inputTokens']} tok / 出力 {parsed['outputTokens']} tok"
            f" / {parsed['latencyMs']} ms"
        )

    print("\n=== 2. 中身は同じ。違うのは形だけ ===")
    texts = {r["text"] for r in natives.values()}
    stops = ", ".join(f"{name}={r['stopReason']}" for name, r in natives.items())
    print(f"  3形式の回答が一致    : {len(texts) == 1}")
    print(f"  回答（先頭40文字）   : {natives['nova']['text'][:40]}")
    print(f"  停止理由の呼び方の差 : {stops}")

    print("\n=== 3. Converse API で同じ3モデルを呼ぶ（引数の形は1つ） ===")
    for family, model_id in MODELS.items():
        r = invoke_converse(runtime, model_id)
        print(
            f"[{family}] {r['stopReason']} / 入力 {r['inputTokens']} tok"
            f" / 出力 {r['outputTokens']} tok / {r['latencyMs']} ms"
        )
    print("\n  取り出し方はどのモデルでも output.message.content[0].text の1通りです")


if __name__ == "__main__":
    main()
