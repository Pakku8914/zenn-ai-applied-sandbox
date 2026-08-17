#!/usr/bin/env python3
"""本番ログから評価セットへケースを還流させる（層化サンプリングと qrels 更新）。

  python src/session17/reflow.py

ここで扱うのは配管である。**判定を付けるのは人**であって、このスクリプトではない。
本書では「アノテータ役」として既存の判定データ（qrels）とサンプル用の判定表を使う。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from masking import mask_text  # noqa: E402
from metrics import load_log, rows_by_type  # noqa: E402
from sessions import load_sample  # noqa: E402

# 評価セットを最初に作ったときに入れた型（作った人が思いつく型に偏りやすい）
EVAL_V1_TYPES: tuple[str, ...] = ("natural", "keyword")

# bm25 / fixed のクエリ型別 Recall@10（2026-08-15 実測 / aarch64 / CPU 2コア /
# メモリ 5.8GB / Python 3.12.13）。**ここでは測り直さない**。
# 「同じ検索器を、どの重みで見るか」だけを変えて数字がどう動くかを見るための表。
RECALL_AT_10: dict[str, float] = {
    "abbrev": 0.182,
    "keyword": 0.967,
    "multi_condition": 0.452,
    "natural": 0.968,
    "temporal": 0.919,
}

# v2 サンプルの候補に人が付けた判定（アノテータ役）
SAMPLE_LABELS: dict[tuple[str, str], int] = {
    ("QL-002", "DOC-0007"): 2,
    ("QL-002", "DOC-0004"): 1,
    ("QL-002", "DOC-0008"): 0,  # 旧規程は不適合
    ("QL-003", "DOC-0271"): 2,
    ("QL-003", "DOC-0288"): 0,
    ("QL-005", "DOC-0288"): 2,
    ("QL-005", "DOC-0271"): 0,
    ("QL-006", "DOC-0288"): 2,
    ("QL-007", "DOC-0190"): 2,
    ("QL-007", "DOC-0008"): 0,
}


class MissingFieldError(RuntimeError):
    """還流に必要なフィールドがログに無い。"""


def initial_eval_ids(queries) -> list[str]:
    """最初の評価セット（自然文とキーワードだけで作られている）。"""
    return sorted(q.query_id for q in queries if q.type in EVAL_V1_TYPES)


def query_stats(log: list[dict]) -> dict[str, dict]:
    """クエリごとの行数と失敗シグナル。"""
    stats: dict[str, dict] = {}
    for row in log:
        s = stats.setdefault(row["query_id"], {
            "type": row["query_type"], "rows": 0, "zero_hits": 0, "no_clicks": 0,
        })
        s["rows"] += 1
        if row["n_results"] == 0:
            s["zero_hits"] += 1
        elif not row.get("clicked_rank"):
            s["no_clicks"] += 1
    return stats


def allocate_proportional(n: int, rows: dict[str, int]) -> dict[str, int]:
    """トラフィック比で配る（最大剰余法）。頻出の型が厚くなる。"""
    total = sum(rows.values())
    exact = {t: n * r / total for t, r in rows.items()}
    quota = {t: int(v) for t, v in exact.items()}
    rest = n - sum(quota.values())
    order = sorted(exact.items(), key=lambda kv: (-(kv[1] - int(kv[1])), kv[0]))
    for qtype, _ in order[:rest]:
        quota[qtype] += 1
    return quota


def allocate_min_then_traffic(n: int, rows: dict[str, int],
                              min_per_type: int = 2) -> dict[str, int]:
    """各型に最低 min_per_type 件を保証し、残りを行数の多い型から1件ずつ配る。"""
    types = sorted(rows, key=lambda t: (-rows[t], t))
    if n < min_per_type * len(types):
        raise ValueError(f"n={n} では {len(types)} 型に {min_per_type} 件ずつ配れません")
    quota = {t: min_per_type for t in types}
    rest = n - min_per_type * len(types)
    i = 0
    while rest > 0:
        quota[types[i % len(types)]] += 1
        rest -= 1
        i += 1
    return quota


def select_head(log: list[dict], n: int) -> list[str]:
    """頻度上位から取る（層化しない場合）。"""
    stats = query_stats(log)
    ordered = sorted(stats.items(), key=lambda kv: (-kv[1]["rows"], kv[0]))
    return [qid for qid, _ in ordered[:n]]


def select_cases(log: list[dict], n: int, *, allocator: str = "min_then_traffic",
                 min_per_type: int = 2) -> list[str]:
    """層化サンプリングでケースを選ぶ。

    型ごとの並び順は「ゼロヒットを含むクエリ → 行数の多い順 → query_id 昇順」で
    固定する（実行するたびに選ばれるケースが変わると、還流が再現できなくなる）。
    """
    rows = rows_by_type(log)
    if allocator == "proportional":
        quota = allocate_proportional(n, rows)
    elif allocator == "min_then_traffic":
        quota = allocate_min_then_traffic(n, rows, min_per_type=min_per_type)
    else:
        raise ValueError(f"未知の allocator です: {allocator}")

    stats = query_stats(log)
    picked: list[str] = []
    for qtype, k in quota.items():
        candidates = sorted(
            (0 if s["zero_hits"] > 0 else 1, -s["rows"], qid)
            for qid, s in stats.items() if s["type"] == qtype
        )
        picked.extend(qid for _, _, qid in candidates[:k])
    return sorted(picked)


def type_counts(query_ids, queries) -> dict[str, int]:
    kinds = {q.query_id: q.type for q in queries}
    counts: dict[str, int] = {}
    for qid in query_ids:
        counts[kinds[qid]] = counts.get(kinds[qid], 0) + 1
    return counts


def weighted_recall(counts: dict[str, float]) -> float:
    """型別の実測 Recall@10 を、渡された重みで平均する（測り直しではない）。"""
    num = 0.0
    den = 0.0
    for qtype, weight in counts.items():
        if qtype not in RECALL_AT_10:
            continue  # unanswerable は Recall を定義できない
        num += weight * RECALL_AT_10[qtype]
        den += weight
    if den == 0:
        raise ValueError("回答可能な型が1つもありません")
    return num / den


def label_tasks(rows: list[dict], *, k: int = 10) -> tuple[list[dict], dict[str, str], list[str]]:
    """ログから「人が判定すべき (クエリ, 文書) の組」を作る。

    採番は本文（マスク後）ごと。評価セットに PII を持ち込まないため、
    **マスク後の本文で** 採番し、そのままケースとして保存する。
    """
    ids: dict[str, str] = {}
    tasks: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if "result_doc_ids" not in row:
            raise MissingFieldError(
                "result_doc_ids がログにありません。何を返したかを残していないと、"
                "当時の候補は復元できません（索引はすでに入れ替わっています）。"
            )
        raw = row.get("query_text", row.get("text", ""))
        text = mask_text(str(raw))
        if text not in ids:
            ids[text] = f"QL-{len(ids) + 1:03d}"
        qid = ids[text]
        for doc_id in row["result_doc_ids"][:k]:
            key = (qid, doc_id)
            if key in seen:
                continue
            seen.add(key)
            tasks.append({"query_id": qid, "text": text, "doc_id": doc_id, "grade": None})
    with_candidates = {t["query_id"] for t in tasks}
    empty = [qid for qid in ids.values() if qid not in with_candidates]
    return tasks, ids, empty


def apply_labels(tasks: list[dict], labels: dict[tuple[str, str], int]) -> list[dict]:
    """人が付けた判定を流し込む。未入力があれば止める（黙って0にしない）。"""
    out = []
    for task in tasks:
        key = (task["query_id"], task["doc_id"])
        if key not in labels:
            raise KeyError(f"判定が未入力です: {key}")
        out.append({**task, "grade": labels[key]})
    return out


def merge_qrels(base: dict[str, dict[str, int]],
                labeled: list[dict]) -> tuple[dict[str, dict[str, int]], list[tuple]]:
    """判定データに還流分をマージする。**冪等**で、既存の判定を黙って上書きしない。"""
    merged = {qid: dict(per) for qid, per in base.items()}
    conflicts: list[tuple] = []
    for row in labeled:
        qid, doc_id, grade = row["query_id"], row["doc_id"], row["grade"]
        if grade is None:
            raise ValueError(f"判定が付いていません: {qid} / {doc_id}")
        current = merged.get(qid, {}).get(doc_id)
        if current is not None and current != grade:
            conflicts.append((qid, doc_id, current, grade))
            continue
        merged.setdefault(qid, {})[doc_id] = grade
    return merged, conflicts


def _fmt(quota: dict[str, int]) -> str:
    return " / ".join(f"{t} {k}" for t, k in quota.items())


def main() -> None:
    from ragkit.corpus import load_qrels, load_queries

    log = load_log()
    queries = load_queries()
    rows = rows_by_type(log)
    base_ids = initial_eval_ids(queries)

    print(f"=== 本番トラフィックの型分布（{len(log)} 行）===")
    print(_fmt(rows))
    print("\n=== いまの評価セット ===")
    print(f"{' + '.join(EVAL_V1_TYPES)} の {len(base_ids)} 件")

    head = select_head(log, 20)
    print("\n=== 頻度上位20件をそのまま拾った場合 ===")
    print(f"選ばれた型 : {_fmt(type_counts(head, queries))}")
    print(f"新しく評価セットに入る : {len(set(head) - set(base_ids))} 件")

    results = {}
    for allocator, label in (("proportional", "比例配分"),
                             ("min_then_traffic", "各型に最低2件")):
        picked = select_cases(log, 20, allocator=allocator)
        added = sorted(set(picked) - set(base_ids))
        after = sorted(set(base_ids) | set(picked))
        results[allocator] = after
        print(f"\n=== 層化サンプリング（{label}・n=20）===")
        print(f"配分 : {_fmt(type_counts(picked, queries))}")
        print(f"新しく評価セットに入る : {len(added)} 件")
        print(f"評価セットは {len(base_ids)} -> {len(after)} 件")

    print("\n=== 型別の実測値をどう重み付けするか（測り直しではない）===")
    all_ids = [q.query_id for q in queries]
    print(f"いまの評価セット（{len(base_ids)} 件） : "
          f"{weighted_recall(type_counts(base_ids, queries)):.3f}")
    for allocator, label in (("proportional", "比例配分で還流したあと"),
                             ("min_then_traffic", "最低2件ずつ還流したあと")):
        after = results[allocator]
        print(f"{label}（{len(after)} 件） : "
              f"{weighted_recall(type_counts(after, queries)):.3f}")
    print(f"型を均等に見る（{len(all_ids)} 件） : "
          f"{weighted_recall(type_counts(all_ids, queries)):.3f}")
    print(f"本番トラフィックで重み付け（{len(log)} 行） : {weighted_recall(rows):.3f}")

    print("\n=== v1 ログから還流できるか ===")
    try:
        label_tasks(log[:5])
    except MissingFieldError as exc:
        print(f"MissingFieldError: {exc}")

    tasks, ids, empty = label_tasks(load_sample())
    print("\n=== ラベル待ちタスク（v2 サンプルから）===")
    print(f"採番したクエリ : {len(ids)} 件")
    print(f"判定すべき (クエリ, 文書) の組 : {len(tasks)} 件")
    print(f"候補が1件も無いクエリ : {', '.join(empty)}")

    base_qrels = load_qrels()
    merged, conflicts = merge_qrels(base_qrels, apply_labels(tasks, SAMPLE_LABELS))
    print("\n=== 判定データ（qrels）の更新 ===")
    print(f"更新前 : {len(base_qrels)} クエリ / {sum(len(v) for v in base_qrels.values())} 判定")
    print(f"更新後 : {len(merged)} クエリ / {sum(len(v) for v in merged.values())} 判定")
    print(f"衝突 : {len(conflicts)} 件")


if __name__ == "__main__":
    main()
