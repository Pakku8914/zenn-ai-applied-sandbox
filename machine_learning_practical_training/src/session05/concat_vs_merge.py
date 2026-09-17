"""concat（縦に積む）と merge（横にくっつける）の違いを確かめる。

使い方:
    docker compose exec lab python src/session05/concat_vs_merge.py
"""

from __future__ import annotations

import pandas as pd

from common import load_orders


def main() -> None:
    orders = load_orders()
    orders_dedup = orders.drop_duplicates()

    print("■ 縦に積む（行が増える・列は増えない）")
    valid = orders_dedup.loc[orders_dedup["is_canceled"] == 0]
    canceled = orders_dedup.loc[orders_dedup["is_canceled"] == 1]
    rebuilt = pd.concat([valid, canceled], ignore_index=True)
    print(f"  有効注文       : {len(valid):>6,} 行")
    print(f"  キャンセル     : {len(canceled):>6,} 行")
    print(f"  concat で戻すと: {len(rebuilt):>6,} 行 / {rebuilt.shape[1]} 列")
    print(
        f"  行数の検算: {len(valid):,} + {len(canceled):,} = {len(rebuilt):,}"
        f" → {len(valid) + len(canceled) == len(rebuilt)}"
    )

    print("\n■ ignore_index を忘れるとラベルが重複する")
    head3 = orders_dedup.reset_index(drop=True).head(3)
    stacked = pd.concat([head3, head3])
    print(f"  concat([head3, head3]) のラベル: {stacked.index.tolist()}")
    print(f"  重複したラベル: {int(stacked.index.duplicated().sum())} 個")
    print(f"  ignore_index=True にすると    : {pd.concat([head3, head3], ignore_index=True).index.tolist()}")

    print("\n■ axis=1 の concat は「位置」で横に並べる（キーを見ない）")
    left = pd.DataFrame({"key": ["A", "B"], "v": [1, 2]})
    right = pd.DataFrame({"key": ["B", "A"], "w": [30, 40]})
    wide = pd.concat([left, right], axis=1)
    merged = left.merge(right, on="key", how="inner")
    print(f"  concat(axis=1) で key=A の行に付いた w: {int(wide['w'].iloc[0])}  ← 間違い")
    print(f"  merge(on=\"key\") で key=A の行に付いた w: {int(merged.loc[merged['key'] == 'A', 'w'].item())}  ← 正しい")


if __name__ == "__main__":
    main()
