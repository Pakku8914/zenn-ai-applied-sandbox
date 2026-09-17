"""サンドボックスの動作確認用の最小サンプル。

同梱データを読み込み、集計・可視化・モデル学習を一巡させます。
本書の第 1 セッションでは、このスクリプトの中身を 1 行ずつ読み解いていきます。

使い方:
    docker compose exec lab python src/hello.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 画面を持たないコンテナ内で図を PNG として保存するための設定
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_DIR = Path(__file__).resolve().parent.parent / "outputs"


def main() -> None:
    books = pd.read_csv(DATA_DIR / "books.csv")
    reviews = pd.read_csv(DATA_DIR / "reviews.csv", parse_dates=["reviewed_at"])

    print("こんにちは、機械学習とデータ分析の実践入門へ！")
    print(f"書籍マスタ  : {books.shape[0]} 行 × {books.shape[1]} 列")
    print(f"レビュー    : {reviews.shape[0]} 行 × {reviews.shape[1]} 列")

    # 1. 集計：カテゴリごとの平均価格を見る
    print("\n■ カテゴリ別の平均価格")
    print(books.groupby("category")["price"].mean().round().sort_values(ascending=False).to_string())

    # 2. 可視化：星の分布を棒グラフにする（日本語ラベルが表示できることの確認も兼ねる）
    OUT_DIR.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(5, 3.2))
    reviews["rating"].value_counts().sort_index().plot(kind="bar", ax=ax, color="#4c78a8")
    ax.set_title("レビューの星の分布")
    ax.set_xlabel("星の数")
    ax.set_ylabel("件数")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "hello_rating.png", dpi=100)
    plt.close(fig)
    print("\n■ グラフを保存しました: outputs/hello_rating.png")

    # 3. 機械学習：レビューが高評価（星 4 以上）になるかを予測する
    df = reviews.dropna(subset=["rating"]).merge(books, on="book_id", how="left")
    features = ["price", "pages", "body_length"]
    X = StandardScaler().fit_transform(df[features])
    y = (df["rating"] >= 4).astype(int)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )
    model = LogisticRegression(max_iter=1000).fit(X_train, y_train)
    auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])

    print("\n■ 高評価レビューの予測（ロジスティック回帰）")
    print(f"学習データ {len(X_train)} 件 / 評価データ {len(X_test)} 件")
    print(f"ROC AUC : {auc:.4f}")
    print("\n環境の準備は完了です。第 1 セッションへ進みましょう。")


if __name__ == "__main__":
    main()
