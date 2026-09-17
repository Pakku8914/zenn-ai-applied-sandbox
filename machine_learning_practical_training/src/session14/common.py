"""セッション 14 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import evaluate, load_order_table

    df = load_order_table()
    print(evaluate(df, ["unit_price", "quantity", "discount_rate"], []))
"""

from __future__ import annotations

from pathlib import Path

import lightgbm
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# データ分割とモデルの条件は全章で共通（本書の規約）
TEST_SIZE = 0.25
RANDOM_STATE = 42
N_ESTIMATORS = 200

# 基準日はコードの中で固定する（セッション7で決めた「今日」）
REFERENCE_DATE = pd.Timestamp("2026-09-01")
WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]
MONTH_TO_SEASON = {
    3: "春", 4: "春", 5: "春",
    6: "夏", 7: "夏", 8: "夏",
    9: "秋", 10: "秋", 11: "秋",
    12: "冬", 1: "冬", 2: "冬",
}

# この章で使う「境目」の定義。数字を式の中に直接書かず、名前を付けて 1 か所に集める
NEW_CUSTOMER_DAYS = 7     # 登録から 7 日未満（0〜6 日）を「登録直後」とする
BIG_DISCOUNT_RATE = 0.20  # 20% 以上の値引きを「大きな値引き」とする

# ID は数値に見えても文字列として読む（先頭の 0 が落ちないようにする）
ID_COLUMNS = {"order_id": "str", "customer_id": "str", "book_id": "str"}


def load_order_table() -> pd.DataFrame:
    """キャンセル予測の土台になる表を作る（src/verify_setup.py の 6 節と同じ作り方・同じ並び）。

    重複した order_id を落とした 60,031 行に、顧客マスタの流入経路・登録日・生年を結合し、
    登録からの経過日数を足して返します。**行の並びは merge した直後のまま変えません。**
    """
    orders = pd.read_csv(DATA_DIR / "orders.csv", parse_dates=["ordered_at"], dtype=ID_COLUMNS)
    customers = pd.read_csv(DATA_DIR / "customers.csv", parse_dates=["signup_date"])
    df = orders.drop_duplicates("order_id").merge(
        customers[["customer_id", "channel", "signup_date", "birth_year"]],
        on="customer_id",
        how="left",
    )
    df["days_since_signup"] = (df["ordered_at"] - df["signup_date"]).dt.days
    return df


def cancel_rate(df: pd.DataFrame, mask: pd.Series | None = None) -> float:
    """キャンセル率を返す。mask を渡すとその行だけで計算する（母集団は 60,031 行）。"""
    target = df if mask is None else df.loc[mask]
    return float(target["is_canceled"].mean())


def add_amount_and_age(df: pd.DataFrame) -> pd.DataFrame:
    """既にある列を組み合わせて作る特徴量（金額と年齢）を足す。"""
    out = df.copy()
    # 売上規約どおり行ごとには丸めない（合計してから整数にする）
    out["amount"] = out["unit_price"] * out["quantity"] * (1 - out["discount_rate"])
    out["age"] = 2026 - out["birth_year"]  # 基準日を固定しているので毎年変わらない
    return out


def add_datetime_features(df: pd.DataFrame) -> pd.DataFrame:
    """日時の列を「部品」に分解して足す（曜日・月・週末フラグ・季節・基準日からの日数）。"""
    out = df.copy()
    out["weekday"] = out["ordered_at"].dt.dayofweek  # 月曜 = 0 ... 日曜 = 6
    out["month"] = out["ordered_at"].dt.month
    out["is_weekend"] = (out["ordered_at"].dt.dayofweek >= 5).astype("int64")
    out["season"] = out["month"].map(MONTH_TO_SEASON)  # month の粗い要約（モデルには渡さない）
    out["days_to_reference"] = (REFERENCE_DATE - out["ordered_at"]).dt.days
    return out


def add_domain_flags(df: pd.DataFrame) -> pd.DataFrame:
    """「こういう注文は取り消されやすい」という仮説を 0/1 の列にする。"""
    out = df.copy()
    out["is_new_customer"] = (out["days_since_signup"] < NEW_CUSTOMER_DAYS).astype("int64")
    out["is_big_discount"] = (out["discount_rate"] >= BIG_DISCOUNT_RATE).astype("int64")
    return out


