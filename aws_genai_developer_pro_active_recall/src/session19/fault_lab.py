#!/usr/bin/env python3
"""セッション19: 障害注入で6つの症状を確実に起こし、ログだけで原因へたどる。

    docker compose exec app python src/session19/fault_lab.py

前章までに作ったものは**そのまま使います**。本章が足すのは切り分けの手順だけです。

    セッション02  ModelRouter / FATAL_CODES     … 切り替えても直らないエラーの分類
    セッション06  prompt_registry               … 版とハッシュ（プロンプト起因の切り分け）
    セッション10  max_attempts + 1 回の実測     … リトライが吸収した回数の数え方
    セッション12  triage.py の ablation         … 共通語を数えて噛み合わせを見る
    セッション14  provenance.py の説明責任ログ  … 切り分けの一次情報（outcome の4値）

**後片付けを徹底します。** 障害注入はプロセス内の共有状態を書き換えるため、
残したまま次の検証へ進むと**関係のないセッションの verify が落ちます**。
各実験は `try/finally` で囲み、`finally` で必ず `POST /_mock/reset` を呼びます。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")
sys.path.insert(0, "/workspace/src/session04")
sys.path.insert(0, "/workspace/src/session05")
sys.path.insert(0, "/workspace/src/session06")
sys.path.insert(0, "/workspace/src/session14")
sys.path.insert(0, "/workspace/src/session19")

from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402

import model_router  # noqa: E402  セッション2（フェイルオーバー・障害注入の入口）
import poc_probe  # noqa: E402  セッション1（同一入力で計測を再現する）
import prompt_registry as registry  # noqa: E402  セッション6（版・ハッシュ・印）
import provenance  # noqa: E402  セッション14（説明責任ログ）

import diagnose  # noqa: E402  本章の切り分けツール

# ---------------------------------------------------------------------------
# 診断に使う質問（**同じ骨格で流し、変えるのは1か所だけ**にする）
# ---------------------------------------------------------------------------

# 漢字語（認証・必要）を資料と共有しているため、根拠つきで答えられる
HEALTHY = {
    "id": "diag-ok",
    "department": "情報システム部",
    "category": "IT",
    "question": "パスワードのリセットにはどの認証が必要ですか。",
}
# 上と同じ質問。違うのは force_max_tokens を注入することだけ
TRUNCATED = {**HEALTHY, "id": "diag-trunc"}
# カタカナ語しか手がかりが無い質問。**検索は当たるが生成が断る**
KATAKANA = {
    "id": "diag-kana",
    "department": "情報システム部",
    "category": "IT",
    "question": "パスワードリセットの手順を教えてください。",
}
# 該当する分類の文書が1件も無い（＝引用ゼロ。モデルを呼ばずに止まる）
NO_DOC = {
    "id": "diag-nodoc",
    "department": "情報システム部",
    "category": "法務",
    "question": "駐車場の月極料金はいくらですか。",
}
# 入口のガードレールが遮断する（モデルを1回も呼ばない）
BLOCKED = {
    "id": "diag-block",
    "department": "経理部",
    "category": "経費",
    "question": "余剰資金で仮想通貨に投資してもよいですか。",
}

# 資料を渡さずに投げる質問（社内文書のどこにも答えが無い）
NO_CONTEXT_QUESTION = "駐車場の月極料金はいくらですか。"

# 構造化出力の契約（セッション6の answer-contract v1）を使う整形依頼
CONTRACT_INPUT = "パスワードのリセットができないという問い合わせを JSON に整形してください。"

# Converse を持たないモデル。**カタログにある ID** だが埋め込み専用
EMBED_ONLY_MODEL = "amazon.titan-embed-text-v2:0"

# ログを読み戻すときの並び順。**書き込み順に依存させない**
# （同じミリ秒に複数行入ると、読み戻しの順序は保証されません）
LOG_ORDER = ("diag-ok", "diag-trunc", "diag-kana", "diag-nodoc", "diag-block")


# ---------------------------------------------------------------------------
# 小道具
# ---------------------------------------------------------------------------


def mock_behavior() -> dict:
    """いま入っている障害注入の設定を読む（後片付けの確認に使う）。"""
    with urllib.request.urlopen(
        f"{clients.mock_base_url()}/_mock/behavior", timeout=10
    ) as response:
        return json.loads(response.read())


def evidence(entry: dict) -> str:
    """説明責任ログ1行を、切り分けに使う欄だけに絞って1行にする。"""
    return (
        f"outcome={entry['outcome']}"
        f" citations={entry['citationCount']}"
        f" attempts={len(entry['attempts'])}"
        f" stopReason={entry['stopReason']}"
    )


def bootstrap() -> dict:
    """承認済みのプロンプト版とリネージ台帳をそろえる（何度実行してもよい）。"""
    state = provenance.bootstrap()
    state["runtime"] = clients.bedrock_runtime()
    state["agent"] = clients.agent_runtime()
    return state


def ask(scenario: dict, state: dict) -> dict:
    """1件を流して説明責任ログ1行を得る（セッション14の関数をそのまま呼ぶ）。"""
    entry, _ = provenance.answer(
        scenario,
        runtime=state["runtime"],
        agent=state["agent"],
        ddb=state["ddb"],
        s3=state["s3"],
    )
    return entry


def retrieved_texts(scenario: dict, state: dict) -> list[str]:
    """引用の本文（ablation で語を数えるために使う）。"""
    _, context_text = provenance.retrieve_citations(
        state["agent"], state["ddb"], scenario
    )
    return [t for t in context_text.split("\n") if t]


# ---------------------------------------------------------------------------
# 症状1: 回答が途中で切れる（force_max_tokens）
# ---------------------------------------------------------------------------


def symptom_truncated(state: dict, *, verbose: bool = True) -> dict:
    """同じ質問を「注入なし」「注入あり」で流し、違う欄を1つだけにする。

    **1回の実験で変える条件は1つ**にします。2つ変えると、どちらが効いたか
    分からないまま「たぶんこっちだろう」という結論になります。
    """
    result: dict = {}
    try:
        healthy = ask(HEALTHY, state)
        model_router.set_behavior(force_max_tokens=True)
        truncated = ask(TRUNCATED, state)
        result["healthy"] = healthy
        result["truncated"] = truncated
        result["candidates"] = diagnose.narrow(truncated)
        result["shorter"] = truncated["outputTokens"] < healthy["outputTokens"]

        # 同じ原因が別の症状に見える例。**構造化出力では「スキーマ違反」に見える**
        runtime = state["runtime"]
        template = registry.local("answer-contract", 1)
        broken = registry.call(
            runtime,
            template,
            model_id=provenance.PRIMARY_MODEL,
            messages=[{"role": "user", "content": [{"text": CONTRACT_INPUT}]}],
            max_tokens=200,
        )
        broken_text = registry.text_of(broken)
        try:
            registry.validate_contract(broken_text)
            result["contractError"] = None
        except ValueError as error:
            result["contractError"] = type(error).__name__
        result["contractStopReason"] = broken["stopReason"]
    finally:
        model_router.reset_mock()

    # 注入を解いたあとで同じ呼び出しをやり直す（＝回復の確認）
    healed = registry.call(
        state["runtime"],
        registry.local("answer-contract", 1),
        model_id=provenance.PRIMARY_MODEL,
        messages=[{"role": "user", "content": [{"text": CONTRACT_INPUT}]}],
        max_tokens=200,
    )
    result["healedKeys"] = sorted(registry.validate_contract(registry.text_of(healed)))
    result["healedStopReason"] = healed["stopReason"]

    if verbose:
        print("=== 1. 症状 S1-TRUNCATED: 回答が途中で切れる（force_max_tokens） ===")
        print(f"  注入なし: {evidence(result['healthy'])}")
        print(f"  注入あり: {evidence(result['truncated'])}")
        print(f"  ログだけで決まる原因: {' / '.join(result['candidates'])}")
        print(f"  打ち切られた出力は注入なしより短い: {result['shorter']}")
        print("  同じ原因が別の症状に見える例（構造化出力）:")
        print(
            f"    注入あり: {result['contractError']}"
            f" / stopReason={result['contractStopReason']}"
        )
        print(
            f"    注入解除: 契約検証 ok / キー={'/'.join(result['healedKeys'])}"
            f" / stopReason={result['healedStopReason']}"
        )
        print("  スキーマ違反は「モデルが形式を守らなかった」ではなく打ち切りでした")
    return result


# ---------------------------------------------------------------------------
# 症状2: 呼び出しが即座に失敗する（force_validation_error）
# ---------------------------------------------------------------------------


def symptom_bad_request(state: dict, *, verbose: bool = True) -> dict:
    """待っても直らないエラーを、**待たずに**そう判定できるか確かめる。"""
    result: dict = {"code": None, "operation": None, "message": ""}
    try:
        model_router.reset_mock()
        model_router.set_behavior(force_validation_error=True)
        try:
            ask(HEALTHY, state)
        except ClientError as error:
            result["code"] = error.response["Error"]["Code"]
            result["operation"] = error.operation_name
            result["message"] = error.response["Error"]["Message"]
        result["fatal"] = result["code"] in model_router.FATAL_CODES
        result["calls"] = model_router.mock_usage()["calls"]
        result["byCode"] = diagnose.from_error(result["code"])
    finally:
        model_router.reset_mock()

    # 同じ ValidationException を、別の原因で起こす（注入なし）
    result.update(secondCode=None, secondOperation=None, secondMessage="")
    try:
        state["runtime"].converse(
            modelId=EMBED_ONLY_MODEL,
            system=[{"text": poc_probe.SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": HEALTHY["question"]}]}],
            inferenceConfig={"maxTokens": 300, "temperature": 0.0},
        )
    except ClientError as error:
        result["secondCode"] = error.response["Error"]["Code"]
        result["secondOperation"] = error.operation_name
        result["secondMessage"] = error.response["Error"]["Message"]
    result["byMessage"] = diagnose.from_error(
        result["secondCode"], result.get("secondMessage", "")
    )

    if verbose:
        print()
        print("=== 2. 症状 S2-BAD-REQUEST: 呼び出しが即座に失敗する（force_validation_error） ===")
        print(f"  例外: {result['code']} / operation={result['operation']}")
        print(f"  基盤モデルの呼び出し回数: {result['calls']}（入口で落ちたのでモデルに届いていません）")
        print(f"  FATAL_CODES に含まれる: {result['fatal']}（リトライもフェイルオーバーもしません）")
        print(f"  コードだけで残る候補: {' / '.join(result['byCode'])}")
        print(f"  同じコードの別の原因: {result['secondCode']} / operation={result['secondOperation']}")
        print(f"    メッセージ: {result['secondMessage']}")
        print(f"  メッセージまで見て絞った候補: {' / '.join(result['byMessage'])}")
    return result


# ---------------------------------------------------------------------------
# 症状3: 特定のモデルだけ落ちる（unavailable_model）
# ---------------------------------------------------------------------------


def symptom_model_down(state: dict, *, verbose: bool = True) -> dict:
    """503 とブレーカーの区別。**どちらも「別モデルの回答が返る」に見えます。**"""
    result: dict = {}
    question, source = poc_probe.QUESTIONS[0]
    primary = model_router.DEFAULT_CONFIG["primary"]
    try:
        model_router.reset_mock()
        model_router.set_behavior(unavailable_model=primary)
        router = model_router.ModelRouter(config=model_router.DEFAULT_CONFIG)
        first = router.invoke(question, context=source)
        router.invoke(question, context=source)
        breaker = router.breaker(primary)
        third = router.invoke(question, context=source)
        result["first"] = model_router.attempts_line(first)
        result["serviceLevel"] = first["serviceLevel"]
        result["breakerState"] = breaker.state
        result["third"] = model_router.attempts_line(third)
        result["thirdOutcomes"] = [a["outcome"] for a in third["attempts"]]
    finally:
        model_router.reset_mock()

    if verbose:
        print()
        print("=== 3. 症状 S3-MODEL-DOWN: 特定のモデルだけ落ちる（unavailable_model） ===")
        print(f"  [1回目] {result['first']}")
        print(f"    serviceLevel={result['serviceLevel']}")
        print(f"  [2回目] {primary} のブレーカー: {result['breakerState']}")
        print(f"  [3回目] {result['third']}")
        print("  3回目は 503 が1件も出ていません（呼んでいないからです）")
        print("  一次情報は attempts 欄です。skipped_open は「呼ばずにあきらめた」印です")
    return result


# ---------------------------------------------------------------------------
# 症状4: 429 が増えた・急に遅くなった（throttle_next / latency_ms）
# ---------------------------------------------------------------------------


def symptom_throttled(state: dict, *, verbose: bool = True) -> dict:
    """SDK が吸収した 429 は、アプリのログに1件も残りません。"""
    result: dict = {}
    question, source = poc_probe.QUESTIONS[0]
    try:
        # (a) リトライが吸収して成功する
        model_router.reset_mock()
        model_router.set_behavior(throttle_next=2)
        absorbed = poc_probe.ask(clients.bedrock_runtime(max_attempts=3), question, source)
        result["absorbedOk"] = bool(absorbed["answer"])
        result["absorbedThrottled"] = model_router.mock_usage()["throttled"]

        # (b) リトライを使い切って例外が表に出る
        model_router.reset_mock()
        model_router.set_behavior(throttle_next=5)
        try:
            poc_probe.ask(clients.bedrock_runtime(max_attempts=1), question, source)
            result["exhaustedCode"] = None
        except ClientError as error:
            result["exhaustedCode"] = error.response["Error"]["Code"]
        result["exhaustedRequests"] = model_router.mock_usage()["throttled"]
        result["byCode"] = diagnose.from_error(result["exhaustedCode"])

        # (c) 遅延が基盤モデルの外で起きている（サーバーの latencyMs は変わらない）
        model_router.reset_mock()
        runtime = clients.bedrock_runtime()
        started = time.perf_counter()
        base = poc_probe.ask(runtime, question, source)
        base_wall = time.perf_counter() - started
        model_router.set_behavior(latency_ms=400)
        started = time.perf_counter()
        slow = poc_probe.ask(runtime, question, source)
        slow_wall = time.perf_counter() - started
        result["serverLatencyUnchanged"] = base["latencyMs"] == slow["latencyMs"]
        result["clientWallGrew"] = (slow_wall - base_wall) > 0.2
    finally:
        model_router.reset_mock()

    if verbose:
        print()
        print("=== 4. 症状 S4-THROTTLED: 429 が増えた・急に遅くなった（throttle_next / latency_ms） ===")
        print(
            f"  [吸収された] max_attempts=3 / 注入2回 -> 呼び出しは成功={result['absorbedOk']}"
            f" / 受けた429={result['absorbedThrottled']}"
        )
        print("    アプリのエラーログには1件も残りません")
        print(
            f"  [使い切った] max_attempts=1 / 注入5回 -> {result['exhaustedCode']}"
            f" / 受けた429={result['exhaustedRequests']}"
        )
        print("    飛んだ要求は max_attempts + 1 回（セッション10の実測）")
        print(f"  コードだけで残る候補: {' / '.join(result['byCode'])}")
        print(
            f"  [モデルの外] metrics.latencyMs は変わらない: {result['serverLatencyUnchanged']}"
            f" / 実測の待ち時間だけ伸びた: {result['clientWallGrew']}"
        )
        print("  一次情報が2つ要ります（サーバーが返す latencyMs と、自分で測った時間）")
    return result


# ---------------------------------------------------------------------------
# 症状5: 引用が付かない・作り話をする（hallucinate_without_context）
# ---------------------------------------------------------------------------


def symptom_no_citation(state: dict, *, verbose: bool = True) -> dict:
    """資料を渡さないと何が起きるか。**断るのが既定であるべき**という話です。"""
    result: dict = {}
    system_blocks = registry.render_system(
        registry.local(provenance.PROMPT_NAME, 2),
        {"department": "情報システム部", "max_sentences": provenance.MAX_SENTENCES},
    )

    def call_without_context() -> str:
        response = state["runtime"].converse(
            modelId=provenance.PRIMARY_MODEL,
            system=system_blocks,
            messages=[{"role": "user", "content": [{"text": NO_CONTEXT_QUESTION}]}],
            inferenceConfig={"maxTokens": 300, "temperature": 0.0},
        )
        return registry.text_of(response)

    try:
        model_router.reset_mock()
        invented = call_without_context()
        result["inventedHasDigits"] = any(ch.isdigit() for ch in invented)
        result["inventedRefused"] = "回答できません" in invented

        model_router.set_behavior(hallucinate_without_context=False)
        refused = call_without_context()
        result["refusedText"] = refused
    finally:
        model_router.reset_mock()

    result["noDoc"] = ask(NO_DOC, state)
    result["blocked"] = ask(BLOCKED, state)
    result["noDocCandidates"] = diagnose.narrow(result["noDoc"])
    result["blockedCandidates"] = diagnose.narrow(result["blocked"])

    if verbose:
        print()
        print("=== 5. 症状 S5-NO-CITATION: 引用が付かない・作り話をする（hallucinate_without_context） ===")
        print(
            f"  [既定 true] 資料なしでも答える。数字を含む: {result['inventedHasDigits']}"
            f" / 断っている: {result['inventedRefused']}"
        )
        print(f"  [false] {result['refusedText']}")
        print(f"  検索0件のログ: {evidence(result['noDoc'])}")
        print(f"  入口で遮断のログ: {evidence(result['blocked'])}")
        print(
            "  同じ「答えてくれない」でも、"
            f"{' / '.join(result['noDocCandidates'])} と "
            f"{' / '.join(result['blockedCandidates'])} は別の原因です"
        )
    return result


# ---------------------------------------------------------------------------
# 症状6: 資料は出ているのに断る（モックの語一致の癖）
# ---------------------------------------------------------------------------


def symptom_refuse_with_hits(state: dict, *, verbose: bool = True) -> dict:
    """**注入を1つも使わない症状。** 障害ではなく噛み合わせの問題です。

    モックの `_keywords()` は `[ぁ-んァ-ヴー]{2,}` という文字クラスを使っており、
    ひらがなとカタカナを区別しません。そのためカタカナ語のうしろに助詞が続くと
    1語に融合します（`パスワードリセットの`）。資料側は鍵括弧で切れて
    `パスワードリセット` になるため、**この2つは別語**として扱われます。
    """
    result: dict = {}
    try:
        model_router.reset_mock()
        entry = ask(KATAKANA, state)
        result["entry"] = entry
        result["candidates"] = diagnose.narrow(entry)

        approved_version, _, approved_checksum = registry.load_approved(
            state["s3"], provenance.PROMPT_NAME
        )
        result["approvedVersion"] = approved_version
        result["checksumMatches"] = entry["promptChecksum"] == approved_checksum
        # 「v1 に戻ったのでは？」も同じ欄で否定できる
        result["matchesV1"] = entry["promptChecksum"] == registry.checksum(
            registry.local(provenance.PROMPT_NAME, 1)
        )

        sources = retrieved_texts(KATAKANA, state)
        result["citedDocIds"] = sorted(
            c["docId"] for c in entry["citations"] if c["docId"]
        )
        result["shared"] = diagnose.shared_words(KATAKANA["question"], sources)
        result["sharedAfter"] = diagnose.shared_words(HEALTHY["question"], sources)
        result["cause"] = diagnose.confirm(
            result["candidates"],
            checksum_matches=result["checksumMatches"],
            shared_words_count=len(result["shared"]),
        )
        result["rewritten"] = ask(HEALTHY, state)
    finally:
        model_router.reset_mock()

    if verbose:
        print()
        print("=== 6. 症状 S6-REFUSE-WITH-HITS: 資料は出ているのに断る（語一致の癖） ===")
        print(f"  ログ1行: {evidence(result['entry'])}")
        print(f"  引いた文書: {' / '.join(result['citedDocIds'])}")
        print(f"  ログだけで残る候補: {' / '.join(result['candidates'])}")
        print(
            f"  promptChecksum は承認版(v{result['approvedVersion']})と一致:"
            f" {result['checksumMatches']} -> C-PROMPT-REGRESSION を外す"
        )
        print(f"  質問「{KATAKANA['question']}」の共通語: {len(result['shared'])} 語 {result['shared']}")
        print(
            f"  質問「{HEALTHY['question']}」の共通語:"
            f" {len(result['sharedAfter'])} 語 {result['sharedAfter']}"
        )
        print(f"  書き換え後の結末: {result['rewritten']['outcome']}")
        print(f"  確定した原因: {result['cause']}（検索は正しい文書を引いていました）")
    return result


# ---------------------------------------------------------------------------
# ログだけを見て原因を割り当てる
# ---------------------------------------------------------------------------


def store(entries: list[dict], *, logs=None) -> dict[str, dict]:
    """1行ずつ CloudWatch Logs に残し、**読み戻したもの**を requestId で引ける形にする。

    切り分けは「手元の変数」ではなく「残ったログ」で成立しなければ意味がありません。
    実運用では障害が起きた時刻に人はその場にいないからです。
    """
    logs = logs or clients.aws("logs")
    stream = provenance.stream_name(provenance.new_run_id())
    provenance.ensure_groups(logs, stream=stream)
    for entry in entries:
        provenance.write(logs, stream, entry)
    return {e["requestId"]: e for e in provenance.read_all(logs, stream)}


def assign(stored: dict[str, dict], *, verbose: bool = True) -> list[tuple[str, list[str]]]:
    """読み戻したログ1行ごとに候補原因を割り当てる。"""
    rows = [
        (request_id, diagnose.narrow(stored[request_id]))
        for request_id in LOG_ORDER
        if request_id in stored
    ]
    if verbose:
        print()
        print("=== 7. ログだけを見て原因を割り当てる ===")
        for request_id, codes in rows:
            print(
                f"  {request_id} outcome={stored[request_id]['outcome']}"
                f" -> {' / '.join(codes)}"
            )
        print("  同じ outcome=exhausted が2件あり、分けたのは stopReason だけです")
    return rows


def main() -> None:
    model_router.reset_mock()
    state = bootstrap()
    version, _, checksum = registry.load_approved(state["s3"], provenance.PROMPT_NAME)

    print("=== 0. 準備 ===")
    print(f"  承認済みのプロンプト: {provenance.PROMPT_NAME} v{version}")
    print(f"  ハッシュの桁数: {len(checksum)}")
    print(f"  説明責任ログ: {provenance.LOG_GROUP}")
    print()

    trunc = symptom_truncated(state)
    symptom_bad_request(state)
    symptom_model_down(state)
    symptom_throttled(state)
    citation = symptom_no_citation(state)
    refuse = symptom_refuse_with_hits(state)

    entries = [
        trunc["healthy"],
        trunc["truncated"],
        refuse["entry"],
        citation["noDoc"],
        citation["blocked"],
    ]
    assign(store(entries))

    model_router.reset_mock()
    print()
    print(f"  後片付け後の behavior: {mock_behavior()}")
    print("モックの状態を初期化しました（注入した設定は残していません）")


if __name__ == "__main__":
    main()
