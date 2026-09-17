"""セッション 28 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import build_meta, predict_one, psi_table, repeat_bundle, save_model

    bundle = repeat_bundle()                      # 再購入予測の Pipeline（同じプロセスでは再学習しない）
    info = save_model(bundle["model"], build_meta(bundle))
    proba = predict_one(bundle["model"], sample_record())

この章では 2 つの題材を使い分けます。

- **保存と推論**: 再購入予測（顧客 1 人につき 1 行。最終プロジェクトと同じ題材）
- **監視**: キャンセル予測と注文の分布（注文 1 件につき 1 行。日付があるので時間で切れる）

このディレクトリのスクリプトは、他のセッションのディレクトリを一切参照しません
（読者がこの章のファイルだけを作って実行できるようにするためです）。
"""

from __future__ import annotations

import platform
from functools import lru_cache
from pathlib import Path

import joblib
import lightgbm
import numpy as np
import pandas as pd
import sklearn
from lightgbm import LGBMClassifier
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# ------------------------------------------------------------------
# 再購入予測（保存・読み込み・1 件推論の題材）
# ------------------------------------------------------------------
AS_OF = pd.Timestamp("2026-09-01")                 # データの基準日（本書共通）
HORIZON_DAYS = 90                                  # 「この先 90 日で再購入するか」を当てる
CUTOFF = AS_OF - pd.Timedelta(days=HORIZON_DAYS)   # 2026-06-03。特徴量はここまでの履歴だけで作る
LABEL_START = CUTOFF + pd.Timedelta(days=1)        # 2026-06-04。ここから基準日までの再購入を当てる

TEST_SIZE = 0.25
RANDOM_STATE = 42
N_ESTIMATORS = 200

NUMERIC = [
    "n_orders",          # cutoff までの有効注文の件数
    "total_amount",      # 同じ期間の売上合計（行ごとに丸めない）
    "mean_amount",       # 1 件あたりの平均
    "mean_discount",     # 平均の値引き率
    "recency",           # cutoff − 最終購入日（日）
    "tenure",            # cutoff − 初回購入日（日）
    "n_categories",      # 買ったカテゴリの数
    "age",               # 2026 − birth_year
    "days_since_signup",  # cutoff − 登録日（日）
]
CATEGORICAL = ["channel", "region"]
FEATURES = NUMERIC + CATEGORICAL
TARGET = "repeat"

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

MODEL_PATH = OUT_DIR / "s28_repeat_model.joblib"
OLD_MODEL_PATH = OUT_DIR / "s28_repeat_model_old.joblib"  # 照合を試すための「古い記録」つきファイル

# ------------------------------------------------------------------
# 監視（データドリフトと性能の劣化）
# ------------------------------------------------------------------
SPLIT_DATE = pd.Timestamp("2025-09-01")  # ここより前を「学習したころ」、ここから後を「いま」とする

PSI_COLUMNS = ["unit_price", "quantity", "discount_rate", "amount"]
PSI_BINS = 10          # 前半データの 10 分位をビン境界にする
PSI_FLOOR = 1e-6       # ゼロ割り・log(0) を避けるために比率をこの値でクリップする
PSI_WATCH = 0.10       # 慣例的な目安: 0.1 未満は安定
PSI_ACT = 0.25         # 0.25 以上は要再学習

DRIFT_RATIOS = (1.00, 1.05, 1.20, 1.50)  # 後半の単価を何倍にするか（1.00 は手を加えない）
QUANTITY_FRACTION = 0.30                 # 後半の何割の注文の数量を差し替えるか
QUANTITY_VALUE = 5                       # 差し替える数量

# キャンセル予測（セッション24 と同じ特徴量。性能の劣化を測る題材）
CANCEL_NUMERIC = ["unit_price", "quantity", "discount_rate", "days_since_signup"]
CANCEL_CATEGORICAL = ["channel"]
CANCEL_FEATURES = CANCEL_NUMERIC + CANCEL_CATEGORICAL

