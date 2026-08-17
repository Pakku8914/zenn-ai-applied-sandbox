#!/usr/bin/env python3
"""最終プロジェクト：検索基盤を1回の実行で測り切り、レポートにする。

    docker compose exec app python src/final/evaluate.py

測るのは4つ。**どれか1つでも欠けると引き継げない。**

  1. 検索の精度   クエリ型別の Recall@10（基準線と採用構成）
  2. 権限         全クエリ × 全役割の混入検査（0 でなければ即不合格）
  3. 回答         6判定の分布と、失敗の3層分類（コーパス / 検索 / 生成）
  4. 運用の前提   レイテンシ予算・コスト試算・可観測性で検知できる幅

生成物: `reports/final_platform.json` / `reports/final_platform.md`
APIキーは不要（生成は合成カセット）。埋め込みモデルもリランカも使わない。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from final_cassette import ensure_cassette  # noqa: E402
from reuse import ROOT, access, bench, cost, drift, obs, ops, plan  # noqa: E402
from search_platform import (  # noqa: E402
    ADOPTED,
    BASELINE,
    FIRST_STAGE_MS,
    LATENCY_BUDGET_MS,
    ROLES,
    SearchPlatform,
    budget_candidates,
)

from ragkit.answer import answer_with_citations  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402

OUT = ROOT / "reports"
K = 10
TYPES = ("abbrev", "keyword", "multi_condition", "natural", "temporal")


def _macro(rep) -> dict:
    m = rep.macro
    return {"recall": round(m["recall"], 3), "ndcg": round(m["ndcg"], 3),
            "mrr": round(m["mrr"], 3), "precision": round(m["precision"], 3),
            "n": int(m["n_queries"])}


def _by_type(rep) -> dict:
    return {t: round(rep.by_type[t]["recall"], 3) for t in TYPES if t in rep.by_type}


def measure_retrieval(platforms: dict, queries, qrels) -> dict:
    """構成ごとに Recall@10 を測る。役割は member（一般社員）で固定する。"""
    out: dict[str, dict] = {}
    for name, platform in platforms.items():
        retriever = platform.retriever(ROLES["member"])
        rep = evaluate(retriever, queries, qrels, k=K, label=name)
        out[name] = {"macro": _macro(rep), "by_type": _by_type(rep)}
    # 権限フィルタ無し（比較用）。フィルタで取りこぼしていないかを確かめるために測る
    plain = evaluate(platforms[ADOPTED.name].base, queries, qrels, k=K, label="no-filter")
    out["final-v1（権限フィルタ無し・比較用）"] = {"macro": _macro(plain),
                                                   "by_type": _by_type(plain)}
    return out


def measure_permission(platform: SearchPlatform) -> dict:
    """全クエリ × 全役割で混入を数える。**成果物はこの 0 である。**"""
    queries = access.leak_test_queries()  # 業務クエリ120 ＋ 制限文書を狙うプローブ
    member, manager = ROLES["member"], ROLES["manager"]
    rows = {
        "フィルタ無し（member 相当）": access.sweep(
            lambda t, k: platform.base.search(t, k=k), member, queries, label="no-filter"),
        "事後フィルタ（member）": access.sweep(
            access.PostFilterRetriever(platform.base, member).search, member, queries,
            label="post"),
        "事前フィルタ（member）": access.sweep(
            platform.retriever(member).search, member, queries, label="pre"),
        "事前フィルタ（manager）": access.sweep(
            platform.retriever(manager).search, manager, queries, label="pre-manager"),
    }
    return {
        "n_queries": len(queries),
        "rows": {name: {"leaked_hits": r.n_leaked_hits, "leaked_queries": r.n_leaked_queries,
                        "short": r.n_short, "empty": r.n_empty}
                 for name, r in rows.items()},
        "clean": all(r.clean for name, r in rows.items() if "フィルタ無し" not in name),
    }


def measure_answers(platforms: dict, b) -> dict:
    """6判定の分布と、失敗の3層分類を構成ごとに出す。"""
    out: dict[str, dict] = {}
    principal = ROLES["member"]
    for name, platform in platforms.items():
        pipe = platform.pipeline(principal)
        verdicts = {v: 0 for v in ("ok", "abstained", "low_evidence", "unparsable",
                                   "no_citation", "invalid_citation")}
        layers = {layer: 0 for layer in ("ok", "corpus", "retrieval", "generation")}
        failures: list[dict] = []
        for q in b.queries:
            qr = b.qrels_for(q)
            hits = platform.retrieve(principal, q.text)
            res = pipe.run(q.text, q.query_id, hits=hits)
            verdicts[res.verdict] += 1
            ans = answer_with_citations(platform.client, q.text, hits,
                                        max_chars=platform.config.max_chars)
            j = bench.judge(b, ans, hits, qr)
            layer = bench.classify_case(qr, hits, j)
            layers[layer] += 1
            if layer != "ok":
                failures.append({"query_id": q.query_id, "type": q.type, "layer": layer,
                                 "verdict": res.verdict,
                                 "relevant_in_context": sum(
                                     1 for h in hits if qr.get(h.doc_id, 0) >= 1)})
        out[name] = {"verdicts": verdicts, "layers": layers, "failures": failures}
    return out


def measure_operations() -> dict:
    """運用の前提（レイテンシ予算・コスト・検知できる幅）をまとめる。"""
    log = obs.load_log()
    summary = obs.summarize(log)
    p0 = summary["zero_hit_rate"]
    return {
        "budget": {
            "latency_budget_ms": LATENCY_BUDGET_MS,
            "first_stage_ms": FIRST_STAGE_MS,
            "candidates": budget_candidates(),
            "table": {str(b): plan.candidates_for_budget(b) for b in (300, 480, 500, 1000)},
        },
        "cost": cost.summary(),
        "observability": {
            "rows": summary["rows"],
            "zero_hit_rate": round(summary["zero_hit_rate"] * 100, 1),
            "no_click_rate": round(summary["no_click_rate"] * 100, 1),
            "min_detectable": {n: round(drift.min_detectable_rate(n, p0) * 100, 1)
                               for n in (20, 50, 100, 500, 1000)},
            "coin_flip": {"10回中7勝以上": round(ops.tail_prob(10, 7), 6),
                          "20回中15勝以上": round(ops.tail_prob(20, 15), 6)},
        },
    }


def build_report() -> dict:
    ensure_cassette()
    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    platforms = {config.name: SearchPlatform(config) for config in (BASELINE, ADOPTED)}
    chunks = platforms[ADOPTED.name].chunks
    b = bench.Bench()

    visibility: dict[str, int] = {}
    for d in docs:
        visibility[d.visibility] = visibility.get(d.visibility, 0) + 1

    return {
        "config": {"adopted": ADOPTED.summary(), "baseline": BASELINE.summary()},
        "corpus": {"docs": len(docs), "chunks": len(chunks), "queries": len(queries),
                   "answerable": len(b.answerable_queries()),
                   "qrels": sum(len(v) for v in qrels.values()),
                   "visibility": visibility},
        "retrieval": measure_retrieval(platforms, queries, qrels),
        "permission": measure_permission(platforms[ADOPTED.name]),
        "answers": measure_answers(platforms, b),
        "operations": measure_operations(),
    }


def to_markdown(data: dict) -> str:
    ret, ans, ope = data["retrieval"], data["answers"], data["operations"]
    lines = [
        "# 検索基盤の評価レポート（最終プロジェクト）",
        "",
        f"- コーパス: {data['corpus']['docs']} 文書 / チャンク {data['corpus']['chunks']} 個 / "
        f"クエリ {data['corpus']['queries']} 件（回答可能 {data['corpus']['answerable']} 件）",
        "- 公開範囲: " + " / ".join(f"{k} {v}" for k, v in
                                    sorted(data["corpus"]["visibility"].items())),
        "",
        "## 1. 検索の精度（役割は member・k=10）",
        "",
        "| 構成 | Recall@10 | nDCG@10 | MRR | P@10 | abbrev | keyword | multi | natural | temporal |",
        "| :--- | --: | --: | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for name, row in ret.items():
        m, t = row["macro"], row["by_type"]
        lines.append(
            f"| {name} | {m['recall']:.3f} | {m['ndcg']:.3f} | {m['mrr']:.3f} | "
            f"{m['precision']:.3f} | {t.get('abbrev', 0):.3f} | {t.get('keyword', 0):.3f} | "
            f"{t.get('multi_condition', 0):.3f} | {t.get('natural', 0):.3f} | "
            f"{t.get('temporal', 0):.3f} |")

    perm = data["permission"]
    lines += ["", f"## 2. 権限（{perm['n_queries']} クエリ × 役割）", "",
              "| 掛け方 | 混入ヒット | 混入クエリ | k未満 | 0件 |",
              "| :--- | --: | --: | --: | --: |"]
    for name, r in perm["rows"].items():
        lines.append(f"| {name} | {r['leaked_hits']} | {r['leaked_queries']} | "
                     f"{r['short']} | {r['empty']} |")
    lines.append("")
    lines.append(f"- 事前フィルタの混入は **{'0 件' if perm['clean'] else '0 件ではない'}**"
                 "（0 でなければ、他の数字を読む前に止める）")

    lines += ["", "## 3. 回答（6判定と失敗の3層分類）", "",
              "| 構成 | ok | abstained | low_evidence | unparsable | no_citation | "
              "invalid_citation |", "| :--- | --: | --: | --: | --: | --: | --: |"]
    for name, row in ans.items():
        v = row["verdicts"]
        lines.append(f"| {name} | {v['ok']} | {v['abstained']} | {v['low_evidence']} | "
                     f"{v['unparsable']} | {v['no_citation']} | {v['invalid_citation']} |")
    lines += ["", "| 構成 | 成功 | コーパス起因 | 検索起因 | 生成起因 |",
              "| :--- | --: | --: | --: | --: |"]
    for name, row in ans.items():
        y = row["layers"]
        lines.append(f"| {name} | {y['ok']} | {y['corpus']} | {y['retrieval']} | "
                     f"{y['generation']} |")

    budget, c, o = ope["budget"], ope["cost"], ope["observability"]
    lines += ["", "## 4. 運用の前提", "",
              f"- レイテンシ予算 {budget['latency_budget_ms']}ms（1段目 "
              f"{budget['first_stage_ms']}ms）→ リランクの候補上限 "
              f"{budget['candidates']} 件",
              f"- 10万チャンクの全再索引 {c['full_minutes']} 分 / 日次1%の増分 "
              f"{c['daily_seconds']} 秒（{c['ratio']} 倍）",
              f"- 本文はベクトルの {c['text_ratio']} 倍（容量の主役はベクトル）",
              f"- クエリログ {o['rows']} 件 / ゼロヒット率 {o['zero_hit_rate']}% / "
              f"上位無クリック率 {o['no_click_rate']}%",
              "",
              "| 窓の大きさ | 検知できる最小の悪化幅 |", "| --: | --: |"]
    lines += [f"| {n} 件 | {v}% |" for n, v in o["min_detectable"].items()]
    lines += ["",
              "窓が小さいほど、検知できるのは大きな悪化だけになる。"
              "アラートの閾値はこの表より下に置かない（鳴るのはノイズだけになる）。", ""]
    return "\n".join(lines)


def main() -> None:
    data = build_report()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "final_platform.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = to_markdown(data)
    (OUT / "final_platform.md").write_text(markdown, encoding="utf-8")
    print("reports/final_platform.json / reports/final_platform.md を書きました\n")
    print(markdown)
    print("※ 数値は手元の実行結果です。成果物③（評価レポート）に転記してください。")


if __name__ == "__main__":
    main()
