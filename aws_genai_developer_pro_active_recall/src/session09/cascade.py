#!/usr/bin/env python3
"""セッション9: モデルカスケード（小型モデルで受け、必要な分だけ上位モデルへ回す）。

    docker compose exec app python src/session09/cascade.py

前章までに作ったモデル解決層（`src/session02/model_router.py` の `ModelRouter`）は
そのまま使います。本章が足すのは、その **手前** で「どの層へ出すか」を決める判断です。

実務では推論の置き方として「バッチ推論（CreateModelInvocationJob）」
「プロビジョンドスループット」「SageMaker エンドポイント」も選べますが、
Bedrock 互換モックと LocalStack Community にはどれも無いため、
本書ではオンデマンド呼び出しと SQS（非同期の受け口）で構造だけを再現します。
"""

from __future__ import annotations

import math
import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")

from bedrock_mock import catalog  # noqa: E402

import model_router  # noqa: E402
import poc_probe  # noqa: E402

# ---------------------------------------------------------------------------
# カスケードの定義（2層）
# ---------------------------------------------------------------------------

# tier1 は「分類・短い定型応答」だけを担当する小型モデル
TIER1 = "amazon.nova-micro-v1:0"
# tier2 は tier1 が受け入れられなかったぶんだけを引き取る上位モデル
TIER2 = "amazon.nova-pro-v1:0"

# 層ごとの出力上限。tier1 に長い応答を任せると tier1 の意味がなくなる
TIER1_MAX_TOKENS = 128
TIER2_MAX_TOKENS = 300

# tier1 へ渡す入力の上限（見積トークン）。超える入力は呼ぶ前に tier2 へ出す
TIER1_INPUT_TOKEN_LIMIT = 260

# tier1 に任せるタスク種別。ここに無いタスクは最初から tier2 へ出す
TIER1_TASKS = frozenset({"classify", "answer"})

# 分類タスクで許可するラベル。この集合に無い出力は受け入れない
LABELS = ("請求に関する問い合わせ", "技術的な不具合", "解約の相談")

CLASSIFY_TEMPLATE = (
    "次の問い合わせを分類してください。カテゴリは {labels} のいずれかです。\n"
    "問い合わせ: {question}"
)

# セッション2と同じ参照ワークロード（入力1,000 / 出力300 トークン）
REFERENCE_WORKLOAD = (1_000, 300)

# 事前ゲートに掛かる長い資料（複数文書をまとめて渡してしまった状況）
LONG_CONTEXT = (
    "国内出張の宿泊費の上限は1泊15000円です。"
    "海外出張の宿泊費の上限は1泊25000円です。"
    "出張の申請は出発の3営業日前までに上長の承認を得てください。"
    "宿泊費の精算には宿泊施設が発行した領収書の原本が必要です。"
    "日当は国内出張が1日2000円、海外出張が1日4000円です。"
    "交通費は最も経済的な経路の実費を精算します。"
    "精算の申請期限は帰着日の翌月10日です。"
    "承認された出張計画に変更が生じた場合は速やかに再申請してください。"
    "出張中の食事代は日当に含まれるため個別には精算できません。"
    "出張先での交通費は領収書が発行されない区間のみ経路と金額を申請書に記載してください。"
    "宿泊を伴わない日帰り出張の場合は宿泊費の申請はできません。"
)

# tier1 の出力上限には収まらないが tier2 では収まる長さの資料
LONG_ANSWER_CONTEXT = (
    "社内システムのパスワードの再設定は、社内ポータルの「アカウント設定」から"
    "本人確認を行ったうえで実施し、再設定後は同じパスワードを"
    "他のサービスで使い回さないでください。"
    "パスワードは12文字以上で英大文字・英小文字・数字・記号を組み合わせて設定し、"
    "90日ごとの変更と、過去に使用した5世代分の再利用の禁止が適用されます。"
)