MONITOR_MONTHS = 6        # 月次の性能を追う期間（直近何か月ぶんを見るか）
SLOPE_LIMIT = -0.005      # 1 か月あたりこれより急に下がっていたら「下降トレンド」とみなす
BAND_SIGMA = 2.0          # 平均 ± 何σを「ばらつきの範囲」とするか
RETRAIN_MAX_DAYS = 180    # 学習データの最終日からこれ以上たったら再学習する
RETRAIN_GROWTH = 2.0      # 学習時の何倍までデータが増えたら再学習するか

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


def valid_orders(orders: pd.DataFrame | None = None) -> pd.DataFrame:
    """キャンセルを除いた有効注文（57,869 件）。購買行動を語るときの母集団。"""
    frame = load_orders() if orders is None else orders
    return frame.loc[frame["is_canceled"] == 0]


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
# 再購入予測のデータとモデル
# ------------------------------------------------------------------
def build_repeat_table() -> pd.DataFrame:
    """cutoff までの履歴で特徴量を作り、その後 90 日の再購入を目的変数にする。

    セッション14 で学んだ「期間を切って特徴量を作る」をそのまま使います。
    **cutoff より後のデータを特徴量に混ぜないこと**がこの表のいちばん大事な約束です。
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
    df[TARGET] = df["customer_id"].isin(future["customer_id"]).astype("int64")
    return df


def build_pipeline() -> Pipeline:
    """前処理と LightGBM を 1 つのオブジェクトにまとめる（セッション25 の最終形）。

    保存するのはこの Pipeline **まるごと**です。前処理だけ別に保存すると、
    推論する側で同じ手順を書き直すことになり、必ずどこかでずれます。
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
                        ("num", numeric_steps, NUMERIC),
                        ("cat", categorical_steps, CATEGORICAL),
                    ]
                ),
            ),
            ("model", LGBMClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, verbose=-1)),
        ]
    )


@lru_cache(maxsize=None)
def repeat_bundle() -> dict:
    """再購入予測の表を作り、分割して学習したものをまとめて返す（1 プロセスで 1 回だけ学習）。"""
    df = build_repeat_table()
    X, y = df[FEATURES], df[TARGET]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    model = build_pipeline().fit(X_train, y_train)
    proba = model.predict_proba(X_test)[:, 1]
    return {
        "df": df,
        "X": X,
        "y": y,
        "X_train": X_train,
        "X_test": X_test,
        "y_train": y_train,
        "y_test": y_test,
        "model": model,
        "proba": proba,
        "roc_auc": float(roc_auc_score(y_test, proba)),
        "pr_auc": float(average_precision_score(y_test, proba)),
    }


@lru_cache(maxsize=None)
def allowed_levels() -> dict[str, tuple[str, ...]]:
    """カテゴリ列が学習時に持っていた水準。入力検証で「未知の値」を弾くのに使う。"""
    bundle = repeat_bundle()
    return {
        name: tuple(sorted(bundle["X_train"][name].dropna().unique().tolist()))
        for name in CATEGORICAL
    }


# ------------------------------------------------------------------
# 保存と読み込み
# ------------------------------------------------------------------
def current_versions() -> dict[str, str]:
    """いま動いているライブラリのバージョンをまとめる。保存時と読み込み時に同じ関数を使う。"""
    return {
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "scikit-learn": sklearn.__version__,
        "lightgbm": lightgbm.__version__,
        "joblib": joblib.__version__,
    }


def build_meta(bundle: dict | None = None) -> dict:
    """モデルといっしょに保存する「説明書」。

    ここに入れる情報は「あとから自分を助けるもの」だけに絞ります。
    - どのバージョンで作ったか（**これが無いと読み込み時に何も確かめられない**）
    - どの期間のデータで、何を予測するモデルか
    - どの列をどの順で受け取るか
    - 保存した時点の性能（再学習したモデルと比べる起点になる）
    """
    bundle = repeat_bundle() if bundle is None else bundle
    return {
        "model_name": "repeat_purchase",
        "cutoff": str(CUTOFF.date()),
        "as_of": str(AS_OF.date()),
        "horizon_days": HORIZON_DAYS,
        "target": TARGET,
        "numeric": list(NUMERIC),
        "categorical": list(CATEGORICAL),
        "nullable": list(NULLABLE),
        "n_train": int(len(bundle["X_train"])),
        "n_test": int(len(bundle["X_test"])),
        "positive_rate": float(bundle["y"].mean()),
        "roc_auc_test": bundle["roc_auc"],
        "pr_auc_test": bundle["pr_auc"],
        "versions": current_versions(),
    }


