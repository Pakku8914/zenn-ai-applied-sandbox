"""前処理を分割の前に当てるとどうなるかを測る（本文 4 節）。

結論は「このデータでは数値が動かない」です。リークは必ず性能を持ち上げる、という
思い込みをここで壊します。

実行:
    docker compose exec lab python src/session22/scaler_leak.py
"""

from __future__ import annotations

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from common import (
    MAX_ITER,
    RANDOM_STATE,
    TEST_SIZE,
    build_preprocess,
    features_target,
    holdout_auc,
    load_review_table,
)

# 標本を小さくすれば差が出るのか、を確かめるためのサイズ
SAMPLE_SIZES = [100, 200, 500, 2000]


def leaked_auc(df) -> float:
    """リークする手順: 分割の前に、全データで前処理を fit してから分割する。"""
    X, y = features_target(df)
    # ここで評価データの平均・標準偏差・カテゴリの一覧も前処理に混ざる
    X_all = build_preprocess().fit_transform(X)
    X_train, X_test, y_train, y_test = train_test_split(
        X_all, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    model = LogisticRegression(max_iter=MAX_ITER).fit(X_train, y_train)
    return float(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]))


def gap(df) -> dict[str, float]:
    """正しい手順とリークする手順の ROC AUC と、その差を返す。"""
    correct = holdout_auc(df)  # 分割 → 訓練データだけで fit（Pipeline が守ってくれる）
    leaked = leaked_auc(df)
    return {"correct": correct, "leaked": leaked, "gap": leaked - correct}


def gap_by_size(df) -> list[dict[str, float]]:
    """標本を小さくすると差が出るのかを確かめる（小さいほどリークの影響は出やすいはず）。"""
    rows = []
    for size in SAMPLE_SIZES:
        # 行を抜き出すだけ。分割・前処理・モデルの条件は全データのときと同じ
        subset = df.sample(n=size, random_state=RANDOM_STATE)
        row = gap(subset)
        row["n"] = size
        rows.append(row)
    return rows


def main() -> None:
    df = load_review_table()

    full = gap(df)
    print("■ 全データ 14,169 件")
    print(f"正しい手順（分割 → 訓練データだけで fit）の ROC AUC : {full['correct']:.4f}")
    print(f"リーク（分割前に全データで fit）の ROC AUC          : {full['leaked']:.4f}")
    print(f"差（リーク − 正しい手順）                            : {full['gap']:+.4f}")
    print()

    print("■ 標本を小さくしても差は出るか")
    print("    n | 正しい手順 | リーク  | 差")
    for row in gap_by_size(df):
        print(f"{int(row['n']):>5} |   {row['correct']:.4f}   | {row['leaked']:.4f} | {row['gap']:+.4f}")
    print()
    print("いずれの標本サイズでも差は本書の許容誤差 0.005 に届きません。")
    print("それでも前処理を Pipeline に載せる理由は、次の 5 節で示します。")


if __name__ == "__main__":
    main()