# 1日ぶんの問い合わせを模したワークロード（12件）。
# 分類5件・短い資料付きの質問5件・長い資料1件・長い応答が必要な質問1件。
WORKLOAD: list[dict] = [
    {"requestId": "req-001", "task": "classify",
     "question": "請求書の金額が二重に計上されています。確認してください。"},
    {"requestId": "req-002", "task": "classify",
     "question": "社内ポータルにログインできません。復旧の見込みを知りたいです。"},
    {"requestId": "req-003", "task": "classify",
     "question": "契約中のオプションを解約したい場合の窓口を教えてください。"},
    {"requestId": "req-004", "task": "classify",
     "question": "経費精算システムでエラーコードE12が表示され申請できません。"},
    {"requestId": "req-005", "task": "classify",
     "question": "領収書の再発行をお願いしたいです。"},
    {"requestId": "req-006", "task": "answer",
     "question": poc_probe.QUESTIONS[0][0], "context": poc_probe.QUESTIONS[0][1]},
    {"requestId": "req-007", "task": "answer",
     "question": poc_probe.QUESTIONS[1][0], "context": poc_probe.QUESTIONS[1][1]},
    {"requestId": "req-008", "task": "answer",
     "question": poc_probe.QUESTIONS[2][0], "context": poc_probe.QUESTIONS[2][1]},
    {"requestId": "req-009", "task": "answer",
     "question": "社内ネットワークへのVPN接続が切れる場合の連絡先はどこですか。",
     "context": "VPN接続の不具合はIT部門のサービスデスク（内線4567）へ連絡してください。"},
    {"requestId": "req-010", "task": "answer",
     "question": "経費精算の締め日はいつですか。",
     "context": "経費精算の締め日は毎月10日で、10日が休日の場合は翌営業日となります。"},
    {"requestId": "req-011", "task": "answer",
     "question": "国内出張の宿泊費と日当の精算はどう申請しますか。",
     "context": LONG_CONTEXT},
    {"requestId": "req-012", "task": "answer",
     "question": "パスワードの再設定手順を教えてください。",
     "context": LONG_ANSWER_CONTEXT},
]


# ---------------------------------------------------------------------------
# 呼ぶ前に分かること（事前ゲート）
# ---------------------------------------------------------------------------


def token_estimate(text: str) -> int:
    """入力トークン数を呼び出す前に見積もる。

    モックのトークン規則（ASCII 4文字＝1トークン、非ASCII 1文字＝1トークン）と
    同じ計算をクライアント側で行います。実 Bedrock でもモデルごとの
    トークナイザに合わせた見積もり関数を用意しておくと、
    **課金される前に**「この入力は小型モデルに任せられない」と判断できます。
    """
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    return (len(text) - ascii_chars) + math.ceil(ascii_chars / 4)


def request_parts(record: dict) -> tuple[str, str | None]:
    """(ユーザーメッセージ, 資料) を返す。資料は `<context>` として渡される。"""
    if record["task"] == "classify":
        return (
            CLASSIFY_TEMPLATE.format(
                labels=" / ".join(LABELS), question=record["question"]
            ),
            None,
        )
    return record["question"], record.get("context")


def prompt_text(record: dict) -> str:
    """モデルへ実際に届く本文（`ModelRouter` が組み立てるものと同じ形）。"""
    question, context = request_parts(record)
    if context is None:
        return question
    return f"{question}\n<context>{context}</context>"


def pre_route(record: dict) -> tuple[str, str]:
    """呼び出す前に決める振り分け。(層, 理由コード) を返す。

    ここで落とせるものを tier1 に投げると、失敗ぶんの料金を丸ごと捨てます。
    「入力を見れば分かること」は必ず呼び出し前に判断します。
    """
    if record["task"] not in TIER1_TASKS:
        return "tier2", "task_out_of_scope"
    tokens = token_estimate(poc_probe.SYSTEM_PROMPT + prompt_text(record))
    if tokens > TIER1_INPUT_TOKEN_LIMIT:
        return "tier2", "input_too_long"
    return "tier1", "in_scope"


# ---------------------------------------------------------------------------
# 呼んだ後に分かること（受け入れ判定）
# ---------------------------------------------------------------------------


def accept(record: dict, result: dict) -> tuple[bool, str]:
    """層の出力を受け入れるか。(受け入れるか, 理由コード) を返す。

    受け入れ判定は **タスクごとに違います**。分類なら許可ラベルの集合に入るか、
    資料に基づく回答なら根拠を提示できているか。
    どちらの場合も「打ち切られた応答は受け入れない」が先に来ます。
    """
    if result["stopReason"] != "end_turn":
        return False, "truncated"
    if record["task"] == "classify":
        if result["text"].strip() in LABELS:
            return True, "label_ok"
        return False, "bad_label"
    if result["grounded"]:
        return True, "grounded"
    return False, "not_grounded"


