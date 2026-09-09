#!/usr/bin/env python3
"""セッション6の検証。

プロンプトを「版のある資産」として扱えているかを、次の観点で確かめます。
**期待値と一致しなければ非0で終了します。**

判定に使うのは「存在」「集合の一致」「大小関係」「0との比較」だけです。
トークン数そのもの（絶対値）は system の長さで変わるため合否条件にしていません。

    docker compose exec app python src/session06/verify.py
"""

from __future__ import annotations

import copy
import json
import sys
import urllib.request
import uuid

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session06")

from awskit import clients  # noqa: E402

import conversation_store  # noqa: E402
import poc_probe  # noqa: E402
import prompt_audit  # noqa: E402
import prompt_registry as registry  # noqa: E402

FAILURES: list[str] = []

MODEL_ID = "amazon.nova-lite-v1:0"
NAME = registry.PROMPT_NAME
PARAMS = {"department": "情報システム部", "max_sentences": 3}
CACHE_PARAMS = {"department": "経理部", "max_sentences": 2}

QUESTION, FACT = poc_probe.QUESTIONS[0]
NEXT_QUESTION, NEXT_FACT = poc_probe.QUESTIONS[1]
UNRELATED_FACT = poc_probe.QUESTIONS[2][1]


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


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


def raises_value_error(func, *args, **kwargs) -> bool:
    try:
        func(*args, **kwargs)
    except ValueError:
        return True
    return False


