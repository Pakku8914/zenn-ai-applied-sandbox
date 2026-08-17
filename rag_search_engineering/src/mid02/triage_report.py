#!/usr/bin/env python3
"""中間プロジェクト02：失敗を3層に分け、上限測定で分類を反証し、代理指標を点検する。

    docker compose exec app python src/mid02/triage_report.py

成果物③（失敗ケースの3層分類レポート）の材料を、手で写さずに作るためのスクリプト。

生成物:
  reports/mid02_triage.json   機械が読む（次の測定との差分に使う）
  reports/mid02_triage.md     人が読む（成果物③に貼る）

APIキーは不要（合成カセットの再生だけ）。リランクも埋め込みも使わないので CPU で完走する。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # sandbox/
for _p in (str(ROOT), str(ROOT / "src" / "session12"), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from eval_lab import LAYERS, Bench, collect_cases, layer_counts, pearson  # noqa: E402
from make_cassette import ensure_gold_cassette, miss_count  # noqa: E402
from make_gold_cassette import CASSETTE, FLAW_ABSTAIN, FLAW_CITATION  # noqa: E402
from pipeline import MAX_CHARS, TOP_K, AnswerPipeline, verdict_counts  # noqa: E402

from ragkit.eval import evaluate  # noqa: E402
from ragkit.llm import FixtureClient  # noqa: E402

OUT = ROOT / "reports"
BANDS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01))
LABEL_JA = {"ok": "成功", "corpus": "コーパス起因", "retrieval": "検索起因",
            "generation": "生成起因"}


def why(case) -> str:
    """なぜその結末になったのかを1行で言う。理由を残さないと議論できない。"""
    j = case.judgement
    if case.layer == "corpus":
        return "適合文書がコーパスに無く、回答不能と判定した（打ち手はコーパス）"
    if case.layer == "retrieval":
        return f"適合文書が1件も届いていない（上位{case.n_hits}件・完全適合0件）"
    if not j.answerable:
        return "根拠が届いているのに回答不能と答えた"
    if not j.has_citation:
        return "引用が付いていない"
    if not j.citations_valid:
        return f"存在しない chunk_id を引用した（{'・'.join(j.invalid_citations)}）"
    if not j.grounded:
        return "引用先が判定データ上の適合文書ではない"
    return "検査を通過"


def upper_bound_view(bench: Bench, retrieved, upper) -> dict:
    """検索結果版の層ごとに、正解チャンクを渡すとどうなったかを並べる。

    分類は仮説にすぎない。**上限測定で反証されたら分類の方を訂正する。**
    """
    order = {q.query_id: i for i, q in enumerate(bench.queries)}

    def flawed_slot(qid: str) -> bool:
        # 上限測定用カセットは 19件おき・23件おきに欠陥を仕込んである（合成データの仕様）
        i = order[qid]
        return i % FLAW_CITATION == 0 or i % FLAW_ABSTAIN == 0

    rows = []
    for layer in LAYERS:
        ids = [c.query_id for c in retrieved if c.layer == layer]
        if not ids:
            continue
        recovered = sum(1 for qid in ids if upper[qid].layer == "ok")
        rows.append({"layer": layer, "n": len(ids), "recovered": recovered,
                     "stuck": len(ids) - recovered})

    def detail(case) -> dict:
        return {"query_id": case.query_id, "type": case.query_type,
                "reason": why(upper[case.query_id]),
                "n_gold": upper[case.query_id].n_hits,
                "flawed_slot": flawed_slot(case.query_id)}

    return {
        "ok": sum(1 for c in upper.values() if c.layer == "ok"),
        "by_layer": rows,
        # 検索起因と分類したのに、正解チャンクを渡しても直らなかった＝生成起因だった
        "stubborn": [detail(c) for c in retrieved
                     if c.layer == "retrieval" and upper[c.query_id].layer != "ok"],
        # もとは成功していたのに上限測定で失敗した＝カセットが違えば結果も違う
        "regressed": [detail(c) for c in retrieved
                      if c.layer == "ok" and upper[c.query_id].layer != "ok"],
    }


def corrected_layers(counts: dict[str, int], stubborn: list[dict]) -> dict[str, int]:
    """上限測定の結果で分類を訂正する（検索起因 → 生成起因）。"""
    out = dict(counts)
    out["retrieval"] -= len(stubborn)
    out["generation"] += len(stubborn)
    return out


def proxy_view(bench: Bench, retrieved) -> dict:
    """Recall@10 を回答品質の代理指標として使ってよいかを点検する。"""
    rep = evaluate(bench.index, bench.queries, bench.qrels, k=10, label="bm25/fixed")
    by_id = {c.query_id: c for c in retrieved}
    pairs = [(rep.per_query[qid]["recall"], by_id[qid]) for qid in rep.per_query if qid in by_id]
    recalls = [r for r, _ in pairs]
    success = [1.0 if c.layer == "ok" else 0.0 for _, c in pairs]
    faith = [c.judgement.faithfulness for _, c in pairs]

    bands = []
    for lo, hi in BANDS:
        rows = [(r, c) for r, c in pairs if lo <= r < hi]
        ok = sum(1 for _, c in rows if c.layer == "ok")
        bands.append({"band": f"[{lo:.1f}, {min(hi, 1.0):.1f})", "n": len(rows), "ok": ok,
                      "rate": round(ok / len(rows), 3) if rows else None})

    return {
        "n": len(pairs),
        "recall_mean": round(sum(recalls) / len(recalls), 3),
        "success_rate": round(sum(success) / len(success), 3),
        "r_success": round(pearson(recalls, success), 3),
        "r_faithfulness": round(pearson(recalls, faith), 3),
        "bands": bands,
        "high_recall_failures": sum(1 for r, c in pairs if r >= 0.8 and c.layer != "ok"),
        "low_recall_successes": sum(1 for r, c in pairs if r <= 0.2 and c.layer == "ok"),
    }


def build_report(bench: Bench | None = None) -> dict:
    """成果物③に必要な数字を1回の実行でまとめて作る。"""
    bench = bench or Bench()
    normal = FixtureClient("answers_v1")
    retrieved = collect_cases(bench, normal)
    upper = {c.query_id: c for c in collect_cases(bench, ensure_gold_cassette(bench), gold=True)}

    counts = layer_counts(retrieved)
    ub = upper_bound_view(bench, retrieved, upper)
    total = len(bench.queries)

    return {
        "condition": {
            "retriever": "LexicalIndex(BM25)", "chunk": "fixed(400,80)",
            "top_k": TOP_K, "max_chars": MAX_CHARS,
            "llm": "FixtureClient（合成カセット・APIキー不要）",
            "cassettes": {"retrieved": "answers_v1", "upper_bound": CASSETTE,
                          "flawed": "answers_flawed_v1"},
        },
        "totals": {"queries": total, "ok": counts["ok"], "failures": total - counts["ok"],
                   "success_rate": round(counts["ok"] / total, 3)},
        "layers": counts,
        "upper_bound": ub,
        "corrected_layers": corrected_layers(counts, ub["stubborn"]),
        "proxy": proxy_view(bench, retrieved),
        "verdicts": {
            "answers_v1": verdict_counts(AnswerPipeline(bench.index, normal), bench.queries),
            "answers_flawed_v1": verdict_counts(
                AnswerPipeline(bench.index, FixtureClient("answers_flawed_v1")), bench.queries),
        },
        "cassette_cost": {"gold": CASSETTE, "keyerror_on_answers_v1": miss_count(bench, normal),
                          "probed": 30},
        "failures": [{"query_id": c.query_id, "type": c.query_type, "layer": c.layer,
                      "relevant_in_context": c.relevant_in_context, "reason": why(c)}
                     for c in retrieved if c.layer != "ok"],
    }


def to_markdown(data: dict) -> str:
    t, ub, proxy = data["totals"], data["upper_bound"], data["proxy"]
    v = data["verdicts"]
    lines = [
        "# 失敗ケースの3層分類レポート（中間プロジェクト02）",
        "",
        f"- 条件: {data['condition']['chunk']} / {data['condition']['retriever']} / "
        f"上位{data['condition']['top_k']}件 / コンテキスト{data['condition']['max_chars']}字",
        f"- 生成: {data['condition']['llm']}",
        f"- 全体: {t['ok']}/{t['queries']} 件成功（{t['success_rate']:.1%}）／失敗 {t['failures']} 件",
        "",
        "## 1. 層別の内訳（上限測定の前）",
        "",
        "| 層 | 件数 | 打ち手の担当 |",
        "| :--- | ---: | :--- |",
    ]
    owner = {"ok": "—", "corpus": "コーパス（文書を足す）", "retrieval": "検索（届かせる）",
             "generation": "生成（プロンプトと後処理）"}
    lines += [f"| {LABEL_JA[k]} | {data['layers'][k]} | {owner[k]} |" for k in LAYERS]

    lines += ["", "## 2. 上限測定（正解チャンクを渡したらどうなるか）", "",
              f"- 上限で成功: {ub['ok']}/{t['queries']} 件",
              "",
              "| もとの層 | 件数 | 上限で成功 | 上限でも失敗 |",
              "| :--- | ---: | ---: | ---: |"]
    lines += [f"| {LABEL_JA[r['layer']]} | {r['n']} | {r['recovered']} | {r['stuck']} |"
              for r in ub["by_layer"]]

    lines += ["", "### 分類が反証されたケース（検索起因 → 生成起因）", "",
              "| クエリ | 型 | 上限でも失敗した理由 | 欠陥の周期に当たる |",
              "| :--- | :--- | :--- | :--- |"]
    lines += [f"| {s['query_id']} | {s['type']} | {s['reason']} | "
              f"{'はい' if s['flawed_slot'] else 'いいえ'} |"
              for s in ub["stubborn"]] or ["| — | — | — | — |"]

    corrected = data["corrected_layers"]
    lines += ["", "### 訂正後の層", "",
              "| 層 | 訂正前 | 訂正後 |", "| :--- | ---: | ---: |"]
    lines += [f"| {LABEL_JA[k]} | {data['layers'][k]} | {corrected[k]} |" for k in LAYERS]

    lines += ["", "## 3. 後処理が止めた件数（引用検証と回答不能）", "",
              "| カセット | " + " | ".join(v["answers_v1"].keys()) + " |",
              "| :--- |" + " ---: |" * len(v["answers_v1"])]
    for name, counts in v.items():
        lines.append(f"| {name} | " + " | ".join(str(counts[k]) for k in v["answers_v1"]) + " |")

    lines += ["", "## 4. 代理指標の点検", "",
              f"- 対象 {proxy['n']} 件（回答可能クエリのみ）",
              f"- Recall@10 の平均 {proxy['recall_mean']} / 回答成功率 {proxy['success_rate']}",
              f"- r(Recall@10 × 回答成功) = {proxy['r_success']:+.3f}",
              f"- r(Recall@10 × 忠実性) = {proxy['r_faithfulness']:+.3f}",
              f"- Recall 0.8 以上で失敗 {proxy['high_recall_failures']} 件 / "
              f"0.2 以下で成功 {proxy['low_recall_successes']} 件",
              "",
              "| Recall@10 の帯 | 件数 | 回答成功 | 成功率 |", "| :--- | ---: | ---: | ---: |"]
    lines += [f"| {b['band']} | {b['n']} | {b['ok']} | "
              f"{'-' if b['rate'] is None else format(b['rate'], '.1%')} |" for b in proxy["bands"]]

    cc = data["cassette_cost"]
    lines += ["", "## 5. この測定の限界", "",
              f"- 上限測定は別のカセット（{cc['gold']}）で測っている。"
              f"既存カセットに上限測定のプロンプトを投げると "
              f"{cc['keyerror_on_answers_v1']}/{cc['probed']} 件が KeyError になる。",
              "- 生成は合成カセットの再生である。**生成側の失敗率そのものは作り物**であり、"
              "ここで学ぶのは数字ではなく手続き（分類 → 反証 → 訂正）である。",
              "- 判定データは 622 件・クエリ 120 件。1件の増減が成功率を 0.8 ポイント動かす。",
              "", "## 6. 次の打ち手（記入欄）", "",
              "1. 直す層: ", "2. 根拠にした数字: ", "3. 戻ると見込む件数（上限）: ",
              "4. 効果を確認する再測定の条件: ", ""]
    return "\n".join(lines)


def main() -> None:
    bench = Bench()
    data = build_report(bench)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "mid02_triage.json").write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    (OUT / "mid02_triage.md").write_text(to_markdown(data), encoding="utf-8")
    print("reports/mid02_triage.json を書きました")
    print("reports/mid02_triage.md   を書きました")
    print()
    print(to_markdown(data))


if __name__ == "__main__":
    main()
