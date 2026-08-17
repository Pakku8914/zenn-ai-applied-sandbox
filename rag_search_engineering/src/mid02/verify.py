#!/usr/bin/env python3
"""中間プロジェクト02（引用付き回答）の自己検証。

  1. 製品側の凍結条件が、セッション12の測定条件と一致していること
  2. 後処理が6つの判定を正しい順序で出すこと（StubClient・カセット不要）
  3. 合成カセット全体で、後処理が止める件数が再現すること
  4. 失敗が3層に切り分けられること
  5. 上限測定が分類を反証し、訂正が入ること
  6. Recall@10 を代理指標として使ってよいかの点検が再現すること
  7. 優先順位の算術（期待できる上限・レイテンシ予算からの逆算）が合うこと
  8. 提出物のテンプレートとレポートがそろっていること

APIキーは不要。埋め込みモデルもリランカも使わないので CPU だけで完走する。
期待値と一致しなければ非0で終了する（人が出力を読んで判断しない）。
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
from make_cassette import matches_session12  # noqa: E402
from pipeline import (  # noqa: E402
    ABSTAINED,
    FALLBACK_TEXT,
    INVALID_CITATION,
    LOW_EVIDENCE,
    NO_CITATION,
    OK,
    UNPARSABLE,
    AnswerPipeline,
    context_ids,
    json_stub,
)
from priority import build_actions, candidates_for_budget, reach_within_candidates  # noqa: E402
from triage_report import OUT, build_report, to_markdown  # noqa: E402

from ragkit.llm import StubClient  # noqa: E402
from ragkit.models import Hit  # noqa: E402

failures: list[str] = []

REQUIRED_DOCS = {
    "failure_report.md": ["## 1. 測定した条件", "## 2. 層別の内訳",
                          "## 3. 上限測定と分類の訂正", "## 4. 代理指標の点検",
                          "## 5. 各層の読み手と次の判断", "## 6. この測定の限界"],
    "improvement_plan.md": ["## 1. 現在地", "## 2. 打ち手の一覧（コストと効果）",
                            "## 3. 優先順位と理由", "## 4. レイテンシ予算からの逆算",
                            "## 5. やらないと決めたこと", "## 6. 測っていないこと"],
}


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'OK' if cond else 'NG'}] {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(label)


class FixedHits:
    """決まったヒットを返すだけの検索器（後処理だけを試すために使う）。"""

    def __init__(self, hits: list[Hit]) -> None:
        self.hits = list(hits)

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        return self.hits[:k]


bench = Bench()
answerable = bench.answerable_queries()

# ---------------------------------------------------------------------------
# 1. 凍結条件
# ---------------------------------------------------------------------------
print("--- 1. 凍結条件 ---")
check("製品側の条件がセッション12の測定条件と一致する", matches_session12())
check("チャンクは fixed(400/80) の 673 個", len(bench.chunks) == 673, f"{len(bench.chunks)} 個")
check("クエリ 120 件・回答可能 110 件",
      len(bench.queries) == 120 and len(answerable) == 110,
      f"{len(bench.queries)} 件 / 回答可能 {len(answerable)} 件")

# ---------------------------------------------------------------------------
# 2. 後処理の判定（カセットを使わない単体検査）
# ---------------------------------------------------------------------------
print("\n--- 2. 後処理の判定（StubClient）---")
demo = [Hit(f"DOC-{i:04d}#001", f"DOC-{i:04d}", 1.0 / i, "あ" * 200, {"title": "手当の申請"})
        for i in (1, 2, 3)]
fixed = FixedHits(demo)
QUERY = "手当の申請はどうすればよいですか"


def verdict_of(client, **kwargs) -> object:
    return AnswerPipeline(fixed, client, **kwargs).run(QUERY, "Q-TEST")


cases = [
    ("回答不能の自己申告 → abstained", ABSTAINED,
     json_stub({"answerable": False, "answer": "見つかりませんでした。", "citations": []}), {}),
    ("JSON として読めない → unparsable", UNPARSABLE, StubClient(default="はい、承知しました。"), {}),
    ("引用が無い → no_citation", NO_CITATION,
     json_stub({"answerable": True, "answer": "窓口へ申請します。", "citations": []}), {}),
    ("存在しない chunk_id → invalid_citation", INVALID_CITATION,
     json_stub({"answerable": True, "answer": "規程のとおりです。",
                "citations": ["DOC-9999#001"]}), {}),
    ("正しい引用 → ok", OK,
     json_stub({"answerable": True, "answer": "規程のとおりです。",
                "citations": [demo[0].chunk_id]}), {}),
    ("スコアが閾値未満 → low_evidence（引用が正しくても落ちる）", LOW_EVIDENCE,
     json_stub({"answerable": True, "answer": "規程のとおりです。",
                "citations": [demo[0].chunk_id]}), {"min_score": float("inf")}),
]
for label, want, client, kwargs in cases:
    got = verdict_of(client, **kwargs)
    check(label, got.verdict == want, f"got={got.verdict}")

dropped = verdict_of(json_stub({"answerable": True, "answer": "規程のとおりです。",
                                "citations": ["DOC-9999#001"]}))
check("落ちた回答は定型文に差し替わり、引用が残らない",
      dropped.text == FALLBACK_TEXT and dropped.citations == () and not dropped.delivered,
      f"invalid={list(dropped.invalid)}")

check("コンテキスト上限で候補が落ちる（300字なら1件だけ載る）",
      context_ids(demo, max_chars=300) == [demo[0].chunk_id],
      f"{context_ids(demo, max_chars=300)}")
cite_dropped = json_stub({"answerable": True, "answer": "規程のとおりです。",
                          "citations": [demo[2].chunk_id]})
loose = AnswerPipeline(fixed, cite_dropped, max_chars=300).run(QUERY)
strict = AnswerPipeline(fixed, cite_dropped, max_chars=300, strict_citations=True).run(QUERY)
check("母集合を候補全件にすると通ってしまう引用がある", loose.verdict == OK, loose.verdict)
check("母集合をコンテキスト内に絞ると同じ引用が落ちる",
      strict.verdict == INVALID_CITATION, strict.verdict)

# ---------------------------------------------------------------------------
# 3〜6. 合成カセット全体（レポートを1回作って、その中身を検査する）
# ---------------------------------------------------------------------------
data = build_report(bench)
v_ok, v_flawed = data["verdicts"]["answers_v1"], data["verdicts"]["answers_flawed_v1"]

print("\n--- 3. 後処理が止めた件数 ---")
check("正常系カセット: ok=94 / abstained=26",
      v_ok[OK] == 94 and v_ok[ABSTAINED] == 26 and sum(v_ok.values()) == 120, f"{v_ok}")
check("異常系カセット: ok=31 / no_citation=49 / invalid_citation=40",
      (v_flawed[OK], v_flawed[NO_CITATION], v_flawed[INVALID_CITATION]) == (31, 49, 40),
      f"{v_flawed}")
check("異常系カセットで引用が付いた応答は 71 件（うち実在は 31 件）",
      v_flawed[OK] + v_flawed[INVALID_CITATION] == 71)
check("異常系カセットでは 89 件を利用者に出さずに止める",
      sum(v_flawed.values()) - v_flawed[OK] == 89)

print("\n--- 4. 3層の切り分け ---")
layers = data["layers"]
check("層別 成功94 / コーパス起因10 / 検索起因16 / 生成起因0",
      (layers["ok"], layers["corpus"], layers["retrieval"], layers["generation"])
      == (94, 10, 16, 0), f"{layers}")
check("失敗は 26 件（120 − 94）", data["totals"]["failures"] == 26)
check("コーパス起因はすべて回答不能クエリ",
      all(f["type"] == "unanswerable" for f in data["failures"] if f["layer"] == "corpus"))
check("検索起因はすべて略語クエリ（abbrev）",
      all(f["type"] == "abbrev" for f in data["failures"] if f["layer"] == "retrieval"))

print("\n--- 5. 上限測定と分類の訂正 ---")
ub = data["upper_bound"]
rows = {r["layer"]: r for r in ub["by_layer"]}
check("正解チャンクを渡すと成功 100/120", ub["ok"] == 100, f"{ub['ok']}/120")
check("もとの成功94件のうち86件が上限でも成功（8件は失敗する）",
      (rows["ok"]["recovered"], rows["ok"]["stuck"]) == (86, 8), f"{rows['ok']}")
check("コーパス起因は上限測定でも 0/10 しか戻らない",
      (rows["corpus"]["recovered"], rows["corpus"]["stuck"]) == (0, 10), f"{rows['corpus']}")
check("検索起因16件のうち14件が回復し、2件が残る",
      (rows["retrieval"]["recovered"], rows["retrieval"]["stuck"]) == (14, 2),
      f"{rows['retrieval']}")
check("残った2件は Q-070 と Q-077",
      {s["query_id"] for s in ub["stubborn"]} == {"Q-070", "Q-077"},
      f"{[s['query_id'] for s in ub['stubborn']]}")
check("上限測定で失敗したケースは、すべてカセットに仕込んだ欠陥の位置に当たる",
      all(s["flawed_slot"] for s in ub["stubborn"] + ub["regressed"]),
      f"stubborn {len(ub['stubborn'])} 件 / regressed {len(ub['regressed'])} 件")
corrected = data["corrected_layers"]
check("訂正後の層は 検索起因14 / 生成起因2",
      (corrected["retrieval"], corrected["generation"]) == (14, 2), f"{corrected}")
cc = data["cassette_cost"]
check("上限測定のプロンプトは既存カセットに当たらない（30/30 件が KeyError）",
      cc["keyerror_on_answers_v1"] == 30, f"{cc['keyerror_on_answers_v1']}/{cc['probed']}")

print("\n--- 6. 代理指標の点検 ---")
proxy = data["proxy"]
check("対象は回答可能な 110 件", proxy["n"] == 110, f"{proxy['n']} 件")
check("Recall@10 の平均 0.763 / 回答成功率 0.855",
      (proxy["recall_mean"], proxy["success_rate"]) == (0.763, 0.855),
      f"{proxy['recall_mean']} / {proxy['success_rate']}")
check("r(Recall@10 × 回答成功) = +0.871", proxy["r_success"] == 0.871, f"{proxy['r_success']:+.3f}")
check("r(Recall@10 × 忠実性) = +0.908", proxy["r_faithfulness"] == 0.908,
      f"{proxy['r_faithfulness']:+.3f}")
bands = {b["band"]: b for b in proxy["bands"]}
check("帯 [0.0, 0.2) は 15 件・成功 0 件",
      (bands["[0.0, 0.2)"]["n"], bands["[0.0, 0.2)"]["ok"]) == (15, 0), f"{bands['[0.0, 0.2)']}")
check("帯 [0.8, 1.0) は 82 件・成功 82 件",
      (bands["[0.8, 1.0)"]["n"], bands["[0.8, 1.0)"]["ok"]) == (82, 82), f"{bands['[0.8, 1.0)']}")
check("Recall 0.8 以上の失敗 0 件 / 0.2 以下の成功 0 件",
      (proxy["high_recall_failures"], proxy["low_recall_successes"]) == (0, 0))

# ---------------------------------------------------------------------------
# 7. 優先順位の算術
# ---------------------------------------------------------------------------
print("\n--- 7. 優先順位の算術 ---")
actions = build_actions(data)
check("打ち手が6件そろっている", len(actions) == 6, f"{len(actions)} 件")
top = actions[0]
check("第1優先は検索側の打ち手で、上限が +14 件（94/120 → 108/120 = 90.0%）",
      top["decision"] == "第1優先" and "+14 件" in top["ceiling"] and "90.0%" in top["ceiling"],
      top["ceiling"])
pending = [a for a in actions if a["decision"].startswith("保留")]
check("効果を測っていない打ち手は保留になっている",
      len(pending) >= 2 and all("未測定" in a["ceiling"] for a in pending),
      f"{[a['action'] for a in pending]}")
check("レイテンシ予算 500ms から逆算した候補数は 10 件台前半",
      12 <= candidates_for_budget(500) <= 14, f"{candidates_for_budget(500)} 件")
check("予算が最小の測定点に届かなければ候補は 0", candidates_for_budget(300) == 0)
check("測定範囲より広い予算は外挿しない（頭打ちにする）", candidates_for_budget(9999) == 100)

retrieval_ids = [f["query_id"] for f in data["failures"] if f["layer"] == "retrieval"]
reach50 = reach_within_candidates(bench, retrieval_ids, candidates=50)
reach10 = reach_within_candidates(bench, retrieval_ids, candidates=10)
check("リランクの上限（候補50 に完全適合が届く件数）は検索起因の件数以下",
      0 <= reach50 <= len(retrieval_ids), f"{reach50}/{len(retrieval_ids)} 件")
check("候補を広げると届く件数は減らない（並べ替えの上限は候補数で決まる）",
      reach10 <= reach50, f"候補10 {reach10} 件 / 候補50 {reach50} 件")

# ---------------------------------------------------------------------------
# 8. 成果物
# ---------------------------------------------------------------------------
print("\n--- 8. 成果物 ---")
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "mid02_triage.json").write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
markdown = to_markdown(data)
(OUT / "mid02_triage.md").write_text(markdown, encoding="utf-8")
check("レポートが JSON として往復できる",
      json.loads(json.dumps(data, ensure_ascii=False))["layers"] == data["layers"])
check("レポートに上限測定の表がある", "| もとの層 | 件数 | 上限で成功 | 上限でも失敗 |" in markdown)
check("レポートに測定の限界の節がある", "## 5. この測定の限界" in markdown)

for filename, markers in REQUIRED_DOCS.items():
    path = HERE / "docs" / filename
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    check(f"{filename} が存在する", bool(text))
    for marker in markers:
        check(f"{filename} に「{marker}」がある", marker in text)

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\n中間プロジェクト02の検証はすべて成功しました。")
