"""問題5：cache_control の置き場所で、キャッシュの効き方と料金がどう変わるかを mockllm で比べる。

    docker compose exec api python -m src.session06.solutions.q5_cache
"""

from __future__ import annotations

import httpx2
from anthropic import Anthropic

from kondate.media import media_path
from kondate.settings import get_settings
from src.session06.app import SYSTEM_PROMPT
from src.session06.documents import pdf_block
from src.session06.pages import select_pages

QUESTIONS = ["肉じゃがは何人分ですか？", "肉じゃがの調理時間は何分ですか？", "肉じゃがは何人分ですか？"]
CACHE = {"type": "ephemeral"}
WRITE_RATE, READ_RATE = 1.25, 0.1  # 基本の入力単価に対する倍率（5分のキャッシュの基本の値。読み出しはモデルにより 0.05 倍もある）


def content(doc: dict, question: str, where: str) -> list[dict]:
    q = {"type": "text", "text": question}
    if where == "document":
        return [{**doc, "cache_control": CACHE}, q]
    return [doc, {**q, "cache_control": CACHE}]


def run(where: str) -> list[tuple[int, int, int]]:
    """3つの質問を順に送り、(input, 作成, 読み出し) を返す。"""
    doc = pdf_block(select_pages(media_path("recipe_book_full.pdf").read_bytes(), [29]))
    client = Anthropic()
    try:
        rows = []
        for question in QUESTIONS:
            u = client.messages.create(model=get_settings().llm_model, max_tokens=256, system=SYSTEM_PROMPT,
                                       messages=[{"role": "user", "content": content(doc, question, where)}]).usage
            rows.append((u.input_tokens, u.cache_creation_input_tokens or 0, u.cache_read_input_tokens or 0))
        return rows
    finally:
        client.close()


def weighted(rows: list[tuple[int, int, int]]) -> float:
    """基本単価の何トークン分にあたるか（キャッシュ作成は割増、読み出しは割引）。"""
    return round(sum(i + WRITE_RATE * w + READ_RATE * r for i, w, r in rows), 1)


def main() -> None:
    with httpx2.Client(base_url=get_settings().mockllm_url, timeout=5.0) as c:
        c.post("/_mock/reset").raise_for_status()
    results = {}
    for where, label in (("document", "文書の後ろに置く"), ("question", "質問の後ろに置く")):
        results[where] = run(where)
        for n, (i, w, r) in enumerate(results[where], 1):
            print(f"{label} {n}回目: input={i} 作成={w} 読み出し={r}")
    plain = sum(i + w + r for i, w, r in results["document"])  # キャッシュが無ければ全部が基本単価
    print(f"換算（基本単価のトークン数）: キャッシュなし {plain} ／ 文書の後ろ {weighted(results['document'])} ／ "
          f"質問の後ろ {weighted(results['question'])}")


if __name__ == "__main__":
    main()
