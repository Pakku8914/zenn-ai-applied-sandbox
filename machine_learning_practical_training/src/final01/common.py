"""最終プロジェクト（再購入予測）で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import dataset, fitted, threshold_table

    data = dataset()                 # 期間を切って作った表（1 プロセスで 1 回だけ作る）
    lgbm = fitted("lgbm")            # Pipeline を学習したものをまとめて返す
    table = threshold_table(lgbm["proba"], data["y_test"])

この章のいちばん大事な約束は **cutoff より後の情報を特徴量に混ぜないこと** です。
`build_repeat_table` は `future_orders`（予測期間の注文数）も作りますが、これは
**目的変数を作るためだけの列**で、`FEATURES` には入っていません。リークを再現する
課題でだけ `leak=True` として明示的に足します。

このディレクトリのスクリプトは、他のセッションのディレクトリを一切参照しません
（読者がこの章のファイルだけを作って実行できるようにするためです）。
"""

from __future__ import annotations

import platform
import warnings
from functools import lru_cache
from pathlib import Path

import joblib
import lightgbm
import numpy as np
import pandas as pd
import shap
import sklearn
from lightgbm import LGBMClassifier
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# ------------------------------------------------------------------
# 期間の切り方（この 4 行がプロジェクトの設計そのもの）
# ------------------------------------------------------------------
AS_OF = pd.Timestamp("2026-09-01")                 # データの基準日（本書共通）
HORIZON_DAYS = 90                                  # 「この先 90 日で再購入するか」を当てる
CUTOFF = AS_OF - pd.Timedelta(days=HORIZON_DAYS)   # 2026-06-03。特徴量はここまでの履歴だけ
LABEL_START = CUTOFF + pd.Timedelta(days=1)        # 2026-06-04。ここから基準日までを予測期間とする

TEST_SIZE = 0.25
RANDOM_STATE = 42
N_ESTIMATORS = 200
N_SPLITS = 5
SCORING = "roc_auc"
MAX_ITER = 1000

NUMERIC = [
    "n_orders",           # cutoff までの有効注文の件数
    "total_amount",       # 同じ期間の売上合計（行ごとに丸めない）
    "mean_amount",        # 1 件あたりの平均
    "mean_discount",      # 平均の値引き率
    "recency",            # cutoff − 最終購入日（日）
    "tenure",             # cutoff − 初回購入日（日）
    "n_categories",       # 買ったカテゴリの数
    "age",                # 2026 − birth_year
    "days_since_signup",  # cutoff − 登録日（日）
]
CATEGORICAL = ["channel", "region"]
FEATURES = NUMERIC + CATEGORICAL
TARGET = "repeat"

# 目的変数を作るための列。**特徴量に入れてはいけない**（課題5 でわざと入れて確かめる）
LEAK_COLUMN = "future_orders"

# 学習時に欠損があった列だけ、推論でも欠損を受け付ける（region は 392 件の欠損がある）
NULLABLE = ("region",)

# 入力検証で使う「ありえる値の範囲」。業務の常識を下限・上限として書き出したもの
NUMERIC_RANGES = {
    "n_orders": (1.0, 1000.0),
    "total_amount": (0.0, 10_000_000.0),
    "mean_amount": (0.0, 1_000_000.0),
    "mean_discount": (0.0, 1.0),
    "recency": (0.0, 20_000.0),
    "tenure": (0.0, 20_000.0),
    "n_categories": (1.0, 5.0),
    "age": (0.0, 120.0),
    "days_since_signup": (0.0, 20_000.0),
}

MODELS = ("logistic", "lgbm")
MODEL_LABELS = {"logistic": "ロジスティック回帰", "lgbm": "LightGBM"}

# ------------------------------------------------------------------
# 業務の前提（データからは出てこない。人が決める数字）
# ------------------------------------------------------------------
COUPON_COST_YEN = 500                                     # クーポン 1 通あたりの原価
MONTHLY_BUDGET_YEN = 500_000                              # 今月の販促予算
CAPACITY = MONTHLY_BUDGET_YEN // COUPON_COST_YEN          # 送れるのは 1,000 通まで
THRESHOLDS = (0.3, 0.5, 0.7)                              # 報告に並べる閾値
OPERATING_THRESHOLD = 0.7                                 # 課題6 で予算から逆算した結果

