#!/usr/bin/env python3
"""セッション16の練習問題の判定。

    python src/session16/verify_practice.py

参照解（`ex_cost.py`）を判定する。自分の実装を判定したい場合は、
下の import 元を自分のファイルに差し替えるだけでよい。
1つでも落ちたら非0で終了する。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _d in (ROOT, HERE, ROOT / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from costshape import reset_data  # noqa: E402
from ex_cost import (behaviour_table, cache_effect, check_design,  # noqa: E402
                     cost_table, daily_plan, guard_table, pad_effect,
                     slim_effect, step_breakdown, tier_plan)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


reset_data()

a = cost_table()
check("問題1 1タスクあたり単価を出せる",
      a["cu"] == [12620, 6110, 6190, 30260] and a["合計"] == 55180
      and a["最も高い"] == "同じ検索を繰り返す" and a["倍率"] == 2.4
      and a["最も高い件の停止理由"] == "max_steps",
      f"合計 {a['合計']} cu / 最も高いのは {a['最も高い']}（{a['倍率']} 倍・成果ゼロ）")

b = step_breakdown()
check("問題2 ステップ別の内訳から支配要因を特定できる",
      b["cu"] == [380, 1490, 4090, 7050] and b["合計"] == 13010
      and b["割合"] == [2.9, 11.5, 31.4, 54.2]
      and (b["入力割合"], b["出力割合"]) == (81.6, 18.4) and b["支配要因"] == "入力",
      f"最後のステップが {b['割合'][-1]}% / 入力が {b['入力割合']}%")

c = pad_effect()
check("問題3 ツール結果は残りステップ数だけ課金されることを示せる",
      c["増分"] == [300, 200, 100] == c["理論値"]
      and c["入力合計"] == [1061, 1361, 1261, 1161]
      and c["基準のステップ別"] == [13, 129, 374, 545]
      and c["get_policy のステップ別"] == [13, 229, 474, 645],
      f"増分 {c['増分']}（同じ 300 文字が 3 : 2 : 1 の重さになる）")

d = cache_effect()
check("問題4 前方一致で再利用できる量を出せる",
      d["再利用できる入力"] == 516 and d["新しく払う入力"] == 545
      and d["最後のステップの入力"] == 545 and d["時刻を先頭に入れた場合"] == 0
      and d["コスト"] == (13010, 8366) and d["削減率"] == 35.7,
      f"再利用 {d['再利用できる入力']} / 新規 {d['新しく払う入力']} / "
      f"時刻を入れると {d['時刻を先頭に入れた場合']}")

e = tier_plan()
check("問題5 成功率を落とさずに単価を下げられる",
      (e["全部上位"], e["役割で振り分け"], e["閾値で格下げ"]) == (13010, 6665, 6665)
      and e["削減率"] == 48.8 and e["成功"] is True
      and e["階層"] == ["上位（判断向け）"] * 3 + ["下位（整形向け）"],
      f"{e['全部上位']} → {e['役割で振り分け']} cu（{e['削減率']}% 減）")
bad = e["格下げで壊れた版"]
check("問題5 挙動が変わった格下げを軌跡テストで落とせる",
      bad["手数"] == 5 and bad["成功"] is False and bad["再現率"] == 1.0
      and bad["適合率"] == 0.75 and bad["余計なツール"] == ["search_docs"],
      f"再現率 {bad['再現率']} のまま適合率 {bad['適合率']}（余計な呼び出し1回）")

f = guard_table()
check("問題6 見積もり型の上限を実装できる",
      f["上限"] == [400, 520, 1000, 1200]
      and f["事後"] == [(3, 516, "budget"), (4, 1061, "done"),
                        (4, 1061, "done"), (4, 1061, "done")]
      and f["見積"] == [(3, 516, "budget"), (3, 516, "budget"),
                        (3, 516, "budget"), (4, 1061, "done")]
      and f["守れた上限（事後）"] == [1200]
      and f["守れた上限（見積）"] == [520, 1000, 1200],
      "事後は上限 520 で 1,061 まで使う。見積もりなら 516 で止まる")

g = slim_effect()
check("問題7 ツール結果を短くしても軌跡が変わらない",
      g["半分以下になったか"] is True and g["減った入力"] > 0
      and g["ツール列は同じ"] is True and g["停止理由"] == "done",
      f"結果 {g['結果の文字数'][0]} → {g['結果の文字数'][1]} 文字 / "
      f"入力 {g['入力の合計'][0]} → {g['入力の合計'][1]}")

h = daily_plan()
check("問題8 1タスク上限が無いと到着順で拒否されるタスクが変わる",
      h["到着順"]["上限なし"] == {"拒否": ["同じ検索を繰り返す"], "合計": 24920}
      and h["暴走が先"]["上限なし"] == {"拒否": ["経費レポート作成"], "合計": 42560},
      "暴走した1件が先に来ると、正常なタスクが締め出される")
check("問題8 1タスク上限を置けば到着順によらず全件通る",
      h["到着順"]["1タスク上限あり"] == {"拒否": [], "合計": 39920}
      and h["暴走が先"]["1タスク上限あり"] == {"拒否": [], "合計": 39920},
      "どちらの順でも1日の合計は 39,920 cu")

i = behaviour_table()
check("問題9 超過時の3つの振る舞いを実装できる",
      i["行"] == [("打ち切り（fail）", 3, 5960, "budget"),
                  ("格下げ（downgrade）", 4, 6665, "done"),
                  ("人間に渡す（handoff）", 3, 5960, "budget")]
      and i["上限内で完走した振る舞い"] == ["格下げ（downgrade）"]
      and i["引き継ぎ書の不足項目"] == [],
      "上限 10,000 cu で完走できるのは格下げだけ")

missing = check_design()
check("問題10 コスト上限の設計メモに必要な節がそろっている",
      missing == [], f"不足: {missing or 'なし'}")

reset_data()

if failures:
    print(f"\n{len(failures)} 問の判定に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション16の練習問題はすべて OK です。")
