"""問題4：別名（同じ物の別の呼び方）を照合に足し、適合率・再現率がどう変わるかを見る。

    docker compose exec api python -m src.session12.solutions.q4_aliases
"""

from __future__ import annotations

from collections.abc import Callable

from src.session12.gold import fridge_gold
from src.session12.matching import CaseScore, norm_name, ratio, score_case

# キーは norm_name を通した「後」の形（カタカナはひらがなになっている）で書く
ALIASES = {
    "玉子": "卵",
    "たまご": "卵",
    "みるく": "牛乳",
}

PRED = {"items": [
    {"name": "キャベツ", "amount": 0.5},
    {"name": "鶏胸肉", "amount": 1},
    {"name": "玉子", "amount": 4},
    {"name": "ニンジン", "amount": 1},
    {"name": "ミルク", "amount": 1},
], "header": {}}


def with_aliases(aliases: dict[str, str]) -> Callable[[str], str]:
    """名前全体を正規化してから、別名の表で引き直す（部分一致の置き換えはしない）。"""
    def norm(text: str) -> str:
        key = norm_name(text)
        return norm_name(aliases[key]) if key in aliases else key
    return norm


def run(norm: Callable[[str], str]) -> CaseScore:
    return score_case("問題4", fridge_gold(), PRED, norm=norm)


def line(label: str, s: CaseScore) -> str:
    return (f"{label}：一致 {s.matched}・適合率 {ratio(s.matched, s.predicted)}・再現率 {ratio(s.matched, s.gold)}"
            f"・項目 {s.fields_correct}/{s.fields_checked}・完全一致 {'○' if s.exact else '×'}")


def main() -> int:
    print(line("別名なし", run(norm_name)))
    print(line("別名あり", run(with_aliases(ALIASES))))
    print(line("キーをカタカナで書いた", run(with_aliases({"玉子": "卵", "ミルク": "牛乳"}))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
