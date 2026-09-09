#!/usr/bin/env python3
"""セッション5の検証（OpenSearch を使わない部分）。

分け方（チャンキング）・埋め込みの次元・検索方式（SEMANTIC / HYBRID）・クエリの
書き換え・リランク・共通入口の6点を確かめます。**期待値と一致しなければ非0で終了します。**

判定に使うのは「順位」「集合」「件数」「大小関係」だけです。スコアそのもの（浮動小数）の
一致は合否の条件にしていません（末尾が環境差で動くため）。

    docker compose exec app python src/session05/verify.py

OpenSearch を使うハイブリッド検索の検証は `verify_hybrid.py` に分けてあります。
"""

from __future__ import annotations

import json
import math
import sys
import urllib.request

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session04")
sys.path.insert(0, "/workspace/src/session05")

from awskit import clients  # noqa: E402

import chunking  # noqa: E402
import retriever  # noqa: E402
import vector_store  # noqa: E402

FAILURES: list[str] = []

QUERY = "有給休暇 繰越 上限"
QUESTION = "有給休暇の繰越上限は何日ですか？"
COMPOUND = "有給休暇の繰越上限と、在宅勤務の上限日数を教えてください"

# hr-001 の2文目。「丸ごと1つのチャンクに入っていてほしい文」の代表として使う
PROBE = "未消化分は翌年度に限り繰り越せますが、繰越上限は20日です。"

SIZE = 50
OVERLAP = 15

# キーワードが1語でも一致する3文書（fixtures/kb_corpus.json より）
KEYWORD_HITS = {"hr-001", "ex-001", "hr-002"}


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def mock_post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{clients.mock_base_url()}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


def usage_calls() -> int:
    with urllib.request.urlopen(f"{clients.mock_base_url()}/_mock/usage", timeout=10) as res:
        return int(json.loads(res.read())["calls"])


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def reset_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE doc_chunks")
    conn.commit()