def save_model(model: Pipeline, meta: dict, path: Path = MODEL_PATH) -> dict:
    """Pipeline とメタデータを **1 つのタプル**にして保存する。

    `joblib.dump(model, path)` のようにモデルだけ保存すると、
    「どのバージョンで作ったか」を確かめる手がかりが永久に失われます。
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump((model, meta), path)
    size = path.stat().st_size
    return {"path": path, "name": path.name, "bytes": int(size), "kb": size / 1024}


def compare_versions(meta: dict) -> list[dict[str, object]]:
    """保存時のバージョンと、いまのバージョンを 1 項目ずつ突き合わせる。"""
    saved = dict(meta.get("versions", {}))
    now = current_versions()
    rows = []
    for name, current in now.items():
        recorded = saved.get(name, "（記録なし）")
        rows.append(
            {
                "name": name,
                "saved": recorded,
                "current": current,
                "same": bool(recorded == current),
            }
        )
    return rows


def load_model(path: Path = MODEL_PATH, strict: bool = True) -> tuple[Pipeline, dict, list[dict]]:
    """保存したファイルを読み込み、バージョンを照合してから返す。

    `strict=True` なら 1 つでも違えば `ValueError` で止めます。黙って動かして
    「なぜか予測がおかしい」と悩むより、読み込みの時点で落ちたほうが安全です。

    セキュリティ上の注意: `joblib.load` は内部で pickle を復元するため、
    **ファイルに書かれた処理がそのまま実行されます**。読み込むのは
    「自分が save_model で作ったファイルだけ」にしてください（ここでは
    同じスクリプトが outputs/ に書いたファイルしか読みません）。
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
    """保存済みのファイルが無ければ学習して保存し、読み込んで返す。

    この章のスクリプトは、どれから実行しても動くようにしてあります。
    """
    if not Path(path).exists():
        bundle = repeat_bundle()
        save_model(bundle["model"], build_meta(bundle), path)
    return load_model(path)


def tamper_versions(meta: dict, **overrides: str) -> dict:
    """バージョンの記録だけを書き換えたメタデータを作る（照合が働くか試すため）。"""
    return {**meta, "versions": {**meta["versions"], **overrides}}


# ------------------------------------------------------------------
# 1 件だけの推論と入力の検証
# ------------------------------------------------------------------
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
    """1 件推論の題材にする 1 行を dict にして返す（評価データの `row` 行目）。

    実務では Web フォームや API のリクエストから来る dict を想定します。
    """
    bundle = repeat_bundle()
    return {name: _plain(value) for name, value in bundle["X_test"].iloc[row].items()}


