#!/usr/bin/env python3
"""セッション5の自己検証。

  1. トイ例の転置索引と BM25 スコア（本文の数表と1文字も違わないこと）
  2. k1・b の係数表（純粋な計算なので環境に依存しない）
  3. 文字 bi-gram の分割結果と、略語が救えないという構造的事実
  4. コーパス側の事実（略語は本文に1度も出てこない／適合文書の顔ぶれ）
  5. 自作 BM25 が ragkit.lexical.LexicalIndex と一致し、本文の実測値を再現すること
  6. k1・b の不変条件（k1=0 はバイナリ／b を変えると順位が動く）
  7. 索引側の同義語展開が略語クエリを救い、他の型を壊さないこと
  8. OpenSearch との突き合わせ（起動していないときはスキップ）

埋め込みモデルは使わない。期待値と一致しなければ非0で終了する。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import opensearch_compare as osc  # noqa: E402
from bm25_factors import len_factor, tf_factor  # noqa: E402
from mini_bm25 import TOY, MyLexicalIndex, TinyIndex, format_scores, top1  # noqa: E402
from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate, recall_at_k  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.tokenize_ja import tokenize, tokens_bigram, tokens_morph  # noqa: E402
from synonym_index import SYNONYMS, SynonymLexicalIndex  # noqa: E402

failures: list[str] = []


def check(label: str, got, want, tol: float = 0.0) -> None:
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    print(f"[{'OK' if ok else 'NG'}] {label}: got={got} want={want}")
    if not ok:
        failures.append(label)


def check_true(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'OK' if cond else 'NG'}] {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(label)


# --- 1. トイ例の転置索引と BM25 ---------------------------------------------
print("--- 1. トイ例の転置索引と BM25 ---")
tiny = TinyIndex(TOY)
check("トイ例の文書数", tiny.n_docs, 3)
check("トイ例の語彙数", len(tiny.postings), 8)
check("トイ例の平均文書長", f"{tiny.avgdl:.2f}", "4.67")
check("df(有給休暇)", tiny.df("有給休暇"), 2)
check("df(期限)", tiny.df("期限"), 3)
check("idf(df=1) 総務部", f"{tiny.idf('総務部'):.4f}", "0.9808")
check("idf(df=2) 有給休暇", f"{tiny.idf('有給休暇'):.4f}", "0.4700")
check("idf(df=3) 期限", f"{tiny.idf('期限'):.4f}", "0.1335")
check("索引に無い語の idf は 0", tiny.idf("交通費"), 0.0)

EXPECTED_TOY = {
    (1.2, 0.75): ("d1=1.1008 d2=1.0763 d3=0.0000", "d1"),
    (1.2, 0.00): ("d1=0.9400 d2=1.2925 d3=0.0000", "d2"),
    (0.0, 0.75): ("d1=0.9400 d2=0.9400 d3=0.0000", "d1"),
    (3.0, 0.75): ("d1=1.1763 d2=1.1382 d3=0.0000", "d1"),
}
for (k1, b), (want_line, want_top) in EXPECTED_TOY.items():
    scores = tiny.score(["有給休暇", "申請"], k1=k1, b=b)
    check(f"トイ例のスコア k1={k1} b={b}", format_scores(scores), want_line)
    check(f"トイ例の1位 k1={k1} b={b}", top1(scores), want_top)

# k1=0 は「語が在るか無いか」だけを見る検索になる（IDF の足し算）
zero = tiny.score(["有給休暇", "申請"], k1=0.0, b=0.75)
check_true("k1=0 のスコアは IDF の合計に等しい",
           abs(zero["d1"] - (tiny.idf("有給休暇") + tiny.idf("申請"))) < 1e-12)
check_true("k1=0 では出現回数の違いが消える（d1 と d2 が同点）",
           zero["d1"] == zero["d2"])

# --- 2. k1・b の係数表 -------------------------------------------------------
print("\n--- 2. k1・b の係数表 ---")
TF_ROWS = [
    (1, "1.0000", "1.0000", "1.0000"),
    (2, "1.1304", "1.3750", "1.6000"),
    (3, "1.1818", "1.5714", "2.0000"),
    (5, "1.2264", "1.7742", "2.5000"),
    (10, "1.2621", "1.9643", "3.0769"),
    (20, "1.2808", "2.0755", "3.4783"),
]
for tf, *wants in TF_ROWS:
    got = [f"{tf_factor(tf, k1):.4f}" for k1 in (0.3, 1.2, 3.0)]
    check(f"tf={tf} の係数", got, wants)
check("tf→∞ の上限は k1+1", [f"{k1 + 1:.4f}" for k1 in (0.3, 1.2, 3.0)],
      ["1.3000", "2.2000", "4.0000"])

LEN_ROWS = [
    (0.5, "1.0000", "1.1579", "1.2571", "1.3750"),
    (1.0, "1.0000", "1.0000", "1.0000", "1.0000"),
    (2.0, "1.0000", "0.7857", "0.7097", "0.6471"),
    (4.0, "1.0000", "0.5500", "0.4490", "0.3793"),
]
for ratio, *wants in LEN_ROWS:
    got = [f"{len_factor(ratio, b):.4f}" for b in (0.0, 0.5, 0.75, 1.0)]
    check(f"dl/avgdl={ratio} の係数", got, wants)
check_true("b=0 では文書長がスコアに一切影響しない",
           len({f"{len_factor(r, 0.0):.6f}" for r in (0.5, 1.0, 2.0, 4.0)}) == 1)

# --- 3. 文字 bi-gram の性質 ---------------------------------------------------
print("\n--- 3. 文字 bi-gram ---")
BIGRAM_CASES = [
    ("多要素認証", ["多要", "要素", "素認", "認証"]),
    ("二要素認証", ["二要", "要素", "素認", "認証"]),
    ("MFA", ["mf", "fa"]),
    ("有給休暇", ["有給", "給休", "休暇"]),
    ("年休", ["年休"]),
    ("MN-Book13", ["mn", "nb", "bo", "oo", "ok", "k1", "13"]),
    ("MN-Book15", ["mn", "nb", "bo", "oo", "ok", "k1", "15"]),
]
for text, want in BIGRAM_CASES:
    check(f"tokens_bigram({text})", tokens_bigram(text), want)

SHARED = [("多要素認証", "二要素認証", 3), ("多要素認証", "MFA", 0),
          ("有給休暇", "年休", 0), ("MN-Book13", "MN-Book15", 6),
          ("貸与スマートフォン", "スマホ", 1), ("外部サービス", "SaaS", 0)]
for a, b, want in SHARED:
    check(f"共有 bi-gram 数 {a}∩{b}",
          len(set(tokens_bigram(a)) & set(tokens_bigram(b))), want)

sample = "有給休暇の申請期限を教えてください"
morph_tokens = tokens_morph(sample)
check("bi-gram の語数は文字数-1", len(tokens_bigram(sample)), len(sample) - 1)
check_true("形態素モードは助詞を落とす",
           not any(t in ("の", "を", "は", "が", "に", "で") for t in morph_tokens))
check_true("形態素モードはストップワードを落とす",
           not any(t in ("こと", "もの", "ため", "する", "ある") for t in morph_tokens))
check_true("morph+bigram は2つの連結",
           tokenize(sample, "morph+bigram") == morph_tokens + tokens_bigram(sample))

# --- 4. コーパス側の事実 ------------------------------------------------------
print("\n--- 4. コーパス側の事実 ---")
docs = load_docs()
queries = load_queries()
qrels = load_qrels()
corpus_text = "\n".join(d.full_text for d in docs)
check("文書数", len(docs), 301)

ALIASES = ["年休", "有休", "残業", "育休", "定期代", "パソコン", "スマホ", "MFA",
           "二要素認証", "社員証", "フリーアドレス", "フィッシング", "SaaS", "インシデント"]
for alias in ALIASES:
    check(f"略語「{alias}」は本文に1度も出てこない", corpus_text.count(alias), 0)
check_true("正式名称は本文に出てくる",
           all(corpus_text.count(term) > 0 for term in SYNONYMS),
           f"{len(SYNONYMS)} 語すべて")
check_true("「手続」は多くの文書に出てくる（略語クエリの残りカスの正体）",
           sum(1 for d in docs if "手続" in d.full_text) >= 50)

q067 = next(q for q in queries if q.text == "年休の手続きを知りたい")
check("Q-067 の query_id", q067.query_id, "Q-067")
check("Q-067 の型", q067.type, "abbrev")
check("Q-067 の適合文書",
      sorted(d for d, g in qrels[q067.query_id].items() if g >= 1),
      ["DOC-0001", "DOC-0002", "DOC-0003", "DOC-0004", "DOC-0007"])
check("abbrev クエリの本数", sum(1 for q in queries if q.type == "abbrev"), 20)

# --- 5. 自作 BM25 が既存実装と一致する -----------------------------------------
print("\n--- 5. 自作 BM25 と ragkit の一致 ---")
chunks = chunk_all(docs, "fixed", size=400, overlap=80)
check("チャンク数 fixed(400/80)", len(chunks), 673)

ref = LexicalIndex().build(chunks)
mine = MyLexicalIndex().build(chunks)
check("語彙数の一致", len(mine.postings), len(ref.postings))
check("平均文書長の一致", f"{mine.avgdl:.6f}", f"{ref.avgdl:.6f}")

diff = 0
for q in queries[:30]:
    a = [(h.chunk_id, round(h.score, 9)) for h in ref.search(q.text, k=10)]
    b = [(h.chunk_id, round(h.score, 9)) for h in mine.search(q.text, k=10)]
    diff += 0 if a == b else 1
check("上位10件が食い違ったクエリ数（先頭30件で確認）", diff, 0)

rep = evaluate(mine, queries, qrels, k=10, label="bm25 / fixed")
print(rep.summary())
check("Recall@10", round(rep.macro["recall"], 3), 0.763, 0.02)
check("nDCG@10", round(rep.macro["ndcg"], 3), 0.713, 0.02)
check("MRR", round(rep.macro["mrr"], 3), 0.765, 0.02)
check("P@10", round(rep.macro["precision"], 3), 0.538, 0.02)
check("評価対象クエリ数", int(rep.macro["n_queries"]), 110)
BY_TYPE = {"abbrev": 0.182, "keyword": 0.967, "multi_condition": 0.452,
           "natural": 0.968, "temporal": 0.919}
for t, want in BY_TYPE.items():
    check(f"{t} の Recall@10", round(rep.by_type[t]["recall"], 3), want, 0.03)
check_true("略語クエリだけが突出して弱い",
           rep.by_type["abbrev"]["recall"] < 0.5 * rep.by_type["keyword"]["recall"])

# --- 6. k1・b の不変条件（実コーパス）------------------------------------------
print("\n--- 6. k1・b の不変条件 ---")


def top10(index: LexicalIndex) -> dict[str, list[str]]:
    return {q.query_id: [h.chunk_id for h in index.search(q.text, k=10)] for q in queries}


base_top = top10(ref)
ref.b = 0.0
b0_top = top10(ref)
ref.b, ref.k1 = 0.75, 0.0
k0_top = top10(ref)
ref.k1 = 1.2
back_top = top10(ref)

check_true("b=0 にすると順位が変わるクエリがある",
           sum(1 for qid in base_top if base_top[qid] != b0_top[qid]) > 0,
           f"{sum(1 for qid in base_top if base_top[qid] != b0_top[qid])} 件")
check_true("k1=0 にすると順位が変わるクエリがある",
           sum(1 for qid in base_top if base_top[qid] != k0_top[qid]) > 0,
           f"{sum(1 for qid in base_top if base_top[qid] != k0_top[qid])} 件")
check("k1・b を戻すと元の順位に戻る（索引の作り直しは不要）",
      sum(1 for qid in base_top if base_top[qid] != back_top[qid]), 0)

# k1=0 のスコアは、そのチャンクに在るクエリ語の IDF の合計になる
ref.k1 = 0.0
probe = next(q for q in queries if q.type == "keyword")
hit = ref.search(probe.text, k=1)[0]
want_score = sum(ref._idf(t) for t in tokenize(probe.text, ref.mode)
                 if hit.chunk_id in ref.postings.get(t, {}))
check_true("k1=0 のスコア = 一致した語の IDF の合計", abs(hit.score - want_score) < 1e-9,
           f"{hit.score:.6f} vs {want_score:.6f}")
ref.k1 = 1.2

# --- 7. トークナイザ方式 -------------------------------------------------------
print("\n--- 7. トークナイザ方式 ---")
big = LexicalIndex(mode="bigram").build(chunks)
check_true("bi-gram のほうが語彙が多い", len(big.postings) > len(ref.postings),
           f"{len(big.postings)} > {len(ref.postings)}")
check_true("bi-gram のほうが延べポスティングが多い（索引が太る）",
           sum(len(v) for v in big.postings.values())
           > sum(len(v) for v in ref.postings.values()))
check_true("bi-gram のほうが1チャンクあたりの語数が多い", big.avgdl > ref.avgdl,
           f"{big.avgdl:.1f} > {ref.avgdl:.1f}")
rep_big = evaluate(big, queries, qrels, k=10, label="bm25(bigram) / fixed")
print(rep_big.summary())
check_true("bi-gram でも検索として成立している（Recall@10 >= 0.40）",
           rep_big.macro["recall"] >= 0.40, f"{rep_big.macro['recall']:.3f}")
check_true("bi-gram でも略語クエリは keyword ほどには救えない",
           rep_big.by_type["abbrev"]["recall"] < rep_big.by_type["keyword"]["recall"])

# --- 8. 索引側の同義語展開 -----------------------------------------------------
print("\n--- 8. 索引側の同義語展開 ---")
syn = SynonymLexicalIndex(SYNONYMS).build(chunks)
check_true("展開されたチャンクがある", syn.expanded_chunks > 0, f"{syn.expanded_chunks} 件")
check_true("展開しても本文（Hit.text）は元のまま",
           all(syn.chunks[c.chunk_id].text == c.text for c in chunks))
check_true("語彙が増えている", len(syn.postings) > len(ref.postings))

rep_syn = evaluate(syn, queries, qrels, k=10, label="bm25 + 同義語 / fixed")
print(rep_syn.summary())
before = rep.by_type["abbrev"]["recall"]
after = rep_syn.by_type["abbrev"]["recall"]
check_true("略語クエリの Recall@10 が大きく改善する（+0.10 以上）", after - before >= 0.10,
           f"{before:.3f} -> {after:.3f}")
for t in ("keyword", "natural", "temporal"):
    check_true(f"{t} を壊していない（-0.05 以内）",
               rep_syn.by_type[t]["recall"] >= rep.by_type[t]["recall"] - 0.05,
               f"{rep.by_type[t]['recall']:.3f} -> {rep_syn.by_type[t]['recall']:.3f}")

r067_before = recall_at_k(ref.search(q067.text, k=10), qrels[q067.query_id], 10)
r067_after = recall_at_k(syn.search(q067.text, k=10), qrels[q067.query_id], 10)
check_true("Q-067「年休の手続きを知りたい」が展開で悪化しない", r067_after >= r067_before,
           f"{r067_before:.3f} -> {r067_after:.3f}")
check_true("Q-067 は展開後に適合文書を拾える", r067_after > 0.0,
           f"Recall@10={r067_after:.3f}")

# --- 9. OpenSearch（起動していないときはスキップ）--------------------------------
print("\n--- 9. OpenSearch との突き合わせ ---")
if not osc.is_available():
    print("[SKIP] OpenSearch が起動していません "
          "（docker compose --profile search-engine up -d で起動できます）")
else:
    check("cjk アナライザは文字 bi-gram を作る", osc.analyze("多要素認証", "cjk"),
          ["多要", "要素", "素認", "認証"])
    check("standard アナライザは漢字を1文字ずつに割る", osc.analyze("多要素認証", "standard"),
          ["多", "要", "素", "認", "証"])
    check("cjk は英字を割らない", osc.analyze("MFA", "cjk"), ["mfa"])
    osc.rebuild(chunks)
    count = osc.request("GET", "/" + osc.INDEX + "/_count")["count"]
    check("OpenSearch に登録された件数", count, 673)
    ok = 0
    targets = [q for q in queries if q.type == "keyword"][:3]
    for q in targets:
        got = {doc_id for _, doc_id, _ in osc.search(q.text, k=10)}
        rel = {d for d, g in qrels.get(q.query_id, {}).items() if g >= 1}
        ok += 1 if got & rel else 0
    check("keyword クエリ3件すべてで適合文書を上位10件に拾える", ok, 3)

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション5の検証はすべて成功しました。")