MODEL_PATH = OUT_DIR / "final01_repeat_model.joblib"
REPORT_PATH = OUT_DIR / "final01_report.md"

# ------------------------------------------------------------------
# 監視（PSI の目安はセッション28 と同じ）
# ------------------------------------------------------------------
PSI_BINS = 10
PSI_FLOOR = 1e-6
PSI_WATCH = 0.10
PSI_ACT = 0.25
DRIFT_RATIOS = (1.0, 1.5, 3.0)

ID_COLUMNS = {"order_id": "str", "customer_id": "str", "book_id": "str"}


# ------------------------------------------------------------------
# 読み込み
# ------------------------------------------------------------------
def load_orders() -> pd.DataFrame:
    """注文を読み込み、完全重複 30 件を落として 60,031 行にする（本書の規約）。

    売上額 `amount` は **行ごとに丸めません**（丸めると章をまたいで金額がずれます）。
    """
    orders = pd.read_csv(DATA_DIR / "orders.csv", dtype=ID_COLUMNS, parse_dates=["ordered_at"])
    orders = orders.drop_duplicates("order_id")
    return orders.assign(
        amount=orders["unit_price"] * orders["quantity"] * (1 - orders["discount_rate"])
    )


def valid_orders() -> pd.DataFrame:
    """キャンセルを除いた有効注文（57,869 件）。購買行動を語るときの母集団。"""
    orders = load_orders()
    return orders.loc[orders["is_canceled"] == 0]


def load_customers() -> pd.DataFrame:
    """顧客マスタ（8,000 行）。region には 392 件の欠損がある。"""
    return pd.read_csv(
        DATA_DIR / "customers.csv",
        dtype={"customer_id": "str"},
        parse_dates=["signup_date"],
        usecols=["customer_id", "signup_date", "birth_year", "region", "channel"],
    )


def load_books() -> pd.DataFrame:
    """書籍マスタからカテゴリだけを取り出す（買ったカテゴリ数を数えるため）。"""
    return pd.read_csv(DATA_DIR / "books.csv", dtype={"book_id": "str"}, usecols=["book_id", "category"])


# ------------------------------------------------------------------
# 期間を切って表を作る
# ------------------------------------------------------------------
@lru_cache(maxsize=None)
def repeat_table() -> pd.DataFrame:
    """cutoff までの履歴で特徴量を作り、その後 90 日の再購入を目的変数にする。

    3 つの期間を混ぜないことが要点です。
    - 観測期間: 〜 cutoff（2026-06-03）。**特徴量はここだけから作る**
    - 予測期間: LABEL_START（2026-06-04）〜 AS_OF（2026-09-01）。**目的変数だけをここから作る**
    - 対象顧客: cutoff までに有効注文が 1 件以上ある顧客
    """
    valid = valid_orders()
    past = valid.loc[valid["ordered_at"] <= CUTOFF].merge(load_books(), on="book_id", how="left")
    future = valid.loc[(valid["ordered_at"] >= LABEL_START) & (valid["ordered_at"] <= AS_OF)]

    agg = past.groupby("customer_id", as_index=False).agg(
        n_orders=("order_id", "count"),
        total_amount=("amount", "sum"),
        mean_amount=("amount", "mean"),
        mean_discount=("discount_rate", "mean"),
        last_order=("ordered_at", "max"),
        first_order=("ordered_at", "min"),
        n_categories=("category", "nunique"),
    )
    agg["recency"] = (CUTOFF - agg["last_order"]).dt.days
    agg["tenure"] = (CUTOFF - agg["first_order"]).dt.days

    df = agg.merge(load_customers(), on="customer_id", how="left")
    df["age"] = 2026 - df["birth_year"]  # 基準日固定なので毎年変わらない（本書の規約）
    df["days_since_signup"] = (CUTOFF - df["signup_date"]).dt.days

    counts = future.groupby("customer_id").size()
    df[LEAK_COLUMN] = df["customer_id"].map(counts).fillna(0).astype("int64")
    df[TARGET] = (df[LEAK_COLUMN] > 0).astype("int64")
    return df


