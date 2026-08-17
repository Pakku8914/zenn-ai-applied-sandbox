#!/usr/bin/env python3
"""セッション11の自己検証：合成カセットで回答生成と引用検証が動くこと。

APIキーは使わない（FixtureClient で再生する）。
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from answer_lab import (  # noqa: E402
    ABSTAINED,
    FALLBACK_TEXT,
    INVALID_CITATION,
    NO_CITATION,
    OK,
    STRATEGIES,
    UNPARSABLE,
    MiddleBlindClient,
    abstain_sweep,
    context_hits,
    demo_hits,
    guarded_answer,
    pack_context,
    reorder,
    review_answer,
)
from ragkit.answer import (  # noqa: E402
    Answer,
    answer_with_citations,
    build_context,
    build_user_prompt,
    parse_answer,
    verify_citations,
)
from ragkit.chunk import chunk_all, chunk_parent_window  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.llm import FixtureClient, StubClient  # noqa: E402
from ragkit.models import Doc, Hit  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


docs, queries, qrels = load_docs(), load_queries(), load_qrels()
chunks = chunk_all(docs, "fixed", size=400, overlap=80)
index = LexicalIndex().build(chunks)

# --- コンテキスト構成 -------------------------------------------------------
hits = index.search("有給休暇の申請期限を教えてください", k=5)
ctx = build_context(hits, max_chars=2000)
included = [h for h in hits if f"[{h.chunk_id}]" in ctx]
# 上限文字数に収まらない分は落とされる。落とされた分は引用できないので、
# 「入っているものだけが引用候補になる」ことを確認する（S11 の後処理の前提）
check("上位の候補がコンテキストに入っている", hits[0].chunk_id == included[0].chunk_id if included else False,
      f"{len(included)}/{len(hits)} 件が収録")
check("収録されたのは先頭から連続した候補", [h.chunk_id for h in hits[: len(included)]]
      == [h.chunk_id for h in included])
check("コンテキストが上限文字数を超えない", len(ctx) <= 2000, f"{len(ctx)}字")

# --- 正常系のカセット -------------------------------------------------------
client = FixtureClient("answers_v1")
answerable_q = [q for q in queries if any(g >= 2 for g in qrels.get(q.query_id, {}).values())]
unanswerable_q = [q for q in queries if q.type == "unanswerable"]

ok_cited = 0
for q in answerable_q[:20]:
    hits = index.search(q.text, k=5)
    ans = answer_with_citations(client, q.text, hits)
    valid, invalid = verify_citations(ans, hits)
    if ans.answerable and valid:
        ok_cited += 1
check("回答可能クエリの多数で引用が有効", ok_cited >= 14, f"{ok_cited}/20 件")

abstained = 0
for q in unanswerable_q:
    hits = index.search(q.text, k=5)
    ans = answer_with_citations(client, q.text, hits)
    if not ans.answerable:
        abstained += 1
check("回答不能クエリで回答不能と判定される", abstained == len(unanswerable_q),
      f"{abstained}/{len(unanswerable_q)} 件")

# --- 異常系のカセット（後処理で弾けること）---------------------------------
flawed = FixtureClient("answers_flawed_v1")
no_citation = fake_citation = 0
for q in queries[:30]:
    hits = index.search(q.text, k=5)
    ans = answer_with_citations(flawed, q.text, hits)
    valid, invalid = verify_citations(ans, hits)
    if not ans.citations:
        no_citation += 1
    elif invalid:
        fake_citation += 1
check("引用なしの応答を検出できる", no_citation > 0, f"{no_citation} 件")
check("存在しない chunk_id の引用を検出できる", fake_citation > 0, f"{fake_citation} 件")

# --- 登録外の入力では例外になる（カセット管理コストの体験）-----------------
try:
    client.complete("別のシステムプロンプト", "登録していない質問")
    check("登録外の入力で KeyError になる", False, "例外が出なかった")
except KeyError:
    check("登録外の入力で KeyError になる", True)

# --- StubClient は決定的 ----------------------------------------------------
stub = StubClient({"有給休暇": '{"answerable": true, "answer": "3営業日前", "citations": ["X#001"]}'})
r1 = stub.complete("s", "有給休暇について")
r2 = stub.complete("s", "有給休暇について")
check("StubClient の応答が決定的", r1.text == r2.text)

# --- コンテキストの予算（合成データなので出力は環境に依存しない）-----------
# 100字ちょうどのブロックを3件。上限300字でも「3件で304字」になる（区切り文字の分）
three = demo_hits([100, 100, 100])
ctx300 = build_context(three, max_chars=300)
check("build_context は区切り文字を予算に数えない", len(ctx300) == 304,
      f"上限300字に対して{len(ctx300)}字（100字×3件＋区切り4字）")
packed300, taken300 = pack_context(three, budget=300)
check("pack_context は区切り文字ごと上限を守る", len(packed300) == 202 and len(taken300) == 2,
      f"{len(taken300)}件・{len(packed300)}字")
_, taken1000 = pack_context(demo_hits([100] * 5), budget=1000)
check("予算を広げれば収録件数が増える", len(taken1000) == 5, f"上限1000字で{len(taken1000)}件")

long_first = demo_hits([360, 50, 50])
_, stop_ids = pack_context(long_first, budget=100)
_, skip_ids = pack_context(long_first, budget=100, stop_on_overflow=False)
check("先頭が予算を超えると打ち切り方式は空になる", stop_ids == [], f"{len(stop_ids)}件")
check("詰め込み方式は下位を拾う", skip_ids == ["DOC-0002#001"], f"{skip_ids}")

# --- 並び順（lost in the middle の戯画）-------------------------------------
five = demo_hits([100] * 5)
target_id = five[2].chunk_id
base_prompt = build_user_prompt("テスト", five, max_chars=2000)
head = base_prompt.index(f"[{five[2].chunk_id}]")
tail = len(base_prompt) - base_prompt.index(f"[{five[4].chunk_id}]")
read_by = {}
for strategy in STRATEGIES:
    blind = MiddleBlindClient([target_id], head=head, tail=tail)
    ordered = reorder(five, strategy)
    read_by[strategy] = answer_with_citations(blind, "テスト", ordered, max_chars=2000)
check("並べ替えても候補の集合は変わらない",
      all({h.chunk_id for h in reorder(five, s)} == {h.chunk_id for h in five} for s in STRATEGIES))
check("並べ替えてもプロンプトの長さは変わらない",
      len(build_user_prompt("テスト", reorder(five, "edges"), max_chars=2000)) == len(base_prompt),
      f"{len(base_prompt)}字")
check("中央に置いた根拠は読み落とされる（score・reversed）",
      not read_by["score"].answerable and not read_by["reversed"].answerable)
check("両端に寄せると読める（edges）",
      read_by["edges"].answerable and read_by["edges"].citations == [target_id],
      f"引用 {read_by['edges'].citations}")

# --- 親子チャンク（子で検索し親を渡す）--------------------------------------
demo_doc = Doc(doc_id="DOC-9001", title="デモ文書", body="あ" * 1000, category="勤怠",
               updated_at="2026-08-15", visibility="all", dept="人事",
               source_type="faq", theme="demo")
pw = chunk_parent_window(demo_doc, child=200, window=600)
pw_hits = [Hit(c.chunk_id, c.doc_id, 1.0, c.text, c.meta) for c in pw[:5]]
check("親テキストは子テキストを含む", all(c.text in c.meta["parent_text"] for c in pw))
n_child = len(context_hits(pw_hits, max_chars=1000))
n_parent = len(context_hits(pw_hits, max_chars=1000, use_parent=True))
check("親を渡すと同じ予算に入る件数が減る", n_parent < n_child, f"子 {n_child} 件 / 親 {n_parent} 件")

# --- 引用の検証は「コンテキストに入った集合」で行う -------------------------
dropped_cite = Answer(True, "回答", [three[2].chunk_id], "")
loose_ok, loose_invalid = verify_citations(dropped_cite, three)
pool = context_hits(three, max_chars=250)
strict_ok, strict_invalid = verify_citations(dropped_cite, pool)
check("全候補で検証すると、入っていない候補への引用を見逃す", loose_ok and not loose_invalid)
check("コンテキストの集合で検証すると無効と分かる",
      (not strict_ok) and strict_invalid == [three[2].chunk_id], f"母集合 {len(pool)} 件")

# --- 後処理（判定）----------------------------------------------------------
hits_by_query = {q.query_id: index.search(q.text, k=5) for q in queries}


def verdicts_for(cl, targets) -> Counter:
    counter: Counter = Counter()
    for q in targets:
        hs = hits_by_query[q.query_id]
        counter[review_answer(answer_with_citations(cl, q.text, hs), hs).verdict] += 1
    return counter


good_ok = verdicts_for(client, answerable_q[:20])
check("正常系カセットは回答可能クエリで ok になる", good_ok[OK] == 20, f"ok {good_ok[OK]}/20 件")
good_abs = verdicts_for(client, unanswerable_q)
check("正しい棄却は欠陥として数えない", good_abs[ABSTAINED] == len(unanswerable_q),
      f"abstained {good_abs[ABSTAINED]}/{len(unanswerable_q)} 件")
bad = verdicts_for(flawed, queries[:30])
check("欠陥応答を種類ごとに分類できる",
      bad[NO_CITATION] == 10 and bad[INVALID_CITATION] == 10 and bad[OK] == 10,
      f"no_citation {bad[NO_CITATION]} / invalid_citation {bad[INVALID_CITATION]} / ok {bad[OK]}")

dropped_unans = 0
for q in unanswerable_q:
    safe, review = guarded_answer(flawed, q.text, hits_by_query[q.query_id])
    if not review.accepted and not safe.answerable and safe.text == FALLBACK_TEXT:
        dropped_unans += 1
check("回答不能クエリへの誤った回答は引用の検証だけで全部落ちる",
      dropped_unans == len(unanswerable_q), f"{dropped_unans}/{len(unanswerable_q)} 件")

check("JSON が取り出せない応答は unparsable になる",
      review_answer(parse_answer("すみません、JSON では出せません"), three).verdict == UNPARSABLE)
check("壊れた JSON も unparsable になる",
      review_answer(parse_answer('{"answerable": true, "citations": [}'), three).verdict == UNPARSABLE)

# --- 回答不能の判定（スコア閾値）--------------------------------------------
demo_sweep = abstain_sweep([(3.0, True), (2.0, True), (1.0, False), (0.5, False)],
                           [0.0, 1.5, 10.0])
check("閾値スイープの両端が理屈どおりになる",
      [(r["false_abstain"], r["false_accept"]) for r in demo_sweep] == [(0, 2), (0, 0), (2, 0)],
      "誤棄却/誤受容 = 0/2 → 0/0 → 2/0")
rows = [(hits_by_query[q.query_id][0].score if hits_by_query[q.query_id] else float("-inf"),
         q.type != "unanswerable") for q in queries]
sweep = abstain_sweep(rows, [0.0, 2.0, 4.0, 6.0, 8.0, 100.0])
check("閾値を上げるほど誤棄却は増え、誤受容は減る",
      all(sweep[i]["false_abstain"] <= sweep[i + 1]["false_abstain"]
          and sweep[i]["false_accept"] >= sweep[i + 1]["false_accept"]
          for i in range(len(sweep) - 1)), "6段階の閾値で単調")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション11の検証はすべて成功しました。")
