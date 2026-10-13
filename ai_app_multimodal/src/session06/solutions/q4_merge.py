"""問題4：分割の範囲を作り、範囲ごとの読み取り結果を統合する（重複・食い違い・取りこぼし）。

    docker compose exec api python -m src.session06.solutions.q4_merge
"""

from __future__ import annotations

# 7ページの本を3ページずつ1ページ重ねて読んだ結果（page は範囲の中での番号）
CHUNKS = [
    (1, [{"id": "R001", "page": 1, "minutes": 15}, {"id": "R002", "page": 2, "minutes": 20}, {"id": "R003", "page": 3, "minutes": 25}]),
    (3, [{"id": "R003", "page": 1, "minutes": 25}, {"id": "R004", "page": 2, "minutes": 30}, {"id": "R005", "page": 3, "minutes": 10}]),
    (5, [{"id": "R005", "page": 1, "minutes": 12}, {"id": "R007", "page": 3, "minutes": 40}]),
]


def chunk_ranges(pages: int, size: int, overlap: int) -> list[tuple[int, int]]:
    if pages < 1 or not 0 <= overlap < size:
        raise ValueError("pages は 1 以上、overlap は 0 以上 size 未満にしてください")
    ranges, start = [], 1
    while True:
        end = min(start + size - 1, pages)
        ranges.append((start, end))
        if end == pages:
            return ranges
        start = end - overlap + 1  # 次の範囲は、重ねるページの分だけ手前から始める


def merge(chunks: list[tuple[int, list[dict]]], pages: int) -> dict:
    by_id: dict[str, dict] = {}
    duplicates, conflicts = 0, set()
    for start, records in chunks:  # 範囲の順に見る（先に読んだ方を残すため、順番が結果を決める）
        for r in records:
            rec = {**r, "page": start + r["page"] - 1}  # 元の本のページ番号に戻す
            first = by_id.setdefault(rec["id"], rec)
            if first is rec:
                continue
            if first == rec:
                duplicates += 1
            else:
                conflicts.add(rec["id"])
    recipes = sorted(by_id.values(), key=lambda r: (r["page"], r["id"]))
    covered = {r["page"] for r in recipes}
    return {
        "ids": [r["id"] for r in recipes],
        "duplicates_removed": duplicates,
        "conflicts": sorted(conflicts),
        "missing_pages": [p for p in range(1, pages + 1) if p not in covered],
    }


def main() -> None:
    for args in ((120, 10, 1), (120, 10, 0)):
        ranges = chunk_ranges(*args)
        print(f"{args}: {len(ranges)} 個・送るページの合計 {sum(e - s + 1 for s, e in ranges)}")
    print(f"(7, 3, 1): {chunk_ranges(7, 3, 1)}")
    m = merge(CHUNKS, 7)
    print(f"統合: {len(m['ids'])} 件 {m['ids']}・重複除去 {m['duplicates_removed']}・"
          f"食い違い {m['conflicts']}・取りこぼし {m['missing_pages']}")


if __name__ == "__main__":
    main()
