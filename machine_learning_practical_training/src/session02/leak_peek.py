"""「レビュー本文の長さ」から「星」を予測してよいのかを考えるための下見。

数字と図を出すだけで、結論は出しません。
この関係を特徴量として使ってよいかどうかは、あなたが判断する材料です。

使い方:
    docker compose exec lab python src/session02/leak_peek.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"
OUT_DIR.mkdir(exist_ok=True)

reviews = pd.read_csv(DATA_DIR / "reviews.csv", parse_dates=["reviewed_at"])

corr = reviews["body_length"].corr(reviews["rating"])
print("■ レビュー本文の文字数（body_length）と星（rating）の関係")
print(f"相関係数: {corr:.4f}")
print(f"符号: {'負（本文が長いほど星が低い傾向）' if corr < 0 else '正（本文が長いほど星が高い傾向）'}")

df = reviews.dropna(subset=["rating"])
groups = [df.loc[df["rating"] == star, "body_length"].to_numpy() for star in (1, 2, 3, 4, 5)]

fig, ax = plt.subplots(figsize=(5.2, 3.4))
ax.boxplot(groups, tick_labels=["星1", "星2", "星3", "星4", "星5"])
ax.set_title("星ごとのレビュー本文の長さ")
ax.set_xlabel("星の数")
ax.set_ylabel("本文の文字数")
fig.tight_layout()
fig.savefig(OUT_DIR / "s02_body_length_rating.png", dpi=100)
plt.close(fig)
print("図を保存しました: outputs/s02_body_length_rating.png")

print("\n■ 考える材料")
print("この関係は「本文が長いから星が低くなる」のでしょうか。")
print("それとも「星が低い人が長く書く」のでしょうか。")
print("レビューを投稿する前に、本文の長さは分かりますか？")
