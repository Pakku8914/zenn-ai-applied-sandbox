"""同じ文書に2回質問して、2回目にキャッシュが効くか（cache_read_input_tokens）を mockllm で確かめる。

    docker compose exec api python -m src.session06.cache_demo
"""

from __future__ import annotations

import httpx2
from anthropic import Anthropic

from kondate.media import media_path
from kondate.settings import get_settings
from src.session06.app import SYSTEM_PROMPT
from src.session06.documents import cached, extract_pages, pdf_block, text_block
from src.session06.pages import select_pages

QUESTION = "肉じゃがは何人分ですか？"


def ask_once(client: Anthropic, block: dict) -> tuple[int, int, int]:
    msg = client.messages.create(
        model=get_settings().llm_model,
        max_tokens=256,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [block, {"type": "text", "text": QUESTION}]}],
    )
    u = msg.usage
    return u.input_tokens, u.cache_creation_input_tokens or 0, u.cache_read_input_tokens or 0


def run() -> dict[str, list[tuple[int, int, int]]]:
    with httpx2.Client(base_url=get_settings().mockllm_url, timeout=5.0) as c:
        c.post("/_mock/reset").raise_for_status()  # 統計とキャッシュを消す
    page29 = select_pages(media_path("recipe_book_full.pdf").read_bytes(), [29])  # 1回だけ作って使い回す
    pdf = cached(pdf_block(page29))                         # 接頭辞＝4＋system 69＋3＋1600＝1676
    text = cached(text_block(extract_pages(page29)[0]))    # 抜き出した文字だけ：接頭辞が 1024 未満
    client = Anthropic()
    try:
        return {"pdf": [ask_once(client, pdf) for _ in range(2)], "text": [ask_once(client, text) for _ in range(2)]}
    finally:
        client.close()


def main() -> None:
    rows = run()
    for i, (inp, made, read) in enumerate(rows["pdf"], 1):
        print(f"PDF 1ページ {i}回目: input_tokens={inp} cache_creation_input_tokens={made} cache_read_input_tokens={read}")
    for i, (_, made, read) in enumerate(rows["text"], 1):
        print(f"抜き出した文字 {i}回目: cache_creation_input_tokens={made} cache_read_input_tokens={read}")


if __name__ == "__main__":
    main()
