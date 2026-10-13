"""問題1：手で採点した結果を score_case で答え合わせする。

    docker compose exec api python -m src.session12.solutions.q1_hand_score
"""

from __future__ import annotations

from src.session12.gold import fridge_gold
from src.session12.matching import ratio, score_case

PRED = {"items": [
    {"name": "キャベツ", "amount": 1},
    {"name": "卵", "amount": 4},
    {"name": "卵", "amount": 4},
    {"name": "ニンジン", "amount": 2},
    {"name": "牛乳", "amount": 1},
    {"name": "バター", "amount": 1},
], "header": {}}


def main() -> int:
    s = score_case("問題1", fridge_gold(), PRED)
    print(f"予測 {s.predicted}・正解 {s.gold}・一致 {s.matched}")
    print(f"適合率 {ratio(s.matched, s.predicted)}・再現率 {ratio(s.matched, s.gold)}"
          f"・項目 {s.fields_correct}/{s.fields_checked}・完全一致 {'○' if s.exact else '×'}")
    for err in s.errors:
        print(f"    {err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
