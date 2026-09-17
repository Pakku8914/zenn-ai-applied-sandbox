"""サンドボックス全体の自己検証スクリプト。

本書の本文に載せている数値（行数・欠損数・モデルの精度など）が、
いまこの環境で再現できるかを確認します。期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/verify_setup.py
"""

from __future__ import annotations

import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import lightgbm
import numpy as np
import pandas as pd
import shap
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, r2_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TOLERANCE = 0.005  # 指標の許容誤差

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual}")
    if not ok:
        print(f"     期待値: {expected}")
        failures.append(label)


def check_close(label: str, actual: float, expected: float) -> None:
    ok = abs(actual - expected) <= TOLERANCE
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:.4f}")
    if not ok:
        print(f"     期待値: {expected:.4f} ± {TOLERANCE}")
        failures.append(label)


# 1. ライブラリのバージョン（本文のコードはこの組み合わせで検証している）
check("pandas のバージョン", pd.__version__, "3.0.5")
check("numpy のバージョン", np.__version__, "2.5.3")
check("scikit-learn のバージョン", sklearn.__version__, "1.9.0")
check("LightGBM のバージョン", lightgbm.__version__, "4.7.0")

# 2. データセットが生成済みで、想定どおりの形をしていること
missing = [name for name in ("books", "customers", "orders", "reviews") if not (DATA_DIR / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

books = pd.read_csv(DATA_DIR / "books.csv")
customers = pd.read_csv(DATA_DIR / "customers.csv", parse_dates=["signup_date"])
orders = pd.read_csv(DATA_DIR / "orders.csv", parse_dates=["ordered_at"])
reviews = pd.read_csv(DATA_DIR / "reviews.csv", parse_dates=["reviewed_at"])

check("books.csv の行数", len(books), 600)
check("customers.csv の行数", len(customers), 8000)
check("orders.csv の行数", len(orders), 60061)
check("reviews.csv の行数", len(reviews), 14467)
check("customers.region の欠損数", int(customers["region"].isna().sum()), 392)
check("reviews.rating の欠損数", int(reviews["rating"].isna().sum()), 298)
check("orders の完全重複行の数", int(orders.duplicated().sum()), 30)
check_close("キャンセル率", float(orders["is_canceled"].mean()), 0.0360)

# 3. pandas 3.0 の型の既定値（2.x の記事と食い違う点なので明示的に確認する）
check("文字列カラムの dtype", str(customers["region"].dtype), "str")
check("日時カラムの dtype", str(customers["signup_date"].dtype), "datetime64[us]")

# 4. グラフの日本語が豆腐（□）にならないこと
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    fig, ax = plt.subplots(figsize=(4, 3))
    books.groupby("category")["price"].mean().plot(kind="bar", ax=ax)
    ax.set_title("カテゴリ別の平均価格")
    fig.tight_layout()
    fig.savefig("/tmp/verify_ja.png", dpi=72)
    plt.close(fig)
    glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("日本語フォントの欠落警告の数", len(glyph_warnings), 0)

# 5. 本文に載せている精度が再現できること
review_df = (
    reviews.dropna(subset=["rating"])
    .merge(books, on="book_id", how="left")
    .merge(orders.drop_duplicates("order_id")[["order_id", "unit_price"]], on="order_id", how="left")
)
review_df["is_high"] = (review_df["rating"] >= 4).astype(int)
features = ["unit_price", "pages", "published_year", "body_length", "category"]
preprocess = ColumnTransformer(
    [
        ("num", StandardScaler(), ["unit_price", "pages", "published_year", "body_length"]),
        ("cat", OneHotEncoder(handle_unknown="ignore"), ["category"]),
    ]
)
X, y = review_df[features], review_df["is_high"]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)
check("高評価レビューの学習データ件数", len(X_train), 10626)

for label, model, expected_auc in [
    ("ロジスティック回帰の ROC AUC", LogisticRegression(max_iter=1000), 0.8265),
    ("ランダムフォレストの ROC AUC", RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=1), 0.7705),
    ("LightGBM の ROC AUC", lightgbm.LGBMClassifier(n_estimators=200, random_state=42, verbose=-1), 0.7966),
]:
    pipeline = Pipeline([("pre", preprocess), ("model", model)]).fit(X_train, y_train)
    check_close(label, roc_auc_score(y_test, pipeline.predict_proba(X_test)[:, 1]), expected_auc)

X_tr, X_te, y_tr, y_te = train_test_split(X, review_df["rating"], test_size=0.25, random_state=42)
regressor = Pipeline(
    [("pre", preprocess), ("model", lightgbm.LGBMRegressor(n_estimators=200, random_state=42, verbose=-1))]
).fit(X_tr, y_tr)
check_close("星の回帰の決定係数 R2", r2_score(y_te, regressor.predict(X_te)), 0.3182)

# 6. 不均衡データ（キャンセル予測）— ROC AUC は高いのに PR-AUC は低い、という本書の論点
order_df = orders.drop_duplicates("order_id").merge(
    customers[["customer_id", "channel", "signup_date"]], on="customer_id", how="left"
)
order_df["days_since_signup"] = (order_df["ordered_at"] - order_df["signup_date"]).dt.days
cancel_features = ["unit_price", "quantity", "discount_rate", "days_since_signup", "channel"]
cancel_pre = ColumnTransformer(
    [
        ("num", StandardScaler(), ["unit_price", "quantity", "discount_rate", "days_since_signup"]),
        ("cat", OneHotEncoder(handle_unknown="ignore"), ["channel"]),
    ]
)
Xc, yc = order_df[cancel_features], order_df["is_canceled"]
Xc_tr, Xc_te, yc_tr, yc_te = train_test_split(Xc, yc, test_size=0.25, random_state=42, stratify=yc)
cancel_model = Pipeline(
    [("pre", cancel_pre), ("model", lightgbm.LGBMClassifier(n_estimators=200, random_state=42, verbose=-1))]
).fit(Xc_tr, yc_tr)
cancel_proba = cancel_model.predict_proba(Xc_te)[:, 1]
check_close("キャンセル予測の ROC AUC", roc_auc_score(yc_te, cancel_proba), 0.7911)
check_close("キャンセル予測の PR-AUC", average_precision_score(yc_te, cancel_proba), 0.1827)

# 7. SHAP でモデルの説明が計算できること
tree_model = lightgbm.LGBMClassifier(n_estimators=50, random_state=42, verbose=-1)
numeric_only = review_df[["unit_price", "pages", "published_year", "body_length"]]
tree_model.fit(numeric_only, y)
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    shap_values = shap.TreeExplainer(tree_model).shap_values(numeric_only.head(100))
check("SHAP 値の形", np.asarray(shap_values).shape, (100, 4))

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("すべての検証に成功しました。")