def main() -> int:
    # 前の演習の障害注入設定と会計が残っていると測定値が変わるため必ずリセットする
    mock_post("/_mock/reset", {})

    runtime = clients.bedrock_runtime()
    agent = clients.agent_runtime()
    documents = chunking.load_documents()
    doc_id_by_uri = {doc["uri"]: doc["id"] for doc in documents}
    target = next(doc for doc in documents if doc["id"] == "hr-001")
    text = target["text"]

    def ids(hits: list[dict]) -> list[str]:
        return [doc_id_by_uri.get(hit["uri"], hit["uri"]) for hit in hits]

    # ------------------------------------------------------------------
    section("1. 分け方（チャンキング）")
    plain = chunking.fixed_size(text, size=SIZE)
    check("固定長で切って連結すると元の本文に戻る（重なりなし）", "".join(plain) == text)
    check("すべてのチャンクが指定した上限以内", all(len(c) <= SIZE for c in plain), [len(c) for c in plain])
    check(
        "チャンク数が ceil(本文の長さ / size) と一致する",
        len(plain) == math.ceil(len(text) / SIZE),
        (len(plain), len(text)),
    )
    report_plain = chunking.strategy_report(plain, probe=PROBE)
    check(
        "固定長50・重なりなしは3チャンク・最長50・文の途中で切れたのが2件",
        (report_plain["count"], report_plain["longest"], report_plain["cut_mid"]) == (3, 50, 2),
        report_plain,
    )
    check("重なりなしでは文2を丸ごと含むチャンクが無い", not report_plain["has_probe"])

    lapped = chunking.fixed_size(text, size=SIZE, overlap=OVERLAP)
    report_lapped = chunking.strategy_report(lapped, probe=PROBE)
    check("重なり15を入れると文2を丸ごと含むチャンクが現れる", report_lapped["has_probe"])
    check(
        "重なりを入れるとチャンク数が3から4に増える（索引が太る）",
        (report_plain["count"], report_lapped["count"]) == (3, 4),
        (report_plain["count"], report_lapped["count"]),
    )
    check(
        "隣接するチャンクが15文字を共有している",
        all(lapped[i][-OVERLAP:] == lapped[i + 1][:OVERLAP] for i in range(len(lapped) - 1)),
    )

    windows = chunking.sentence_windows(text, max_chars=SIZE)
    check(
        "文単位（上限50）は4チャンク・すべて句点で終わる",
        len(windows) == 4 and all(c.endswith("。") for c in windows),
        [len(c) for c in windows],
    )
    check(
        "文単位（上限140）は1チャンク・全文が収まる",
        chunking.sentence_windows(text, max_chars=140) == [text],
    )
    titled = chunking.with_title_prefix(target["title"], plain)
    check(
        "タイトルを前置すると全チャンクに文書名が入る",
        all(target["title"] in c for c in titled) and len(titled) == len(plain),
    )

    # ------------------------------------------------------------------
    section("2. 埋め込み（次元数の選択）")
    vectors = {d: vector_store.embed_text(runtime, QUERY, dimensions=d) for d in (256, 512, 1024)}
    check(
        "256 / 512 / 1024 のどれでも指定した次元数で返る",
        all(len(v) == d for d, v in vectors.items()),
        {d: len(v) for d, v in vectors.items()},
    )
    norms = {d: sum(x * x for x in v) ** 0.5 for d, v in vectors.items()}
    check(
        "どの次元数でも L2 正規化されている（ノルムが 1.0）",
        all(abs(n - 1.0) < 1e-3 for n in norms.values()),
        norms,
    )
    check(
        "同じ入力・同じ次元なら同じベクトル（再現可能）",
        vector_store.embed_text(runtime, QUERY, dimensions=512) == vectors[512],
    )
    raised = False
    probe_conn = vector_store.connect()
    try:
        with probe_conn.cursor() as cur:
            cur.execute(
                vector_store.UPSERT_SQL,
                ("dim-probe", 0, "s3://sample-shoji-docs/probe.md", "次元テスト",
                 "IT", "2026-09-08", "次元テスト", vectors[512]),
            )
    except Exception:
        raised = True
    finally:
        probe_conn.rollback()
        probe_conn.close()
    check("512次元のベクトルは vector(1024) の列に投入できない", raised)

    # ------------------------------------------------------------------
    plain_rows = chunking.chunk_corpus(documents, lambda t: chunking.fixed_size(t, size=SIZE))
    lapped_rows = chunking.chunk_corpus(
        documents, lambda t: chunking.fixed_size(t, size=SIZE, overlap=OVERLAP)
    )

    with vector_store.connect() as conn:
        section("3. チャンク化して投入する（pgvector）")
        # まず「1文書=1チャンク」の状態で、上位3件の文脈量を測っておく
        reset_table(conn)
        vector_store.sync(conn, runtime, vector_store.load_chunks())
        whole_hits = vector_store.search(conn, runtime, QUERY, top_k=3)
        whole_chars = sum(len(h["content"]) for h in whole_hits)

        reset_table(conn)
        before = usage_calls()
        vector_store.sync(conn, runtime, plain_rows)
        embed_calls = usage_calls() - before
        check("行数が用意したチャンク数と一致する", vector_store.row_count(conn) == len(plain_rows),
              (vector_store.row_count(conn), len(plain_rows)))
        check("1文書=1チャンクより行数が増える", vector_store.row_count(conn) > 12, vector_store.row_count(conn))
        check("埋め込みの呼び出し回数がチャンク数と一致する", embed_calls == len(plain_rows),
              (embed_calls, len(plain_rows)))

        chunk_hits = vector_store.search(conn, runtime, QUERY, top_k=3)
        check("上位3件の本文がすべて50文字以内（渡す文脈が短くなる）",
              all(len(h["content"]) <= SIZE for h in chunk_hits),
              [len(h["content"]) for h in chunk_hits])
        check("上位3件の合計文字数が1文書=1チャンクのときより少ない",
              sum(len(h["content"]) for h in chunk_hits) < whole_chars,
              (sum(len(h["content"]) for h in chunk_hits), whole_chars))
        check("チャンクにしても上位3件すべてに出典 URI が残る",
              all(h["source_uri"].startswith("s3://sample-shoji-docs/") for h in chunk_hits),
              [h["source_uri"] for h in chunk_hits])

        reset_table(conn)
        vector_store.sync(conn, runtime, lapped_rows)
        check("重なりありの行数は重なりなしより多い", len(lapped_rows) > len(plain_rows),
              (len(lapped_rows), len(plain_rows)))
        # 分け方を変えると chunk_index の対応が崩れる。prune は doc_id 単位なので拾えない
        vector_store.sync(conn, runtime, plain_rows)
        check("分け方を変えて UPSERT しても古いチャンクが残る（全件作り直しが必要）",
              vector_store.row_count(conn) > len(plain_rows), vector_store.row_count(conn))
        reset_table(conn)
        vector_store.sync(conn, runtime, plain_rows)
        check("TRUNCATE してから入れ直すと行数が一致する",
              vector_store.row_count(conn) == len(plain_rows), vector_store.row_count(conn))

        # --------------------------------------------------------------
        section("4. 子で当てて親を返す（small-to-big）")
        parent = chunking.fetch_parent(conn, "hr-001")
        check("子チャンクを chunk_index 順に連結すると元の本文に戻る", parent == text, len(parent))
        check("子チャンク単独では文2が丸ごと入っていない", not any(PROBE in c for c in plain))
        check("親を返せば文2が丸ごと含まれる", PROBE in parent)

    # ------------------------------------------------------------------
    section("5. 検索方式（SEMANTIC と HYBRID）")
    semantic = retriever.retrieve(agent, QUERY, search_type="SEMANTIC", top_k=3)
    hybrid = retriever.retrieve(agent, QUERY, search_type="HYBRID", top_k=3)
    check("SEMANTIC の1位は hr-001（年次有給休暇の付与と繰越）", ids(semantic)[0] == "hr-001", ids(semantic))
    check("SEMANTIC の2位は sec-003（生成AI利用ガイドライン）", ids(semantic)[1] == "sec-003", ids(semantic))
    check("HYBRID の1位も hr-001", ids(hybrid)[0] == "hr-001", ids(hybrid))
    check("HYBRID の上位3件はキーワードが一致した3文書（hr-001 / ex-001 / hr-002）",
          set(ids(hybrid)) == KEYWORD_HITS, ids(hybrid))
    check("SEMANTIC と HYBRID で上位3件の並びが変わる", ids(semantic) != ids(hybrid),
          (ids(semantic), ids(hybrid)))
    check("HYBRID のほうが1位と2位のスコア差が大きい",
          (hybrid[0]["score"] - hybrid[1]["score"]) > (semantic[0]["score"] - semantic[1]["score"]),
          (hybrid[0]["score"] - hybrid[1]["score"], semantic[0]["score"] - semantic[1]["score"]))
    filtered = retriever.retrieve(agent, QUERY, search_type="HYBRID", top_k=3, category="人事")
    check("分類フィルタ（人事）を掛けた HYBRID でも1位は hr-001", ids(filtered)[0] == "hr-001", ids(filtered))

    # ------------------------------------------------------------------
    section("6. クエリの書き換え")
    check("自然文が「有給休暇 繰越 上限」に書き換わる",
          retriever.to_keywords(QUESTION) == QUERY, retriever.to_keywords(QUESTION))
    check("複合質問からは4語が抽出される",
          retriever.to_keywords(COMPOUND) == "有給休暇 繰越 上限 在宅勤務",
          retriever.to_keywords(COMPOUND))
    # スコアは「同じ文書どうし」で比べる（順位で比べると丸め由来の同点で揺れるため）
    def semantic_by_uri(query: str) -> dict[str, float]:
        return {
            hit["uri"]: hit["score"]
            for hit in retriever.retrieve(agent, query, search_type="SEMANTIC", top_k=12)
        }

    raw_hybrid = retriever.retrieve(agent, QUESTION, search_type="HYBRID", top_k=3)
    raw_semantic_scores = semantic_by_uri(QUESTION)
    raw_top = raw_hybrid[0]
    check("原文のままではキーワード一致が0（HYBRID のスコアが SEMANTIC の 0.7 倍のまま）",
          abs(raw_top["score"] - 0.7 * raw_semantic_scores[raw_top["uri"]]) < 1e-4,
          (raw_top["score"], raw_semantic_scores[raw_top["uri"]]))
    semantic_scores = semantic_by_uri(QUERY)
    check("書き換えるとキーワード一致が効く（HYBRID のスコアが 0.7 倍より 0.29 以上大きい）",
          hybrid[0]["score"] - 0.7 * semantic_scores[hybrid[0]["uri"]] >= 0.29,
          (hybrid[0]["score"], semantic_scores[hybrid[0]["uri"]]))

    # ------------------------------------------------------------------
    section("7. リランク")
    shuffled = list(reversed(retriever.retrieve(agent, QUERY, search_type="SEMANTIC", top_k=5)))
    reranked = retriever.rerank(agent, QUERY, shuffled, top_n=3)
    scores = [r["rerank_score"] for r in reranked]
    check("numberOfResults で指定した件数だけ返る", len(reranked) == 3, len(reranked))
    check("relevanceScore が降順に並んでいる", scores == sorted(scores, reverse=True), scores)
    check("逆順で渡しても1位が hr-001 に戻る", ids(reranked)[0] == "hr-001",
          (ids(shuffled), ids(reranked)))
    check("リランク後の1位と2位のスコア差が 0.1 より大きい", scores[0] - scores[1] > 0.1, scores)
    check("リランクは渡した順番の添字（index）で結果を返す",
          reranked[0]["source_index"] == len(shuffled) - 1,
          [r["source_index"] for r in reranked])

    # ------------------------------------------------------------------
    section("8. 検索の共通入口（Retriever）")
    by_mode = {mode: retriever.search(agent, QUERY, mode=mode, top_k=3) for mode in retriever.MODES}
    check("3つの mode すべてで上位3件が返る",
          all(len(hits) == 3 for hits in by_mode.values()),
          {mode: len(hits) for mode, hits in by_mode.items()})
    check("SEMANTIC と HYBRID_RERANK で2位が入れ替わる",
          ids(by_mode["SEMANTIC"])[1] != ids(by_mode["HYBRID_RERANK"])[1],
          (ids(by_mode["SEMANTIC"]), ids(by_mode["HYBRID_RERANK"])))
    invalid = False
    try:
        retriever.search(agent, QUERY, mode="KEYWORD")
    except ValueError:
        invalid = True
    check("無効な mode を渡すと ValueError になる", invalid)
    check("ツール定義に検索語が必須引数として入っている",
          retriever.TOOL_SPEC["toolSpec"]["inputSchema"]["json"]["required"] == ["query"])

    # ------------------------------------------------------------------
    section("9. 元の状態（1文書=1チャンク）へ戻す")
    with vector_store.connect() as conn:
        reset_table(conn)
        stats = vector_store.sync(conn, runtime, vector_store.load_chunks())
        check("1文書=1チャンクに戻して行数が12",
              vector_store.row_count(conn) == 12 and stats["inserted"] == 12,
              (vector_store.row_count(conn), stats))

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション5の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
