#!/usr/bin/env python3
"""セッション19の検証。

    docker compose exec app python src/session19/verify.py

**期待値と一致しなければ非0で終了します。** 判定に使うのは決定的な性質だけです。

    * 症状カタログのすべての症状に候補原因が2つ以上あるか（決め打ちしていないか）
    * 候補にすべて「見る欄」「決め手」「打ち手」がそろっているか
    * 障害注入で狙った症状が確実に起きるか（例外クラス名・stopReason・outcome）
    * **同じ結末（exhausted）の2件を、stopReason だけで分けられるか**
    * ログ1行だけから候補原因を割り当てられるか
    * 実験のあと、障害注入の設定が1つも残っていないか（後続の検証を落とさない）

時間の絶対値は合否条件にしていません（環境で変わるため）。レイテンシは
「サーバーが返す値が変わらない」「クライアント実測だけが伸びる」という
**関係**だけを見ます。
"""

from __future__ import annotations

import json
import sys
import urllib.request

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")
sys.path.insert(0, "/workspace/src/session04")
sys.path.insert(0, "/workspace/src/session05")
sys.path.insert(0, "/workspace/src/session06")
sys.path.insert(0, "/workspace/src/session14")
sys.path.insert(0, "/workspace/src/session19")

from awskit import clients  # noqa: E402

import model_router  # noqa: E402
import provenance  # noqa: E402

import diagnose  # noqa: E402
import fault_lab  # noqa: E402

FAILURES: list[str] = []

# 6つの症状すべてに手順書があること（1つでも欠けたら手順書として使えない）
EXPECTED_SYMPTOMS = (
    "S1-TRUNCATED",
    "S2-BAD-REQUEST",
    "S3-MODEL-DOWN",
    "S4-THROTTLED",
    "S5-NO-CITATION",
    "S6-REFUSE-WITH-HITS",
)

# ログだけで残る候補（**1つに決まらないことも期待値**にする）
EXPECTED_ASSIGNMENT = {
    "diag-ok": ["C-NONE"],
    "diag-trunc": ["C-TRUNCATION"],
    "diag-kana": ["C-KEYWORD-MISMATCH", "C-CHUNK-BOUNDARY", "C-PROMPT-REGRESSION"],
    "diag-nodoc": ["C-EMPTY-RETRIEVAL", "C-INDEX-STALE"],
    "diag-block": ["C-GUARDRAIL-BLOCK"],
}

REFUSAL_WITHOUT_CONTEXT = (
    "根拠となる資料が与えられていないため、確認できる情報の範囲では回答できません。"
)