def validate_record(record: object) -> dict:
    """1 件ぶんの入力を検証し、モデルに渡せる形に直して返す。

    落とす順番を「列がそろっているか → 欠損 → 型 → 範囲 → 未知の水準」に固定してあります。
    順番が決まっていれば、エラーメッセージを見ただけでどこで落ちたか分かります。
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


def unknown_keys(record: dict) -> list[str]:
    """モデルが使わない余分なキー。捨てても動くが、ログに残すと取り違えに気づける。"""
    return [name for name in record if name not in FEATURES]


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


# ------------------------------------------------------------------
# データドリフトの監視（PSI）
# ------------------------------------------------------------------
@lru_cache(maxsize=None)
def halves() -> dict:
    """注文を「前半（〜2025-08）」と「後半（2025-09〜）」に分ける。

    `*_all` はキャンセルも含む全件（キャンセル率を見るため）、
    `before` / `after` は有効注文だけ（分布を比べるため）です。
    """
    orders = load_orders()
    before_all = orders.loc[orders["ordered_at"] < SPLIT_DATE]
    after_all = orders.loc[orders["ordered_at"] >= SPLIT_DATE]
    return {
        "before_all": before_all,
        "after_all": after_all,
        "before": before_all.loc[before_all["is_canceled"] == 0],
        "after": after_all.loc[after_all["is_canceled"] == 0],
    }


def psi_edges(expected, bins: int = PSI_BINS) -> np.ndarray:
    """学習したころのデータ（expected）の分位からビン境界を作り、両端を開く。

    同じ値が多い列（`quantity` など）では分位が重なるので `np.unique` で 1 本にします。
    重なったままだと幅 0 のビンができて、件数の数え方が壊れます。
    """
    quantiles = np.quantile(np.asarray(expected, dtype="float64"), np.linspace(0.0, 1.0, bins + 1))
    edges = np.unique(quantiles)
    edges[0] = -np.inf   # 下にはみ出した値を最初のビンに入れる
    edges[-1] = np.inf   # 上にはみ出した値を最後のビンに入れる
    return edges


def bin_shares(values, edges: np.ndarray) -> np.ndarray:
    """各ビンに入った件数の比率。0 になったビンは PSI_FLOOR でクリップする。"""
    counts, _ = np.histogram(np.asarray(values, dtype="float64"), bins=edges)
    shares = counts / counts.sum()
    return np.clip(shares, PSI_FLOOR, None)


def psi(expected, actual, bins: int = PSI_BINS) -> float:
    """PSI（Population Stability Index）。0 に近いほど分布が動いていない。

    Σ (いまの比率 − 前の比率) × log(いまの比率 / 前の比率) で、
    「どのビンにどれだけ移ったか」を 1 つの数にまとめた指標です。
    """
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


def psi_table(before: pd.DataFrame | None = None, after: pd.DataFrame | None = None) -> pd.DataFrame:
    """監視したい列をまとめて PSI にする。前半・後半の平均も並べて目で確かめる。"""
    parts = halves()
    before = parts["before"] if before is None else before
    after = parts["after"] if after is None else after
    rows = []
    for column in PSI_COLUMNS:
        value = psi(before[column], after[column])
        rows.append(
            {
                "column": column,
                "psi": value,
                "judgement": verdict(value),
                "before_mean": float(before[column].mean()),
                "after_mean": float(after[column].mean()),
            }
        )
    return pd.DataFrame(rows)


def cancel_rates() -> dict:
    """前半・後半のキャンセル率（キャンセルを含む全件が母集団）。"""
    parts = halves()
    return {
        "before_n": int(len(parts["before_all"])),
        "after_n": int(len(parts["after_all"])),
        "before_valid": int(len(parts["before"])),
        "after_valid": int(len(parts["after"])),
        "before_rate": float(parts["before_all"]["is_canceled"].mean()),
        "after_rate": float(parts["after_all"]["is_canceled"].mean()),
    }


def shift_unit_price(frame: pd.DataFrame, ratio: float) -> pd.DataFrame:
    """後半の単価を一律 ratio 倍にする（人工的なドリフトを作る）。"""
    return frame.assign(unit_price=frame["unit_price"] * ratio)


def replace_quantity(
    frame: pd.DataFrame, fraction: float = QUANTITY_FRACTION, value: int = QUANTITY_VALUE
) -> pd.DataFrame:
    """後半の一部の注文の数量を固定値に差し替える（別の形のドリフト）。"""
    picked = frame.sample(frac=fraction, random_state=RANDOM_STATE).index
    changed = frame.copy()
    changed.loc[picked, "quantity"] = value
    return changed


def unit_price_drift(ratios: tuple[float, ...] = DRIFT_RATIOS) -> pd.DataFrame:
    """単価を何倍にすると PSI がどこまで上がるかを並べる（監視の動作確認）。"""
    parts = halves()
    rows = []
    for ratio in ratios:
        shifted = shift_unit_price(parts["after"], ratio)
        value = psi(parts["before"]["unit_price"], shifted["unit_price"])
        rows.append({"ratio": float(ratio), "psi": value, "judgement": verdict(value)})
    return pd.DataFrame(rows)


def quantity_drift(
    fraction: float = QUANTITY_FRACTION, value: int = QUANTITY_VALUE
) -> dict:
    """数量を差し替えたときの PSI（差し替え前と後の両方を返す）。"""
    parts = halves()
    changed = replace_quantity(parts["after"], fraction, value)
    n_changed = int(round(len(parts["after"]) * fraction))
    plain = psi(parts["before"]["quantity"], parts["after"]["quantity"])
    injected = psi(parts["before"]["quantity"], changed["quantity"])
    return {
        "n_after": int(len(parts["after"])),
        "n_changed": n_changed,
        "value": value,
        "psi_plain": plain,
        "psi_injected": injected,
        "judgement_plain": verdict(plain),
        "judgement_injected": verdict(injected),
        "changed": changed,
    }


# ------------------------------------------------------------------
# 性能の劣化の監視（時間で分けたキャンセル予測）
# ------------------------------------------------------------------
def cancel_table() -> pd.DataFrame:
    """キャンセル予測の表（セッション24 と同じ作り方・同じ並び）。"""
    orders = load_orders()
    df = orders.merge(load_customers()[["customer_id", "channel", "signup_date"]], on="customer_id", how="left")
    df["days_since_signup"] = (df["ordered_at"] - df["signup_date"]).dt.days
    return df


def build_cancel_pipeline() -> Pipeline:
    """セッション24 と同じ前処理 + LightGBM（比較できるように条件を変えない）。"""
    return Pipeline(
        [
            (
                "pre",
                ColumnTransformer(
                    [
                        ("num", StandardScaler(), CANCEL_NUMERIC),
                        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CANCEL_CATEGORICAL),
                    ]
                ),
            ),
            ("model", LGBMClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, verbose=-1)),
        ]
    )


@lru_cache(maxsize=None)
def cancel_time_split() -> dict:
    """前半で学習し、後半で評価する（本番の順序と同じ向きに時間で分ける）。

    セッション24 は同じ時期のデータを無作為に分けていました。ここでは
    「過去で学習して未来で評価する」形にします。運用の見積もりに近いのはこちらです。
    """
    df = cancel_table()
    train = df.loc[df["ordered_at"] < SPLIT_DATE]
    test = df.loc[df["ordered_at"] >= SPLIT_DATE]
    model = build_cancel_pipeline().fit(train[CANCEL_FEATURES], train["is_canceled"])
    proba = model.predict_proba(test[CANCEL_FEATURES])[:, 1]
    return {
        "model": model,
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "train_end": train["ordered_at"].max(),
        "y_test": test["is_canceled"].to_numpy(),
        "proba": proba,
        "month": test["ordered_at"].dt.to_period("M").astype("str").to_numpy(),
        "roc_auc": float(roc_auc_score(test["is_canceled"], proba)),
        "pr_auc": float(average_precision_score(test["is_canceled"], proba)),
    }


def monthly_auc(months: int = MONITOR_MONTHS) -> pd.DataFrame:
    """月ごとの ROC AUC を並べ、直近 months か月ぶんを返す。

    片方のクラスしかない月は AUC が計算できないので飛ばします。
    """
    bundle = cancel_time_split()
    frame = pd.DataFrame({"month": bundle["month"], "y": bundle["y_test"], "proba": bundle["proba"]})
    rows = []
    for month, part in frame.groupby("month", sort=True):
        if part["y"].nunique() < 2:
            continue
        rows.append({"month": str(month), "roc_auc": float(roc_auc_score(part["y"], part["proba"]))})
    return pd.DataFrame(rows).tail(months).reset_index(drop=True)


def trend_summary(table: pd.DataFrame | None = None) -> dict:
    """月次の AUC に「下降トレンドがあるか」を決まった手続きで判定する。

    1 か月下がっただけでは判断しません。次の 3 つを順に見ます。
    1. 直近の月が「平均 − 2σ」を下回っているか
    2. 「平均 − 2σ」を 2 か月続けて下回っているか
    3. 1 か月あたりの傾きが SLOPE_LIMIT より急に下がっているか
    """
    table = monthly_auc() if table is None else table
    values = table["roc_auc"].to_numpy(dtype="float64")
    positions = np.arange(len(values), dtype="float64")
    mean = float(values.mean())
    std = float(values.std())  # ddof=0。この 6 か月そのもののばらつき
    lower = mean - BAND_SIGMA * std
    below = values < lower
    consecutive = bool(np.any(below[1:] & below[:-1]))
    slope = float(np.polyfit(positions, values, 1)[0])
    return {
        "months": [str(m) for m in table["month"]],
        "values": [float(v) for v in values],
        "mean": mean,
        "std": std,
        "lower": lower,
        "upper": mean + BAND_SIGMA * std,
        "min": float(values.min()),
        "max": float(values.max()),
        "span": float(values.max() - values.min()),
        "latest": float(values[-1]),
        "latest_below": bool(below[-1]),
        "n_below": int(below.sum()),
        "consecutive_below": consecutive,
        "slope": slope,
        "slope_declining": bool(slope < SLOPE_LIMIT),
        "declining": bool(below[-1] and consecutive) or bool(slope < SLOPE_LIMIT),
    }


# ------------------------------------------------------------------
# 再学習の判断
# ------------------------------------------------------------------
def retrain_rules() -> list[dict[str, object]]:
    """再学習するかどうかを、4 つの条件で機械的に判定する。

    「なんとなく古くなった気がする」で再学習しないために、**先に条件と閾値を書いて**
    おきます。閾値の値そのものは業務によって変わりますが、決めておくことが大事です。
    """
    drift = psi_table()
    psi_max = float(drift["psi"].max())
    psi_worst = str(drift.loc[drift["psi"].idxmax(), "column"])
    trend = trend_summary()
    split = cancel_time_split()
    elapsed_days = int((AS_OF - split["train_end"]).days)
    growth = len(load_orders()) / split["n_train"]
    return [
        {
            "name": "データドリフト",
            "rule": f"PSI の最大が {PSI_ACT} 以上",
            "actual": f"{psi_max:.4f}（{psi_worst}）",
            "fire": bool(psi_max >= PSI_ACT),
        },
        {
            "name": "性能の低下",
            "rule": f"月次 AUC が「平均 − {BAND_SIGMA:.0f}σ」を 2 か月連続で下回る",
            "actual": f"下回った月 {trend['n_below']} か月（連続は{'あり' if trend['consecutive_below'] else 'なし'}）",
            "fire": bool(trend["declining"]),
        },
        {
            "name": "時間の経過",
            "rule": f"学習データの最終日から {RETRAIN_MAX_DAYS} 日以上",
            "actual": f"{elapsed_days:,} 日",
            "fire": bool(elapsed_days >= RETRAIN_MAX_DAYS),
        },
        {
            "name": "データ量の増加",
            "rule": f"学習時の {RETRAIN_GROWTH:.1f} 倍以上",
            "actual": f"{growth:.2f} 倍",
            "fire": bool(growth >= RETRAIN_GROWTH),
        },
    ]


def should_retrain(rules: list[dict[str, object]] | None = None) -> dict:
    """1 つでも条件が発火したら再学習する、という方針にする。"""
    rules = retrain_rules() if rules is None else rules
    fired = [str(rule["name"]) for rule in rules if rule["fire"]]
    return {"retrain": bool(fired), "fired": fired, "n_fired": len(fired), "n_rules": len(rules)}


def print_rules(rules: list[dict[str, object]]) -> None:
    """判断基準を毎回同じ順・同じ形で表示する（報告に貼れる形にしておく）。

    列をそろえた表にすると日本語の幅で崩れるので、1 条件 4 行で出します。
    """
    for index, rule in enumerate(rules, start=1):
        print(f"[{index}] {rule['name']}")
        print(f"    閾値: {rule['rule']}")
        print(f"    実測: {rule['actual']}")
        print(f"    発火: {'する' if rule['fire'] else 'しない'}")


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
