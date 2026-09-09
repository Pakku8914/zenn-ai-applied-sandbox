#!/usr/bin/env python3
"""セッション4の検証。

ベクトルストアの器（列・索引・次元）、増分更新の挙動、メタデータフィルタの効き方、
そしてマネージド側（Knowledge Bases）との責任範囲の違いを確認します。
**期待値と一致しなければ非0で終了します。**

判定に使うのは「順位」「集合」「件数」だけです。類似度そのもの（浮動小数）は
環境差で末尾が動くため、値の一致を合否の条件にしていません。

    docker compose exec app python src/session04/verify.py
"""

from __future__ import annotations

import json
import sys
import urllib.request

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session04")

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

import vector_store  # noqa: E402

FAILURES: list[str] = []

QUERY = "有給休暇の繰越上限"

KB_ID = "SAMPLEKB01"

PAID_LEAVE_URI = "s3://sample-shoji-docs/hr/paid-leave.md"

CATEGORY_COUNTS = {"IT": 3, "経費": 3, "人事": 3, "セキュリティ": 3}

# 更新日が 2026-06-01 以降の文書（fixtures/kb_corpus.json より）
FRESH_DOC_IDS = ["ex-001", "ex-003", "hr-002", "hr-003", "sec-002", "sec-003"]
FRESH_URIS = {
    "s3://sample-shoji-docs/expense/travel-expense.md",
    "s3://sample-shoji-docs/expense/equipment-purchase.md",
    "s3://sample-shoji-docs/hr/remote-work.md",
    "s3://sample-shoji-docs/hr/training-support.md",
    "s3://sample-shoji-docs/security/incident-report.md",
    "s3://sample-shoji-docs/security/genai-usage.md",
}
HR_FRESH_URIS = {
    "s3://sample-shoji-docs/hr/remote-work.md",
    "s3://sample-shoji-docs/hr/training-support.md",
}


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
    with urllib.request.urlopen(
        f"{clients.mock_base_url()}/_mock/usage", timeout=10
    ) as res:
        return int(json.loads(res.read())["calls"])


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def retrieve(agent, *, filter_expr: dict | None = None, top_k: int = 3) -> list[dict]:
    config: dict = {"numberOfResults": top_k}
    if filter_expr is not None:
        config["filter"] = filter_expr
    return agent.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": QUERY},
        retrievalConfiguration={"vectorSearchConfiguration": config},
    )["retrievalResults"]


def uris(results: list[dict]) -> set[str]:
    return {r["location"]["s3Location"]["uri"] for r in results}


