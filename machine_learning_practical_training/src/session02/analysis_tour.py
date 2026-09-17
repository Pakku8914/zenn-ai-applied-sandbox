"""分析の一連の流れ（問い → 見る → 整える → モデル化 → 評価 → 説明）を一巡させる。

セッション 2 の時点では、コードの 1 行ずつを読み解く必要はありません。
「この 6 つの工程が順に並んでいる」ことだけを確認してください。

使い方:
    docker compose exec lab python src/session02/analysis_tour.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 画面のないコンテナで図を PNG として保存するための設定
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"
OUT_DIR.mkdir(exist_ok=True)

books = pd.read_csv(DATA_DIR / "books.csv")
reviews = pd.read_csv(DATA_DIR / "reviews.csv", parse_dates=["reviewed_at"])

# ステップ 1：問いを立てる。ここが決まらないと、どの列を見るべきかも決まらない
print("■ ステップ 1：問いを立てる")
print("  レビューが高評価（星 4 以上）になるかを、本の属性から言い当てられるか？")

# ステップ 2：データを見る。分布と欠損を見ないまま先に進まない
print("\n■ ステップ 2：データを見る")
print(f"レビューの行数: {len(reviews):,} 件")
print(f"星が未入力のレビュー: {int(reviews['rating'].isna().sum())} 件")
print(f"星の平均: {reviews['rating'].mean():.4f}")
star_counts = reviews["rating"].value_counts().sort_index()
for star, count in star_counts.items():
    print(f"  星 {int(star)} : {count:,} 件")

fig, ax = plt.subplots(figsize=(5, 3.2))
ax.bar([str(int(star)) for star in star_counts.index], star_counts.to_numpy(), color="#4c78a8")
ax.set_title("レビューの星の分布")
ax.set_xlabel("星の数")
ax.set_ylabel("件数")
fig.tight_layout()
fig.savefig(OUT_DIR / "s02_rating_distribution.png", dpi=100)
plt.close(fig)
print("図を保存しました: outputs/s02_rating_distribution.png")

# ステップ 3：整える。星が未入力の行は正解が分からないので学習には使えない
print("\n■ ステップ 3：整える")
df = reviews.dropna(subset=["rating"]).merge(books, on="book_id", how="left")
print(f"星が入っているレビュー: {len(df):,} 件")
print(f"書籍の情報を足した後の形: {len(df):,} 行 × {df.shape[1]} 列")

# ステップ 4：モデル化する。特徴量（入力）と目的変数（予測したい対象）を決める
print("\n■ ステップ 4：モデル化する")
features = ["price", "pages", "body_length"]
X = StandardScaler().fit_transform(df[features])
y = (df["rating"] >= 4).astype(int)
print(f"特徴量: {', '.join(features)}")
print("目的変数: 高評価かどうか（星 4 以上なら 1、そうでなければ 0）")
print(f"高評価の割合（正例率）: {y.mean():.0%}")

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.25, random_state=42, stratify=y
)
print(f"学習データ: {len(X_train):,} 件 / 評価データ: {len(X_test):,} 件")
model = LogisticRegression(max_iter=1000).fit(X_train, y_train)

# ステップ 5：評価する。学習に使っていないデータでどれだけ当たるかを測る
print("\n■ ステップ 5：評価する")
proba = model.predict_proba(X_test)[:, 1]
auc = roc_auc_score(y_test, proba)
print(f"ROC AUC: {auc:.4f}")

fpr, tpr, _ = roc_curve(y_test, proba)
fig, ax = plt.subplots(figsize=(4.2, 4.2))
ax.plot(fpr, tpr, color="#4c78a8", label=f"このモデル（AUC = {auc:.4f}）")
ax.plot([0, 1], [0, 1], linestyle="--", color="gray", label="でたらめに予測した場合")
ax.set_title("ROC 曲線（高評価レビューの予測）")
ax.set_xlabel("高評価でないものを高評価と判定した割合")
ax.set_ylabel("高評価を正しく高評価と判定できた割合")
ax.legend(loc="lower right", fontsize=8)
fig.tight_layout()
fig.savefig(OUT_DIR / "s02_roc_curve.png", dpi=100)
plt.close(fig)
print("図を保存しました: outputs/s02_roc_curve.png")

# ステップ 6：説明する。数字と図がそろって、はじめて人に渡せる
print("\n■ ステップ 6：説明する")
print("図と数字がそろいました。ここまでが分析の一巡です。")
