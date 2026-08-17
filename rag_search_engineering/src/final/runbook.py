#!/usr/bin/env python3
"""最終プロジェクト：運用手順（再索引・切り替え・障害時）を**実行できる形**で持つ。

    docker compose exec app python src/final/runbook.py

runbook は文章だけでは検証できない。ここでは切り替えの手順を、使い捨ての
コレクション（`minato_final_*`）で実際に1周回して、手順そのものを検査する。
**本番のコレクション（`minato_docs_fixed`）には触れない。** 最後に必ず片付ける。

埋め込みモデルは使わない。ベクトルは本文から決定的に作る（S16 の `vector_for`）。
順位は測れないが、「どの点が入れ替わったか・何件残ったか」は正確に測れる。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from reuse import cost, ops  # noqa: E402
from search_platform import LATENCY_BUDGET_MS, budget_candidates  # noqa: E402

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402

# 使い捨てのコレクション（本番名と衝突させない。最後に必ず消す）
BLUE = "minato_final_blue"
GREEN = "minato_final_green"
ALIAS = "minato_final_live"

#: 障害時の判断表。症状ではなく「最初に見る数字」から書く
INCIDENTS: tuple[tuple[str, str, str, str], ...] = (
    ("検索が0件ばかり返す", "ゼロヒット率（24時間）",
     "索引の点数が想定と違う → 切り替え直後ならエイリアスを戻す",
     "alias を旧コレクションへ戻し、点数を数え直す"),
    ("特定の利用者だけ結果が空", "権限フィルタの許可リスト",
     "未知の役割で fail-closed が働いている（正しい挙動）",
     "役割の払い出しを直す。検索層の fail-closed は緩めない"),
    ("見えてはいけない文書が出た", "混入検査（全クエリ × 全役割）",
     "**即時にサービスを止める判断**。原因が分かるまで再開しない",
     "キャッシュを破棄し、フィルタの掛け方（事前 / 事後 / 空辞書）を確認する"),
    ("回答は返るが引用が実在しない", "invalid_citation の件数",
     "後処理が止めているなら影響は無い。増え方だけ監視する",
     "カセット／モデルの変更履歴と突き合わせる"),
    ("p95 レイテンシが予算を超えた", "候補数とリランクの段数",
     "候補数を予算から引き直す（外挿しない）",
     "リランクを一時的に外す。1段目だけでも権限は効いている"),
    ("更新した文書が検索に出ない", "鮮度（更新から索引までの日数）",
     "増分更新が止まっている。全再索引に逃げない",
     "差分の検出（指紋）から順に確認し、孤児チャンクを掃除する"),
)


def client():
    """Qdrant のクライアント（コレクションは作らない）。"""
    return DenseIndex("dummy").client


def sample_chunks(revised: bool = False):
    """使い捨ての小さな文書集合（3文書 × 3チャンク = 9チャンク）。

    revised=True で1文書の末尾だけを書き換える。**1チャンクしか変わらない**ので、
    増分更新が「変わった分だけ」を触っているかを件数で確認できる。
    """
    docs = [
        ops.make_doc("DOC-F001", 900, tail="（改訂）" if revised else ""),
        ops.make_doc("DOC-F002", 900),
        ops.make_doc("DOC-F003", 900),
    ]
    return chunk_all(docs, "fixed", size=400, overlap=80)


def rehearse(cleanup: bool = True) -> dict:
    """切り替え手順を1周回して、各ステップの件数を返す（これが runbook の検証）。"""
    c = client()
    v1, v2 = sample_chunks(), sample_chunks(revised=True)
    ops.recreate(c, BLUE)
    ops.recreate(c, GREEN)

    first = ops.sync(c, BLUE, v1, indexed_at="2026-08-15")        # 初回構築
    again = ops.sync(c, BLUE, v1, indexed_at="2026-08-15")        # 冪等の確認
    ops.switch_alias(c, ALIAS, BLUE)
    live_before = ops.alias_target(c, ALIAS)

    incremental = ops.sync(c, BLUE, v2, indexed_at="2026-08-16")  # 改訂を1件流す
    parallel = ops.sync(c, GREEN, v2, indexed_at="2026-08-16")    # 新方式を並行構築
    ops.switch_alias(c, ALIAS, GREEN)                             # 切り替え（原子的）
    live_after = ops.alias_target(c, ALIAS)
    ops.switch_alias(c, ALIAS, BLUE)                              # 異常検知 → 切り戻し
    live_rolled = ops.alias_target(c, ALIAS)

    pruned = ops.sync(c, GREEN, v2[:-1], indexed_at="2026-08-16")  # 廃止 → 孤児の掃除
    remaining = ops.count(c, GREEN)

    result = {
        "first": {"upserted": first.upserted, "unchanged": first.unchanged},
        "again": {"upserted": again.upserted, "unchanged": again.unchanged},
        "incremental": {"upserted": incremental.upserted, "unchanged": incremental.unchanged},
        "parallel": {"upserted": parallel.upserted},
        "alias": {"before": live_before, "after": live_after, "rolled_back": live_rolled},
        "pruned": {"deleted": pruned.deleted, "orphans": len(pruned.orphans),
                   "remaining": remaining},
        "cleaned": False,
    }
    if cleanup:
        ops.drop_alias(c, ALIAS)
        ops.drop(c, BLUE, GREEN)
        result["cleaned"] = not (c.collection_exists(BLUE) or c.collection_exists(GREEN))
    return result


def main() -> None:
    print("=== 1. 切り替えのリハーサル（使い捨てコレクション）===")
    r = rehearse()
    print(f"  初回構築        : 追加 {r['first']['upserted']} / 変更なし "
          f"{r['first']['unchanged']}")
    print(f"  もう一度流す    : 追加 {r['again']['upserted']} / 変更なし "
          f"{r['again']['unchanged']}  ← 冪等")
    print(f"  改訂を1件流す   : 追加 {r['incremental']['upserted']} / 変更なし "
          f"{r['incremental']['unchanged']}  ← 変わった分だけ")
    print(f"  エイリアス      : {r['alias']['before']} → {r['alias']['after']} → "
          f"{r['alias']['rolled_back']}（切り戻し）")
    print(f"  廃止の掃除      : 孤児 {r['pruned']['orphans']} 件を削除 / 残り "
          f"{r['pruned']['remaining']} 点")
    print(f"  後片付け        : {'完了' if r['cleaned'] else '未完了'}")

    print("\n=== 2. 再索引の判断（S16 のコスト試算）===")
    s = cost.summary()
    print(f"  全再索引（10万チャンク）: {s['full_minutes']} 分")
    print(f"  日次1%の増分            : {s['daily_seconds']} 秒（{s['ratio']} 倍の差）")
    print(f"  本文はベクトルの {s['text_ratio']} 倍（容量の主役はベクトル）")
    print("  → 全再索引は「方式を変えたとき」だけ。日々の更新は増分で回す")

    print("\n=== 3. レイテンシ予算 ===")
    print(f"  予算 {LATENCY_BUDGET_MS}ms → リランクの候補上限 {budget_candidates()} 件")
    print("  予算を超えたらまずリランクを外す。1段目だけでも権限フィルタは効いている")

    print("\n=== 4. 障害時の判断表 ===")
    print(f"  {'症状':<26}{'最初に見る数字':<26}判断")
    for symptom, metric, judgement, _action in INCIDENTS:
        print(f"  {symptom:<26}{metric:<26}{judgement}")

    print("\n手順は書いた時点では正しくない。**回して確かめた時点で正しくなる。**")


if __name__ == "__main__":
    main()