def main() -> int:
    # 前の演習の障害注入設定と会計が残っていると測定値が変わるため必ずリセットする
    mock_post("/_mock/reset", {})

    runtime = clients.bedrock_runtime()
    agent = clients.agent_runtime()
    chunks = vector_store.load_chunks()

    with vector_store.connect() as conn:
        # 章をまたいで同じテーブルを使うため、空の状態から始める
        with conn.cursor() as cur:
            cur.execute("TRUNCATE doc_chunks")
        conn.commit()

        # --------------------------------------------------------------
        section("1. 器の定義（列・索引・次元）")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'doc_chunks'"
            )
            indexes = {name: define for name, define in cur.fetchall()}
        check(
            "HNSW 索引がある",
            "doc_chunks_embedding_hnsw" in indexes,
            sorted(indexes),
        )
        check(
            "HNSW 索引がコサイン距離用（vector_cosine_ops）",
            "vector_cosine_ops" in indexes.get("doc_chunks_embedding_hnsw", ""),
            indexes.get("doc_chunks_embedding_hnsw"),
        )
        check(
            "メタデータ列に索引がある（category / updated_at）",
            {"doc_chunks_category_idx", "doc_chunks_updated_at_idx"} <= set(indexes),
            sorted(indexes),
        )
        unique = [
            define
            for define in indexes.values()
            if "UNIQUE" in define and "doc_id" in define and "chunk_index" in define
        ]
        check("(doc_id, chunk_index) が一意（冪等な取り込みの前提）", len(unique) == 1, unique)
        check(
            "埋め込みモデル ID がカタログにある",
            vector_store.EMBED_MODEL_ID in catalog.MODELS,
            vector_store.EMBED_MODEL_ID,
        )

        # --------------------------------------------------------------
        section("2. 埋め込みは Titan を invoke_model で呼んで作る")
        first = vector_store.embed_text(runtime, QUERY)
        second = vector_store.embed_text(runtime, QUERY)
        norm = sum(x * x for x in first) ** 0.5
        check("1024 次元で返る", len(first) == vector_store.EMBED_DIMENSIONS, len(first))
        check("L2 正規化されている（ノルムが 1.0）", abs(norm - 1.0) < 1e-3, norm)
        check("同じ入力なら同じベクトル（再現可能）", first == second)

        # --------------------------------------------------------------
        section("3. 全件同期（初回）")
        before = usage_calls()
        stats = vector_store.sync(conn, runtime, chunks)
        embed_calls = usage_calls() - before
        check(
            "12件すべてが新規投入される",
            (stats["inserted"], stats["updated"], stats["skipped"], stats["deleted"])
            == (12, 0, 0, 0),
            stats,
        )
        check("埋め込みの呼び出しは12回（1文書=1チャンク）", embed_calls == 12, embed_calls)
        check("行数が12", vector_store.row_count(conn) == 12, vector_store.row_count(conn))
        counts = vector_store.category_counts(conn, list(CATEGORY_COUNTS))
        check("カテゴリ別が IT / 経費 / 人事 / セキュリティ = 3 / 3 / 3 / 3", counts == CATEGORY_COUNTS, counts)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT min(vector_dims(embedding)), max(vector_dims(embedding)) "
                "FROM doc_chunks"
            )
            dims = cur.fetchone()
        check("格納されたベクトルはすべて1024次元", dims == (1024, 1024), dims)

        # --------------------------------------------------------------
        section("4. 変更検知（2回目の同期）")
        before = usage_calls()
        again = vector_store.sync(conn, runtime, chunks)
        no_embed = usage_calls() - before
        check(
            "12件すべてが「変更なし」",
            (again["inserted"], again["updated"], again["skipped"]) == (0, 0, 12),
            again,
        )
        check("埋め込みを1回も呼び直さない", no_embed == 0, no_embed)

        # --------------------------------------------------------------
        section("5. コサイン距離による最近傍検索")
        results = vector_store.search(conn, runtime, QUERY, top_k=3)
        check("上位3件が返る", len(results) == 3, len(results))
        check(
            "1位は hr-001（年次有給休暇の付与と繰越）",
            results[0]["doc_id"] == "hr-001",
            [r["doc_id"] for r in results],
        )
        check(
            "1位に引用できる出典 URI が付く",
            results[0]["source_uri"] == PAID_LEAVE_URI,
            results[0]["source_uri"],
        )
        similarities = [r["similarity"] for r in results]
        check(
            "類似度が降順に並んでいる（距離順に取れている）",
            similarities == sorted(similarities, reverse=True),
            similarities,
        )

        # --------------------------------------------------------------
        section("6. メタデータフィルタ")
        hr_ids = vector_store.candidates(conn, category="人事")
        check("カテゴリ=人事 の母集団は3件", hr_ids == ["hr-001", "hr-002", "hr-003"], hr_ids)
        hr_hits = vector_store.search(conn, runtime, QUERY, top_k=3, category="人事")
        check(
            "カテゴリ=人事 でも1位は hr-001",
            hr_hits[0]["doc_id"] == "hr-001",
            [r["doc_id"] for r in hr_hits],
        )
        it_hits = vector_store.search(conn, runtime, QUERY, top_k=3, category="IT")
        check(
            "カテゴリ=IT では hr-001 が消える（フィルタは正解も落とす）",
            all(r["category"] == "IT" for r in it_hits)
            and all(r["doc_id"] != "hr-001" for r in it_hits),
            [(r["doc_id"], r["category"]) for r in it_hits],
        )
        fresh_ids = vector_store.candidates(conn, updated_from="2026-06-01")
        check("更新日>=2026-06-01 の母集団は6件", fresh_ids == FRESH_DOC_IDS, fresh_ids)
        fresh_hits = vector_store.search(
            conn, runtime, QUERY, top_k=3, updated_from="2026-06-01"
        )
        check(
            "鮮度フィルタでも hr-001（2026-04-01）は消える",
            all(r["doc_id"] != "hr-001" for r in fresh_hits),
            [r["doc_id"] for r in fresh_hits],
        )
        both_ids = vector_store.candidates(
            conn, category="人事", updated_from="2026-06-01"
        )
        check("カテゴリ AND 更新日 の母集団は2件", both_ids == ["hr-002", "hr-003"], both_ids)

        # --------------------------------------------------------------
        section("7. 増分更新（規程の改定を反映する）")
        revised = [dict(chunk) for chunk in chunks]
        target = next(c for c in revised if c["doc_id"] == "hr-001")
        target["content"] = target["content"].replace(
            "繰越上限は20日です", "繰越上限は25日です"
        )
        target["updated_at"] = "2026-10-01"
        check("改定文を用意できた（20日 → 25日）", "25日" in target["content"], target["content"][:40])
        before = usage_calls()
        revised_stats = vector_store.sync(conn, runtime, revised)
        check(
            "改定した1件だけが更新される",
            (
                revised_stats["inserted"],
                revised_stats["updated"],
                revised_stats["skipped"],
                revised_stats["deleted"],
            )
            == (0, 1, 11, 0),
            revised_stats,
        )
        check("埋め込みの呼び出しも1回だけ", usage_calls() - before == 1, usage_calls() - before)
        check("行数は12のまま（重複行が増えない）", vector_store.row_count(conn) == 12, vector_store.row_count(conn))
        revised_hits = vector_store.search(conn, runtime, QUERY, top_k=3)
        hit = next((r for r in revised_hits if r["doc_id"] == "hr-001"), None)
        check("改定後も hr-001 が上位3件に入る", hit is not None, [r["doc_id"] for r in revised_hits])
        check("返るのは改定後の本文（25日）", hit is not None and "25日" in hit["content"], hit)
        check(
            "更新日も置き換わる（2026-10-01）",
            hit is not None and str(hit["updated_at"]) == "2026-10-01",
            None if hit is None else str(hit["updated_at"]),
        )

        # --------------------------------------------------------------
        section("8. マネージド側（Knowledge Bases）との対照")
        managed = retrieve(agent)
        check(
            "同じ質問で同じ文書が1位になる",
            managed[0]["location"]["s3Location"]["uri"] == PAID_LEAVE_URI,
            managed[0]["metadata"],
        )
        managed_hr = retrieve(
            agent, filter_expr={"equals": {"key": "category", "value": "人事"}}, top_k=10
        )
        check(
            "equals フィルタで人事カテゴリだけに絞れる",
            len(managed_hr) == 3
            and all(r["metadata"]["category"] == "人事" for r in managed_hr),
            [r["metadata"]["category"] for r in managed_hr],
        )
        managed_fresh = retrieve(
            agent,
            filter_expr={
                "greaterThanOrEquals": {"key": "updatedAt", "value": "2026-06-01"}
            },
            top_k=10,
        )
        check(
            "greaterThanOrEquals で鮮度を絞れる（母集団が自前側と一致）",
            uris(managed_fresh) == FRESH_URIS,
            sorted(uris(managed_fresh)),
        )
        managed_both = retrieve(
            agent,
            filter_expr={
                "andAll": [
                    {"equals": {"key": "category", "value": "人事"}},
                    {
                        "greaterThanOrEquals": {
                            "key": "updatedAt",
                            "value": "2026-06-01",
                        }
                    },
                ]
            },
            top_k=10,
        )
        check(
            "andAll で複合条件を書ける（2件）",
            uris(managed_both) == HR_FRESH_URIS,
            sorted(uris(managed_both)),
        )
        check(
            "マネージド側は改定前の本文（20日）を返す＝同期の責任範囲が違う",
            "20日" in managed[0]["content"]["text"],
            managed[0]["content"]["text"][:40],
        )

        # --------------------------------------------------------------
        section("9. 削除の反映（取り込み元から消えた文書）")
        without = [c for c in revised if c["doc_id"] != "hr-003"]
        deleted_stats = vector_store.sync(conn, runtime, without)
        check(
            "消えた1件が索引からも削除される",
            (
                deleted_stats["inserted"],
                deleted_stats["updated"],
                deleted_stats["skipped"],
                deleted_stats["deleted"],
            )
            == (0, 0, 11, 1),
            deleted_stats,
        )
        check("行数が11になる", vector_store.row_count(conn) == 11, vector_store.row_count(conn))
        remaining = vector_store.search(
            conn, runtime, "資格取得支援の受験料補助", top_k=11
        )
        check(
            "削除した文書は検索に出てこない",
            len(remaining) == 11 and all(r["doc_id"] != "hr-003" for r in remaining),
            [r["doc_id"] for r in remaining],
        )

        # --------------------------------------------------------------
        section("10. 元の状態へ戻す（全件同期）")
        restored = vector_store.sync(conn, runtime, chunks)
        check(
            "削除した1件が再投入され、改定した1件が元に戻る",
            (
                restored["inserted"],
                restored["updated"],
                restored["skipped"],
                restored["deleted"],
            )
            == (1, 1, 10, 0),
            restored,
        )
        final = vector_store.search(conn, runtime, QUERY, top_k=1)
        check(
            "行数が12・hr-001 の本文が元に戻る（20日）",
            vector_store.row_count(conn) == 12
            and final[0]["doc_id"] == "hr-001"
            and "20日" in final[0]["content"],
            (vector_store.row_count(conn), final[0]["doc_id"]),
        )

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション4の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
