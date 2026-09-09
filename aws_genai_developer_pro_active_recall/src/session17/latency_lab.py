#!/usr/bin/env python3
"""セッション17: 速さを2つに分けて測る（初回差分までと、完了まで）。

    docker compose exec app python src/session17/latency_lab.py

レイテンシを1つの数字にまとめると、体感の話ができなくなります。本章で扱うのは
次の2つで、**縮め方がまったく違います**。

    体感（初回差分まで）  利用者が最初の1文字を見るまで  → ストリーミングが効く
    完了まで              最後の1文字が届くまで          → ストリーミングは効かない

計測はセッション10の `streaming.sync_answer` / `stream_answer` をそのまま使います
（同じ計測器を使い回さないと、章をまたいだ比較ができません）。事前計算の経路は
セッション16の `answer_cache`（完全一致キャッシュ）を置き場として使います。

**時間の絶対値は環境で変わるため、判定は「注入量以上か」「大小関係」で行います。**
モックの決定的な規則（申告レイテンシ ＝ 20 + 出力トークン数）から導ける値だけを
数字として扱います。
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")
sys.path.insert(0, "/workspace/src/session04")
sys.path.insert(0, "/workspace/src/session09")
sys.path.insert(0, "/workspace/src/session10")
sys.path.insert(0, "/workspace/src/session16")

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

import answer_cache  # noqa: E402  セッション16（完全一致キャッシュ）
import cascade  # noqa: E402  セッション9（トークンの見積もり）
import model_router  # noqa: E402  セッション2（モックの制御 API）
import poc_probe  # noqa: E402  セッション1（質問と system）
import streaming  # noqa: E402  セッション10（2分割の計測器）

MODEL_ID = streaming.DEFAULT_MODEL

# キャッシュキーに入れる版の名前（セッション16と同じ規約）
PROMPT_VERSION = "helpdesk-answer/v2-compact"

# 上流の待ちを再現する注入量。モックの生成時間より十分大きく取り、
# 「注入量以上か」で判定できるようにする
INJECT_MS = 600
INJECT_FLOOR_MS = INJECT_MS * 0.9

# モックの申告レイテンシの規則: 20 + 出力トークン数（決定的）
BASE_LATENCY_MS = 20

# モックが差分を切り出す幅（`bedrock_mock/app.py` の `_chunks(text, size=12)`）
DELTA_CHARS = 12

# 呼ぶ前にトークン数を見積もる関数はセッション9のものを使う（規則を1つに保つ）
token_estimate = cascade.token_estimate


# ---------------------------------------------------------------------------
# レイテンシ予算（設計時の見積もり）
# ---------------------------------------------------------------------------

# **仮定値です。** 実測ではなく「どこに時間が消えるか」を設計時に並べるための値で、
# `bedrock_mock` の擬似単価と同じ位置づけです（絶対値ではなく削れる場所を学ぶ）。
#   group             同時に走らせられる工程のまとまり（並列化の対象）
#   beforeFirstDelta  最初の1文字を出すまでに終わっていなければならないか
#   precomputable     問い合わせが来る前に済ませておけるか
STAGES: tuple[dict, ...] = (
    {"name": "入口の認可", "ms": 10, "group": None,
     "beforeFirstDelta": True, "precomputable": False},
    {"name": "クエリ前処理（書き換え）", "ms": 120, "group": None,
     "beforeFirstDelta": True, "precomputable": True},
    {"name": "ベクトル検索", "ms": 40, "group": "search",
     "beforeFirstDelta": True, "precomputable": False},
    {"name": "キーワード検索", "ms": 30, "group": "search",
     "beforeFirstDelta": True, "precomputable": False},
    {"name": "リランク", "ms": 90, "group": None,
     "beforeFirstDelta": True, "precomputable": False},
    {"name": "入口のガードレール", "ms": 25, "group": None,
     "beforeFirstDelta": True, "precomputable": False},
    {"name": "生成（初回差分まで）", "ms": 320, "group": None,
     "beforeFirstDelta": True, "precomputable": False},
    {"name": "生成（残り）", "ms": 580, "group": None,
     "beforeFirstDelta": False, "precomputable": False},
    {"name": "出口のガードレール", "ms": 25, "group": None,
     "beforeFirstDelta": False, "precomputable": False},
)


def stage_ms(name: str) -> int:
    return next(stage["ms"] for stage in STAGES if stage["name"] == name)


def budget_ms(
    *,
    parallel_search: bool = False,
    precomputed_query: bool = False,
    until_first_delta: bool = False,
) -> int:
    """条件を変えたときの所要時間を、予算から積み上げる。

    並列化した工程は**合計ではなく最大値**で数えます。ここが「並列化で買えるのは
    いちばん遅い1本ぶんまで」という上限の正体です。
    """
    total = 0
    groups: dict[str, int] = {}
    for stage in STAGES:
        if until_first_delta and not stage["beforeFirstDelta"]:
            continue
        if precomputed_query and stage["precomputable"]:
            continue
        if parallel_search and stage["group"]:
            groups[stage["group"]] = max(groups.get(stage["group"], 0), stage["ms"])
            continue
        total += stage["ms"]
    return total + sum(groups.values())


def cache_hit_ms() -> int:
    """事前計算した答えを返すだけの経路。認可以外は1つも通らない。"""
    return stage_ms("入口の認可")


def scenarios() -> list[dict]:
    """体感（初回差分まで）と完了までを、手を1つずつ足しながら並べる。"""
    parallel = {"parallel_search": True}
    precomputed = {"parallel_search": True, "precomputed_query": True}
    return [
        {"tag": "S0", "label": "直列・非ストリーミング",
         "perceived": budget_ms(), "total": budget_ms()},
        {"tag": "S1", "label": "検索2本を並列",
         "perceived": budget_ms(**parallel), "total": budget_ms(**parallel)},
        {"tag": "S2", "label": "＋クエリ前処理を事前計算",
         "perceived": budget_ms(**precomputed), "total": budget_ms(**precomputed)},
        {"tag": "S3", "label": "＋ストリーミング",
         "perceived": budget_ms(**precomputed, until_first_delta=True),
         "total": budget_ms(**precomputed)},
        {"tag": "S3'", "label": "S3 で出口ガードレールを全文に掛ける",
         "perceived": budget_ms(**precomputed), "total": budget_ms(**precomputed)},
        {"tag": "S4", "label": "回答そのものを事前計算（命中）",
         "perceived": cache_hit_ms(), "total": cache_hit_ms()},
    ]


# ---------------------------------------------------------------------------
# 差分がいつ出来上がるか（モックの規則から導く）
# ---------------------------------------------------------------------------


def token_clock(text: str, *, chunk_chars: int = DELTA_CHARS) -> dict:
    """モックの規則を「1トークンあたりの生成時間」と読み替えて見積もる。

    モックが申告するレイテンシは `20 + 出力トークン数` です。この規則を
    生成の進み方だと読み替えると、**最初の差分は全文よりずっと早く出来上がる**
    ことが数字で言えます。実 Bedrock でも構造は同じで、最初のトークンは
    生成完了より前に届きます（だからストリーミングは体感に効きます）。
    """
    pieces = [text[i : i + chunk_chars] for i in range(0, len(text), chunk_chars)] or [""]
    output_tokens = token_estimate(text)
    first_tokens = token_estimate(pieces[0])
    return {
        "chars": len(text),
        "pieces": len(pieces),
        "firstPiece": pieces[0],
        "firstDeltaTokens": first_tokens,
        "outputTokens": output_tokens,
        "modelFirstMs": BASE_LATENCY_MS + first_tokens,
        "modelTotalMs": BASE_LATENCY_MS + output_tokens,
    }


# ---------------------------------------------------------------------------
# 事前計算の経路（置き場はセッション16の完全一致キャッシュ）
# ---------------------------------------------------------------------------


def cache_key_for(question: str, source: str | None) -> str:
    """答えが変わる条件をすべて材料にする（セッション16の原則）。"""
    return answer_cache.cache_key(
        model_id=MODEL_ID,
        prompt_version=PROMPT_VERSION,
        system=poc_probe.SYSTEM_PROMPT,
        user_text=streaming.prompt_text(question, source),
    )


def precompute(runtime, ddb, question: str, source: str | None) -> dict:
    """1件を先に作って置いておく（夜間バッチ・公開時の暖機に相当）。"""
    result = streaming.sync_answer(runtime, question, source)
    answer_cache.put(
        ddb,
        cache_key_for(question, source),
        question=question,
        answer=result["text"],
        output_tokens=result["usage"]["outputTokens"],
    )
    return result


def serve_precomputed(ddb, question: str, source: str | None) -> dict:
    """置いてあるものを返すだけ。基盤モデルは1回も呼ばない。

    初回差分と完了が同時になる点が特徴です（全文を一度に返せる）。
    """
    started = time.perf_counter()
    hit = answer_cache.get(ddb, cache_key_for(question, source))
    elapsed = (time.perf_counter() - started) * 1000
    return {
        "mode": "precomputed",
        "hit": hit is not None,
        "text": hit["answer"] if hit else None,
        "firstDeltaMs": elapsed,
        "totalMs": elapsed,
    }


def run_routes(
    runtime,
    ddb,
    question: str | None = None,
    source: str | None = None,
    *,
    inject_ms: int = INJECT_MS,
) -> dict:
    """同じ質問を3経路で流す。上流の待ちは `latency_ms` で確実に作る。"""
    if question is None:
        question, source = poc_probe.QUESTIONS[0]

    model_router.reset_mock()
    # 事前計算は「問い合わせが来る前」の作業なので、注入する前に済ませる
    reference = precompute(runtime, ddb, question, source)
    # 置き場への初回接続ぶんを計測に混ぜないよう、1回だけ空読みして温める
    serve_precomputed(ddb, question, source)

    model_router.set_behavior(latency_ms=inject_ms)
    try:
        before = model_router.mock_usage()["calls"]
        sync = streaming.sync_answer(runtime, question, source)
        after_sync = model_router.mock_usage()["calls"]
        streamed = streaming.stream_answer(runtime, question, source)
        after_stream = model_router.mock_usage()["calls"]
        cached = serve_precomputed(ddb, question, source)
        after_cache = model_router.mock_usage()["calls"]
    finally:
        # 注入を残すと後続の検証が遅くなる／落ちる。必ず戻す
        model_router.set_behavior(latency_ms=0)

    routes = [
        {
            "tag": "A", "label": "非ストリーミング",
            "calls": after_sync - before,
            # 非ストリーミングは全文が揃うまで何も出せない。初回差分＝完了
            "firstDeltaMs": sync["wallMs"], "totalMs": sync["wallMs"],
            "text": sync["text"], "reportedLatencyMs": sync["reportedLatencyMs"],
        },
        {
            "tag": "B", "label": "ストリーミング",
            "calls": after_stream - after_sync,
            "firstDeltaMs": streamed["firstDeltaMs"], "totalMs": streamed["totalMs"],
            "text": streamed["text"], "reportedLatencyMs": streamed["reportedLatencyMs"],
        },
        {
            "tag": "C", "label": "事前計算（命中）",
            "calls": after_cache - after_stream,
            "firstDeltaMs": cached["firstDeltaMs"], "totalMs": cached["totalMs"],
            "text": cached["text"], "reportedLatencyMs": None,
        },
    ]
    return {"injectMs": inject_ms, "routes": routes, "reference": reference}


# ---------------------------------------------------------------------------
# よくある質問を事前計算で受ける
# ---------------------------------------------------------------------------

# 1日ぶんの問い合わせを模した6件（`poc_probe.QUESTIONS` の添字）。
# 同じ質問の再送を含むので、事前計算の効き方が命中率として出る
CACHE_STREAM: tuple[int, ...] = (0, 0, 1, 0, 1, 2)


def run_cache_stream(runtime, ddb=None) -> list[dict]:
    """命中したら返す、外したら作って置く（キャッシュを温めながら流す）。"""
    ddb = ddb or answer_cache.ensure_table()
    answer_cache.clear(ddb)
    records: list[dict] = []
    for index in CACHE_STREAM:
        question, source = poc_probe.QUESTIONS[index]
        served = serve_precomputed(ddb, question, source)
        if served["hit"]:
            records.append({"qid": f"q{index}", "servedBy": "cache", **served})
            continue
        result = precompute(runtime, ddb, question, source)
        records.append(
            {
                "qid": f"q{index}", "servedBy": "model", "hit": False,
                "text": result["text"],
                "firstDeltaMs": result["wallMs"], "totalMs": result["wallMs"],
            }
        )
    return records


def cache_stats(records: list[dict]) -> dict:
    """命中率は「引いた回数」を分母にする（呼んだ回数ではない）。"""
    hits = sum(1 for record in records if record["servedBy"] == "cache")
    lookups = len(records)
    return {
        "lookups": lookups,
        "hits": hits,
        "calls": lookups - hits,
        "hitRate": round(hits / lookups, 4) if lookups else 0.0,
    }


def served_marks(records: list[dict]) -> str:
    return " ".join(record["servedBy"] for record in records)


# ---------------------------------------------------------------------------
# レイテンシ最適化モデルの選び分け
# ---------------------------------------------------------------------------

# (経路, タスク, 表示名, 宛先モデル)。**対話経路には optimized しか置かない**のが規約
LATENCY_ROUTES: tuple[tuple[str, str, str, str], ...] = (
    ("interactive", "classify", "対話 × 分類・抽出", "amazon.nova-micro-v1:0"),
    ("interactive", "answer", "対話 × 資料に基づく回答", "amazon.nova-lite-v1:0"),
    ("interactive", "reason", "対話 × 推論の質が要る",
     "anthropic.claude-3-5-haiku-20241022-v1:0"),
    ("batch", "answer", "バッチ × 資料に基づく回答", "amazon.nova-pro-v1:0"),
    ("batch", "reason", "バッチ × 推論の質が要る",
     "anthropic.claude-sonnet-4-5-20250929-v1:0"),
    ("batch", "openweight", "バッチ × オープンウェイト",
     "meta.llama3-3-70b-instruct-v1:0"),
)

# セッション2・16と同じ参照ワークロード（入力1,000 / 出力300 トークン）
REFERENCE_WORKLOAD = (1_000, 300)


def latency_class_of(model_id: str) -> str:
    spec, _ = catalog.resolve(model_id)
    return spec.latency_class


def models_by_latency_class() -> dict[str, list[str]]:
    """Converse を使えるモデルを、レイテンシクラスで2つに分ける。"""
    groups: dict[str, list[str]] = {"optimized": [], "standard": []}
    for spec in catalog.MODELS.values():
        if not spec.supports_converse:
            continue
        groups[spec.latency_class].append(spec.model_id)
    return groups


def pick_model(mode: str, task: str) -> str:
    for row_mode, row_task, _, model_id in LATENCY_ROUTES:
        if (row_mode, row_task) == (mode, task):
            return model_id
    raise KeyError(f"未定義の組み合わせです: {mode}/{task}")


def validate_routes(routes: tuple = LATENCY_ROUTES) -> None:
    """宛先表を配る前に検査する（セッション10の `validate_routes` と同じ作法）。

    人が待っている経路にレイテンシ最適化でないモデルを置く、という設定ミスは
    レビューでは見落とされます。**表として検査できる形にしておく**のが要点です。
    """
    for mode, _task, _label, model_id in routes:
        try:
            spec, _ = catalog.resolve(model_id)
        except KeyError:
            raise ValueError(f"カタログに無いモデル ID です: {model_id}") from None
        if not spec.supports_converse:
            raise ValueError(f"Converse API に対応していないモデルです: {model_id}")
        if mode == "interactive" and spec.latency_class != "optimized":
            raise ValueError(
                f"対話経路にレイテンシ最適化でないモデルを置いています: {model_id}"
            )


# ---------------------------------------------------------------------------
# 演習の本体
# ---------------------------------------------------------------------------


def main() -> None:
    runtime = clients.bedrock_runtime()
    ddb = answer_cache.ensure_table()
    question, source = poc_probe.QUESTIONS[0]

    print("=== 1. レイテンシ予算を並べる（仮定値・設計時の見積もり） ===")
    print(f"  工程 {len(STAGES)}つ / 直列に足すと {budget_ms()} ms")
    for row in scenarios():
        print(
            f"[{row['tag']}] {row['label']} -> 体感 {row['perceived']} ms"
            f" / 完了 {row['total']} ms"
        )
    print("ストリーミングが縮めるのは体感だけです（完了までは1msも縮みません）")

    print()
    print("=== 2. 差分がいつ出来上がるか（モックの規則 20 + 出力トークン） ===")
    model_router.reset_mock()
    reference = streaming.sync_answer(runtime, question, source)
    clock = token_clock(reference["text"])
    print(f"  答えの長さ {clock['chars']} 文字 / 出力 {clock['outputTokens']} トークン")
    print(f"  {DELTA_CHARS} 文字ずつ {clock['pieces']} 個の差分に分かれます")
    print(f"  最初の差分「{clock['firstPiece']}」は {clock['firstDeltaTokens']} トークン")
    print(
        f"  最初の差分が出来上がるまで: {BASE_LATENCY_MS} +"
        f" {clock['firstDeltaTokens']} = {clock['modelFirstMs']} ms"
    )
    print(
        f"  全文が出来上がるまで: {BASE_LATENCY_MS} +"
        f" {clock['outputTokens']} = {clock['modelTotalMs']} ms"
    )
    print(f"  API が申告するレイテンシ: {reference['reportedLatencyMs']} ms")

    print()
    print(f"=== 3. 同じ質問を3経路で流す（上流の待ち {INJECT_MS} ms を注入） ===")
    outcome = run_routes(runtime, ddb, question, source)
    for row in outcome["routes"]:
        print(
            f"  [{row['tag']} {row['label']}] 呼び出し {row['calls']}回"
            f" / 初回差分≧注入量: {row['firstDeltaMs'] >= INJECT_FLOOR_MS}"
            f" / 完了≧注入量: {row['totalMs'] >= INJECT_FLOOR_MS}"
        )
    routes = {row["tag"]: row for row in outcome["routes"]}
    print(f"  B の初回差分は完了以前: {routes['B']['firstDeltaMs'] <= routes['B']['totalMs']}")
    print(f"  3経路の本文は一致: {len({row['text'] for row in outcome['routes']}) == 1}")
    print(
        "  申告レイテンシは注入で変わらない:"
        f" {routes['A']['reportedLatencyMs'] == reference['reportedLatencyMs']}"
        f"（{routes['A']['reportedLatencyMs']} ms）"
    )
    print("  注入した待ちは A と B の両方に乗ります。避けられたのは C だけです")

    print()
    print("=== 4. レイテンシ最適化モデルを選び分ける ===")
    validate_routes()
    groups = models_by_latency_class()
    print(f"  optimized: {' / '.join(groups['optimized'])}")
    print(f"  standard : {' / '.join(groups['standard'])}")
    for mode, task, label, model_id in LATENCY_ROUTES:
        usd = catalog.cost_usd(model_id, *REFERENCE_WORKLOAD)
        print(
            f"  {label} -> {model_id}"
            f"（{latency_class_of(model_id)} / 参照ワークロード1回 {usd:.6f} USD）"
        )
    interactive_ok = all(
        latency_class_of(model_id) == "optimized"
        for mode, _task, _label, model_id in LATENCY_ROUTES
        if mode == "interactive"
    )
    print(f"  対話向けの宛先はすべて optimized: {interactive_ok}")

    print()
    print("=== 5. よくある質問を事前計算で受ける（同じ6件を流す） ===")
    records = run_cache_stream(runtime, ddb)
    stats = cache_stats(records)
    print(f"  内訳: {served_marks(records)}")
    print(
        f"  命中 {stats['hits']} / 引き {stats['lookups']} = {stats['hitRate']}"
        f" / モデル呼び出し {stats['calls']}回"
    )
    print("  命中した件は、上流の待ちを1msも払いません（呼んでいないため）")

    answer_cache.clear(ddb)
    model_router.reset_mock()
    print()
    print("モックの障害注入とキャッシュを初期化しました（課金は一切発生していません）")


if __name__ == "__main__":
    main()
