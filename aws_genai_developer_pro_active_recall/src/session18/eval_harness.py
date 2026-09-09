#!/usr/bin/env python3
"""セッション18: 評価ハーネス（検索と生成を**別々に**採点する）。

    docker compose exec app python src/session18/eval_harness.py

「RAG の精度が低い」という報告からは、直す場所が決まりません。決まるのは次の2つを
別々に採点したときだけです。

    検索の評価   正解文書が上位 k 件に入ったか（Recall@k / 精度 / MRR / レイテンシ）
    生成の評価   引いた資料の文で答えたか・正解の値を含むか・引用が付いているか

生成の評価では**検索を満点にした状態**（正解文書を必ず含む文脈）を渡します。そうしないと、
点が落ちたときに「検索が引けなかった」のか「引けているのに使えなかった」のかが分かりません。

**モックの埋め込みは文字 n-gram のハッシュ**（`sandbox/README.md`）なので、検索スコアの
絶対値には意味がありません。本章で確かめるのは値ではなく、**設定を変えると点が動くこと**と
**動きの向きが説明できること**です。だから期待値は「関係」で書きます（`claims()`）。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

sys.path.insert(0, "/workspace")
for _dir in ("session04", "session05", "session06", "session14", "session15", "session18"):
    sys.path.insert(0, f"/workspace/src/{_dir}")

from awskit import clients  # noqa: E402

import prompt_registry as registry  # noqa: E402  セッション6（版・差し込み・根拠の印）
import retriever  # noqa: E402  セッション5（検索の共通入口）
import transparency  # noqa: E402  セッション15（引用の裏取り support_ratio）

import eval_dataset as dataset  # noqa: E402

MODEL_ID = "amazon.nova-lite-v1:0"
PROMPT_VERSION = 2  # 出典を添える版（セッション6）
MAX_SENTENCES = 3
MAX_TOKENS = 400
DEPARTMENT = "全社"
TOP_K = 3

# 本番相当の設定。品質ゲートはこの設定の点数で判定する
SHIPPED_CONFIG_ID = "cfg-07"

# 検索の設定。**1つずつしか変えない**（2つ変えるとどちらが効いたか分からない）
CONFIGS: tuple[dict, ...] = (
    {"id": "cfg-01", "label": "SEMANTIC / k=1 / 分類なし", "mode": "SEMANTIC",
     "topK": 1, "filter": "none", "rewrite": False},
    {"id": "cfg-02", "label": "SEMANTIC / k=3 / 分類なし", "mode": "SEMANTIC",
     "topK": 3, "filter": "none", "rewrite": False},
    {"id": "cfg-03", "label": "HYBRID / k=3 / 分類なし", "mode": "HYBRID",
     "topK": 3, "filter": "none", "rewrite": False},
    {"id": "cfg-04", "label": "HYBRID / k=3 / 分類なし / クエリ書き換え", "mode": "HYBRID",
     "topK": 3, "filter": "none", "rewrite": True},
    {"id": "cfg-05", "label": "HYBRID_RERANK / k=3 / 分類なし / クエリ書き換え",
     "mode": "HYBRID_RERANK", "topK": 3, "filter": "none", "rewrite": True},
    {"id": "cfg-06", "label": "HYBRID / k=12（母集団の全件）/ 分類なし", "mode": "HYBRID",
     "topK": 12, "filter": "none", "rewrite": False},
    {"id": "cfg-07", "label": "HYBRID / k=3 / 正しい分類", "mode": "HYBRID",
     "topK": 3, "filter": "gold", "rewrite": False},
    {"id": "cfg-08", "label": "HYBRID / k=3 / 誤った分類", "mode": "HYBRID",
     "topK": 3, "filter": "wrong", "rewrite": False},
)


def config_by_id(config_id: str) -> dict:
    return next(config for config in CONFIGS if config["id"] == config_id)


def reset_mock() -> None:
    """評価を流す前に必ず呼ぶ。前の実験の障害注入が残っていると評価が汚れる。"""
    request = urllib.request.Request(
        f"{clients.mock_base_url()}/_mock/reset",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        json.loads(response.read())


# ---------------------------------------------------------------------------
# 検索の評価
# ---------------------------------------------------------------------------


def category_for(config: dict, row: dict) -> str | None:
    if config["filter"] == "gold":
        return row["category"]
    if config["filter"] == "wrong":
        return dataset.WRONG_CATEGORY_OF[row["category"]]
    return None


def query_for(config: dict, row: dict) -> tuple[str, bool]:
    """(検索に投げる文字列, 書き換えが空になったか) を返す。

    `to_keywords` は語彙辞書に載っている語だけを拾います（セッション5）。辞書に無い語で
    聞かれると**空文字**になり、そのまま投げると boto3 の検証で落ちます。
    書き換えを入れるならフォールバックも一緒に入れます。
    """
    if not config["rewrite"]:
        return row["question"], False
    rewritten = retriever.to_keywords(row["question"])
    if rewritten:
        return rewritten, False
    return row["question"], True


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[min(int(0.95 * (len(ordered) - 1)), len(ordered) - 1)], 1)


def evaluate_retrieval(agent, config: dict, rows: tuple[dict, ...]) -> dict:
    """正解文書が上位 k 件に入ったかを採点する。**基盤モデルは1回も呼ばない。**

    Recall@k は「取りこぼしていないか」、精度は「渡した資料のうち何割が当たりか」です。
    k を増やせば Recall は上がりますが、精度は下がり、生成に渡すトークンは増えます。
    片方だけを見て k を決めると、必ずもう片方が悪くなります。
    """
    scored: list[dict] = []
    latencies: list[float] = []
    empty_rewrites: list[str] = []
    for row in rows:
        query, fell_back = query_for(config, row)
        if fell_back:
            empty_rewrites.append(row["id"])
        started = time.perf_counter()
        hits = retriever.search(
            agent,
            query,
            mode=config["mode"],
            top_k=config["topK"],
            category=category_for(config, row),
        )
        latencies.append((time.perf_counter() - started) * 1000)
        uris = [hit["uri"] for hit in hits]
        gold_uri = dataset.URI_OF[row["docId"]]
        rank = uris.index(gold_uri) + 1 if gold_uri in uris else 0
        scored.append(
            {
                "id": row["id"],
                "hit": rank > 0,
                "rank": rank,
                "returned": len(hits),
                # 1件の質問に正解文書は1つなので、精度は当たれば 1/返した件数
                "precision": round(1 / len(hits), 6) if rank > 0 and hits else 0.0,
                "reciprocalRank": round(1 / rank, 6) if rank > 0 else 0.0,
            }
        )
    total = len(scored) or 1
    return {
        "configId": config["id"],
        "label": config["label"],
        "rows": scored,
        "hits": sum(1 for row in scored if row["hit"]),
        "total": len(scored),
        "recall": round(sum(1 for row in scored if row["hit"]) / total, 4),
        "precision": round(sum(row["precision"] for row in scored) / total, 4),
        "mrr": round(sum(row["reciprocalRank"] for row in scored) / total, 4),
        "latencyMsP95": _p95(latencies),
        "emptyRewrites": empty_rewrites,
    }


# ---------------------------------------------------------------------------
# 生成の評価
# ---------------------------------------------------------------------------


def context_for(agent, row: dict) -> tuple[list[dict], str]:
    """生成に渡す文脈を作る。**正解文書を必ず含む分類で引く**（検索を満点にする）。"""
    hits = retriever.search(
        agent, row["question"], mode="HYBRID", top_k=TOP_K, category=row["category"]
    )
    # **並び順を固定する。** 並びが変わると生成の出力も変わるので、検索のばらつきが
    # そのまま生成の点数に混ざります。評価では順序を決め打ちにします
    ordered = sorted(hits, key=lambda hit: dataset.DOC_ID_BY_URI[hit["uri"]])
    citations = [
        {
            "uri": hit["uri"],
            "docId": dataset.DOC_ID_BY_URI[hit["uri"]],
            "revision": hit["updated_at"],
            "score": hit["score"],
        }
        for hit in ordered
    ]
    return citations, "\n".join(hit["text"] for hit in ordered)


def generate(runtime, question: str, sources: str, *, model_id: str = MODEL_ID) -> str:
    """1件生成する。温度0なので**同じ入力なら同じ答え**になる（再現できる評価の前提）。"""
    template = registry.local(registry.PROMPT_NAME, PROMPT_VERSION)
    response = runtime.converse(
        modelId=model_id,
        system=registry.render_system(
            template, {"department": DEPARTMENT, "max_sentences": MAX_SENTENCES}
        ),
        messages=[
            {"role": "user", "content": registry.render_user(question, context_text=sources)}
        ],
        inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.0},
    )
    return registry.text_of(response)


def score_generation(row: dict, *, answer: str, sources: str, citations: list[dict]) -> dict:
    """生成を4つの観測で採点する。**モデルの自己申告は使わない。**

        grounded   根拠に基づいて答えた形になっているか（関連性・一貫性の代理）
        support    その文が本当に資料に書いてあるか（事実正確性。セッション15の裏取り）
        hasValue   正解の値を含むか（事実正確性。ゴールデンデータがあって初めて測れる）
        refused    答えられないと述べたか（断るべき件で断れたか）
    """
    grounded = registry.GROUNDING_MARKER in answer
    refused = registry.REFUSAL_MARKER in answer
    support = transparency.support_ratio(answer, sources)
    has_value = bool(row["goldValue"]) and row["goldValue"] in answer
    if row["docId"] is None:
        # 答えが無い質問は「断れたら正解」。引用付きで何か答えたらハルシネーション
        ok = refused and not grounded
        reason = "断れた" if ok else "答えが無いのに答えた"
    else:
        ok = grounded and support == 1.0 and has_value
        reason = "資料の範囲外と応答した" if refused else ("契約どおり" if ok else "根拠が足りない")
    return {
        "id": row["id"],
        "docId": row["docId"],
        "grounded": grounded,
        "refused": refused,
        "support": support,
        "hasValue": has_value,
        "citationCount": len(citations),
        "ok": ok,
        "reason": reason,
        # 採点役に渡す材料。**評価の結果は本文を持ちます**（本文を持たないのは
        # セッション14の説明責任ログのほうで、役割が違います）
        "answer": answer,
        "sources": sources,
        "citations": citations,
    }


def evaluate_generation(runtime, agent, rows: tuple[dict, ...]) -> dict:
    scored: list[dict] = []
    for row in rows:
        citations, sources = context_for(agent, row)
        answer = generate(runtime, row["question"], sources)
        scored.append(score_generation(row, answer=answer, sources=sources, citations=citations))
    with_gold = [row for row in scored if row["docId"] is not None]
    without_gold = [row for row in scored if row["docId"] is None]
    answerable_total = len(with_gold) or 1
    refusal_total = len(without_gold) or 1
    return {
        "rows": scored,
        "answerable": with_gold,
        "unanswerable": without_gold,
        "grounded": sum(1 for row in with_gold if row["grounded"]),
        "factual": sum(1 for row in with_gold if row["hasValue"]),
        "groundedRate": round(
            sum(1 for row in with_gold if row["grounded"]) / answerable_total, 4
        ),
        "factualRate": round(sum(1 for row in with_gold if row["hasValue"]) / answerable_total, 4),
        "supportMean": round(sum(row["support"] for row in with_gold) / answerable_total, 4),
        "refused": sum(1 for row in without_gold if row["refused"]),
        "refusalRate": round(
            sum(1 for row in without_gold if row["refused"]) / refusal_total, 4
        ),
        "hallucinationRate": round(
            sum(1 for row in without_gold if not row["refused"]) / refusal_total, 4
        ),
        "generationProblems": [
            row["id"] for row in with_gold if not row["ok"]
        ],
    }


# ---------------------------------------------------------------------------
# 切り分けと、評価から言えること
# ---------------------------------------------------------------------------


def diagnose(retrieval: dict, generation: dict) -> dict:
    """検索の問題か、生成の問題かを1件ずつ振り分ける。

    **検索が外れている件に生成の点を付けても、直す場所は分かりません。** 順番が大事で、
    先に検索を見ます。検索が当たっているのに答えられない件だけが生成側の課題です。
    """
    gen_by_id = {row["id"]: row for row in generation["answerable"]}
    verdicts: dict[str, str] = {}
    for row in retrieval["rows"]:
        if not row["hit"]:
            verdicts[row["id"]] = "retrieval"
        elif not gen_by_id[row["id"]]["ok"]:
            verdicts[row["id"]] = "generation"
        else:
            verdicts[row["id"]] = "ok"
    return {
        "configId": retrieval["configId"],
        "verdicts": verdicts,
        "ok": [key for key, value in verdicts.items() if value == "ok"],
        "retrievalProblems": [key for key, value in verdicts.items() if value == "retrieval"],
        "generationProblems": [key for key, value in verdicts.items() if value == "generation"],
    }


def claims(reports: dict[str, dict]) -> list[tuple[str, bool]]:
    """検索の評価から**関係として**言えること。値そのものを覚えないための書き方。"""
    k1, k3 = reports["cfg-01"], reports["cfg-02"]
    everything, gold, wrong = reports["cfg-06"], reports["cfg-07"], reports["cfg-08"]
    return [
        ("[1] k を 1 -> 3 に増やすと Recall@k は下がらない", k3["recall"] >= k1["recall"]),
        (
            f"[2] k=12（母集団の全件）なら Recall@k = {everything['recall']:.4f} /"
            f" 精度 = {everything['precision']:.4f}",
            everything["recall"] == 1.0 and everything["precision"] == 0.0833,
        ),
        (
            f"[3] 正しい分類で絞れば k=3 でも Recall@k = {gold['recall']:.4f} /"
            f" 精度 = {gold['precision']:.4f}",
            gold["recall"] == 1.0 and gold["precision"] == 0.3333,
        ),
        (
            f"[4] 誤った分類で絞ると Recall@k = {wrong['recall']:.4f}（正解が母集団から消える）",
            wrong["recall"] == 0.0,
        ),
        (
            "[5] Recall を k で買うと精度は下がる"
            f"（{gold['precision']:.4f} -> {everything['precision']:.4f}）",
            everything["precision"] < gold["precision"],
        ),
    ]


def measure(
    *, retrieval: dict | None = None, generation: dict | None = None, runtime=None, agent=None
) -> dict:
    """品質ゲートが判定する指標を、1回の実行でそろえる。

    すでに採点済みのレポートがあれば渡してください（同じ評価を2回流すと、呼び出し回数の
    突き合わせも費用も倍になります）。
    """
    if retrieval is None or generation is None:
        runtime = runtime or clients.bedrock_runtime()
        agent = agent or clients.agent_runtime()
        rows = dataset.rows()
        if retrieval is None:
            retrieval = evaluate_retrieval(
                agent, config_by_id(SHIPPED_CONFIG_ID), dataset.answerable(rows)
            )
        if generation is None:
            generation = evaluate_generation(runtime, agent, rows)
    return {
        "retrievalRecall": retrieval["recall"],
        "generationGrounded": generation["groundedRate"],
        "generationFactual": generation["factualRate"],
        "supportRatio": generation["supportMean"],
        "refusalRate": generation["refusalRate"],
        "hallucinationRate": generation["hallucinationRate"],
        "retrievalLatencyMsP95": retrieval["latencyMsP95"],
    }


# ---------------------------------------------------------------------------
# 実行
# ---------------------------------------------------------------------------


def retrieval_line(report: dict) -> str:
    return (
        f"  {report['configId']} Recall@k={report['recall']:.4f}"
        f" 精度={report['precision']:.4f} MRR={report['mrr']:.4f}"
        f" 書き換えが空={len(report['emptyRewrites'])}件  {report['label']}"
    )


def generation_line(row: dict) -> str:
    mark = "○" if row["grounded"] else "×"
    fact = "○" if row["hasValue"] else "×"
    verdict = "ok" if row["ok"] else f"ng（{row['reason']}）"
    return (
        f"  {row['id']} {row['docId']} 根拠{mark} 裏取り {row['support']:.4f}"
        f" 事実{fact} 引用{row['citationCount']} {verdict}"
    )


def refusal_line(row: dict) -> str:
    return (
        f"  {row['id']} 断り{'○' if row['refused'] else '×'}"
        f" 作り話{'×' if row['refused'] else '○'} {'ok' if row['ok'] else 'ng'}"
    )


def main() -> None:
    reset_mock()
    agent = clients.agent_runtime()
    runtime = clients.bedrock_runtime()
    rows = dataset.rows()
    covered, total_docs = dataset.coverage(rows)

    print("=== 1. 評価データセット ===")
    print(
        f"  質問 {len(rows)} 件"
        f"（資料から答えられる {len(dataset.answerable(rows))} /"
        f" 答えが無い {len(dataset.unanswerable(rows))}）"
    )
    print(f"  正解文書のカバレッジ: {total_docs} 文書のうち {covered} 件")
    counts = dataset.category_counts(rows)
    print("  分類の内訳: " + " / ".join(f"{name} {counts[name]}" for name in dataset.CATEGORIES))

    print()
    print(f"=== 2. 検索の評価（設定ごとに {len(dataset.answerable(rows))} 件を採点する） ===")
    reports: dict[str, dict] = {}
    for config in CONFIGS:
        reports[config["id"]] = evaluate_retrieval(agent, config, dataset.answerable(rows))
        print(retrieval_line(reports[config["id"]]))

    print()
    print("=== 3. 設定を変えるとスコアは動く（値ではなく関係で確かめる） ===")
    for label, holds in claims(reports):
        print(f"  {label}: {holds}")
    print(
        f"  [6] クエリ書き換えが空になった質問: {len(reports['cfg-04']['emptyRewrites'])}"
        f"/{reports['cfg-04']['total']} 件（語彙辞書に無い語で聞かれている）"
    )
    again = evaluate_retrieval(agent, config_by_id("cfg-03"), dataset.answerable(rows))
    print(f"  [7] 同じ設定を2回流すと同じスコアになる: {again['recall'] == reports['cfg-03']['recall']}")

    print()
    print("=== 4. 生成の評価（検索を満点にした状態で生成だけを測る） ===")
    generation = evaluate_generation(runtime, agent, rows)
    print(f"  -- 資料から答えられる {len(generation['answerable'])} 件 --")
    for row in generation["answerable"]:
        print(generation_line(row))
    print(
        f"  根拠提示率 {generation['grounded']}/{len(generation['answerable'])}"
        f" = {generation['groundedRate']:.4f} /"
        f" 事実一致率 {generation['factual']}/{len(generation['answerable'])}"
        f" = {generation['factualRate']:.4f} /"
        f" 裏取りの平均 {generation['supportMean']:.4f}"
    )
    print(f"  -- 資料に答えが無い {len(generation['unanswerable'])} 件（断れれば正解） --")
    for row in generation["unanswerable"]:
        print(refusal_line(row))
    print(
        f"  適切な拒否率 {generation['refused']}/{len(generation['unanswerable'])}"
        f" = {generation['refusalRate']:.4f} /"
        f" ハルシネーション率 {generation['hallucinationRate']:.4f}"
    )

    print()
    print("=== 5. 切り分け（検索の問題か、生成の問題か） ===")
    shipped = diagnose(reports[SHIPPED_CONFIG_ID], generation)
    broken = diagnose(reports["cfg-08"], generation)
    for label, report in (("正しい分類(cfg-07)", shipped), ("誤った分類(cfg-08)", broken)):
        print(
            f"  {label}: ok {len(report['ok'])} 件 /"
            f" 生成の問題 {len(report['generationProblems'])} 件 /"
            f" 検索の問題 {len(report['retrievalProblems'])} 件"
        )
    print(f"  生成の問題と判定された質問: {shipped['generationProblems']}")
    print("  ※ 検索が外れている件の生成スコアを見ても、直す場所は分かりません")


if __name__ == "__main__":
    main()
