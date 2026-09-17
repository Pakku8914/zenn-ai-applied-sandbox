"""モデルで埋める ― KNNImputer を 5 行の toy で確かめる。

近い行を探して、その平均で埋める代入です。手で検算できる大きさにしてあります。

使い方:
    docker compose exec lab python src/session11/model_impute_toy.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.impute import KNNImputer

# 5 行目だけ price が欠損している。pages が近い行は 1 行目（100）と 2 行目（110）
TOY = pd.DataFrame(
    {
        "pages": [100.0, 110.0, 300.0, 320.0, 105.0],
        "price": [1000.0, 1100.0, 3000.0, 3200.0, np.nan],
    }
)


def main() -> None:
    imputer = KNNImputer(n_neighbors=2)
    filled = pd.DataFrame(imputer.fit_transform(TOY), columns=TOY.columns)

    print("■ KNNImputer（近い 2 行の平均で埋める）")
    for i in range(len(TOY)):
        original = TOY.loc[i, "price"]
        before = "欠損" if pd.isna(original) else f"{original:.1f}"
        print(f"  pages={TOY.loc[i, 'pages']:.0f}: price {before} → {filled.loc[i, 'price']:.1f}")
    print("  5 行目は pages が近い 2 行の平均（(1000 + 1100) / 2 = 1050）で埋まった")


if __name__ == "__main__":
    main()
