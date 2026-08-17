#!/usr/bin/env python3
"""評価レポートを作る（引き継げる成果物）。

    python src/session12/report.py

レポートは「数字の一覧」ではなく「誰が何を判断するための数字か」の一覧にする。
読み手が決まっていない数字は、翌週には誰も見ない。

生成物:
  reports/session12_rag_report.json  機械が読む（差分比較・回帰検知に使う）
  reports/session12_rag_report.md    人が読む（週次のふりかえりに貼る）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_lab import MAX_CHARS, TOP_K, Bench, collect_cases, layer_counts, pearson  # noqa: E402
from faithfulness import abstention_matrix, mean  # noqa: E402
from upper_bound import gold_client  # noqa: E402

from ragkit.eval import evaluate  # noqa: E402
from ragkit.llm import FixtureClient  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "reports"


def build_report(bench: Bench) -> dict:
    retrieved = collect_cases(bench, FixtureClient("answers_v1"))
    upper = {c.query_id: c for c in collect_cases(bench, gold_client(bench), gold=True)}
    rep = evaluate(bench.index, bench.queries, bench.qrels, k=10, label="bm25/fixed")

    counts = layer_counts(retrieved)
    answered = [c for c in retrieved if c.judgement.answerable]
    valid = [c for c in answered if c.judgement.citations_valid]
    pairs = [(rep.per_query[c.query_id]["recall"], c)
             for c in retrieved if c.query_id in rep.per_query]

    return {
        "label": "session12 / bm25 / fixed(400,80)",
        "condition": {"retriever": "LexicalIndex(BM25)", "chunk": "fixed(400,80)",
                      "top_k": TOP_K, "max_chars": MAX_CHARS,
                      "llm": "FixtureClient(answers_v1) ＝ 合成カセット"},
        "corpus_layer": {
            "queries": len(bench.queries),
            "answerable": len(bench.answerable_queries()),
            "unanswerable": len(bench.queries) - len(bench.answerable_queries()),
            "failures": counts["corpus"],
            "question": "コーパスに文書を足すべきか",
        },
        "retrieval_layer": {
            "recall@10": round(rep.macro["recall"], 3),
            "ndcg@10": round(rep.macro["ndcg"], 3),
            "mrr": round(rep.macro["mrr"], 3),
            "failures": counts["retrieval"],
            "recoverable_by_retrieval": sum(
                1 for c in retrieved if c.layer == "retrieval" and upper[c.query_id].layer == "ok"),
            "question": "検索の改修に工数を割くべきか",
        },
        "generation_layer": {
            "failures": counts["generation"],
            "abstention": abstention_matrix(bench, retrieved),
            "citation_valid": len(valid),
            "grounded": sum(1 for c in valid if c.judgement.grounded),
            "faithfulness_mean": round(mean([c.judgement.faithfulness for c in valid]), 3),
            "question": "プロンプトと後処理を直すべきか",
        },
        "proxy_check": {
            "r_recall_vs_success": round(
                pearson([r for r, _ in pairs], [1.0 if c.layer == "ok" else 0.0 for _, c in pairs]), 3),
            "question": "Recall@10 を改善指標として使い続けてよいか",
        },
        "upper_bound": {
            "ok": sum(1 for c in upper.values() if c.layer == "ok"),
            "ok_with_retrieved": counts["ok"],
            "question": "検索を直しきったとき、どこまで戻るのか",
        },
        "layer_counts": counts,
    }


def to_markdown(data: dict) -> str:
    rows = [
        ("コーパス担当", data["corpus_layer"]["question"],
         f"コーパス起因 {data['corpus_layer']['failures']} 件 / 回答不能クエリ "
         f"{data['corpus_layer']['unanswerable']} 件"),
        ("検索担当", data["retrieval_layer"]["question"],
         f"検索起因 {data['retrieval_layer']['failures']} 件 / Recall@10 "
         f"{data['retrieval_layer']['recall@10']} / 上限測定で戻る "
         f"{data['retrieval_layer']['recoverable_by_retrieval']} 件"),
        ("生成担当", data["generation_layer"]["question"],
         f"生成起因 {data['generation_layer']['failures']} 件 / 引用有効 "
         f"{data['generation_layer']['citation_valid']} 件 / 忠実性平均 "
         f"{data['generation_layer']['faithfulness_mean']}"),
        ("評価の設計者", data["proxy_check"]["question"],
         f"Recall@10 と回答成功の相関 r = {data['proxy_check']['r_recall_vs_success']}"),
    ]
    lines = [
        "# セッション12 RAG 評価レポート",
        "",
        f"- 条件: {data['label']}",
        f"- 生成: {data['condition']['llm']}（APIキー不要・決定的）",
        "",
        "| 読み手 | 何を判断するか | 見る数字 |",
        "| :--- | :--- | :--- |",
    ]
    lines += [f"| {who} | {what} | {value} |" for who, what, value in rows]
    lines += ["", "## 層別の内訳", "", "| 層 | 件数 |", "| :--- | ---: |"]
    lines += [f"| {k} | {v} |" for k, v in data["layer_counts"].items()]
    lines += ["", "## 次の打ち手（記入欄）", "",
              "1. 直す層: ", "2. 根拠にした数字: ", "3. 直したら戻ると見込む件数: ",
              "4. 効果を確認する再測定日: ", ""]
    return "\n".join(lines)


def main() -> None:
    bench = Bench()
    data = build_report(bench)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "session12_rag_report.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "session12_rag_report.md").write_text(to_markdown(data), encoding="utf-8")
    print("reports/session12_rag_report.json を書きました")
    print("reports/session12_rag_report.md   を書きました")
    print()
    print(to_markdown(data))


if __name__ == "__main__":
    main()
