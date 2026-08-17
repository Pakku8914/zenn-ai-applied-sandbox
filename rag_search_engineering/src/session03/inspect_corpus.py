#!/usr/bin/env python3
"""取り込みの点検。1件ずつ目で見る代わりに、分布と異常の件数で全体を見る。

  python src/session03/inspect_corpus.py raw     抽出直後を点検する
  python src/session03/inspect_corpus.py clean   取り込み後（out/docs.jsonl）を点検する

「点検してから前処理を足す」「前処理を足したらもう一度点検する」の往復が、
取り込みの改善ループそのものになる。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clean import (  # noqa: E402
    content_hash, has_boilerplate, has_broken_chars, has_excess_blank_lines,
    has_fullwidth_or_enclosed, is_effectively_empty, is_order_suspect, jaccard, shingles,
)
from dirty_corpus import load_raw  # noqa: E402
from ingest import MIN_CHARS, OUT_DIR, SIMILARITY_THRESHOLD  # noqa: E402

BUCKETS = [(0, 9), (10, 99), (100, 1999), (2000, None)]


def from_raw(raws: list[dict]) -> list[dict]:
    return [
        dict(
            id=r["path"],
            text=r["text"],
            order_suspect=is_order_suspect(r["text"], r.get("alt")),
            needs_review=False,
        )
        for r in raws
    ]


def from_records(records: list[dict]) -> list[dict]:
    return [
        dict(
            id=r["doc_id"],
            text=r["body"],
            order_suspect="order_suspect" in r.get("review_reasons", []),
            needs_review=bool(r.get("needs_review")),
        )
        for r in records
    ]


def count_exact_dup(items: list[dict]) -> tuple[int, list[dict]]:
    """完全重複の余剰件数と、重複を除いた代表の一覧を返す。"""
    seen: dict[str, dict] = {}
    surplus = 0
    for item in items:
        key = content_hash(item["text"])
        if key in seen:
            surplus += 1
        else:
            seen[key] = item
    return surplus, list(seen.values())


def count_near_dup(items: list[dict], threshold: float) -> int:
    """近重複の余剰件数（完全重複を除いたあとに数える）。"""
    clusters: list[set[str]] = []
    surplus = 0
    for item in sorted(items, key=lambda i: i["id"]):
        sh = shingles(item["text"])
        if any(jaccard(sh, c) >= threshold for c in clusters):
            surplus += 1
        else:
            clusters.append(sh)
    return surplus


def bucket_of(length: int) -> str:
    for low, high in BUCKETS:
        if high is None or length <= high:
            return f"{low}-" if high is None else f"{low}-{high}"
    return "?"


def inspect(items: list[dict]) -> dict:
    exact_surplus, uniques = count_exact_dup(items)
    stats = {
        "文書数": len(items),
        f"実質空（{MIN_CHARS}字未満）": sum(1 for i in items if is_effectively_empty(i["text"], MIN_CHARS)),
        "完全重複（余剰）": exact_surplus,
        f"近重複（余剰・Jaccard>={SIMILARITY_THRESHOLD:.2f}）": count_near_dup(uniques, SIMILARITY_THRESHOLD),
        "ヘッダー・フッターの残存": sum(1 for i in items if has_boilerplate(i["text"])),
        "全角英数・囲み文字を含む": sum(1 for i in items if has_fullwidth_or_enclosed(i["text"])),
        "3行以上の連続改行": sum(1 for i in items if has_excess_blank_lines(i["text"])),
        "置換文字・制御文字": sum(1 for i in items if has_broken_chars(i["text"])),
        "抽出結果の不一致（順序崩れの疑い）": sum(1 for i in items if i["order_suspect"]),
        "要レビュー": sum(1 for i in items if i["needs_review"]),
    }
    buckets = {f"{low}-" if high is None else f"{low}-{high}": 0 for low, high in BUCKETS}
    for item in items:
        buckets[bucket_of(len(item["text"]))] += 1
    return {"stats": stats, "buckets": buckets}


def print_report(label: str, report: dict) -> None:
    print(f"=== 取り込み点検: {label} ===")
    for key, value in report["stats"].items():
        print(f"{key}: {value}")
    print("--- 文字数の分布 ---")
    for key, value in report["buckets"].items():
        bar = f" {'#' * value}" if value else ""
        print(f"{key}: {value}{bar}")


def load_clean_records() -> list[dict]:
    path = OUT_DIR / "docs.jsonl"
    if not path.exists():
        raise SystemExit(
            f"{path} がありません。先に `python src/session03/ingest.py` を実行してください。"
        )
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def main(argv: list[str]) -> int:
    target = argv[0] if argv else "raw"
    if target == "raw":
        print_report("抽出直後（raw）", inspect(from_raw(load_raw())))
    elif target == "clean":
        print_report("取り込み後（clean）", inspect(from_records(load_clean_records())))
    else:
        raise SystemExit("使い方: python src/session03/inspect_corpus.py [raw|clean]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
