"""LightGBM の重要度を gain（減らした不純度の合計）で読む。

使い方:
    docker compose exec lab python src/session19/gain_importance.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # 画面のない環境なのでファイルに保存する
import matplotlib.pyplot as plt
import numpy as np

from common import OUT_DIR, gain_importance, load_review_table, make_lgbm, prepare, split_xy


def draw(path, table) -> None:
    """gain の大きい順に横棒で並べる（上にあるほど効いている列）。"""
    ordered = table.sort_values("gain")  # 横棒は下から積むので昇順にする
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    ax.barh(ordered["feature"], ordered["gain"], color="#4c78a8")
    ax.set_xlabel("gain（その列の分割で減った不純度の合計）")
    ax.set_title("LightGBM の重要度（gain）― 単価と本文の長さで説明が付いている")
    fig.tight_layout()
    OUT_DIR.mkdir(exist_ok=True)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_xy(df)
    pre, train, test, names = prepare(X_train, X_test)

    # importance_type を指定しておくと feature_importances_ の中身が gain になる（既定は split）
    model = make_lgbm(importance_type="gain").fit(train, y_train)
    table = gain_importance(model, names)

    print("■ gain で並べた重要度（n_estimators = 200・既定パラメータ）")
    print("順位 | 特徴量            | gain")
    # 小さな gain は丸め方で ±1 変わるので、表示は int()（切り捨て）で統一する
    for rank, row in enumerate(table.itertuples(index=False), start=1):
        print(f"{rank:>3}  | {row.feature:<17} | {int(row.gain):>9,}")
    print()

    print("■ feature_importances_ の中身は importance_type で変わる")
    same = bool(np.allclose(model.feature_importances_, [table.loc[table['feature'] == name, 'gain'].iloc[0] for name in names]))
    print(f"feature_importances_ が gain と一致するか（importance_type='gain' を指定したので）: {same}")
    split_order = list(table.sort_values("split", ascending=False)["feature"])
    print(f"gain で 1 位の列  : {table.iloc[0]['feature']}")
    print(f"split で 1 位の列 : {split_order[0]}")
    print(f"gain と split で順位が入れ替わるか: {split_order != list(table['feature'])}")
    print()
    print("判断: gain は『その列で分けたときにどれだけ迷いが減ったか』の合計です。")
    print("      split（分割に使われた回数）とは別物なので、どちらの重要度を見ているか必ず確認します。")

    path = OUT_DIR / "s19_gain_importance.png"
    draw(path, table)
    print(f"図を保存しました: outputs/{path.name}")


if __name__ == "__main__":
    main()
