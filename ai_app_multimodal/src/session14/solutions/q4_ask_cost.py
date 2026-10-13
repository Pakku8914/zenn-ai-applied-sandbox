"""問題4：PDF への質問の月の費用を、応答キャッシュとプロンプトキャッシュの有無で比べる。

    docker compose exec api python -m src.session14.solutions.q4_ask_cost

単価と倍率は pricing.yaml（例示用の仮の値）から読む。結果は「仮の値での計算例」。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from src.session14.estimate import load_pricing

FULL, PREFIX, REST, OUT = 4888, 4876, 12, 38  # recipe_book.pdf への質問（mockllm）：全体・接頭辞・残り・出力
ASKS_PER_DAY, DAYS = 100, 30
RESPONSE_HIT = Decimal("0.2")      # 同じ人の同じ質問の再送（応答キャッシュに命中）
PROMPT_READ = Decimal("0.75")      # LLM を呼んだうち、5分以内に同じ文書が読まれていた割合


def per_call(p: dict) -> dict[str, Decimal]:
    """1回あたりの入力を「通常の入力単価で何トークン分か」（P_in 換算）で表す。"""
    llm = p["llm"]
    return {
        "none": Decimal(FULL),
        "write": REST + PREFIX * llm["cache_write_multiplier"],
        "read": REST + PREFIX * llm["cache_read_multiplier"],
    }


def plan(p: dict, response_cache: bool, prompt_cache: bool) -> tuple[Decimal, Decimal, Decimal]:
    """(入力換算トークン, 出力トークン, 費用) を月あたりで返す。"""
    c = per_call(p)
    calls = Decimal(ASKS_PER_DAY * DAYS) * (1 - RESPONSE_HIT if response_cache else 1)
    if prompt_cache:
        tokens_in = calls * (1 - PROMPT_READ) * c["write"] + calls * PROMPT_READ * c["read"]
    else:
        tokens_in = calls * c["none"]
    tokens_out = calls * OUT
    cost = tokens_in / 1_000_000 * p["llm"]["input_per_mtok"] + tokens_out / 1_000_000 * p["llm"]["output_per_mtok"]
    return tokens_in, tokens_out, cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def plain(d: Decimal) -> str:
    return str(int(d)) if d == d.to_integral_value() else str(d.normalize())


def run() -> list[str]:
    p = load_pricing()
    c = per_call(p)
    lines = [f"1回あたりの入力（P_in 換算）：キャッシュなし {plain(c['none'])}・作成 {plain(c['write'])}・"
             f"読み出し {plain(c['read'])}（出力はどれも {OUT}）"]
    for label, rc, pc in (("(A) キャッシュなし", False, False), ("(B) 応答キャッシュだけ", True, False),
                          ("(C) 応答キャッシュ＋プロンプトキャッシュ", True, True)):
        t_in, t_out, cost = plan(p, rc, pc)
        lines.append(f"{label}：入力換算 {int(t_in):,}・出力 {int(t_out):,} → {cost} {p['currency']}/月（仮の値での計算例）")
    return lines


def main() -> None:
    print("\n".join(run()))


if __name__ == "__main__":
    main()