def feature_list(leak: bool = False) -> list[str]:
    """モデルに渡す列。`leak=True` のときだけ予測期間の注文数を足す（課題5 専用）。"""
    numeric = NUMERIC + [LEAK_COLUMN] if leak else list(NUMERIC)
    return numeric + CATEGORICAL


def numeric_list(leak: bool = False) -> list[str]:
    """前処理の数値側に渡す列。"""
    return NUMERIC + [LEAK_COLUMN] if leak else list(NUMERIC)


# ------------------------------------------------------------------
# Pipeline（セッション25 の最終形）
# ------------------------------------------------------------------
def build_estimator(kind: str):
    """モデル本体だけを作る。`random_state` は必ず指定する（本書の規約）。"""
    if kind == "logistic":
        return LogisticRegression(max_iter=MAX_ITER)
    if kind == "lgbm":
        return LGBMClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, verbose=-1)
    raise ValueError(f"知らないモデルの名前です: {kind!r}（使えるのは {MODELS}）")


def build_pipeline(kind: str = "lgbm", leak: bool = False) -> Pipeline:
    """前処理とモデルを 1 つのオブジェクトにまとめる。

    欠損を埋める → 標準化する → モデルに渡す、までを 1 本にしておくと、
    交差検証でも 1 件推論でも **同じ手順が必ず走る**ようになります。
    """
    numeric_steps = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )
    categorical_steps = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    return Pipeline(
        [
            (
                "pre",
                ColumnTransformer(
                    [
                        ("num", numeric_steps, numeric_list(leak)),
                        ("cat", categorical_steps, CATEGORICAL),
                    ]
                ),
            ),
            ("model", build_estimator(kind)),
        ]
    )


@lru_cache(maxsize=None)
def _dataset(leak: bool) -> dict:
    df = repeat_table()
    columns = feature_list(leak)
    X, y = df[columns], df[TARGET]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    return {
        "df": df,
        "columns": columns,
        "X": X,
        "y": y,
        "X_train": X_train,
        "X_test": X_test,
        "y_train": y_train,
        "y_test": y_test,
        "n_customers": int(len(df)),
        "n_positive": int(y.sum()),
        "positive_rate": float(y.mean()),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "n_positive_test": int(y_test.sum()),
        "positive_rate_test": float(y_test.mean()),
    }


def dataset(leak: bool = False) -> dict:
    """期間を切った表を分割してまとめて返す（1 プロセスで 1 回だけ作る）。"""
    return _dataset(bool(leak))


@lru_cache(maxsize=None)
def _fitted(kind: str, leak: bool) -> dict:
    data = dataset(leak)
    model = build_pipeline(kind, leak).fit(data["X_train"], data["y_train"])
    proba = model.predict_proba(data["X_test"])[:, 1]
    y_test = data["y_test"]
    return {
        "kind": kind,
        "label": MODEL_LABELS[kind],
        "leak": leak,
        "model": model,
        "proba": proba,
        "roc_auc": float(roc_auc_score(y_test, proba)),
        "pr_auc": float(average_precision_score(y_test, proba)),
        "accuracy": float(accuracy_score(y_test, (proba >= 0.5).astype("int64"))),
        "mean_proba": float(proba.mean()),
    }


def fitted(kind: str = "lgbm", leak: bool = False) -> dict:
    """Pipeline を学習し、評価データの確率と指標をまとめて返す。"""
    return _fitted(kind, bool(leak))


# ------------------------------------------------------------------
# ベースラインと指標
# ------------------------------------------------------------------
def baseline() -> dict:
    """多数クラスをそのまま答える予測。**モデルを学習する前に**置いておく。"""
    data = dataset()
    y_test = data["y_test"]
    major = int(data["y_train"].mode().iloc[0])
    predicted = np.full(len(y_test), major, dtype="int64")
    constant = np.full(len(y_test), 0.5)  # 順位が付かないので ROC AUC は 0.5 になる
    return {
        "major": major,
        "accuracy": float(accuracy_score(y_test, predicted)),
        "roc_auc": float(roc_auc_score(y_test, constant)),
        "pr_auc": float(average_precision_score(y_test, constant)),
        "positive_rate_test": float(y_test.mean()),
    }