# ---------------------------------------------------------------------------
# 呼び出し（モデル解決層はセッション2のものを再利用する）
# ---------------------------------------------------------------------------


def call(record: dict, model_id: str, max_tokens: int, router) -> dict:
    """1つの層へ1回だけ問い合わせる。"""
    question, context = request_parts(record)
    config = {
        **model_router.DEFAULT_CONFIG,
        "primary": model_id,
        # カスケードの上位層は「品質のための昇格」であって障害時の代替ではない。
        # 障害時の切り替えはセッション2の fallbacks が担当するので、ここでは混ぜない
        "fallbacks": [],
        "maxTokens": max_tokens,
    }
    return router.invoke(question, context=context, config=config)


def run_one(record: dict, router) -> dict:
    """1件をカスケードで処理する。"""
    tier, reason = pre_route(record)
    path = "tier1" if tier == "tier1" else "gate>tier2"
    calls = 0
    result = None

    if tier == "tier1":
        result = call(record, TIER1, TIER1_MAX_TOKENS, router)
        calls += 1
        ok, why = accept(record, result)
        if ok:
            return _decision(record, "tier1", TIER1, "accepted", why, calls, result)
        # 受け入れられなかったので上位へ回す（ここで料金は二重に払う）
        path, reason = "tier1>tier2", why

    result = call(record, TIER2, TIER2_MAX_TOKENS, router)
    calls += 1
    ok, why = accept(record, result)
    if ok:
        return _decision(record, path, TIER2, "accepted", reason, calls, result)
    # 上位でも受け入れられない。モデルを上げても直らない問題なので縮退する
    return _decision(record, path, None, "exhausted", why, calls, result)


def _decision(
    record: dict,
    path: str,
    served_by: str | None,
    outcome: str,
    reason: str,
    calls: int,
    result: dict,
) -> dict:
    # どの層も受け入れられなかったときは縮退の定型文を返す（作り話をさせない）
    degraded = model_router.DEFAULT_CONFIG["degradedMessage"]
    return {
        "requestId": record["requestId"],
        "task": record["task"],
        "path": path,
        "servedBy": served_by,
        "outcome": outcome,
        "reason": reason,
        "calls": calls,
        "text": result["text"] if served_by else degraded,
        "outputTokens": result["outputTokens"],
        "estimatedUsd": result["estimatedUsd"],
    }


def run_cascade(records: list[dict], router) -> list[dict]:
    return [run_one(record, router) for record in records]


def run_single_tier(records: list[dict], model_id: str, max_tokens: int, router):
    """全件を1つの層へ投げる（比較の基準・コストの下限を測るため）。"""
    return [call(record, model_id, max_tokens, router) for record in records]


# ---------------------------------------------------------------------------
# コストの比較
# ---------------------------------------------------------------------------


def break_even_rate(
    tier1: str = TIER1, tier2: str = TIER2, workload: tuple[int, int] = REFERENCE_WORKLOAD
) -> float:
    """カスケードが「全件を上位モデル」より高くなるエスカレーション率。

    カスケードの費用は C1 + p * C2、全件上位は C2。等しくなるのは p = 1 - C1/C2。
    **単価差が大きいほどブレークイーブンは 1 に近づく**（＝カスケードが有利）。
    """
    c1 = catalog.cost_usd(tier1, *workload)
    c2 = catalog.cost_usd(tier2, *workload)
    return 1.0 - c1 / c2


def measure(run) -> tuple[dict, object]:
    """モックの会計を初期化してから実行し、(使用量, 実行結果) を返す。"""
    model_router.reset_mock()
    outcome = run()
    return model_router.mock_usage(), outcome


# ---------------------------------------------------------------------------
# 演習の本体
# ---------------------------------------------------------------------------


