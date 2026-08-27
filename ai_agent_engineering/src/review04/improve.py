#!/usr/bin/env python3
"""復習04：今週直す1件を選ぶ（問題3）。

    python src/review04/improve.py

S14 は症状を頻度順に並べるところまでを扱った。運用ではその先に「今週の枠は1件」と
いう制約が来る。頻度の1位をそのまま直すと、**コストだけの症状を先に直して、社外へ
出てしまう症状を来週に回す**ことが起きる。

そこで頻度に**被害の重み**を掛ける。重みは宣言値であり、S12 の「禁止された結果」に
近いものほど大きい。重みを表に書き出しておくことに意味がある（毎回その場で決めると、
声の大きい人の順に直ることになる）。

あわせて、記録の残し方も同じ形で選ぶ。「取りこぼしが 0 の案のうち、保存量が最小のもの」
という規則にしておけば、容量が厳しくなったときも診断能力を落とさずに減らせる。
"""

from __future__ import annotations

from _paths import reset_data, setup

ROOT = setup()

from failtags import (S_CUTOFF, S_EMPTY, S_ERROR, S_EXTERNAL, S_REPEAT,  # noqa: E402
                      S_TOOL_OK, all_traces, sampling_rows, symptom_ranking,
                      verdict)

# 被害の重み（宣言値）。「取り返しがつくか」「利用者に嘘が届くか」で決める。
HARM = {
    S_EXTERNAL: 5,   # 社外へ出る。取り消せない（S12 の禁止された結果そのもの）
    S_EMPTY: 3,      # 完了したように見えて中身が無い。利用者が気づけない
    S_CUTOFF: 2,     # 途中で止まる。利用者は待たされたうえでやり直す
    S_ERROR: 2,      # 例外で止まる。副作用が中途半端に残りうる
    S_REPEAT: 1,     # 増えるのはコストだけ（S16）
    S_TOOL_OK: 0,    # 回復している。数えるが直さない
}


def traces():
    """8件の軌跡を取り直す。前後で業務データを初期状態に戻す。"""
    reset_data()
    rows = all_traces()
    return rows


def frequency_rows(rows=None) -> list[dict]:
    """S14 の頻度順（件数が同じなら最初に見つかった順）。"""
    return symptom_ranking(rows if rows is not None else traces())


def ranked(freq: list[dict]) -> list[dict]:
    """頻度 × 被害で並べ替える。同点なら重みの大きい順、次に頻度順の並び。"""
    order = {row["symptom"]: i for i, row in enumerate(freq)}
    out = [{"症状": r["symptom"], "件数": r["count"], "重み": HARM[r["symptom"]],
            "スコア": r["count"] * HARM[r["symptom"]], "代表": r["example"]}
           for r in freq]
    return sorted(out, key=lambda r: (-r["スコア"], -r["重み"], order[r["症状"]]))


def pick_one(rows: list[dict]) -> str:
    """今週直す1件。**1件しか選ばない**のが要点。"""
    return rows[0]["症状"]


def sampling_choice(rows) -> dict:
    """記録の残し方を選ぶ：取りこぼし 0 の案のうち、保存量が最小のもの。"""
    plans = sampling_rows(rows)
    zero_loss = [p for p in plans if p["lost"] == 0]
    if not zero_loss:
        raise ValueError("取りこぼし 0 の案がありません。間引き方を見直してください。")
    return min(zero_loss, key=lambda p: int(p["kept"].split("/")[0]))


def main() -> None:
    rows = traces()
    freq = frequency_rows(rows)

    print("=== 症状の頻度（S14 の実測・8件の軌跡）===")
    print(f"軌跡 {len(rows)} 件 / 失敗 {sum(1 for t in rows if verdict(t) == '失敗')} 件")
    print("症状 | 件数 | 代表 task_id")
    for row in freq:
        print(f"{row['symptom']} | {row['count']} | {row['example']}")

    scored = ranked(freq)
    print("\n=== 頻度 × 被害で並べ替える（被害の重みは宣言値）===")
    print("順 | 症状 | 件数 | 重み | スコア | 代表 task_id")
    for i, row in enumerate(scored, start=1):
        print(f"{i} | {row['症状']} | {row['件数']} | {row['重み']} | "
              f"{row['スコア']} | {row['代表']}")
    print(f"→ 頻度の1位は「{freq[0]['symptom']}」だが、"
          f"今週直す1件は「{pick_one(scored)}」である。")

    print("\n=== 記録の残し方（S14 の実測）===")
    print("方式 | 保存 | 失敗の保存 | 取りこぼした失敗")
    for plan in sampling_rows(rows):
        print(f"{plan['plan']} | {plan['kept']} | {plan['kept_failures']} | {plan['lost']}")
    choice = sampling_choice(rows)
    print(f"→ 取りこぼし 0 の案のうち保存量が最小なのは「{choice['plan']}」"
          f"（{choice['kept']}）。")

    reset_data()
    print("\n※ data/ は初期状態に戻しました。")


if __name__ == "__main__":
    main()