def threshold_table(proba, y_test, thresholds: tuple[float, ...] = THRESHOLDS) -> pd.DataFrame:
    """閾値ごとに「何人に送るか」「何人当たるか」を数える。

    適合率・再現率だけでなく **件数**を必ず並べます。件数が無いと業務の人と話せません。
    """
    rows = []
    for threshold in thresholds:
        predicted = (np.asarray(proba) >= threshold).astype("int64")
        tn, fp, fn, tp = confusion_matrix(y_test, predicted, labels=[0, 1]).ravel()
        n_sent = int(fp + tp)
        rows.append(
            {
                "threshold": float(threshold),
                "precision": float(precision_score(y_test, predicted, zero_division=0)),
                "recall": float(recall_score(y_test, predicted, zero_division=0)),
                "f1": float(f1_score(y_test, predicted, zero_division=0)),
                "n_sent": n_sent,
                "tp": int(tp),
                "fp": int(fp),
                "fn": int(fn),
                "tn": int(tn),
                "coupons_per_hit": float(n_sent / tp) if tp else float("nan"),
                "cost_yen": int(n_sent * COUPON_COST_YEN),
                "within_budget": bool(n_sent <= CAPACITY),
            }
        )
    return pd.DataFrame(rows)


def capacity_plan(table: pd.DataFrame | None = None) -> dict:
    """予算に収まる閾値のうち、いちばん多く捕まえられるものを選ぶ。

    「F1 が最大の閾値」ではありません。**送れる通数が上限**だからです。
    """
    data = dataset()
    table = threshold_table(fitted("lgbm")["proba"], data["y_test"]) if table is None else table
    affordable = table.loc[table["within_budget"]]
    if affordable.empty:
        raise ValueError("どの閾値も予算に収まりません（閾値の候補を上げてください）")
    chosen = affordable.loc[affordable["recall"].idxmax()]
    best_f1 = table.loc[table["f1"].idxmax()]
    random_hits = int(round(CAPACITY * data["positive_rate_test"]))
    return {
        "capacity": int(CAPACITY),
        "budget_yen": int(MONTHLY_BUDGET_YEN),
        "coupon_cost_yen": int(COUPON_COST_YEN),
        "threshold": float(chosen["threshold"]),
        "precision": float(chosen["precision"]),
        "recall": float(chosen["recall"]),
        "n_sent": int(chosen["n_sent"]),
        "tp": int(chosen["tp"]),
        "fp": int(chosen["fp"]),
        "fn": int(chosen["fn"]),
        "cost_yen": int(chosen["cost_yen"]),
        "left_yen": int(MONTHLY_BUDGET_YEN - chosen["cost_yen"]),
        "spare": int(CAPACITY - chosen["n_sent"]),
        "best_f1_threshold": float(best_f1["threshold"]),
        "best_f1": float(best_f1["f1"]),
        "best_f1_n_sent": int(best_f1["n_sent"]),
        "best_f1_over": int(best_f1["n_sent"] - CAPACITY),
        "random_hits": random_hits,
        "beats_random": bool(int(chosen["tp"]) > random_hits),
    }


@lru_cache(maxsize=None)
def _cv_scores(kind: str, leak: bool) -> dict:
    data = dataset(leak)
    cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    scores = cross_val_score(build_pipeline(kind, leak), data["X"], data["y"], cv=cv, scoring=SCORING)
    return {
        "kind": kind,
        "label": MODEL_LABELS[kind],
        "scores": [float(value) for value in scores],
        "mean": float(scores.mean()),
        "std": float(scores.std()),  # ddof=0。この 5 分割そのもののばらつき
        "min": float(scores.min()),
        "max": float(scores.max()),
    }


def cv_scores(kind: str = "lgbm", leak: bool = False) -> dict:
    """層化 5 分割の交差検証。分割前の全データに対して行う（本書の規約）。"""
    return _cv_scores(kind, bool(leak))


# ------------------------------------------------------------------
# リークの点検
# ------------------------------------------------------------------
LEAK_CHECKLIST = (
    "その列は、予測する瞬間に手に入るか（cutoff より後の値を使っていないか）",
    "その列の計算に、当てたい結果そのものが入っていないか",
    "集約して作った列は、cutoff 以前だけを集めたものになっているか",
    "前処理（欠損補完・標準化・特徴量選択）を、分割の前にやっていないか",
    "指標が急に良くなったとき、手を止めて上の 4 つを見直したか",
)