# 障害注入を1つも残していない状態（`bedrock_mock/behavior.py` の Behavior の既定）
CLEAN_BEHAVIOR = {
    "throttle_next": 0,
    "latency_ms": 0,
    "unavailable_model": None,
    "force_validation_error": False,
    "force_max_tokens": False,
    "hallucinate_without_context": True,
}


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def mock_post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{clients.mock_base_url()}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def main() -> int:
    # 前の演習の障害注入が残っていると、狙った症状と混ざる
    mock_post("/_mock/reset", {})
    state = fault_lab.bootstrap()

    # ------------------------------------------------------------------
    section("1. 症状カタログ（手順書として使える形か）")
    check(
        "6つの症状すべてに手順書がある",
        tuple(diagnose.SYMPTOMS) == EXPECTED_SYMPTOMS,
        tuple(diagnose.SYMPTOMS),
    )
    check(
        "どの症状も候補原因を2つ以上持つ（単一の原因に決め打ちしていない）",
        all(len(s.candidates) >= 2 for s in diagnose.SYMPTOMS.values()),
        {c: len(s.candidates) for c, s in diagnose.SYMPTOMS.items()},
    )
    unknown = sorted(
        {
            candidate.cause
            for symptom in diagnose.SYMPTOMS.values()
            for candidate in symptom.candidates
            if candidate.cause not in diagnose.CAUSES
        }
    )
    check("候補の原因コードはすべて辞書に載っている", unknown == [], unknown)
    check(
        "すべての候補に「見る欄」「決め手」「打ち手」がある",
        all(
            candidate.field and candidate.ruling and candidate.fix
            for symptom in diagnose.SYMPTOMS.values()
            for candidate in symptom.candidates
        ),
    )
    lines = diagnose.playbook("S6-REFUSE-WITH-HITS")
    check(
        "手順書は見出し・一次情報・候補ごとの4行・注意で組み立てられる",
        len(lines) == 3 + 4 * len(diagnose.SYMPTOMS["S6-REFUSE-WITH-HITS"].candidates),
        len(lines),
    )
    check(
        "手順書に一次情報の出どころが書かれている",
        lines[1].startswith("  一次情報: "),
        lines[1],
    )

    # ------------------------------------------------------------------
    section("2. 症状 S1-TRUNCATED（force_max_tokens）")
    trunc = fault_lab.symptom_truncated(state, verbose=False)
    healthy, truncated = trunc["healthy"], trunc["truncated"]
    check(
        "注入なしは根拠つきで答えられる",
        healthy["outcome"] == "answered" and healthy["stopReason"] == "end_turn",
        (healthy["outcome"], healthy["stopReason"]),
    )
    check(
        "注入ありは救えず終わる",
        truncated["outcome"] == "exhausted" and truncated["stopReason"] == "max_tokens",
        (truncated["outcome"], truncated["stopReason"]),
    )
    check(
        "打ち切りでも引用は同じ件数だけ取れている（検索は無関係）",
        truncated["citationCount"] == healthy["citationCount"] == 3,
        (truncated["citationCount"], healthy["citationCount"]),
    )
    check(
        "どちらの試行も max_tokens で終わっている",
        [a["stopReason"] for a in truncated["attempts"]] == ["max_tokens"] * 2,
        truncated["attempts"],
    )
    check("打ち切られた出力は注入なしより短い", trunc["shorter"])
    check(
        "ログだけで原因が1つに決まる",
        trunc["candidates"] == ["C-TRUNCATION"],
        trunc["candidates"],
    )
    check(
        "同じ原因が構造化出力ではスキーマ違反に見える",
        trunc["contractError"] == "JSONDecodeError"
        and trunc["contractStopReason"] == "max_tokens",
        (trunc["contractError"], trunc["contractStopReason"]),
    )
    check(
        "注入を解けば契約どおりの JSON に戻る",
        trunc["healedKeys"] == ["keywords", "sentiment", "summary"]
        and trunc["healedStopReason"] == "end_turn",
        (trunc["healedKeys"], trunc["healedStopReason"]),
    )

    # ------------------------------------------------------------------
    section("3. 症状 S2-BAD-REQUEST（force_validation_error）")
    bad = fault_lab.symptom_bad_request(state, verbose=False)
    check(
        "例外クラス名と落ちた API が分かる",
        bad["code"] == "ValidationException" and bad["operation"] == "ApplyGuardrail",
        (bad["code"], bad["operation"]),
    )
    check("待っても直らないエラーとして分類される", bad["fatal"])
    check(
        "基盤モデルは1回も呼ばれていない（入口で落ちている）",
        bad["calls"] == 0,
        bad["calls"],
    )
    check(
        "コードだけでは候補が3つ残る",
        bad["byCode"]
        == ["C-BAD-ARGUMENT", "C-UNSUPPORTED-MODEL", "C-CONTEXT-OVERFLOW"],
        bad["byCode"],
    )
    check(
        "別の原因でも同じコードが返る（埋め込みモデルに Converse）",
        bad["secondCode"] == "ValidationException"
        and bad["secondOperation"] == "Converse",
        (bad["secondCode"], bad["secondOperation"]),
    )
    check(
        "メッセージ本文まで見れば候補が1つに絞れる",
        bad["byMessage"] == ["C-UNSUPPORTED-MODEL"],
        bad["byMessage"],
    )

    # ------------------------------------------------------------------
    section("4. 症状 S3-MODEL-DOWN（unavailable_model）")
    down = fault_lab.symptom_model_down(state, verbose=False)
    check(
        "一次のモデルが 503 で代替へ切り替わる",
        "ServiceUnavailableException" in down["first"]
        and down["serviceLevel"] == "fallback",
        (down["first"], down["serviceLevel"]),
    )
    check(
        "連続失敗でブレーカーが開く",
        down["breakerState"] == "OPEN",
        down["breakerState"],
    )
    check(
        "開いたあとは呼ばずにあきらめた印が残る",
        down["thirdOutcomes"] == ["skipped_open", "ok"],
        down["thirdOutcomes"],
    )
    check(
        "同じ 503 でも候補は2つある（モデル不可とブレーカー）",
        diagnose.from_error("ServiceUnavailableException")
        == ["C-MODEL-UNAVAILABLE", "C-BREAKER-OPEN"],
        diagnose.from_error("ServiceUnavailableException"),
    )

    # ------------------------------------------------------------------
    section("5. 症状 S4-THROTTLED（throttle_next / latency_ms）")
    slow = fault_lab.symptom_throttled(state, verbose=False)
    check(
        "SDK が吸収した 429 は呼び出しを成功させる",
        slow["absorbedOk"] and slow["absorbedThrottled"] == 2,
        (slow["absorbedOk"], slow["absorbedThrottled"]),
    )
    check(
        "使い切れば例外が表に出る",
        slow["exhaustedCode"] == "ThrottlingException",
        slow["exhaustedCode"],
    )
    check(
        "飛んだ要求は max_attempts + 1 回（セッション10の実測と一致）",
        slow["exhaustedRequests"] == 2,
        slow["exhaustedRequests"],
    )
    check(
        "コードだけでは割当不足とリトライの二重掛けを分けられない",
        slow["byCode"] == ["C-QUOTA", "C-RETRY-STORM"],
        slow["byCode"],
    )
    check(
        "モデルの外の遅延はサーバーの latencyMs を変えない",
        slow["serverLatencyUnchanged"],
    )
    check("変わるのはクライアントで測った時間だけ", slow["clientWallGrew"])

    # ------------------------------------------------------------------
    section("6. 症状 S5-NO-CITATION（hallucinate_without_context）")
    citation = fault_lab.symptom_no_citation(state, verbose=False)
    check(
        "既定では資料なしでも数字入りの回答を作る",
        citation["inventedHasDigits"] and not citation["inventedRefused"],
        (citation["inventedHasDigits"], citation["inventedRefused"]),
    )
    check(
        "false にすれば資料なしでは断る",
        citation["refusedText"] == REFUSAL_WITHOUT_CONTEXT,
        citation["refusedText"],
    )
    no_doc, blocked = citation["noDoc"], citation["blocked"]
    check(
        "検索0件の行はモデルを呼ばずに終わる",
        no_doc["outcome"] == "no_citation"
        and no_doc["citationCount"] == 0
        and no_doc["modelId"] is None
        and no_doc["attempts"] == [],
        (no_doc["outcome"], no_doc["citationCount"], no_doc["modelId"]),
    )
    check(
        "入口で遮断した行は guardrailStage / guardrailAction に残る",
        blocked["outcome"] == "blocked"
        and blocked["guardrailStage"] == "INPUT"
        and blocked["guardrailAction"] == "GUARDRAIL_INTERVENED",
        (blocked["outcome"], blocked["guardrailStage"], blocked["guardrailAction"]),
    )
    check(
        "同じ「答えてくれない」でも候補が違う",
        citation["noDocCandidates"] == ["C-EMPTY-RETRIEVAL", "C-INDEX-STALE"]
        and citation["blockedCandidates"] == ["C-GUARDRAIL-BLOCK"],
        (citation["noDocCandidates"], citation["blockedCandidates"]),
    )

    # ------------------------------------------------------------------
    section("7. 症状 S6-REFUSE-WITH-HITS（語一致の癖・注入なし）")
    refuse = fault_lab.symptom_refuse_with_hits(state, verbose=False)
    entry = refuse["entry"]
    check(
        "資料は3件取れているのに救えず終わる",
        entry["outcome"] == "exhausted"
        and entry["citationCount"] == 3
        and entry["stopReason"] == "end_turn",
        (entry["outcome"], entry["citationCount"], entry["stopReason"]),
    )
    check(
        "検索は正しい文書を引いている（IT 分類の3件）",
        refuse["citedDocIds"] == ["hd-001", "hd-002", "hd-003"],
        refuse["citedDocIds"],
    )
    check(
        "ログだけでは候補が3つ残る",
        refuse["candidates"]
        == ["C-KEYWORD-MISMATCH", "C-CHUNK-BOUNDARY", "C-PROMPT-REGRESSION"],
        refuse["candidates"],
    )
    check(
        "プロンプトの版は承認版と一致し、v1 でもない（版の回帰は除外できる）",
        refuse["checksumMatches"] and not refuse["matchesV1"],
        (refuse["checksumMatches"], refuse["matchesV1"]),
    )
    check(
        "質問と資料で共通する語が0語（＝答えを作れない）",
        refuse["shared"] == [],
        refuse["shared"],
    )
    check(
        "漢字語を共有する質問に書き換えると共通語が現れる",
        refuse["sharedAfter"] == ["必要", "認証"],
        refuse["sharedAfter"],
    )
    check(
        "書き換えれば同じ資料で答えられる",
        refuse["rewritten"]["outcome"] == "answered",
        refuse["rewritten"]["outcome"],
    )
    check(
        "原因が1つに確定する",
        refuse["cause"] == "C-KEYWORD-MISMATCH",
        refuse["cause"],
    )
    check(
        "ハッシュが違えば、共通語を数える前に版の回帰と決まる（安い検査が先）",
        diagnose.confirm(
            refuse["candidates"], checksum_matches=False, shared_words_count=0
        )
        == "C-PROMPT-REGRESSION",
    )
    check(
        "打ち切りと語一致は outcome も引用件数も試行回数も同じ",
        (truncated["outcome"], truncated["citationCount"], len(truncated["attempts"]))
        == (entry["outcome"], entry["citationCount"], len(entry["attempts"])),
        (truncated["outcome"], entry["outcome"]),
    )
    check(
        "2件を分けているのは stopReason だけ",
        truncated["stopReason"] != entry["stopReason"],
        (truncated["stopReason"], entry["stopReason"]),
    )

    # ------------------------------------------------------------------
    section("8. ログ1行だけから原因を割り当てる")
    stored = fault_lab.store(
        [
            healthy,
            truncated,
            entry,
            no_doc,
            blocked,
        ]
    )
    check(
        "5件すべてが残り、requestId で引ける",
        sorted(stored) == sorted(EXPECTED_ASSIGNMENT),
        sorted(stored),
    )
    missing = sorted(
        {
            field
            for row in stored.values()
            for field in provenance.ACCOUNTABILITY_FIELDS
            if field not in row
        }
    )
    check("読み戻した行にも説明責任の欄がそろう", missing == [], missing)
    assignment = dict(fault_lab.assign(stored, verbose=False))
    check(
        "割り当てが期待どおり（1つに決まる行と、決まらない行がある）",
        assignment == EXPECTED_ASSIGNMENT,
        assignment,
    )
    check(
        "ログに質問の本文は残っていない（セッション14の契約を壊していない）",
        all(
            scenario["question"] not in json.dumps(stored, ensure_ascii=False)
            for scenario in (fault_lab.HEALTHY, fault_lab.KATAKANA, fault_lab.BLOCKED)
        ),
    )

    # ------------------------------------------------------------------
    section("9. 後片付け（ここが落ちると後続のセッションが落ちる）")
    mock_post("/_mock/reset", {})
    check(
        "障害注入の設定が1つも残っていない",
        fault_lab.mock_behavior() == CLEAN_BEHAVIOR,
        fault_lab.mock_behavior(),
    )
    check(
        "スロットリング枠も残っていない",
        model_router.mock_usage()["throttled"] == 0,
        model_router.mock_usage()["throttled"],
    )

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション19の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