def main() -> int:
    # 前の演習の障害注入とキャッシュが残っていると測定値が変わるため必ずリセットする
    mock_post("/_mock/reset", {})

    runtime = clients.bedrock_runtime()
    s3 = registry.ensure_bucket()
    ddb = conversation_store.ensure_table()

    # ------------------------------------------------------------------
    section("1. テンプレートの構造（4部品・必須フレーズ・変数の宣言）")
    for name, version, tpl in registry.all_local():
        check(
            f"{name} v{version} に4部品がそろっている",
            all(tpl.get(key) for key in registry.PART_KEYS),
            sorted(tpl),
        )
    for (name, version), phrases in registry.REQUIRED_PHRASES.items():
        missing = registry.missing_phrases(registry.local(name, version), phrases)
        check(f"{name} v{version} の必須フレーズが残っている", missing == [], missing)
    for name, version, tpl in registry.all_local():
        check(
            f"{name} v{version} の変数の宣言と本文が一致する",
            registry.used_variables(tpl) == set(registry.declared_variables(tpl)),
            (registry.used_variables(tpl), registry.declared_variables(tpl)),
        )
    check(
        "v1 と v2 はハッシュで区別できる",
        registry.checksum(registry.local(NAME, 1))
        != registry.checksum(registry.local(NAME, 2)),
    )

    # ------------------------------------------------------------------
    section("2. レンダリング（差し込みと、system に入れないもの）")
    tpl_v2 = registry.local(NAME, 2)
    blocks = registry.render_system(tpl_v2, PARAMS, cache=True)
    rendered = blocks[0]["text"]
    check("未解決の差し込み記法が残らない", "{{" not in rendered, rendered[:60])
    check("宣言した変数が差し込まれる", "情報システム部" in rendered and "3文以内" in rendered)
    check("4部品の見出しがすべて出る", all(
        head in rendered for head in ("# 役割", "# 指示", "# コンテキストの扱い", "# 出力形式")
    ))
    check("末尾に cachePoint が付く", blocks[-1] == {"cachePoint": {"type": "default"}}, blocks[-1])
    check(
        "宣言されていない変数は拒否される",
        raises_value_error(registry.render_system, tpl_v2, {**PARAMS, "user_input": "x"}),
    )
    check(
        "値が渡されていない変数は拒否される",
        raises_value_error(registry.render_system, tpl_v2, {"department": "情報システム部"}),
    )
    check("利用者の質問は system に入らない", QUESTION not in rendered)
    user_blocks = registry.render_user(QUESTION, context_text=FACT)
    check(
        "利用者の質問と資料は messages 側に入る",
        QUESTION in user_blocks[0]["text"]
        and f"<context>{FACT}</context>" in user_blocks[0]["text"],
    )

    # ------------------------------------------------------------------
    section("3. 置き場と版（公開・承認・ロールバック・ドリフト検知）")
    for version in (1, 2):
        registry.publish(s3, NAME, version)
    check("2つの版が置かれている", registry.list_versions(s3, NAME) == [1, 2], registry.list_versions(s3, NAME))
    check(
        "公開した版のハッシュが手元の定義と一致する",
        registry.fetch(s3, NAME, 1)["checksum"] == registry.checksum(registry.local(NAME, 1)),
    )
    registry.approve(s3, NAME, 1, approver="helpdesk-owner")
    approved_version, _, _ = registry.load_approved(s3, NAME)
    check("実行時に読むのは承認済みの版（v1）", approved_version == 1, approved_version)
    registry.approve(s3, NAME, 2, approver="helpdesk-owner")
    version, tpl, digest = registry.load_approved(s3, NAME)
    check("承認を切り替えると参照先が v2 になる", version == 2, version)
    check("承認済み版と手元の定義にドリフトが無い", digest == registry.checksum(registry.local(NAME, 2)))
    check("v1 は消えずに残る（ロールバック先がある）", 1 in registry.list_versions(s3, NAME))

    # ------------------------------------------------------------------
    section("4. 応答の契約（根拠・拒否・構造化出力・意図の値域）")
    messages = [{"role": "user", "content": registry.render_user(QUESTION, context_text=FACT)}]
    response = registry.call(
        runtime, tpl, model_id=MODEL_ID, messages=messages, params=PARAMS, cache=True
    )
    answer = registry.text_of(response)
    check("資料ありの回答に根拠の印が付く", registry.GROUNDING_MARKER in answer, answer[:40])
    check("資料の記述がそのまま根拠として現れる", FACT in answer, answer[:60])
    off_topic = [
        {"role": "user", "content": registry.render_user(QUESTION, context_text=UNRELATED_FACT)}
    ]
    refused = registry.text_of(
        registry.call(
            runtime, tpl, model_id=MODEL_ID, messages=off_topic, params=PARAMS, cache=True
        )
    )
    check("答えられない資料しか無ければ断る", registry.REFUSAL_MARKER in refused, refused[:40])
    check("断った回答に根拠の印は付かない", registry.GROUNDING_MARKER not in refused)

    contract_tpl = registry.local("answer-contract", 1)
    contract_messages = [
        {"role": "user", "content": [{"text": f"次の問い合わせを整理してください。\n問い合わせ: {QUESTION}"}]}
    ]
    payload = registry.validate_contract(
        registry.text_of(
            registry.call(runtime, contract_tpl, model_id=MODEL_ID, messages=contract_messages)
        )
    )
    check("構造化出力のキーが契約どおり", set(payload) == set(registry.ANSWER_CONTRACT_KEYS), sorted(payload))
    check("sentiment が値域内", payload["sentiment"] in registry.SENTIMENTS, payload["sentiment"])
    check(
        "契約を破った出力は検査で落ちる",
        raises_value_error(registry.validate_contract, '{"summary": "だけ"}'),
    )
    intent = conversation_store.classify_intent(runtime, "パスワードのリセットができません。")
    check("意図がラベル集合の中に収まる", intent in conversation_store.INTENT_LABELS, intent)
    check(
        "集合外のラベルは既定値へ落ちる",
        conversation_store.normalize_intent("勝手に作ったラベル")
        == conversation_store.FALLBACK_INTENT,
    )

    # ------------------------------------------------------------------
    section("5. 会話の文脈保持（保存は全件・提示は圧縮）")
    conversation_id = f"conv-{uuid.uuid4().hex[:8]}"
    logs = prompt_audit.ensure_log_group(
        stream=prompt_audit.stream_name(conversation_id)
    )
    stream = prompt_audit.stream_name(conversation_id)

    turn_no = 0
    for question, fact in poc_probe.QUESTIONS:
        recent = conversation_store.recent_turns(ddb, conversation_id)
        turn_messages = conversation_store.build_messages(recent, question, context_text=fact)
        turn_response = registry.call(
            runtime, tpl, model_id=MODEL_ID, messages=turn_messages, params=PARAMS, cache=True
        )
        turn_answer = registry.text_of(turn_response)
        turn_no += 1
        conversation_store.append_turn(ddb, conversation_id, turn_no, "user", question)
        turn_no += 1
        conversation_store.append_turn(ddb, conversation_id, turn_no, "assistant", turn_answer)
        prompt_audit.record(
            logs,
            stream=stream,
            prompt_name=NAME,
            prompt_version=version,
            prompt_checksum=digest,
            model_id=MODEL_ID,
            conversation_id=conversation_id,
            response=turn_response,
        )

    rows = conversation_store.turns(ddb, conversation_id)
    check("全6ターンが古い順で取れる", [r["turnNo"] for r in rows] == [1, 2, 3, 4, 5, 6], [r["turnNo"] for r in rows])
    check(
        "user と assistant が交互に並ぶ",
        [r["role"] for r in rows] == ["user", "assistant"] * 3,
        [r["role"] for r in rows],
    )
    check("履歴に資料（context）を混ぜていない", all("<context>" not in r["text"] for r in rows))
    recent = conversation_store.recent_turns(ddb, conversation_id)
    check("直近1往復だけを古い順で返す", [r["turnNo"] for r in recent] == [5, 6], [r["turnNo"] for r in recent])

    summary, kept = conversation_store.compact(runtime, ddb, conversation_id)
    check("古いターンが要約に畳まれる", summary.startswith("要約:"), summary[:24])
    check("直近1往復はそのまま残る", [r["turnNo"] for r in kept] == [5, 6], [r["turnNo"] for r in kept])
    check("要約しても DynamoDB の記録は消えない", len(conversation_store.turns(ddb, conversation_id)) == 6)

    full_usage = registry.call(
        runtime,
        tpl,
        model_id=MODEL_ID,
        messages=conversation_store.build_messages(rows, NEXT_QUESTION, context_text=NEXT_FACT),
        params=PARAMS,
        cache=True,
    )["usage"]
    compact_usage = registry.call(
        runtime,
        tpl,
        model_id=MODEL_ID,
        messages=conversation_store.build_messages(
            kept, NEXT_QUESTION, context_text=NEXT_FACT, history_summary=summary
        ),
        params=PARAMS,
        cache=True,
    )["usage"]
    check(
        "要約に畳むと入力トークンが減る",
        compact_usage["inputTokens"] < full_usage["inputTokens"],
        (compact_usage["inputTokens"], full_usage["inputTokens"]),
    )

    # ------------------------------------------------------------------
    section("6. 利用監査（版とハッシュは残す・本文は残さない）")
    entries = prompt_audit.read_all(logs, stream)
    check("会話3ターン分の監査記録が残る", len(entries) == 3, len(entries))
    check(
        "監査に必要な項目がそろう",
        all(field in entries[0] for field in prompt_audit.REQUIRED_FIELDS),
        sorted(entries[0]),
    )
    check(
        "どの版で答えたかを再現できる",
        entries[0]["promptVersion"] == 2 and entries[0]["promptChecksum"] == digest,
        (entries[0]["promptVersion"], entries[0]["promptChecksum"][:12]),
    )
    serialized = json.dumps(entries, ensure_ascii=False)
    check(
        "プロンプト本文と回答本文は残さない",
        QUESTION not in serialized and registry.GROUNDING_MARKER not in serialized,
    )

    # ------------------------------------------------------------------
    section("7. 長い system の再利用（cachePoint）")
    # ここまでの呼び出しでキャッシュが温まっているため、観測の前に必ず戻す
    mock_post("/_mock/reset", {})
    cache_messages = [
        {"role": "user", "content": registry.render_user(QUESTION, context_text=FACT)}
    ]

    def ask_cache(params: dict, *, cache: bool) -> dict:
        return registry.call(
            runtime,
            tpl,
            model_id=MODEL_ID,
            messages=cache_messages,
            params=params,
            cache=cache,
        )["usage"]

    first = ask_cache(CACHE_PARAMS, cache=True)
    second = ask_cache(CACHE_PARAMS, cache=True)
    tweaked = ask_cache({**CACHE_PARAMS, "max_sentences": 5}, cache=True)
    plain = ask_cache(CACHE_PARAMS, cache=False)

    check(
        "初回はキャッシュへの書き込みだけが起きる",
        first["cacheWriteInputTokens"] > 0 and first["cacheReadInputTokens"] == 0,
        first,
    )
    check(
        "2回目は読み出しに振り替わる（書き込みは起きない）",
        second["cacheReadInputTokens"] > 0 and second["cacheWriteInputTokens"] == 0,
        second,
    )
    check(
        "読み出しトークンは初回の書き込みトークンと同じ",
        second["cacheReadInputTokens"] == first["cacheWriteInputTokens"],
        (second["cacheReadInputTokens"], first["cacheWriteInputTokens"]),
    )
    check(
        "変数を1つ変えるとキャッシュは外れる",
        tweaked["cacheWriteInputTokens"] > 0 and tweaked["cacheReadInputTokens"] == 0,
        tweaked,
    )
    check(
        "cachePoint なしでは振り替えが起きない",
        plain["cacheReadInputTokens"] == 0 and plain["cacheWriteInputTokens"] == 0,
        plain,
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
    check("/_mock/usage のキャッシュ読み出しが 0 より大きい", mock_usage()["cacheReadTokens"] > 0)

    # ------------------------------------------------------------------
    section("8. 壊したテンプレートは検査で止まる（回帰テストが赤くなる）")
    broken = copy.deepcopy(registry.local(NAME, 2))
    broken["instructions"] = [s for s in broken["instructions"] if "資料に無いこと" not in s]
    check(
        "必須フレーズの欠落を検出できる",
        registry.missing_phrases(broken, registry.REQUIRED_PHRASES[(NAME, 2)])
        == ["資料に無いこと"],
        registry.missing_phrases(broken, registry.REQUIRED_PHRASES[(NAME, 2)]),
    )
    check("壊すとハッシュが変わる", registry.checksum(broken) != digest)
    published_immutable = False
    try:
        registry.publish(s3, NAME, 2, template=broken)
    except RuntimeError:
        published_immutable = True
    check("公開済みの版を別内容で上書きできない（版は不変）", published_immutable)
    check(
        "承認済み版は壊れていない（S3 側は無傷）",
        registry.load_approved(s3, NAME)[2] == digest,
    )

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション6の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