def leak_audit() -> dict:
    """予測期間の注文数を特徴量に足すと何が起きるかを測る。

    ここで見たいのは「性能が上がること」ではなく、**エラーが 1 つも出ないこと**です。
    リークは壊れたコードではなく、正しく動くコードとして現れます。
    """
    clean = fitted("lgbm", leak=False)
    leaked = fitted("lgbm", leak=True)
    df = repeat_table()
    zero = df.loc[df[LEAK_COLUMN] == 0]
    return {
        "clean_roc_auc": clean["roc_auc"],
        "clean_pr_auc": clean["pr_auc"],
        "leaked_roc_auc": leaked["roc_auc"],
        "leaked_pr_auc": leaked["pr_auc"],
        "gap": leaked["roc_auc"] - clean["roc_auc"],
        "n_features_clean": len(feature_list(False)),
        "n_features_leaked": len(feature_list(True)),
        "zero_rows": int(len(zero)),
        "zero_positive_rate": float(zero[TARGET].mean()),
        "is_target_itself": bool(
            ((df[LEAK_COLUMN].to_numpy() > 0) == df[TARGET].to_numpy().astype("bool")).all()
        ),
        "checklist": list(LEAK_CHECKLIST),
    }


# ------------------------------------------------------------------
# SHAP による説明
# ------------------------------------------------------------------
def sigmoid(x: float) -> float:
    """対数オッズを 0〜1 の確率に変換する（セッション17 で使ったものと同じ）。"""
    return float(1.0 / (1.0 + np.exp(-x)))


@lru_cache(maxsize=None)
def shap_bundle() -> dict:
    """LightGBM の Pipeline から木の部分だけを取り出して SHAP を計算する。

    `TreeExplainer` に渡すのは **前処理を通したあとの行列**です。Pipeline まるごとは
    渡せないので、`named_steps` で 2 つに分けて考えます。警告は隠さずに捕まえて返します。
    """
    bundle = fitted("lgbm")
    data = dataset()
    pre = bundle["model"].named_steps["pre"]
    tree = bundle["model"].named_steps["model"]
    matrix = np.asarray(pre.transform(data["X_test"]))
    names = [str(name) for name in pre.get_feature_names_out()]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")  # filterwarnings("ignore") で消してはいけない
        explainer = shap.TreeExplainer(tree)
        values = np.asarray(explainer.shap_values(matrix))

    base = np.asarray(explainer.expected_value)
    return {
        "tree": tree,
        "matrix": matrix,
        "names": names,
        "values": values,
        "base": float(base.ravel()[0]),
        "base_dtype": str(base.dtype),
        "base_shape": base.shape,
        # 警告は全文が長いので、冒頭 79 文字だけを取り出しておく
        "warnings": [
            f"{w.category.__name__}: {str(w.message)[:79]} ..."
            for w in caught
            if "TreeExplainer" in str(w.message)
        ],
    }


def shap_local(row: int = 0) -> pd.DataFrame:
    """1 人ぶんの予測を、特徴量ごとの寄与に分解して並べる（局所的説明）。"""
    bundle = shap_bundle()
    raw = dataset()["X_test"].iloc[row]
    shown = []
    for name, transformed in zip(bundle["names"], bundle["matrix"][row]):
        column = name.split("__", 1)[1]
        shown.append(f"{raw[column]:,.1f}" if column in NUMERIC else f"{transformed:.0f}")
    table = pd.DataFrame({"feature": bundle["names"], "value": shown, "shap": bundle["values"][row]})
    order = table["shap"].abs().sort_values(ascending=False).index
    return table.reindex(order).reset_index(drop=True)


def shap_additivity(row: int = 0) -> dict:
    """加法性（SHAP 値の合計 + 基準値 = 対数オッズ）が成り立つことを確かめる。"""
    bundle = shap_bundle()
    total = float(bundle["values"][row].sum())
    logit = total + bundle["base"]
    from_model = float(bundle["tree"].predict_proba(bundle["matrix"][[row]])[0, 1])
    return {
        "total": total,
        "base": bundle["base"],
        "logit": logit,
        "proba_from_shap": sigmoid(logit),
        "proba_from_model": from_model,
        "matches": bool(abs(sigmoid(logit) - from_model) < 1e-6),
    }


