"""環境構築が正しく終わったかを確認するスクリプト。

ライブラリのバージョン、データの読み込み、日本語グラフの保存、
モデルの学習までを一度に通します。

使い方:
    docker compose exec lab python src/check_env.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 画面のない環境で図を PNG に保存するための設定
import matplotlib.pyplot as plt
import lightgbm
import pandas as pd
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_DIR = Path(__file__).resolve().parent.parent / "outputs"

print(f"pandas       : {pd.__version__}")
print(f"scikit-learn : {sklearn.__version__}")
print(f"LightGBM     : {lightgbm.__version__}")

books = pd.read_csv(DATA_DIR / "books.csv")
reviews = pd.read_csv(DATA_DIR / "reviews.csv")
print(f"\n書籍マスタ   : {len(books)} 行")
print(f"レビュー     : {len(reviews)} 行")
print(f"星の平均     : {reviews['rating'].mean():.4f}")

# 日本語のラベルが豆腐（□）にならないかを図で確かめる
OUT_DIR.mkdir(exist_ok=True)
fig, ax = plt.subplots(figsize=(5, 3))
books.groupby("category")["price"].mean().sort_values().plot(kind="barh", ax=ax)
ax.set_title("カテゴリ別の平均価格")
ax.set_xlabel("平均価格（円）")
fig.tight_layout()
fig.savefig(OUT_DIR / "check_env.png", dpi=100)
plt.close(fig)
print("\n図を保存しました: outputs/check_env.png")

# 最小構成のモデルを学習して、予測ができる状態かを確認する
df = reviews.dropna(subset=["rating"]).merge(books, on="book_id", how="left")
X = df[["price", "pages", "body_length"]]
y = (df["rating"] >= 4).astype(int)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)
model = LogisticRegression(max_iter=1000).fit(X_train, y_train)
print(f"ROC AUC      : {roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]):.4f}")
print("\n環境の準備は完了です。")