def main() -> None:
    router = model_router.ModelRouter()

    print("=== 1. カスケードの前提（単価とブレークイーブン） ===")
    print(f"tier1 = {TIER1} / tier2 = {TIER2}")
    c1 = catalog.cost_usd(TIER1, *REFERENCE_WORKLOAD)
    c2 = catalog.cost_usd(TIER2, *REFERENCE_WORKLOAD)
    print(f"参照ワークロード（入力1,000 / 出力300 トークン）1回あたり: "
          f"tier1 {c1:.6f} USD / tier2 {c2:.6f} USD")
    print(f"ブレークイーブンのエスカレーション率: {break_even_rate():.0%}"
          "  ← これを超えるとカスケードのほうが高い")

    print()
    print("=== 2. 事前ゲートと受け入れ判定（12件） ===")
    usage_cascade, decisions = measure(lambda: run_cascade(WORKLOAD, router))
    print(f"{'requestId':<10}{'task':<10}{'path':<14}{'outcome':<10}reason")
    for d in decisions:
        print(f"{d['requestId']:<10}{d['task']:<10}{d['path']:<14}"
              f"{d['outcome']:<10}{d['reason']}")
    tier1_calls = usage_cascade["perModel"].get(TIER1, {}).get("calls", 0)
    tier2_calls = usage_cascade["perModel"].get(TIER2, {}).get("calls", 0)
    escalated = [d["requestId"] for d in decisions if d["path"] == "tier1>tier2"]
    gated = [d["requestId"] for d in decisions if d["path"] == "gate>tier2"]
    print(f"tier1 の呼び出し {tier1_calls}回 / tier2 の呼び出し {tier2_calls}回")
    print(f"事前ゲートで直行: {gated} / 呼んでから昇格: {escalated}")
    print(f"エスカレーション率: {len(escalated)}/{tier1_calls}"
          f" = {len(escalated) / tier1_calls:.1%}"
          f"（ブレークイーブン {break_even_rate():.0%} を大きく下回る）")

    print()
    print("=== 3. コストの比較（GET /_mock/usage の estimatedUsd） ===")
    usage_top, _ = measure(
        lambda: run_single_tier(WORKLOAD, TIER2, TIER2_MAX_TOKENS, router)
    )
    usage_floor, _ = measure(
        lambda: run_single_tier(WORKLOAD, TIER1, TIER1_MAX_TOKENS, router)
    )
    base = usage_top["estimatedUsdTotal"]
    index_cascade = usage_cascade["estimatedUsdTotal"] / base * 100
    index_floor = usage_floor["estimatedUsdTotal"] / base * 100
    saved = 1 - usage_cascade["estimatedUsdTotal"] / base
    print("基準（全件を上位モデルへ）を 100 とした指数で比べます")
    print(f"[実測] 全件を上位モデルへ : 100（{usage_top['calls']}回 / "
          f"{base:.6f} USD）")
    print(f"[実測] カスケード         : {index_cascade:.0f}"
          f"（{usage_cascade['calls']}回 / "
          f"{usage_cascade['estimatedUsdTotal']:.6f} USD）")
    print(f"[実測] 全件を小型モデルへ : {index_floor:.0f}"
          f"（{usage_floor['calls']}回 / "
          f"{usage_floor['estimatedUsdTotal']:.6f} USD・参考値）")
    print(f"[実測] 削減率: {saved:.1%}")
    print(f"判定A カスケード < 全件を上位モデル : "
          f"{'OK' if usage_cascade['estimatedUsdTotal'] < base else 'NG'}")
    print(f"判定B カスケード > 全件を小型モデル : "
          f"{'OK' if usage_cascade['estimatedUsdTotal'] > usage_floor['estimatedUsdTotal'] else 'NG'}")
    print(f"判定C 上位モデルの呼び出しが {usage_top['calls']}回 → {tier2_calls}回 : "
          f"{'OK' if tier2_calls < usage_top['calls'] else 'NG'}")
    print(f"判定D 削減率が 35% 以上 : {'OK' if saved >= 0.35 else 'NG'}")

    print()
    print("=== 4. モデルを上げても直らないケース ===")
    orphan = {
        "requestId": "req-901",
        "task": "answer",
        "question": "退職金の計算方法を教えてください。",
        "context": "経費精算の締め日は毎月10日です。",
    }
    model_router.reset_mock()
    result = run_one(orphan, router)
    print(f"経路: {result['path']} / 結果: {result['outcome']}"
          f" / 理由: {result['reason']} / 呼び出し {result['calls']}回")
    print(f"利用者に返す文: {result['text']}")
    print("資料に答えが無い問題は上位モデルでも直りません（検索層の問題です）。")
    print("カスケードは「二重に払って両方外す」構造にもなり得ます。")

    model_router.reset_mock()
    print()
    print("モックの会計を初期化しました（課金は一切発生していません）")


if __name__ == "__main__":
    main()
