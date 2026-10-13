"""問題8：本物の LLM で精度を測る前に、呼び出し回数とトークン数を見積もる（料金は単価を引数で受け取る）。

    docker compose exec api python -m src.session12.solutions.q8_plan

トークン数は mockllm の近似（fridge.jpg 1件 input 1668・output 194）。本物では count_tokens で数え直す。
"""

from __future__ import annotations

MAX_ATTEMPTS = 2   # セッション4の再試行（1回目＋形が崩れたときの再試行1回）


def plan(cases: int, repeats: int, input_tokens: int, output_tokens: int, max_attempts: int = MAX_ATTEMPTS) -> dict:
    calls = cases * repeats
    return {
        "calls": calls,
        "input_tokens": calls * input_tokens,
        "output_tokens": calls * output_tokens,
        "worst_calls": calls * max_attempts,
        "worst_input_tokens": calls * max_attempts * input_tokens,
        "worst_output_tokens": calls * max_attempts * output_tokens,
    }


def cost(p: dict, input_price_per_mtok: float, output_price_per_mtok: float, worst: bool = False) -> float:
    """単価（100万トークンあたり）は公式の料金ページで確かめて渡す。ここには書かない。"""
    prefix = "worst_" if worst else ""
    return (p[f"{prefix}input_tokens"] * input_price_per_mtok + p[f"{prefix}output_tokens"] * output_price_per_mtok) / 1e6


def main() -> int:
    p = plan(cases=30, repeats=3, input_tokens=1668, output_tokens=194)
    for key, value in p.items():
        print(f"{key}: {value:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
