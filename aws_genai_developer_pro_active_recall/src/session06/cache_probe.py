#!/usr/bin/env python3
"""セッション6: 長い system を再利用したときのトークンの振り替えを観測する。

`system` の末尾に `cachePoint` を置くと、1回目は `cacheWriteInputTokens`、
2回目以降（接頭辞が完全一致した場合）は `cacheReadInputTokens` に振り替わり、
`inputTokens` はキャッシュ分だけ小さくなります。

**接頭辞は完全一致でしか当たりません。** 変数の値を 3 から 4 に変えるだけで
外れることを、ここで自分の目で確かめておきます。

    docker compose exec app python src/session06/cache_probe.py
"""

from __future__ import annotations

import json
import sys
import urllib.request

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session06")

from awskit import clients  # noqa: E402

import poc_probe  # noqa: E402
import prompt_registry as registry  # noqa: E402

MODEL_ID = "amazon.nova-lite-v1:0"
QUESTION, FACT = poc_probe.QUESTIONS[0]

FAILURES: list[str] = []


def mock_post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{clients.mock_base_url()}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


def mock_usage() -> dict:
    with urllib.request.urlopen(
        f"{clients.mock_base_url()}/_mock/usage", timeout=10
    ) as res:
        return json.loads(res.read())


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def ask(runtime, tpl: dict, params: dict, *, cache: bool) -> dict:
    messages = [
        {"role": "user", "content": registry.render_user(QUESTION, context_text=FACT)}
    ]
    response = registry.call(
        runtime, tpl, model_id=MODEL_ID, messages=messages, params=params, cache=cache
    )
    return response["usage"]


def yn(value: int) -> str:
    return "あり" if value else "なし"


def main() -> int:
    # 前の演習でキャッシュが温まっていると「初回」が観測できない
    mock_post("/_mock/reset", {})

    s3 = registry.ensure_bucket()
    for version in (1, 2):
        registry.publish(s3, registry.PROMPT_NAME, version)
    registry.approve(s3, registry.PROMPT_NAME, 2, approver="helpdesk-owner")
    version, tpl, _ = registry.load_approved(s3, registry.PROMPT_NAME)

    print("=== プロンプトキャッシュの観測 ===")
    print(f"承認済みバージョン: {version}")
    print()

    three = {"department": "情報システム部", "max_sentences": 3}
    four = {"department": "情報システム部", "max_sentences": 4}

    runtime = clients.bedrock_runtime()
    first = ask(runtime, tpl, three, cache=True)
    second = ask(runtime, tpl, three, cache=True)
    tweaked = ask(runtime, tpl, four, cache=True)
    plain = ask(runtime, tpl, three, cache=False)

    rows = (
        ("cachePoint あり（初回）", first),
        ("cachePoint あり（2回目・同じ system）", second),
        ("変数を 3文 → 4文 に変更", tweaked),
        ("cachePoint なし（同じ system）", plain),
    )
    for index, (label, usage) in enumerate(rows, start=1):
        print(
            f"[{index}] {label} -> 書き込み {yn(usage['cacheWriteInputTokens'])}"
            f" / 読み出し {yn(usage['cacheReadInputTokens'])}"
        )
    print()

    check(
        "初回はキャッシュへの書き込みだけが起きる",
        first["cacheWriteInputTokens"] > 0 and first["cacheReadInputTokens"] == 0,
        first,
    )
    check(
        "2回目の読み出しトークンが初回の書き込みトークンと一致する",
        second["cacheReadInputTokens"] == first["cacheWriteInputTokens"],
        (second["cacheReadInputTokens"], first["cacheWriteInputTokens"]),
    )
    check(
        "変数を1つ変えるとキャッシュは外れる",
        tweaked["cacheWriteInputTokens"] > 0 and tweaked["cacheReadInputTokens"] == 0,
        tweaked,
    )
    check(
        "cachePoint ありの inputTokens は cachePoint なしより小さい",
        second["inputTokens"] < plain["inputTokens"],
        (second["inputTokens"], plain["inputTokens"]),
    )
    check(
        "減った分がキャッシュへ振り替わったトークン数と一致する",
        plain["inputTokens"] - second["inputTokens"] == second["cacheReadInputTokens"],
        (plain["inputTokens"], second["inputTokens"], second["cacheReadInputTokens"]),
    )
    check(
        "/_mock/usage のキャッシュ読み出しが 0 より大きい",
        mock_usage()["cacheReadTokens"] > 0,
    )

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の観測が期待と違います -> {FAILURES}")
        return 1
    print("観測完了（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
