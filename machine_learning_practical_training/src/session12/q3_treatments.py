"""問題3 の解答: 除外・クリッピング・対数変換を並べて比べる。

使い方:
    docker compose exec lab python src/session12/q3_treatments.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from common import BULK_THRESHOLD, CLIP_UPPER, load_orders


def main() -> None:
    quantity = load_orders()["quantity"]
    kept = quantity.loc[quantity < BULK_THRESHOLD]
    clipped = quantity.clip(upper=CLIP_UPPER)
    logged: pd.Series = np.log1p(quantity)

    print("■ 冊数のままの処置（単位が「冊」なので平均を比べられる）")
    print("処置 | 件数 | 平均 | 最大")
    for label, values in [
        ("そのまま", quantity),
        (f"{BULK_THRESHOLD} 冊以上を除外", kept),
        (f"上限 {CLIP_UPPER} 冊でクリップ", clipped),
    ]:
        print(f"{label} | {len(values):,} | {values.mean():.4f} | {int(values.max())}")
    print()

    print("■ 歪みがどれだけ減ったか")
    print(f"そのまま   : 歪度 {quantity.skew():.4f}")
    print(f"log1p 変換 : 歪度 {logged.skew():.4f}")
    print(f"除外   : 歪度が 5 未満になったか {bool(kept.skew() < 5)}")
    print(f"クリップ: 歪度が 5 未満になったか {bool(clipped.skew() < 5)}")
    print()

    print("■ log1p が冊数をどこへ写すか（単位が「冊」でなくなる）")
    for books_count in (1, CLIP_UPPER, BULK_THRESHOLD, int(quantity.max())):
        print(f"{books_count:>2} 冊 → {float(np.log1p(books_count)):.4f}")
    print()

    print("■ それぞれが失うもの")
    print(f"除外   : {len(quantity) - len(kept):,} 行が消える（その行の他の列の情報も一緒に消える）")
    print(f"クリップ: 行は残るが「{int(quantity.max())} 冊」という大きさの情報が消える")
    print("log1p  : 行も順序も残るが、値の単位が「冊」でなくなり、そのままでは解釈できない")


if __name__ == "__main__":
    main()
