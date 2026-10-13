"""問題2：画像トークン・PDF のページ数・2つのキャッシュを、月の費用の見積もりに入れる。

    docker compose exec api python -m src.review04.solutions.q2_monthly_cost

単価と倍率は pricing.yaml（例示用の仮の値）から読む。結果は「仮の値での計算例」で、実際の料金ではない。
"""

from __future__ import annotations

from decimal import Decimal

from src.review04.kit import (
    FRAME_TOKENS, FRIDGE_PROMPT, PDF_TOKENS_PER_PAGE, SYSTEM_PROMPT, MTOK,
    estimate_image_tokens, fit_long_edge, load_pricing, round_cost, text_tokens,
)

QUESTION = "肉じゃがは何人分ですか？"
PHONE = (4000, 3000)              # スマートフォンで撮った写真（想定）
MAX_LONG_EDGE = 1568              # settings.image_max_long_edge（セッション3）
BOOK_PAGES = 120                  # recipe_book_full.pdf
PHOTO_OUT, ASK_OUT = 194, 38      # 出力トークン（mockllm）
PHOTOS, ASKS = 200 * 30, 100 * 30  # 月の回数（1日 200回・100回 × 30日。セッション14の想定）
PROMPT_READ = Decimal("0.75")     # LLM を呼んだ質問のうち、5分以内に同じページが読まれていた割合（仮定）
RESPONSE_HIT = Decimal("0.2")     # 応答キャッシュの命中率（仮定）


def photo_tokens(size: tuple[int, int]) -> int:
    """冷蔵庫の写真1枚の入力（枠＋画像＋指示文）。"""
    return FRAME_TOKENS + estimate_image_tokens(*size) + text_tokens(FRIDGE_PROMPT)


def ask_tokens(pages: int) -> int:
    """PDF への質問1回の入力（枠＋system＋文書＋質問）。"""
    return FRAME_TOKENS + text_tokens(SYSTEM_PROMPT) + pages * PDF_TOKENS_PER_PAGE + text_tokens(QUESTION)


def cached_ask(p: dict, pages: int) -> tuple[int, Decimal, Decimal]:
    """(接頭辞, 作成のときの入力, 読み出しのときの入力)。入力は「通常の入力単価で何トークン分か」（P_in 換算）。"""
    prefix = 4 + text_tokens(SYSTEM_PROMPT) + 3 + pages * PDF_TOKENS_PER_PAGE   # cache_control を付けた PDF まで
    rest = ask_tokens(pages) - prefix                                           # 質問の 12
    llm = p["llm"]
    return prefix, rest + prefix * llm["cache_write_multiplier"], rest + prefix * llm["cache_read_multiplier"]


def cost(p: dict, tokens_in: Decimal, tokens_out: Decimal) -> Decimal:
    llm = p["llm"]
    return round_cost(tokens_in / MTOK * llm["input_per_mtok"] + tokens_out / MTOK * llm["output_per_mtok"])


def plain(d: Decimal) -> str:
    return str(int(d)) if d == d.to_integral_value() else str(d.normalize())


def run() -> list[str]:
    p = load_pricing()
    small = fit_long_edge(*PHONE, MAX_LONG_EDGE)
    raw_photo, small_photo = photo_tokens(PHONE), photo_tokens(small)
    all_pages, one_page = ask_tokens(BOOK_PAGES), ask_tokens(1)
    prefix, write, read = cached_ask(p, 1)
    mixed = (1 - PROMPT_READ) * write + PROMPT_READ * read   # キャッシュを使う質問1回あたりの平均

    out = Decimal(PHOTOS * PHOTO_OUT + ASKS * ASK_OUT)
    rows = [
        ("(A) 縮めない写真＋120ページ全部", Decimal(PHOTOS * raw_photo + ASKS * all_pages), out),
        ("(B) 縮めた写真＋[29] だけ", Decimal(PHOTOS * small_photo + ASKS * one_page), out),
        ("(C) (B)＋プロンプトキャッシュ", PHOTOS * small_photo + ASKS * mixed, out),
    ]
    keep = 1 - RESPONSE_HIT
    rows.append(("(D) (C)＋応答キャッシュ（命中率 20%）",
                 PHOTOS * keep * small_photo + ASKS * keep * mixed,
                 PHOTOS * keep * PHOTO_OUT + ASKS * keep * ASK_OUT))

    lines = [
        f"1回あたり（入力/出力）：写真 {PHONE[0]}×{PHONE[1]} そのまま {raw_photo}/{PHOTO_OUT}"
        f"・{small[0]}×{small[1]} に縮めて {small_photo}/{PHOTO_OUT}"
        f"・質問 {BOOK_PAGES}ページ全部 {all_pages}/{ASK_OUT}・[29] だけ {one_page}/{ASK_OUT}",
        f"[29] のプロンプトキャッシュ（接頭辞 {prefix}）：作成 {plain(write)}・読み出し {plain(read)}（P_in 換算）",
    ]
    for label, tokens_in, tokens_out in rows:
        lines.append(f"{label}：入力 {int(tokens_in):,}・出力 {int(tokens_out):,} → "
                     f"{cost(p, tokens_in, tokens_out)} {p['currency']}/月（仮の値での計算例）")
    return lines


def main() -> None:
    print("\n".join(run()))


if __name__ == "__main__":
    main()