def shap_global() -> pd.DataFrame:
    """SHAP 値の平均絶対値で「全体としてどの列が効いたか」を並べる。"""
    bundle = shap_bundle()
    table = pd.DataFrame(
        {"feature": bundle["names"], "mean_abs": np.abs(bundle["values"]).mean(axis=0)}
    )
    return table.sort_values("mean_abs", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------
# 保存と 1 件推論
# ------------------------------------------------------------------
def current_versions() -> dict[str, str]:
    """いま動いているライブラリのバージョン。保存時と読み込み時に同じ関数を使う。"""
    return {
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "scikit-learn": sklearn.__version__,
        "lightgbm": lightgbm.__version__,
        "joblib": joblib.__version__,
    }


def build_meta(kind: str = "lgbm") -> dict:
    """モデルといっしょに保存する「説明書」。

    半年後の自分が読んで、**何を予測するモデルでどの列をどの順に渡すか**が
    分かる情報だけを入れます。
    """
    data = dataset()
    bundle = fitted(kind)
    plan = capacity_plan()
    return {
        "model_name": "repeat_purchase",
        "model_kind": kind,
        "cutoff": str(CUTOFF.date()),
        "as_of": str(AS_OF.date()),
        "horizon_days": HORIZON_DAYS,
        "target": TARGET,
        "numeric": list(NUMERIC),
        "categorical": list(CATEGORICAL),
        "nullable": list(NULLABLE),
        "n_train": data["n_train"],
        "n_test": data["n_test"],
        "positive_rate": data["positive_rate"],
        "threshold": plan["threshold"],
        "precision_at_threshold": plan["precision"],
        "recall_at_threshold": plan["recall"],
        "roc_auc_test": bundle["roc_auc"],
        "pr_auc_test": bundle["pr_auc"],
        "versions": current_versions(),
    }


def save_model(model: Pipeline, meta: dict, path: Path = MODEL_PATH) -> dict:
    """Pipeline とメタデータを **1 つのタプル**にして保存する。

    モデルだけ保存すると、「どのバージョンで作ったか」を確かめる手がかりが
    永久に失われます。
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump((model, meta), path)
    size = path.stat().st_size
    return {"path": path, "name": path.name, "bytes": int(size), "kb": size / 1024}


def compare_versions(meta: dict) -> list[dict[str, object]]:
    """保存時のバージョンと、いまのバージョンを 1 項目ずつ突き合わせる。"""
    saved = dict(meta.get("versions", {}))
    rows = []
    for name, current in current_versions().items():
        recorded = saved.get(name, "（記録なし）")
        rows.append({"name": name, "saved": recorded, "current": current, "same": bool(recorded == current)})
    return rows


def load_model(path: Path = MODEL_PATH, strict: bool = True) -> tuple[Pipeline, dict, list[dict]]:
    """保存したファイルを読み込み、バージョンを照合してから返す。

    セキュリティ上の注意: `joblib.load` は内部で pickle を復元するため、
    **ファイルに書かれた処理がそのまま実行されます**。読み込むのは
    「自分が save_model で作ったファイルだけ」にしてください。
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"モデルのファイルがありません: {path}")
    model, meta = joblib.load(path)  # 自分で作ったファイルだけを読む（上の注意を参照）
    differences = [row for row in compare_versions(meta) if not row["same"]]
    if differences and strict:
        detail = " / ".join(
            f"{row['name']}: 保存時 {row['saved']} → 現在 {row['current']}" for row in differences
        )
        raise ValueError(f"保存時とライブラリのバージョンが違います（{detail}）")
    return model, meta, differences


def ensure_model(path: Path = MODEL_PATH) -> tuple[Pipeline, dict, list[dict]]:
    """保存済みのファイルが無ければ学習して保存し、読み込んで返す。"""
    if not Path(path).exists():
        save_model(fitted("lgbm")["model"], build_meta("lgbm"), path)
    return load_model(path)


@lru_cache(maxsize=None)
def allowed_levels() -> dict[str, tuple[str, ...]]:
    """カテゴリ列が学習時に持っていた水準。入力検証で「未知の値」を弾くのに使う。"""
    train = dataset()["X_train"]
    return {name: tuple(sorted(train[name].dropna().unique().tolist())) for name in CATEGORICAL}


