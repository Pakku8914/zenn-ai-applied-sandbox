"""問題6: セグメントに名前と打ち手を付け、k=3 と k=4 のどちらを採るかを決める。

使い方:
    docker compose exec lab python src/session27/q6_segment_decision.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from common import (
    K_ALT,
    K_MAIN,
    labels_for,
    print_profile,
    profile,
    rfm_table,
    segment_names,
    sweep_table,
)

# 「このセグメントに何をするか」を先に決めておく。決められない分け方は使えない分け方
PLAYBOOK = {
    "優良顧客": ("先行販売の案内", "値引きではなく『早く買える』価値で応える"),
    "常連顧客": ("関連ジャンルのおすすめ", "購入間隔が伸びた人から順に声をかける"),
    "一般顧客": ("2 回目を作る施策", "まとめ買いの送料無料など、次の 1 回に集中する"),
    "離脱顧客": ("復帰クーポン", "反応がなければ配信を止め、配信コストを守る"),
}

# 教師なし学習の結果を受け取るときのチェックリスト（正解がないので手続きで守る）
CHECKLIST = [
    ("指標の定義が書いてあるか", "recency は基準日 2026-09-01 から、売上はキャンセルと重複を除く"),
    ("スケーリングしたか", "していなければ、桁の大きい指標だけで分かれている"),
    ("random_state が固定されているか", "固定していない結果は再現できない"),
    ("クラスタ番号ではなく profile で説明しているか", "番号には意味がない"),
    ("セグメントごとに違う打ち手があるか", "同じ打ち手なら分ける必要がない"),
    ("名前が数値と合っているか", "『優良』と呼ぶ根拠の列と値を必ず添える"),
]


def analyze() -> dict:
    """k=4 の profile に構成比を足し、k=3 との対応表を作る。"""
    table = profile(K_MAIN)
    names = segment_names(K_MAIN)
    assigned = rfm_table().assign(cluster=np.asarray(labels_for(K_MAIN)))
    revenue = assigned.groupby("cluster")["monetary"].sum()

    report = table.assign(
        segment=[names[int(cluster)] for cluster in table.index],
        customer_share=table["n"] / int(table["n"].sum()),
        revenue_share=revenue / float(revenue.sum()),
    )
    cross = pd.crosstab(
        pd.Series(np.asarray(labels_for(K_ALT)), name=f"k={K_ALT}"),
        pd.Series(np.asarray(labels_for(K_MAIN)), name=f"k={K_MAIN}"),
    )
    sweep = sweep_table().set_index("k")
    return {
        "report": report,
        "names": names,
        "profile": table,
        "cross": cross,
        "cross_total": int(cross.to_numpy().sum()),
        "cross_shape": cross.shape,
        "split_counts": [int((row > 0).sum()) for _, row in cross.iterrows()],
        "silhouette": {k: float(sweep.loc[k, "silhouette"]) for k in (K_ALT, K_MAIN)},
        "revenue_total": round(float(revenue.sum())),
        "top_revenue_segment": names[int(revenue.idxmax())],
        "smallest_revenue_segment": names[int(revenue.idxmin())],
    }


def main() -> None:
    info = analyze()

    print(f"■ 1. セグメント名と profile（k={K_MAIN}）")
    print_profile(info["profile"], info["names"])

    print("\n■ 2. 人数と売上の構成比")
    print(f"{'セグメント':<12}{'人数の割合':>12}{'売上の割合':>12}")
    for cluster, row in info["report"].iterrows():
        print(f"{row['segment']:<12}{row['customer_share']:>12.1%}{row['revenue_share']:>12.1%}")
    print(f"売上合計 : {info['revenue_total']:,} 円")
    print(f"売上がいちばん大きいセグメント : {info['top_revenue_segment']}")
    print(f"売上がいちばん小さいセグメント : {info['smallest_revenue_segment']}")

    print("\n■ 3. 打ち手（セグメントごとに違うものを用意できるか）")
    for cluster, row in info["report"].iterrows():
        action, reason = PLAYBOOK[row["segment"]]
        print(f"  {row['segment']:<8}{action:<16}{reason}")

    print(f"\n■ 4. k={K_ALT} と k={K_MAIN} の対応")
    print(info["cross"].to_string())
    print(f"表の合計 : {info['cross_total']:,} 人 / 形 : {info['cross_shape']}")
    print(f"k={K_ALT} の各クラスタが k={K_MAIN} で分かれた先の数 : {info['split_counts']}")

    print("\n■ 5. どちらを採るか")
    print(f"シルエット係数 : k={K_ALT} は {info['silhouette'][K_ALT]:.4f} / k={K_MAIN} は {info['silhouette'][K_MAIN]:.4f}")
    print(f"指標だけを見れば k={K_ALT} です。ただし k={K_MAIN} なら『優良』と『離脱』を別々に扱えます。")
    print("打ち手を 4 通り運用できるなら k=4、まず 3 通りから始めたいなら k=3。")
    print("どちらも間違いではありません。決めるのは指標ではなく目的です。")

    print("\n■ 6. 受け取るときのチェックリスト")
    for index, (question, note) in enumerate(CHECKLIST, start=1):
        print(f"  {index}. {question} — {note}")


if __name__ == "__main__":
    main()
