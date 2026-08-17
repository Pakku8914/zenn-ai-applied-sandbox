#!/usr/bin/env python3
"""中間プロジェクト02：打ち手をコストと効果の表にして、優先順位を算術で決める。

    docker compose exec app python src/mid02/priority.py

「効きそう」で並べない。**上限測定で戻ると分かった件数**と、**まだ測っていないという
事実**を、同じ表の同じ列に置く。測っていない欄を空のまま残せることが、この表の価値である。

生成物: reports/mid02_priority.md（成果物④に貼る）
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

from eval_lab import Bench  # noqa: E402
from triage_report import build_report  # noqa: E402

OUT = ROOT / "reports"
REPORT_JSON = OUT / "mid02_triage.json"

# セッション9の実測（2026-08-15 / aarch64 / CPU 2コア / メモリ 5.8GB）
RERANK_LATENCY = ((10, 405), (20, 709), (50, 1571), (100, 2710))


def candidates_for_budget(budget_ms: float, table=RERANK_LATENCY) -> int:
    """レイテンシ予算から候補数を逆算する（実測値を線形補間するだけ）。

    予算が最小の測定点にも届かないなら 0（リランクを入れる余地が無い）。
    測定範囲より広い予算は、測った一番大きい候補数で頭打ちにする（外挿しない）。
    """
    if budget_ms < table[0][1]:
        return 0
    largest = table[0][0]
    for (n0, t0), (n1, t1) in zip(table, table[1:]):
        if t0 <= budget_ms <= t1:
            return int(n0 + (budget_ms - t0) * (n1 - n0) / (t1 - t0))
        if budget_ms > t1:
            largest = n1
    return largest


def reach_within_candidates(bench: Bench, query_ids: list[str], candidates: int = 50) -> int:
    """検索起因の失敗のうち、候補 n 件の中に完全適合が入っているものを数える。

    リランクは並べ替えであって、候補の外にあるものは拾えない。
    **この件数がリランクの上限**になる（本書の測定記録には無い値なので手元で記録する）。
    """
    by_id = {q.query_id: q for q in bench.queries}
    reached = 0
    for qid in query_ids:
        q = by_id[qid]
        qr = bench.qrels_for(q)
        hits = bench.index.search(q.text, k=candidates)
        if any(qr.get(h.doc_id, 0) >= 2 for h in hits):
            reached += 1
    return reached


def load_report(bench: Bench | None = None) -> dict:
    """三層分類レポートを読む。無ければその場で作る（数字を手で写さないため）。"""
    if REPORT_JSON.exists():
        return json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    return build_report(bench or Bench())


def build_actions(data: dict) -> list[dict]:
    """レポートの数字から打ち手の表を組み立てる。定数を手で書かない。"""
    layers = data["layers"]
    rows = {r["layer"]: r for r in data["upper_bound"]["by_layer"]}
    recovered = rows["retrieval"]["recovered"]
    stubborn = len(data["upper_bound"]["stubborn"])
    flawed = data["verdicts"]["answers_flawed_v1"]
    total = data["totals"]["queries"]
    now = data["totals"]["ok"]

    return [
        {
            "action": "クエリ側の同義語展開（略語辞書）",
            "layer": "検索",
            "target": f"検索起因 {layers['retrieval']} 件（すべて略語クエリ）",
            "ceiling": f"+{recovered} 件（{now}/{total} → {now + recovered}/{total} = "
                       f"{(now + recovered) / total:.1%}）",
            "basis": "略語の失敗は 0.592 が到達不足。クエリ側の展開で abbrev の "
                     "Recall@10 は 0.182 → 0.873・到達不足は 0.000 になる（S05・Review01 の実測）",
            "cost": "辞書の作成と保守（人手）／検索時のコストは書き換えのみ／"
                    "**カセットの作り直しが1本**",
            "verify": "展開ありの索引で3層分類をやり直し、検索起因が減ることを見る",
            "decision": "第1優先",
        },
        {
            "action": "引用の実在検証（後処理）",
            "layer": "生成",
            "target": f"異常系カセットの invalid_citation {flawed['invalid_citation']} 件",
            "ceiling": f"誤った引用付き回答を {flawed['invalid_citation']} 件止める"
                       "（成功件数は増えない）",
            "basis": "引用が無効なケースの忠実性は 0.000 になる。"
                     "実在検証を先に通さないと忠実性の数字が意味を持たない（S12 の実測）",
            "cost": "文字列の突き合わせのみ。追加のモデル呼び出しは無い",
            "verify": "異常系カセットを流して ok の件数が引用実在の件数と一致すること",
            "decision": "採用済み（常時有効）",
        },
        {
            "action": "回答不能の判定（abstention）",
            "layer": "生成 / コーパス",
            "target": f"コーパス起因 {layers['corpus']} 件（答えが存在しない質問）",
            "ceiling": f"誤答を {layers['corpus']} 件止める（成功件数は増えない）",
            "basis": "異常系カセットでは 10 件すべてが「黙るべきなのに答えた」になる",
            "cost": "プロンプトの制約1行＋後処理の分岐。運用では誤棄却の監視が要る",
            "verify": "回答不能クエリ 10 件がすべて abstained になること",
            "decision": "採用済み（常時有効）",
        },
        {
            "action": "リランク（クロスエンコーダ・候補50）",
            "layer": "検索（順位）",
            "target": f"検索起因 {layers['retrieval']} 件のうち候補内に届いているもの",
            "ceiling": "**未測定**（候補50 に完全適合が入っている件数が上限。"
                       "手元で測って記入する）",
            "basis": "略語クエリの失敗は到達不足が主因なので、並べ替えでは原理的に救えない分がある",
            "cost": "候補50 で 1,571ms（S09 実測）。予算 500ms なら候補は 10 件台前半／"
                    "モデルのロード 15.5 秒／**カセットの作り直しが1本**",
            "verify": "検索起因の失敗だけに候補を絞ってリランクし、層が変わるかを見る",
            "decision": "保留（効果を測るまで順位を上げない）",
        },
        {
            "action": "コーパスへの追記",
            "layer": "コーパス",
            "target": f"回答不能クエリ {layers['corpus']} 件",
            "ceiling": f"+{layers['corpus']} 件（ただし「答えが無い質問に答えを作る」仕事）",
            "basis": "上限測定で 0/10 件しか回復しない。検索も生成も直しようがない",
            "cost": "文書の作成・レビュー・更新の運用（検索チームの外の仕事）",
            "verify": "追記後に判定データを更新し、回答不能クエリが減ることを確認する",
            "decision": "別チームへ回す",
        },
        {
            "action": "忠実性のしきい値で足切り",
            "layer": "生成",
            "target": f"生成起因 {stubborn} 件（上限測定で訂正した分）",
            "ceiling": "未測定（誤棄却がどれだけ増えるかを測っていない）",
            "basis": "引用が有効なケースの忠実性の平均は 0.018。"
                     "しきい値を素朴に置くと正しい回答まで落ちる",
            "cost": "実装は軽いが、しきい値の維持コストが継続的にかかる",
            "verify": "しきい値を振って誤棄却と誤受容の件数を並べる（S11 の掃引）",
            "decision": "保留",
        },
    ]


def to_markdown(data: dict, actions: list[dict], budget_ms: int = 500) -> str:
    t = data["totals"]
    lines = [
        "# 改善の優先順位（中間プロジェクト02）",
        "",
        f"- 現在地: {t['ok']}/{t['queries']} 件成功（{t['success_rate']:.1%}）／"
        f"失敗 {t['failures']} 件",
        "- 訂正後の層: " + " / ".join(f"{k} {v}" for k, v in data["corrected_layers"].items()),
        "",
        "## 打ち手の一覧（コストと効果）",
        "",
        "| # | 打ち手 | 狙う層 | 対象 | 期待できる上限 | 根拠 | コスト | 検証方法 | 判定 |",
        "| :-- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for i, a in enumerate(actions, start=1):
        lines.append(f"| {i} | {a['action']} | {a['layer']} | {a['target']} | {a['ceiling']} | "
                     f"{a['basis']} | {a['cost']} | {a['verify']} | {a['decision']} |")
    lines += [
        "",
        "## レイテンシ予算からの逆算（S09 の実測を補間）",
        "",
        "| 予算 | 入れられる候補数 |",
        "| ---: | ---: |",
    ]
    lines += [f"| {b} ms | {candidates_for_budget(b)} 件 |" for b in (300, budget_ms, 1000, 2000)]
    lines += ["", "## 測っていないこと（宿題）", "",
              "- リランクが救える件数（候補の中に完全適合が届いているか）",
              "- 同義語展開を入れた後の3層分類（カセットの作り直しが要る）",
              "- 忠実性のしきい値と誤棄却のトレードオフ", ""]
    return "\n".join(lines)


def main() -> None:
    bench = Bench()
    data = load_report(bench)
    actions = build_actions(data)
    md = to_markdown(data, actions)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "mid02_priority.md").write_text(md, encoding="utf-8")
    print("reports/mid02_priority.md を書きました")
    print()
    print(md)

    failures = [f["query_id"] for f in data["failures"] if f["layer"] == "retrieval"]
    print("--- リランクの上限を測る（候補50 の中に完全適合が入っているか）---")
    reached = reach_within_candidates(bench, failures, candidates=50)
    print(f"検索起因の失敗 {len(failures)} 件のうち、候補50 に完全適合が届いている: {reached} 件")
    print("この件数がリランクの上限。残りは到達不足なので、並べ替えでは動かない。")
    print("※ 本書の測定記録に無い値です。あなたの実行結果を成果物④に書き込んでください。")


if __name__ == "__main__":
    main()
