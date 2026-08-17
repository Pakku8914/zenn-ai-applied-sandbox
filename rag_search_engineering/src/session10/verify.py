#!/usr/bin/env python3
"""セッション10の自己検証：入力側（クエリ）の処理。

  1. クエリ分類が正解の型と一致し、ルールの順序が結果を変えること
  2. 素朴な置換が壊れる2ケースと、正規化してから照合する版が直すこと
  3. クエリ側の同義語展開の効果（略語 0.182 -> 0.873）と、対象外の型が1つも動かないこと
  4. 索引側（S05）とクエリ側の対比（略語 0.765 対 0.873）
  5. HyDE が略語に効き、主題のずれた幻覚が検索を汚すこと
  6. クエリ分解が複数条件クエリだけに効き、検索回数が 110 + 12 になること
  7. 会話の続きの発話を自立化できること（指示語が無ければ LLM を呼ばない）
  8. 型別に打ち手を割り当てた検索器が、各打ち手の結果と完全に一致すること

埋め込みモデルもリランカも使わないので、CPU だけで数分で終わる。
期待値と一致しなければ非0で終了する（人が出力を読んで判断しない）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from query_lab import (  # noqa: E402
    CountingClient,
    HydeRetriever,
    IndexSideSynonymIndex,
    MultiQueryRetriever,
    RewriteRetriever,
    TypeRouter,
    call_plan,
    carry_over,
    classify,
    confusion,
    decompose,
    drop_query_stopwords,
    expand_query,
    expand_query_naive,
    failure_split,
    hyde_document,
    hyde_query,
    make_followup_client,
    make_hyde_client,
    multi_query,
    needs_context,
    resolve_followup,
    suggest_term,
)

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.tokenize_ja import tokenize  # noqa: E402

SWAPPED_ORDER = ("multi_condition", "temporal", "abbrev", "keyword")
GUARD_TYPES = ("keyword", "multi_condition", "natural", "temporal")
failures: list[str] = []


def check(label: str, got, want, tol: float = 0.0) -> None:
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    shown = f"{got:.3f}" if isinstance(want, float) else got
    print(f"[{'OK' if ok else 'NG'}] {label}: got={shown} want={want}")
    if not ok:
        failures.append(label)


def check_true(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'OK' if cond else 'NG'}] {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(label)


docs = load_docs()
queries = load_queries()
qrels = load_qrels()
chunks = chunk_all(docs, "fixed", size=400, overlap=80)
index = LexicalIndex().build(chunks)

# ---------------------------------------------------------------------------
# 1. クエリ分類
# ---------------------------------------------------------------------------
print("--- 1. クエリ分類 ---")

EXPECTED_CONFUSION = {
    "abbrev": {"abbrev": 20},
    "keyword": {"keyword": 30},
    "multi_condition": {"multi_condition": 12},
    "natural": {"natural": 36},
    "temporal": {"temporal": 12},
    "unanswerable": {"natural": 10},
}
table = confusion(queries)
for gold, want in EXPECTED_CONFUSION.items():
    check(f"分類の内訳 gold={gold}", dict(table[gold]), want)

answerable = [q for q in queries if q.type != "unanswerable"]
hit = sum(1 for q in answerable if classify(q.text) == q.type)
check("回答可能な110件の正解率", hit, 110)
check_true("回答不能という型は返さない（検索してから判定する・S11）",
           all(classify(q.text) in ("keyword", "natural", "abbrev",
                                    "multi_condition", "temporal") for q in queries))

changed = [q for q in queries if classify(q.text, SWAPPED_ORDER) != classify(q.text)]
check("順序を入れ替えると化けるクエリ数", len(changed), 6)
check("化けるのは temporal の後半6件",
      [q.query_id for q in changed], ["Q-105", "Q-106", "Q-107", "Q-108", "Q-109", "Q-110"])
check_true("化けた先はすべて multi_condition",
           all(classify(q.text, SWAPPED_ORDER) == "multi_condition" for q in changed))

# ---------------------------------------------------------------------------
# 2. ルールベースの書き換え
# ---------------------------------------------------------------------------
print("\n--- 2. ルールベースの書き換え ---")

check("素朴な置換は部分文字列に当たって壊れる",
      expand_query_naive("パスワードの再設定"), "パスワードワードの再設定")
check("素朴な置換は全角の略語に当たらない",
      expand_query_naive("ＭＦＡの手続きを知りたい"), "ＭＦＡの手続きを知りたい")
check("正規化してから照合すれば全角でも当たる",
      expand_query("ＭＦＡの手続きを知りたい"), "ＭＦＡの手続きを知りたい 多要素認証")
check("正式名称がすでに入っているクエリは触らない",
      expand_query("パスワードの再設定"), "パスワードの再設定")
check("略語クエリには正式名称が足される",
      expand_query("年休の手続きを知りたい"), "年休の手続きを知りたい 有給休暇")

fired = [q for q in queries if expand_query(q.text) != q.text]
check("展開が発火したクエリ数", len(fired), 20)
check("発火したのは略語クエリだけ", sorted({q.type for q in fired}), ["abbrev"])

check("定型句を落とす（教えてください）",
      drop_query_stopwords("有給休暇の申請期限を教えてください"), "有給休暇の申請期限")
check("定型句を落とす（知りたい）",
      drop_query_stopwords("年休の手続きを知りたい"), "年休の手続き")
check_true("定型句を落とすと索引に問い合わせる語も減る",
           len(tokenize(drop_query_stopwords("有給休暇の申請期限を教えてください")))
           < len(tokenize("有給休暇の申請期限を教えてください")))

check("多クエリ生成（元・展開・定型句なしの3本）",
      multi_query("年休の手続きを知りたい"),
      ["年休の手続きを知りたい", "年休の手続きを知りたい 有給休暇", "年休の手続き"])

# ---------------------------------------------------------------------------
# 3. クエリ側の展開の効果と副作用
# ---------------------------------------------------------------------------
print("\n--- 3. クエリ側の展開 ---")

rewriter = RewriteRetriever(index, expand_query)
rep_base = evaluate(index, queries, qrels, k=10, label="bm25 / fixed")
rep_syn = evaluate(rewriter, queries, qrels, k=10, label="bm25 / fixed + クエリ側展開")
print(rep_base.summary())
print(rep_syn.summary())
check("110クエリのうち書き換えが発火した回数", rewriter.rewrites, 20)

check("Recall@10 bm25 / fixed（基準線）", rep_base.macro["recall"], 0.763, 0.02)
check("abbrev の Recall@10（基準線）", rep_base.by_type["abbrev"]["recall"], 0.182, 0.03)
check("multi_condition の Recall@10（基準線）",
      rep_base.by_type["multi_condition"]["recall"], 0.452, 0.03)
check("クエリ側展開後の abbrev の Recall@10", rep_syn.by_type["abbrev"]["recall"], 0.873, 0.03)
check("クエリ側展開後の全体 Recall@10", rep_syn.macro["recall"], 0.889, 0.02)
for qtype in GUARD_TYPES:
    check_true(f"{qtype} の指標は1つも動かない（展開が発火しないため）",
               rep_syn.by_type[qtype] == rep_base.by_type[qtype])

split_base = failure_split(index, queries, qrels, k=10, pool=100)
split_syn = failure_split(rewriter, queries, qrels, k=10, pool=100)
check("abbrev の到達不足（基準線）", split_base["abbrev"]["reach_loss"], 0.592, 0.03)
check("abbrev の順位不足（基準線）", split_base["abbrev"]["rank_loss"], 0.227, 0.03)
check("multi_condition の順位不足（基準線）",
      split_base["multi_condition"]["rank_loss"], 0.495, 0.03)
check("multi_condition の到達不足（基準線）",
      split_base["multi_condition"]["reach_loss"], 0.053, 0.03)
check("ALL の到達不足（基準線）", split_base["ALL"]["reach_loss"], 0.115, 0.02)
for qtype in ("abbrev", "multi_condition", "ALL"):
    row = split_base[qtype]
    check_true(f"{qtype}: Recall@10 ＋ 順位不足 ＋ 到達不足 = 1",
               abs(row["recall"] + row["rank_loss"] + row["reach_loss"] - 1.0) < 1e-9)
check_true("クエリ側の展開で略語の到達不足がほぼ消える",
           split_syn["abbrev"]["reach_loss"] <= 0.02,
           f"{split_base['abbrev']['reach_loss']:.3f} -> {split_syn['abbrev']['reach_loss']:.3f}")

# ---------------------------------------------------------------------------
# 4. 索引側との対比（S05 の再現）
# ---------------------------------------------------------------------------
print("\n--- 4. 索引側とクエリ側の対比 ---")

idx_side = IndexSideSynonymIndex().build(chunks)
rep_idx = evaluate(idx_side, queries, qrels, k=10, label="bm25 + 索引側展開 / fixed")
print(rep_idx.summary())
check("索引側で展開されたチャンク数", idx_side.expanded_chunks, 166)
check("索引側展開の abbrev の Recall@10", rep_idx.by_type["abbrev"]["recall"], 0.765, 0.03)
check("索引側展開の全体 Recall@10", rep_idx.macro["recall"], 0.873, 0.02)
check("索引側展開の nDCG@10", rep_idx.macro["ndcg"], 0.827, 0.03)
check("索引側展開の MRR", rep_idx.macro["mrr"], 0.900, 0.03)
check("索引側展開の P@10", rep_idx.macro["precision"], 0.622, 0.03)
check_true("同じ辞書でも、略語にはクエリ側のほうが効く",
           rep_syn.by_type["abbrev"]["recall"] > rep_idx.by_type["abbrev"]["recall"],
           f"クエリ側 {rep_syn.by_type['abbrev']['recall']:.3f} "
           f"> 索引側 {rep_idx.by_type['abbrev']['recall']:.3f}")
check_true("索引側は keyword を壊していない", rep_idx.by_type["keyword"]["recall"] >= 0.9)

# ---------------------------------------------------------------------------
# 5. HyDE
# ---------------------------------------------------------------------------
print("\n--- 5. HyDE ---")

probe = CountingClient(make_hyde_client())
doc_abbrev = hyde_document("年休の手続きを知りたい", probe)
doc_drift = hyde_document("駐車場の月額利用料を教えてください", probe)
doc_default = hyde_document("遅刻の連絡先を教えてください", probe)
check_true("略語クエリの仮想文書に正式名称が入る（クエリに無い語を持ち込む）",
           "有給休暇" in doc_abbrev and "年休" not in doc_abbrev)
check_true("主題のずれた仮想文書は、聞かれていない語で埋まる",
           "通勤交通費" in doc_drift and "駐車場" not in doc_drift)
check_true("主題が分からないクエリには当たり障りのない一般論が返る",
           "所定の様式" in doc_default and "遅刻" not in doc_default)
check_true("検索に投げる文字列は元のクエリを捨てない",
           hyde_query("年休の手続きを知りたい", doc_abbrev).startswith("年休の手続きを知りたい "))
check("仮想文書を3本作るのに要した LLM 呼び出し", probe.calls, 3)

hyde_client = CountingClient(make_hyde_client())
hyde = HydeRetriever(index, hyde_client)
rep_hyde = evaluate(hyde, queries, qrels, k=10, label="bm25 / fixed + HyDE")
print(rep_hyde.summary())
check("110クエリの評価で必要な LLM 呼び出し", hyde_client.calls, 110)
check_true("HyDE は略語クエリに効く",
           rep_hyde.by_type["abbrev"]["recall"] > rep_base.by_type["abbrev"]["recall"],
           f"{rep_base.by_type['abbrev']['recall']:.3f} -> "
           f"{rep_hyde.by_type['abbrev']['recall']:.3f}")

polluted_before = index.search("駐車場の月額利用料を教えてください", k=10)
polluted_after = hyde.search("駐車場の月額利用料を教えてください", k=10)
n_before = sum(1 for h in polluted_before if "通勤交通費" in h.text)
n_after = sum(1 for h in polluted_after if "通勤交通費" in h.text)
check_true("主題のずれた幻覚が、聞かれていない文書を上位に押し込む",
           n_after > n_before, f"上位10件の混入 {n_before}件 -> {n_after}件")

# ---------------------------------------------------------------------------
# 6. クエリ分解
# ---------------------------------------------------------------------------
print("\n--- 6. クエリ分解 ---")

check("複数条件クエリは2本に割れる",
      decompose("有給休暇と代休の手続きの違いを知りたい"), ["有給休暇の手続き", "代休の手続き"])
check("分けられないクエリは1本のまま",
      decompose("有給休暇の申請期限を教えてください"), ["有給休暇の申請期限を教えてください"])
split_fired = [q for q in queries if len(decompose(q.text)) > 1]
check("分解が発火したクエリ数", len(split_fired), 12)
check("発火したのは複数条件クエリだけ", sorted({q.type for q in split_fired}), ["multi_condition"])

decomposer = MultiQueryRetriever(index, decompose, candidates=20)
rep_dec = evaluate(decomposer, queries, qrels, k=10, label="bm25 / fixed + クエリ分解")
print(rep_dec.summary())
check("110クエリの評価に要した検索回数", decomposer.searches, 122)
check_true("複数条件クエリの Recall@10 が上がる",
           rep_dec.by_type["multi_condition"]["recall"]
           > rep_base.by_type["multi_condition"]["recall"],
           f"{rep_base.by_type['multi_condition']['recall']:.3f} -> "
           f"{rep_dec.by_type['multi_condition']['recall']:.3f}")
for qtype in ("abbrev", "keyword", "natural", "temporal"):
    check_true(f"{qtype} の指標は1つも動かない（分解が発火しないため）",
               rep_dec.by_type[qtype] == rep_base.by_type[qtype])

# ---------------------------------------------------------------------------
# 7. 会話文脈からの自立化
# ---------------------------------------------------------------------------
print("\n--- 7. 自立化 ---")

history = ["有給休暇の申請期限を教えてください"]
followup = "それは何日前まで？"
check_true("指示語のある発話を検出できる", needs_context(followup))
check_true("自立している発話は検出しない", not needs_context("パスワードの再設定は？"))
check("ルール版の自立化（直前の発話を前に付ける）",
      carry_over(history, followup), "有給休暇の申請期限を教えてください それは何日前まで？")

fc = CountingClient(make_followup_client())
check("Stub 版の自立化", resolve_followup(history, followup, fc), "有給休暇の申請期限は何日前までか")
check("指示語が無ければ LLM を呼ばない",
      resolve_followup(history, "パスワードの再設定は？", fc), "パスワードの再設定は？")
check("LLM 呼び出しは指示語のある1件だけ", fc.calls, 1)
check("登録外の主題では書き換えられない（Stub の限界）",
      resolve_followup(["駐車場の月額利用料を教えてください"], followup, fc),
      "（書き換えられませんでした）")

raw_hits = index.search(followup, k=10)
resolved_hits = index.search("有給休暇の申請期限は何日前までか", k=10)
check_true("自立化すると上位10件が別物になる",
           [h.chunk_id for h in raw_hits] != [h.chunk_id for h in resolved_hits])
check_true("自立化後は主題の語を含むチャンクが上位に並ぶ",
           sum(1 for h in resolved_hits if "有給休暇" in h.text) >= 3,
           f"{sum(1 for h in resolved_hits if '有給休暇' in h.text)} / 10 件")

# ---------------------------------------------------------------------------
# 8. スペル訂正の候補出し
# ---------------------------------------------------------------------------
print("\n--- 8. スペル訂正 ---")

TOY_VOCAB = ["有給休暇", "代休", "休日出勤"]
check("打ち間違いに近い語を1つ返す", suggest_term("有給休瑕", TOY_VOCAB), ["有給休暇"])
check("索引にある語には候補を出さない（正しい語を壊さない）",
      suggest_term("有給休暇", TOY_VOCAB), [])
check("似ていない語には候補を出さない", suggest_term("駐輪場", TOY_VOCAB), [])

# ---------------------------------------------------------------------------
# 9. 型別に打ち手を割り当てる
# ---------------------------------------------------------------------------
print("\n--- 9. 型別の打ち手 ---")

check("全クエリを LLM に書き換えさせる案の呼び出し回数", call_plan(queries)["ALL"], 120)
check("略語だけ書き換える案の呼び出し回数", call_plan(queries, {"abbrev"})["ALL"], 20)
check("略語と複数条件だけの案の呼び出し回数",
      call_plan(queries, {"abbrev", "multi_condition"})["ALL"], 32)

router = TypeRouter(index, candidates=20)
rep_router = evaluate(router, queries, qrels, k=10, label="bm25 / fixed + 型別の打ち手")
print(rep_router.summary())
check("ルーターの LLM 呼び出し", router.llm_calls, 0)
check("ルーターの検索回数", router.searches, 122)
check("ルーターが見たクエリの内訳", dict(router.stats),
      {"natural": 36, "keyword": 30, "abbrev": 20, "multi_condition": 12, "temporal": 12})
check_true("abbrev はクエリ側展開と完全に同じ結果",
           rep_router.by_type["abbrev"] == rep_syn.by_type["abbrev"])
check_true("multi_condition はクエリ分解と完全に同じ結果",
           rep_router.by_type["multi_condition"] == rep_dec.by_type["multi_condition"])
for qtype in ("keyword", "natural", "temporal"):
    check_true(f"{qtype} は基準線と完全に同じ結果（何もしていない）",
               rep_router.by_type[qtype] == rep_base.by_type[qtype])

weighted = sum(rep_router.by_type[t]["recall"] * rep_router.by_type[t]["n_queries"]
               for t in rep_router.by_type) / rep_router.macro["n_queries"]
check_true("全体の Recall@10 は型別の値の加重平均と一致する",
           abs(weighted - rep_router.macro["recall"]) < 1e-9,
           f"{weighted:.6f} vs {rep_router.macro['recall']:.6f}")
check_true("型別に打ち手を割り当てると基準線から大きく上がる",
           rep_router.macro["recall"] > rep_base.macro["recall"] + 0.10,
           f"{rep_base.macro['recall']:.3f} -> {rep_router.macro['recall']:.3f}")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション10の検証はすべて成功しました。")