def _is_missing(value: object) -> bool:
    """None と NaN のどちらも「欠損」として扱う（NaN は自分自身と等しくない）。"""
    if value is None:
        return True
    if isinstance(value, (float, np.floating)):
        return bool(np.isnan(value))
    return False


def _plain(value: object) -> object:
    """numpy の値を Python の int / float / str に直す（JSON で来た値と同じ形にする）。"""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if _is_missing(value):
        return None
    return value


def sample_record(row: int = 0) -> dict:
    """1 件推論の題材にする 1 行を dict にして返す（評価データの `row` 行目）。"""
    return {name: _plain(value) for name, value in dataset()["X_test"].iloc[row].items()}


def validate_record(record: object) -> dict:
    """1 件ぶんの入力を検証し、モデルに渡せる形に直して返す。

    落とす順番を「列がそろっているか → 欠損 → 型 → 範囲 → 未知の水準」に固定してあります。
    """
    if not isinstance(record, dict):
        raise ValueError(f"入力は dict で渡してください（受け取った型: {type(record).__name__}）")

    missing_columns = [name for name in FEATURES if name not in record]
    if missing_columns:
        raise ValueError(f"必須の列が足りません: {missing_columns}")

    clean: dict[str, object] = {}
    for name in NUMERIC:
        value = record[name]
        if _is_missing(value):
            raise ValueError(f"{name} は欠損を受け付けません（学習時に欠損がなかった列です）")
        if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
            raise ValueError(f"{name} は数値で渡してください（受け取った型: {type(value).__name__}）")
        number = float(value)
        low, high = NUMERIC_RANGES[name]
        if not low <= number <= high:
            raise ValueError(f"{name} は {low:,.1f}〜{high:,.1f} の範囲で渡してください（受け取った値: {number:,.1f}）")
        clean[name] = number

    levels = allowed_levels()
    for name in CATEGORICAL:
        value = record[name]
        if _is_missing(value):
            if name not in NULLABLE:
                raise ValueError(f"{name} は欠損を受け付けません（学習時に欠損がなかった列です）")
            clean[name] = np.nan  # 学習時と同じように、前処理の中で最頻値で埋められる
            continue
        if not isinstance(value, str):
            raise ValueError(f"{name} は文字列で渡してください（受け取った型: {type(value).__name__}）")
        if value not in levels[name]:
            raise ValueError(
                f"{name} に学習時になかった値が入っています: {value!r}"
                f"（使える値: {', '.join(levels[name])}）"
            )
        clean[name] = value
    return clean


def to_frame(clean: dict) -> pd.DataFrame:
    """検証済みの dict を 1 行の DataFrame にする（列の順番は学習時と同じにそろえる）。"""
    frame = pd.DataFrame([clean], columns=FEATURES)
    frame[NUMERIC] = frame[NUMERIC].astype("float64")
    for name in CATEGORICAL:
        frame[name] = frame[name].astype("object")  # 欠損を NaN のまま前処理に渡すため
    return frame


def predict_one(model: Pipeline, record: object) -> float:
    """1 件だけの推論。**検証を必ず通してから** predict_proba に渡す。"""
    return float(model.predict_proba(to_frame(validate_record(record)))[0, 1])


def record_digest(record: dict) -> str:
    """入力の要点だけを 1 行にまとめる（ログに残す用。全部の列は出さない）。"""
    return (
        f"n_orders {record['n_orders']:,} 件 / recency {record['recency']:,} 日 / "
        f"total_amount {record['total_amount']:,.1f} 円"
    )


def decide(proba: float, threshold: float = OPERATING_THRESHOLD) -> str:
    """確率を業務の判断に変える。**閾値を渡さないと決まらない**ことを形で示す。"""
    return "クーポンを送る" if proba >= threshold else "送らない"


# ------------------------------------------------------------------
# 監視（PSI と監視計画）
# ------------------------------------------------------------------
def psi_edges(expected, bins: int = PSI_BINS) -> np.ndarray:
    """学習したころのデータの分位からビン境界を作り、両端を開く。"""
    quantiles = np.quantile(np.asarray(expected, dtype="float64"), np.linspace(0.0, 1.0, bins + 1))
    edges = np.unique(quantiles)
    edges[0] = -np.inf
    edges[-1] = np.inf
    return edges


