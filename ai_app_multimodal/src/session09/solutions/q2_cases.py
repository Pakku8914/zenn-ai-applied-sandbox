"""問題2：文分割の結果を手で予想し、表にして確かめる。

    docker compose exec api python -m src.session09.solutions.q2_cases
"""

from __future__ import annotations

from src.session09.sentences import split_sentences

CASES = [
    ("(a)", "### 材料（2人分）\n- 鶏むね肉 1枚\n- キャベツ 1/4玉", ["材料（2人分）", "鶏むね肉 1枚", "キャベツ 1/4玉"]),
    ("(b)", "**ポイント**：片栗粉をまぶすと、しっとり仕上がります！", ["ポイント：片栗粉をまぶすと、しっとり仕上がります！"]),
    ("(c)", "火を止めて。余熱で3分！完成です", ["火を止めて。", "余熱で3分！", "完成です"]),
    ("(d)", "2) 塩を振る。\n10. 盛り付ける。", ["塩を振る。", "盛り付ける。"]),
    ("(e)", "まだですか？？", ["まだですか？？"]),
    ("(f)", "詳しくは https://example.com/recipe を見てください。", ["詳しくは https://example.com/recipe を見てください。"]),
    ("(g)", "```\n---\n", []),
]


def mismatches() -> list[str]:
    return [f"{label}: 予想 {want} / 実際 {split_sentences(text)}"
            for label, text, want in CASES if split_sentences(text) != want]


def main() -> int:
    for label, text, _ in CASES:
        print(f"{label} {split_sentences(text)}")
    bad = mismatches()
    print("予想と違うもの:", bad or "なし")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
