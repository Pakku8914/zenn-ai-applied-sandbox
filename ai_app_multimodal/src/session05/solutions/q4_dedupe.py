"""問題4：POST /api/documents に4通り送り、同じ文書を同じ ID で見分けられているかを表にする。

    docker compose exec api python -m src.session05.solutions.q4_dedupe
"""

from __future__ import annotations

import asyncio

import httpx2

from kondate.media import media_path
from src.session05.app import DocumentStore, app

BOOK = media_path("recipe_book.pdf").read_bytes()
RECEIPT = media_path("receipt.pdf").read_bytes()
CASES = [
    ("u001", "recipe_book.pdf", BOOK),
    ("u001", "レシピ本のコピー.pdf", BOOK),
    ("u002", "recipe_book.pdf", BOOK),
    ("u001", "receipt.pdf", RECEIPT),
]


async def run_cases() -> list[tuple[str, str, int, str, int]]:
    """[(利用者, ファイル名, status, 文書の記号, ページ数)]。document_id は実行ごとに変わるので A・B・C に置き換える。"""
    app.state.documents = DocumentStore()  # 前の実行の登録を持ち越さない
    labels: dict[str, str] = {}
    rows = []
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as c:
        for user, name, raw in CASES:
            r = await c.post("/api/documents", files={"file": (name, raw, "application/pdf")}, headers={"x-user-id": user})
            body = r.json()
            label = labels.setdefault(body["document_id"], "ABCDEFG"[len(labels)])
            rows.append((user, name, r.status_code, label, body["pages"]))
    return rows


def main() -> None:
    for i, (user, name, status, label, pages) in enumerate(asyncio.run(run_cases()), 1):
        print(f"{i}. {user} {name} → {status} 文書{label}（{pages}ページ）")


if __name__ == "__main__":
    main()