def bin_shares(values, edges: np.ndarray) -> np.ndarray:
    """各ビンに入った件数の比率。0 になったビンは PSI_FLOOR でクリップする。"""
    counts, _ = np.histogram(np.asarray(values, dtype="float64"), bins=edges)
    shares = counts / counts.sum()
    return np.clip(shares, PSI_FLOOR, None)


def psi(expected, actual, bins: int = PSI_BINS) -> float:
    """PSI（Population Stability Index）。0 に近いほど分布が動いていない。"""
    edges = psi_edges(expected, bins)
    expected_shares = bin_shares(expected, edges)
    actual_shares = bin_shares(actual, edges)
    return float(np.sum((actual_shares - expected_shares) * np.log(actual_shares / expected_shares)))


def verdict(value: float) -> str:
    """PSI の慣例的な目安で判定する（0.1 未満 / 0.1〜0.25 / 0.25 以上）。"""
    if value >= PSI_ACT:
        return "要再学習"
    if value >= PSI_WATCH:
        return "注意"
    return "安定"


def drift_probe(column: str = "recency", ratios: tuple[float, ...] = DRIFT_RATIOS) -> pd.DataFrame:
    """監視の関数そのものが正しく動くかを、自分のデータをずらして確かめる。

    まだ運用していないので「本当のドリフト」は観測できません。そこで
    **同じ分布どうしなら 0 になること**と**ずらすほど大きくなること**を確認します。
    """
    values = repeat_table()[column].to_numpy(dtype="float64")
    rows = []
    for ratio in ratios:
        value = psi(values, values * ratio)
        rows.append({"ratio": float(ratio), "psi": value, "judgement": verdict(value)})
    return pd.DataFrame(rows)


def monitoring_plan() -> list[dict[str, object]]:
    """運用に載せる前に決めておく監視の項目。**閾値を先に書く**のが要点。"""
    data = dataset()
    return [
        {
            "name": "入力の分布（PSI）",
            "rule": f"数値 {len(NUMERIC)} 列の PSI の最大が {PSI_ACT} 以上",
            "cycle": "月 1 回",
            "action": "ずれた列を特定し、再学習を検討する",
        },
        {
            "name": "月次の性能（ROC AUC）",
            "rule": "「平均 − 2σ」を 2 か月続けて下回る",
            "cycle": "月 1 回（正解が出そろう 90 日後）",
            "action": "原因を調べてから再学習する",
        },
        {
            "name": "実際の再購入率",
            "rule": f"学習時の {data['positive_rate']:.4f} から ±0.05 を超える",
            "cycle": "月 1 回",
            "action": "閾値と予算の前提を作り直す",
        },
        {
            "name": "予測確率の平均",
            "rule": "実際の再購入率から 0.05 以上離れる",
            "cycle": "月 1 回",
            "action": "キャリブレーションを確認する",
        },
        {
            "name": "時間の経過",
            "rule": f"cutoff（{CUTOFF.date()}）から 180 日",
            "cycle": "日次で判定",
            "action": "無条件で cutoff を進めて作り直す",
        },
    ]


# ------------------------------------------------------------------
# 図
# ------------------------------------------------------------------
def save_figure(fig, name: str) -> str:
    """図を outputs/ に保存してファイル名を返す（MPLBACKEND=Agg なので show は使わない）。"""
    import matplotlib.pyplot as plt  # 図を描くスクリプトだけが必要とするので関数の中で読み込む

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return path.name


def pr_curve(kind: str = "lgbm") -> tuple[np.ndarray, np.ndarray]:
    """PR 曲線の座標（適合率と再現率）を返す。"""
    data = dataset()
    precision, recall, _ = precision_recall_curve(data["y_test"], fitted(kind)["proba"])
    return precision, recall


def sweep(kind: str = "lgbm", step: float = 0.05) -> pd.DataFrame:
    """閾値を細かく動かして、送る通数と適合率・再現率の動きを並べる。"""
    data = dataset()
    grid = tuple(round(value, 2) for value in np.arange(step, 1.0, step))
    return threshold_table(fitted(kind)["proba"], data["y_test"], grid)
