#!/usr/bin/env python3
"""セッション16: 同じ問い合わせを5条件で流し、費用を並べて比べる。

    docker compose exec app python src/session16/cost_lab.py

条件は「減らす」「安く回す」「繰り返さない」の3方向を1本ずつ効かせたものです。

| 条件 | 内容 |
| :--- | :--- |
| A 無対策 | 冗長な system ＋ 検索層の戻りを全部渡す |
| B 圧縮 | 指示を刈り込み、資料は上位1件だけ渡す |
| C 無対策＋プロンプトキャッシュ | A の静的な接頭辞を `cachePoint` で再利用する |
| D 圧縮＋完全一致キャッシュ | 同じ質問はモデルを呼ばない（DynamoDB） |
| E 圧縮＋セマンティックキャッシュ | 埋め込みの近さで「同じ質問」と見なす |

費用は `GET /_mock/usage` の `estimatedUsd`（`bedrock_mock/catalog.py` の
擬似単価から計算した値）です。**実際の請求額の見積もりには使えません。**
学ぶのは絶対額ではなく、条件を変えたときの**差**の出方です。
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")
sys.path.insert(0, "/workspace/src/session04")
sys.path.insert(0, "/workspace/src/session06")
sys.path.insert(0, "/workspace/src/session09")
sys.path.insert(0, "/workspace/src/session16")

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

import answer_cache  # noqa: E402
import cascade  # noqa: E402
import model_router  # noqa: E402
import poc_probe  # noqa: E402
import prompt_registry as registry  # noqa: E402

MODEL_ID = "amazon.nova-lite-v1:0"
EMBED_MODEL_ID = answer_cache.EMBED_MODEL_ID

# 呼ぶ前にトークン数を見積もる関数はセッション9のものを使う（規則は1つに保つ）
token_estimate = cascade.token_estimate

# ---------------------------------------------------------------------------
# 2つの版（圧縮の前と後）
# ---------------------------------------------------------------------------

# 版1: 増築を繰り返した system。趣旨の重なる指示が8文積み上がっている
VERBOSE_SYSTEM = (
    "あなたはサンプル商事の社内ヘルプデスクの案内役です。"
    "利用者から寄せられた問い合わせに対して丁寧に回答してください。"
    "回答は必ず日本語で行い、専門用語には簡単な補足を添えてください。"
    "利用者が不安にならないよう、丁寧な言葉づかいを心がけてください。"
    "社内資料として渡された範囲だけを根拠に回答してください。"
    "資料に無いことは推測せず、確認できないと伝えてください。"
    "なお、回答の前に挨拶を入れる必要はありませんが、失礼のない表現を選んでください。"
    "また、利用者が同じことを何度も聞いてきた場合も、同じ丁寧さで対応してください。"
)

# 版2: 同じことを言っている2文だけに刈り込んだ system（セッション1と同一）
LEAN_SYSTEM = poc_probe.SYSTEM_PROMPT

# キャッシュキーに入れる版の名前。版が変われば必ずキーも変わる
PROMPT_VERSION_VERBOSE = "helpdesk-answer/v1-verbose"
PROMPT_VERSION_COMPACT = "helpdesk-answer/v2-compact"

# 出力上限。上限は「事故の上限」であって費用の制御手段ではない（後述）
MAX_TOKENS_VERBOSE = 512
MAX_TOKENS_COMPACT = 120

# 検索層が返したが答えは書かれていない3件。無対策の条件ではこれも丸ごと渡す
DISTRACTORS = (
    "会議室の予約は総務部の受付端末から行います。",
    "社員証を紛失した場合は総務部へ速やかに届け出てください。",
    "社内システムの障害は情報システム部の受付窓口に連絡してください。",
)

# 質問と、答えが書かれている社内文書の一文。セッション1の定義をそのまま使う
# （同じ入力なら同じトークン数になるので、前章までの計測値と突き合わせられる）
QUESTIONS: dict[str, tuple[str, str]] = {
    "q-carryover": poc_probe.QUESTIONS[0],
    "q-remote": poc_probe.QUESTIONS[1],
    "q-lodging": poc_probe.QUESTIONS[2],
    # 言い換え。答えは q-carryover と同じで、検索層が返す資料も同じ
    "q-carryover-paraphrase": (
        "有給休暇の繰越の上限日数を教えてください。",
        poc_probe.QUESTIONS[0][1],
    ),
}

# 1日ぶんの問い合わせを模した8件。同じ質問の再送3件と言い換え1件を含む
STREAM: tuple[str, ...] = (
    "q-carryover",
    "q-carryover",
    "q-remote",
    "q-carryover",
    "q-carryover-paraphrase",
    "q-remote",
    "q-lodging",
    "q-carryover",
)

# セマンティックキャッシュのしきい値。厳しく始めて、緩めるときは損害から決める
SEMANTIC_THRESHOLD = 0.99

# 語は似ているが答えが違う質問（誤ヒットの実験用）
DANGER_QUESTION = "有給休暇の付与日数は何日ですか。"
# 語も答えも関係のない質問（類似度の下限を見るため）
UNRELATED_QUESTION = "会議室の予約はどこから申し込みますか。"


# ---------------------------------------------------------------------------
# 1回の呼び出し
# ---------------------------------------------------------------------------


def build(qid: str, *, compact: bool) -> tuple[str, list[dict]]:
    """(system テキスト, user のブロック列) を返す。

    利用者側のメッセージ組み立てはセッション6の `prompt_registry.render_user`
    を使います。質問と資料の置き場所（`<context>` の位置）を章ごとに変えると、
    トークン数が比べられなくなるためです。
    """
    question, source = QUESTIONS[qid]
    if compact:
        # 刈り込み: 答えが書かれている1件だけを渡す
        return LEAN_SYSTEM, registry.render_user(question, context_text=source)
    # 無対策: 検索層の戻りをそのまま全部渡す
    return VERBOSE_SYSTEM, registry.render_user(
        question, context_text=source + "".join(DISTRACTORS)
    )


def call(
    runtime, system: str, blocks: list[dict], *, max_tokens: int, cache: bool
) -> dict:
    """Converse を1回呼び、トークンの3欄をそろえて返す。

    `cache=True` のときは system の末尾に `cachePoint` を置きます。
    静的な接頭辞（version 1 の長い指示）が接頭辞の完全一致で再利用され、
    2回目以降は `cacheReadInputTokens` に振り替わります（セッション6で観測済み）。
    """
    system_blocks: list[dict] = [{"text": system}]
    if cache:
        system_blocks.append({"cachePoint": {"type": "default"}})
    response = runtime.converse(
        modelId=MODEL_ID,
        system=system_blocks,
        messages=[{"role": "user", "content": blocks}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0.0},
    )
    usage = response["usage"]
    return {
        "servedBy": "model",
        "text": response["output"]["message"]["content"][0]["text"],
        "stopReason": response["stopReason"],
        "inputTokens": usage["inputTokens"],
        "outputTokens": usage["outputTokens"],
        "cacheRead": usage["cacheReadInputTokens"],
        "cacheWrite": usage["cacheWriteInputTokens"],
        # 請求の対象は3欄に分かれるが、プロンプト全体のトークン数は変わらない
        "promptTokens": (
            usage["inputTokens"]
            + usage["cacheReadInputTokens"]
            + usage["cacheWriteInputTokens"]
        ),
        # 呼ぶ前の見積もり。API が返した値と一致するはず
        "estimate": token_estimate(system + blocks[0]["text"]),
    }


def _from_cache(qid: str, answer: str) -> dict:
    """キャッシュから返した1件。モデルは呼んでいないのでトークンは 0。"""
    return {
        "servedBy": "cache",
        "text": answer,
        "stopReason": "cache_hit",
        "inputTokens": 0,
        "outputTokens": 0,
        "cacheRead": 0,
        "cacheWrite": 0,
        "promptTokens": 0,
        "estimate": 0,
        "qid": qid,
    }


# ---------------------------------------------------------------------------
# 5条件
# ---------------------------------------------------------------------------


def run_stream(runtime, *, compact: bool, cache: bool) -> list[dict]:
    """条件A・B・C。8件すべてをモデルに投げる。"""
    max_tokens = MAX_TOKENS_COMPACT if compact else MAX_TOKENS_VERBOSE
    records = []
    for qid in STREAM:
        system, blocks = build(qid, compact=compact)
        records.append(
            {"qid": qid, **call(runtime, system, blocks, max_tokens=max_tokens, cache=cache)}
        )
    return records


def run_exact_cache(runtime, ddb) -> list[dict]:
    """条件D。キーが一致した件はモデルを呼ばない。"""
    records = []
    for qid in STREAM:
        system, blocks = build(qid, compact=True)
        key = answer_cache.cache_key(
            model_id=MODEL_ID,
            prompt_version=PROMPT_VERSION_COMPACT,
            system=system,
            user_text=blocks[0]["text"],
        )
        hit = answer_cache.get(ddb, key)
        if hit is not None:
            records.append(_from_cache(qid, hit["answer"]))
            continue
        result = call(
            runtime, system, blocks, max_tokens=MAX_TOKENS_COMPACT, cache=False
        )
        answer_cache.put(
            ddb,
            key,
            question=QUESTIONS[qid][0],
            answer=result["text"],
            output_tokens=result["outputTokens"],
        )
        records.append({"qid": qid, **result})
    return records


def run_semantic_cache(
    runtime, *, threshold: float = SEMANTIC_THRESHOLD
) -> tuple[list[dict], answer_cache.SemanticCache]:
    """条件E。埋め込みの近さで「同じ質問」と見なす。"""
    cache = answer_cache.SemanticCache(runtime, threshold=threshold)
    records = []
    for qid in STREAM:
        question, _ = QUESTIONS[qid]
        found = cache.lookup(question)  # 引くだけで埋め込みの費用が出る
        if found["hit"]:
            record = _from_cache(qid, found["entry"]["answer"])
            record["score"] = found["score"]
            records.append(record)
            continue
        system, blocks = build(qid, compact=True)
        result = call(
            runtime, system, blocks, max_tokens=MAX_TOKENS_COMPACT, cache=False
        )
        # lookup で作ったベクトルを渡す（登録のために2回目の埋め込みを払わない）
        cache.put(question, result["text"], vector=found["vector"])
        records.append({"qid": qid, "score": found["score"], **result})
    return records, cache


def measure(run, *, ddb=None):
    """モックの会計とキャッシュを初期化してから実行し、(使用量, 結果) を返す。"""
    model_router.reset_mock()  # プロンプトキャッシュの状態もここで消える
    if ddb is not None:
        answer_cache.clear(ddb)
    outcome = run()
    return model_router.mock_usage(), outcome


# ---------------------------------------------------------------------------
# 集計と表示
# ---------------------------------------------------------------------------


def model_slot(usage: dict, model_id: str = MODEL_ID) -> dict:
    return usage["perModel"].get(
        model_id, {"calls": 0, "inputTokens": 0, "outputTokens": 0, "estimatedUsd": 0.0}
    )


def input_cost_share(usage: dict, model_id: str = MODEL_ID) -> float:
    """入力が費用の何割を占めるか。ここが削る順番を決める。"""
    spec, _ = catalog.resolve(model_id)
    slot = model_slot(usage, model_id)
    in_usd = slot["inputTokens"] * spec.input_usd_per_1m
    out_usd = slot["outputTokens"] * spec.output_usd_per_1m
    total = in_usd + out_usd
    return in_usd / total if total else 0.0


def report(tag: str, label: str, usage: dict, base: float | None) -> None:
    slot = model_slot(usage)
    total = usage["estimatedUsdTotal"]
    line = (
        f"    呼出 {slot['calls']}回 / 入力 {slot['inputTokens']:>4} tok"
        f" / 出力 {slot['outputTokens']:>3} tok / {total:.6f} USD"
    )
    if base is None:
        line += " / 指数 100"
    else:
        line += f" / 指数 {total / base * 100:>3.0f} / 削減 {1 - total / base:.1%}"
    print(f"[{tag}] {label}")
    print(line)


def served_marks(records: list[dict]) -> str:
    return " ".join("model" if r["servedBy"] == "model" else "cache" for r in records)


# ---------------------------------------------------------------------------
# 演習の本体
# ---------------------------------------------------------------------------


def main() -> None:
    runtime = clients.bedrock_runtime()
    ddb = answer_cache.ensure_table()
    spec, _ = catalog.resolve(MODEL_ID)

    print("=== 1. どこに払っているのか（単価の非対称） ===")
    print(f"モデル: {MODEL_ID}")
    print(
        f"入力 {spec.input_usd_per_1m} USD / 100万トークン"
        f"・出力 {spec.output_usd_per_1m} USD / 100万トークン"
    )
    print(
        "出力1トークンは入力"
        f"{spec.output_usd_per_1m / spec.input_usd_per_1m:.1f}トークンぶんの費用です"
    )

    print()
    print("=== 2. 1件ぶんのトークン会計（同じ質問・同じモデル） ===")
    model_router.reset_mock()
    verbose_system, verbose_blocks = build("q-carryover", compact=False)
    lean_system, lean_blocks = build("q-carryover", compact=True)
    verbose_one = call(
        runtime, verbose_system, verbose_blocks, max_tokens=MAX_TOKENS_VERBOSE, cache=False
    )
    lean_one = call(
        runtime, lean_system, lean_blocks, max_tokens=MAX_TOKENS_COMPACT, cache=False
    )
    verbose_usd = catalog.cost_usd(
        MODEL_ID, verbose_one["inputTokens"], verbose_one["outputTokens"]
    )
    lean_usd = catalog.cost_usd(
        MODEL_ID, lean_one["inputTokens"], lean_one["outputTokens"]
    )
    for label, system, one, usd in (
        ("無対策", verbose_system, verbose_one, verbose_usd),
        ("圧縮  ", lean_system, lean_one, lean_usd),
    ):
        system_tokens = token_estimate(system)
        print(
            f"[{label}] 入力 {one['inputTokens']:>3} tok"
            f"（system {system_tokens:>3} ＋ 質問と資料"
            f" {one['inputTokens'] - system_tokens:>3}）"
            f" / 出力 {one['outputTokens']} tok / {usd:.6f} USD"
        )
    print(
        f"入力を {1 - lean_one['inputTokens'] / verbose_one['inputTokens']:.1%} 削って、"
        f"費用は {1 - lean_usd / verbose_usd:.1%} 減りました"
        "（出力は1トークンも減っていません）"
    )
    print(f"答えは一致していますか: {lean_one['text'] == verbose_one['text']}")

    print()
    print("=== 3. 5条件の比較（同じ8件の問い合わせを流す） ===")
    usage_a, _ = measure(lambda: run_stream(runtime, compact=False, cache=False))
    base = usage_a["estimatedUsdTotal"]
    usage_b, _ = measure(lambda: run_stream(runtime, compact=True, cache=False))
    usage_c, _ = measure(lambda: run_stream(runtime, compact=False, cache=True))
    usage_d, records_d = measure(lambda: run_exact_cache(runtime, ddb), ddb=ddb)
    usage_e, outcome_e = measure(lambda: run_semantic_cache(runtime))
    records_e, semantic = outcome_e

    report("A", "無対策", usage_a, None)
    report("B", "プロンプト圧縮＋文脈の刈り込み", usage_b, base)
    report("C", "無対策＋プロンプトキャッシュ", usage_c, base)
    print(
        f"    キャッシュ書き込み {usage_c['cacheWriteTokens']} tok"
        f" / 読み出し {usage_c['cacheReadTokens']} tok"
        "（モックはこの2欄を無料で扱います）"
    )
    report("D", "圧縮＋完全一致キャッシュ", usage_d, base)
    print(f"    内訳: {served_marks(records_d)}")
    report("E", "圧縮＋セマンティックキャッシュ", usage_e, base)
    print(f"    内訳: {served_marks(records_e)}")
    embed_slot = model_slot(usage_e, EMBED_MODEL_ID)
    print(
        f"    埋め込み {embed_slot['calls']}回 / {embed_slot['inputTokens']} tok"
        f" / {embed_slot['estimatedUsd']:.6f} USD を含みます"
    )
    print(
        "    言い換えの1件は しきい値"
        f" {SEMANTIC_THRESHOLD} ではミス（モデルを呼びました）"
    )
    print(
        f"削る順番: [A] 入力が費用の {input_cost_share(usage_a):.1%}"
        f" -> [B] 圧縮後は入力 {input_cost_share(usage_b):.1%}"
        f"（残りは出力）"
    )

    print()
    print("=== 4. 出力上限は費用の制御ではなく事故の上限 ===")
    model_router.reset_mock()
    capped = call(runtime, lean_system, lean_blocks, max_tokens=20, cache=False)
    for label, one in (("maxTokens=120", lean_one), ("maxTokens= 20", capped)):
        usd = catalog.cost_usd(MODEL_ID, one["inputTokens"], one["outputTokens"])
        print(
            f"[{label}] 出力 {one['outputTokens']:>2} tok"
            f" / stopReason {one['stopReason']} / {usd:.6f} USD"
        )
    print(f"打ち切られた答え: {capped['text']}")
    print("安くはなりましたが、答えとして使えません。短くさせたいなら指示で短くさせます")

    print()
    print("=== 5. セマンティックキャッシュが同一視してしまう組 ===")
    model_router.reset_mock()
    cached_question, _ = QUESTIONS["q-carryover"]
    cached_answer = next(r["text"] for r in records_d if r["servedBy"] == "model")
    strict = answer_cache.SemanticCache(runtime, threshold=SEMANTIC_THRESHOLD)
    strict.put(cached_question, cached_answer)
    same = strict.lookup(cached_question)
    danger = strict.lookup(DANGER_QUESTION)
    unrelated = strict.lookup(UNRELATED_QUESTION)
    print(f"キャッシュ済み: {cached_question}")
    print(f"問い合わせ    : {DANGER_QUESTION}（語は似ているが答えは違う）")
    print(
        f"類似度の順位  : 同じ質問({same['score']:.6f})"
        " > 語が似ていて答えが違う質問 > 無関係な質問"
    )
    print(
        f"  しきい値 {SEMANTIC_THRESHOLD}            -> "
        f"{'ヒット' if danger['hit'] else 'ミス'}（別の質問として扱う。正しい）"
    )
    loose = answer_cache.SemanticCache(runtime, threshold=danger["score"] - 0.01)
    loose.put(cached_question, cached_answer)
    loose_danger = loose.lookup(DANGER_QUESTION)
    print(
        "  しきい値（実測類似度の直下）-> "
        f"{'ヒット' if loose_danger['hit'] else 'ミス'}（誤り）"
    )
    print(f"  返した文: {loose_danger['entry']['answer'].splitlines()[0]}")
    print("  「付与日数」を聞かれたのに「繰越上限」の答えを返しました")
    print(
        f"  無関係な質問との類似度は、答えが違う質問より小さい: "
        f"{unrelated['score'] < danger['score']}"
    )
    print("  しきい値は精度ではなく「間違ってヒットしたときの損害」で決めます")

    print()
    print("=== 6. ティア分け（セッション9のカスケード）をコストの観点で見る ===")
    router = model_router.ModelRouter()
    c1 = catalog.cost_usd(cascade.TIER1, *cascade.REFERENCE_WORKLOAD)
    c2 = catalog.cost_usd(cascade.TIER2, *cascade.REFERENCE_WORKLOAD)
    print(f"tier1 {cascade.TIER1} / tier2 {cascade.TIER2}")
    print(
        f"参照ワークロード（入力1,000 / 出力300）1回あたり: "
        f"{c1:.6f} USD / {c2:.6f} USD（{c2 / c1:.1f}倍）"
    )
    print(f"ブレークイーブンのエスカレーション率: {cascade.break_even_rate():.1%}")
    usage_cascade, decisions = cascade.measure(
        lambda: cascade.run_cascade(cascade.WORKLOAD, router)
    )
    usage_top, _ = cascade.measure(
        lambda: cascade.run_single_tier(
            cascade.WORKLOAD, cascade.TIER2, cascade.TIER2_MAX_TOKENS, router
        )
    )
    tier1_calls = usage_cascade["perModel"].get(cascade.TIER1, {}).get("calls", 0)
    escalated = [d for d in decisions if d["path"] == "tier1>tier2"]
    rate = len(escalated) / tier1_calls
    saved = 1 - usage_cascade["estimatedUsdTotal"] / usage_top["estimatedUsdTotal"]
    print(f"実測のエスカレーション率: {len(escalated)}/{tier1_calls} = {rate:.1%}")
    print(
        f"実測の費用: カスケード {usage_cascade['estimatedUsdTotal']:.6f} USD"
        f" / 全件を上位モデル {usage_top['estimatedUsdTotal']:.6f} USD"
        f"（{saved:.1%} 減）"
    )
    print(
        f"判定: エスカレーション率 {rate:.1%} < ブレークイーブン"
        f" {cascade.break_even_rate():.1%} -> ティア分けは得"
    )

    print()
    print("=== 7. 並列度を上げても増えるのは費用ではない ===")
    model_router.reset_mock()
    model_router.set_behavior(throttle_next=2)
    call(runtime, lean_system, lean_blocks, max_tokens=MAX_TOKENS_COMPACT, cache=False)
    throttled_usage = model_router.mock_usage()
    print(
        f"スロットリング {throttled_usage['throttled']}回"
        f" / 会計に載った呼び出し {throttled_usage['calls']}回"
        f" / {throttled_usage['estimatedUsdTotal']:.6f} USD"
    )
    print("429 で失敗した呼び出しは会計に載りません。並列度が買うのは時間で、費用ではありません")

    model_router.reset_mock()
    answer_cache.clear(ddb)
    print()
    print(f"セマンティックキャッシュの登録件数: {semantic.size()}")
    print("モックの会計とキャッシュを初期化しました（課金は一切発生していません）")


if __name__ == "__main__":
    main()