def add_past_features(df: pd.DataFrame) -> pd.DataFrame:
    """その注文より前の注文数・キャンセル数を足す（未来の情報を混ぜない）。

    時間順に並べて数え、**最後に必ず元の並び順へ戻します**。並べ替えたまま学習すると
    train_test_split の分割が変わってしまうためです（本書の規約）。
    """
    ordered = df.sort_values("ordered_at")  # 時間順に並べる
    ordered["past_orders"] = ordered.groupby("customer_id").cumcount()
    ordered["past_cancels"] = (
        ordered.groupby("customer_id")["is_canceled"]
        # shift(1) で 1 行ずらしてから足すので、その行自身のキャンセルは入らない
        .transform(lambda s: s.shift(1).fillna(0).cumsum())
    )
    return ordered.sort_index()  # 元の並び順に戻す


def add_leak_feature(df: pd.DataFrame) -> pd.DataFrame:
    """全期間のキャンセル数を足す。**これはデータリークの実演にだけ使う列です。**"""
    out = df.copy()
    # transform("sum") はその行自身の is_canceled も足してしまう（＝答えを見ている）
    out["all_time_cancels"] = out.groupby("customer_id")["is_canceled"].transform("sum")
    return out


def add_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """①〜⑦の実験で使う列をまとめて足す（段階ごとに使う列だけを選んで学習する）。"""
    out = add_amount_and_age(df)
    out = add_datetime_features(out)
    out = add_domain_flags(out)
    out = add_past_features(out)
    return add_leak_feature(out)


# 増分実験の設計。各段階で「前の段階に何を足すか」だけを書く
STEP_PLAN: list[tuple[str, list[str], list[str]]] = [
    ("① 素の 3 列", ["unit_price", "quantity", "discount_rate"], []),
    ("② + 経過日数と流入経路（基準）", ["days_since_signup"], ["channel"]),
    ("③ + 金額と年齢", ["amount", "age"], ["channel"]),
    ("④ + 日時（曜日・月・週末）", ["weekday", "month", "is_weekend"], ["channel"]),
    ("⑤ + ドメイン知識のフラグ", ["is_new_customer", "is_big_discount"], ["channel"]),
    ("⑥ + 過去だけの集計", ["past_orders", "past_cancels"], ["channel"]),
    ("⑦ + 全期間のキャンセル数（リーク）", ["all_time_cancels"], ["channel"]),
]


def cumulative_steps() -> list[tuple[str, list[str], list[str]]]:
    """STEP_PLAN の「追加分」を積み上げて、各段階が使う特徴量の一覧に展開する。"""
    numeric: list[str] = []
    steps: list[tuple[str, list[str], list[str]]] = []
    for label, added, categorical in STEP_PLAN:
        numeric = numeric + added  # 前の段階を壊さずに増やす
        steps.append((label, numeric, categorical))
    return steps


def split_xy(df: pd.DataFrame, numeric: list[str], categorical: list[str]):
    """特徴量と目的変数を切り出して訓練・評価に分ける（条件は全章共通）。"""
    X = df[numeric + categorical]
    y = df["is_canceled"]
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)


def evaluate(df: pd.DataFrame, numeric: list[str], categorical: list[str]) -> dict[str, float]:
    """指定した特徴量で LightGBM を学習し、列数・ROC AUC・PR-AUC を返す。"""
    transformers: list[tuple] = [("num", StandardScaler(), numeric)]
    if categorical:
        # 引数は常に明示する（既定値はバージョンで変わる）
        transformers.append(("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical))
    model = Pipeline(
        [
            ("pre", ColumnTransformer(transformers)),
            ("model", lightgbm.LGBMClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, verbose=-1)),
        ]
    )
    X_train, X_test, y_train, y_test = split_xy(df, numeric, categorical)
    model.fit(X_train, y_train)
    proba = model.predict_proba(X_test)[:, 1]
    return {
        "n_features": len(numeric) + len(categorical),
        "roc_auc": float(roc_auc_score(y_test, proba)),
        "pr_auc": float(average_precision_score(y_test, proba)),
    }


def run_steps(df: pd.DataFrame) -> list[dict]:
    """①〜⑦を順に学習して結果を集める。"""
    results = []
    for label, numeric, categorical in cumulative_steps():
        score = evaluate(df, numeric, categorical)
        results.append({"label": label, **score})
    return results


def print_steps(results: list[dict]) -> None:
    """増分実験の結果を 1 段階 1 行で表示する。"""
    for r in results:
        print(f"{r['label']} : {r['n_features']} 列 / ROC AUC {r['roc_auc']:.4f} / PR-AUC {r['pr_auc']:.4f}")
