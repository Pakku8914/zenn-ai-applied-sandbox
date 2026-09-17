"""セッション 27 の本文・練習問題・解答で共通して使う読み込みと道具。

同じディレクトリのスクリプトから次のように使います。

    from common import rfm_table, scaled_matrix, profile, sweep_table

    table = rfm_table()          # 有効注文のある 7,629 人 × 3 指標
    X = scaled_matrix()          # 3 指標を標準化した行列
    print(profile(4))            # k=4 のクラスタ profile

このディレクトリのスクリプトは、他のセッションのディレクトリを一切参照しません
（読者がこの章のファイルだけを作って実行できるようにするためです）。

`lru_cache` を付けた関数の返り値は**書き換えないでください**（呼び出し側で共有します）。
列を足したいときは `rfm_table().assign(...)` のようにコピーを作ってください。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"

# 乱数と探索の条件（本書の規約：random_state は必ず指定する）
RANDOM_STATE = 42
N_INIT = 10                  # 初期値を 10 通り試して、いちばん良い結果を採る
K_RANGE = (2, 3, 4, 5, 6)    # クラスタ数の候補
K_MAIN = 4                   # 本文で profile を作るクラスタ数
K_ALT = 3                    # シルエット係数が最大になるクラスタ数
SILHOUETTE_SAMPLE = 3000     # シルエット係数を測るときの標本サイズ

# 基準日はコードの中で固定する（セッション7 で決めた「今日」）
REFERENCE_DATE = pd.Timestamp("2026-09-01")
ACTIVE_DAYS = 90             # 「アクティブ顧客」の境目（本書の規約）

# 3 指標の名前と並び（この順で列を作る。PCA の係数を読むときに順番が効く）
FEATURES = ["recency", "frequency", "monetary"]
FEATURE_JA = {
    "recency": "最終購入からの日数",
    "frequency": "注文回数",
    "monetary": "売上合計（円）",
}

# ID は数値に見えても文字列として読む（先頭の 0 が落ちないようにする）
ID_COLUMNS = {"order_id": "str", "customer_id": "str", "book_id": "str"}


def load_valid_orders() -> pd.DataFrame:
    """有効注文だけの表を返す（完全重複 30 件を落とし、キャンセルを除く 57,869 行）。

    売上額は本書の規約どおり**行ごとに丸めず** `amount` 列に入れます
    （合計してから整数にします）。
    """
    orders = pd.read_csv(DATA_DIR / "orders.csv", parse_dates=["ordered_at"], dtype=ID_COLUMNS)
    deduped = orders.drop_duplicates()             # 60,061 行 → 60,031 行
    valid = deduped[deduped["is_canceled"] == 0]   # 60,031 行 → 57,869 行
    return valid.assign(amount=valid["unit_price"] * valid["quantity"] * (1 - valid["discount_rate"]))


def count_customers() -> dict[str, int]:
    """顧客数の 3 通りの数え方を並べて返す（本書の規約：必ずどれかを明示する）。"""
    customers = pd.read_csv(DATA_DIR / "customers.csv", usecols=["customer_id"])
    # ② の母集団は「完全重複を落とした 60,031 行」なので、列を絞らずに読んでから重複を落とす
    orders = pd.read_csv(DATA_DIR / "orders.csv", dtype=ID_COLUMNS)
    return {
        "all": len(customers),                                             # ① 全顧客
        "ordered": int(orders.drop_duplicates()["customer_id"].nunique()),  # ② 注文が 1 件以上
        "valid": int(load_valid_orders()["customer_id"].nunique()),        # ③ 有効注文が 1 件以上
    }


@lru_cache(maxsize=None)
def rfm_table() -> pd.DataFrame:
    """有効注文のある顧客 1 人 1 行の表（RFM 風の 3 指標）を作る。

    - recency   : 基準日 2026-09-01 から最終購入までの日数（小さいほど最近買っている）
    - frequency : 有効注文の回数
    - monetary  : 売上合計（行ごとに丸めない）

    `groupby` は既定で customer_id の昇順に並べるので、**行の並びは毎回同じ**になります。
    k-means の初期値は行の並びに依存するため、ここを並べ替えると結果が変わります。
    """
    orders = load_valid_orders()
    table = orders.groupby("customer_id").agg(
        last_order=("ordered_at", "max"),
        frequency=("order_id", "count"),
        monetary=("amount", "sum"),
    )
    table["recency"] = (REFERENCE_DATE - table["last_order"]).dt.days
    return table[FEATURES].astype({"recency": "int64", "frequency": "int64", "monetary": "float64"})


@lru_cache(maxsize=None)
def scaled_matrix() -> np.ndarray:
    """3 指標を標準化した行列（各列を平均 0・標準偏差 1 にそろえる）。

    クラスタリングは距離で仲間を決めるので、**単位の違いをそろえてから**渡します。
    標準化しないと、円の桁がそのまま距離になり monetary だけで決まってしまいます。
    """
    return StandardScaler().fit_transform(rfm_table())


def raw_matrix() -> np.ndarray:
    """標準化しない生の行列（スケーリングの有無を比べるためだけに使う）。"""
    return rfm_table().to_numpy(dtype="float64")


def fit_kmeans(X: np.ndarray, k: int) -> KMeans:
    """k-means を 1 回学習する（条件は全章共通：random_state=42・n_init=10）。"""
    return KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=N_INIT).fit(X)


@lru_cache(maxsize=None)
def labels_for(k: int, standardize: bool = True) -> tuple[int, ...]:
    """k-means のクラスタ番号をタプルで返す（同じ条件なら再学習しない）。

    タプルにしているのは `lru_cache` で共有しても書き換えられないようにするためです。
    配列として使うときは `np.asarray(labels_for(4))` としてください。
    """
    X = scaled_matrix() if standardize else raw_matrix()
    return tuple(int(label) for label in fit_kmeans(X, k).labels_)


def cluster_counts(k: int = K_MAIN, standardize: bool = True) -> list[int]:
    """クラスタ番号ごとの人数（番号の順に並べる）。"""
    labels = np.asarray(labels_for(k, standardize))
    return np.bincount(labels, minlength=k).tolist()


@lru_cache(maxsize=None)
def sweep_table() -> pd.DataFrame:
    """k=2〜6 について inertia とシルエット係数を並べた表を作る。

    - inertia    : 各点と自分のクラスタ中心との距離の二乗の合計（小さいほど密集）
    - silhouette : 「自分のクラスタの近さ」と「隣のクラスタの近さ」を比べた値（-1〜1）

    シルエット係数は全点で計算すると重いので、`sample_size=3000` で標本抽出します
    （`random_state` を固定しているので何度実行しても同じ値になります）。
    """
    X = scaled_matrix()
    rows = []
    for k in K_RANGE:
        model = fit_kmeans(X, k)
        rows.append(
            {
                "k": k,
                "inertia": float(model.inertia_),
                "silhouette": float(
                    silhouette_score(
                        X, model.labels_, sample_size=SILHOUETTE_SAMPLE, random_state=RANDOM_STATE
                    )
                ),
            }
        )
    table = pd.DataFrame(rows)
    table["inertia_drop"] = table["inertia"].diff(-1).abs()  # 次の k にしたときの減り方
    return table


def best_k_by_silhouette() -> int:
    """シルエット係数が最大になる k を返す。"""
    table = sweep_table()
    return int(table.loc[table["silhouette"].idxmax(), "k"])


def profile(k: int = K_MAIN, standardize: bool = True) -> pd.DataFrame:
    """クラスタごとの人数と 3 指標の平均（＝クラスタ profile）を作る。

    クラスタリングの結果は「番号の付いた列」でしかありません。**この表を作って
    初めて、そのクラスタがどんな人たちなのかが読めるようになります。**
    """
    table = rfm_table().assign(cluster=np.asarray(labels_for(k, standardize)))
    return table.groupby("cluster").agg(
        n=("frequency", "size"),
        recency=("recency", "mean"),
        frequency=("frequency", "mean"),
        monetary=("monetary", "mean"),
    )


# セグメントの名前は「プロファイルの数値から機械的に決める」ルールにする。
# クラスタ番号を直接書くと、条件を変えて番号が入れ替わったときに名前だけが嘘になります。
SEGMENT_RULES = "recency が最大 → 離脱顧客 / 残りを monetary の大きい順に 優良・常連・一般"


def segment_names(k: int = K_MAIN) -> dict[int, str]:
    """クラスタ profile から業務的な名前を決める（番号を直接書かない）。"""
    table = profile(k)
    churn = int(table["recency"].idxmax())                       # いちばん前に買った人たち
    rest = table.drop(index=churn).sort_values("monetary", ascending=False)
    labels = ["優良顧客", "常連顧客", "一般顧客", "様子見顧客"]
    names = {churn: "離脱顧客"}
    for name, cluster in zip(labels, rest.index):
        names[int(cluster)] = name
    return dict(sorted(names.items()))


def fix_signs(components: np.ndarray) -> np.ndarray:
    """主成分の符号をそろえる（絶対値が最大の係数が正になるように向きを決める）。

    主成分の向き（符号）は計算の都合で反転しうるので、そのまま比べると
    「係数がすべて逆」という食い違いが起きます。読む前に必ず向きをそろえます。
    """
    top = np.abs(components).argmax(axis=1)                      # 各主成分で影響が最大の列
    sign = np.where(components[np.arange(len(components)), top] < 0, -1.0, 1.0)
    return components * sign[:, None]


@lru_cache(maxsize=None)
def pca_bundle() -> dict:
    """主成分分析の結果をまとめて返す（寄与率・累積寄与率・係数・座標）。"""
    X = scaled_matrix()
    pca = PCA(n_components=len(FEATURES), random_state=RANDOM_STATE).fit(X)
    components = fix_signs(pca.components_)
    coords = (X - pca.mean_) @ components.T                      # 符号をそろえた軸の上での座標
    ratio = pca.explained_variance_ratio_
    return {
        "pca": pca,
        "components": components,
        "coords": coords,
        "ratio": [float(value) for value in ratio],
        "cumulative": [float(value) for value in np.cumsum(ratio)],
    }


def loadings() -> pd.DataFrame:
    """主成分の係数を「PC1〜PC3 × 3 指標」の表にする。"""
    bundle = pca_bundle()
    index = [f"PC{i + 1}" for i in range(len(FEATURES))]
    return pd.DataFrame(bundle["components"], columns=FEATURES, index=index)


def save_figure(fig, name: str) -> Path:
    """図を outputs/ に保存してパスを返す（MPLBACKEND=Agg なので show は使わない）。"""
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / name
    fig.savefig(path, dpi=100)
    return path


def print_profile(table: pd.DataFrame, names: dict[int, str] | None = None) -> None:
    """クラスタ profile を 1 クラスタ 1 行で表示する。"""
    header = f"{'クラスタ':<8}{'人数':>7}{'recency':>10}{'frequency':>11}{'monetary':>12}"
    print(header if names is None else header + "  セグメント名")
    for cluster, row in table.iterrows():
        # numpy の整数をそのまま書式指定に渡さない（Python の int に直してから使う）
        number = int(cluster)
        line = (
            f"{number:<8}{int(row['n']):>7,}{float(row['recency']):>10.1f}"
            f"{float(row['frequency']):>11.1f}{float(row['monetary']):>12,.0f}"
        )
        print(line if names is None else f"{line}  {names[number]}")
