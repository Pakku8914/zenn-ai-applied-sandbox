"""実装問題 10：4 種類のモデルを同じ条件で並べ、順位の理由を言葉にする。

使い方:
    docker compose exec lab python src/review02/q10_model_ranking.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # pyplot より前に書く（画面のないコンテナで図を保存するため）
import matplotlib.pyplot as plt
from lightgbm import LGBMClassifier
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from common import (
    MAX_ITER,
    N_ESTIMATORS,
    RANDOM_STATE,
    fit_and_score,
    load_review_table,
    save_fig,
    split_classification,
)

BASELINE_NAME = "ベースライン（多数クラス予測）"
LINEAR_NAME = "ロジスティック回帰"
# 木モデルだけを後でまとめて見たいので、名前を控えておく
TREE_NAMES = [
    "ランダムフォレスト（200 本）",
    "LightGBM（200 本・lr 0.1＝既定）",
    "LightGBM（200 本・lr 0.05）",
    "LightGBM（50 本・lr 0.05）",
]

# 「なぜ線形モデルが勝つのか」の答えは、モデルではなくデータの構造の側にある
REASONS = [
    "特徴量は数値 4 列とカテゴリ 1 列（One-Hot で 5 列）だけで、交互作用を作っていない",
    "unit_price は書籍マスタの price と同じ値で、pages との相関は 0.9709（ほぼ同じ情報）",
    "星の下敷きになる満足度が足し算で決まるように作られている（tools/make_datasets.py を読むと分かる）",
    "正例率 0.8167 の偏ったデータなので、細かく分けるほど葉の件数が減って不安定になる",
    "つまり「直線 1 枚で足りる形」のデータであり、複雑なモデルは当てはめすぎるだけになる",
    "実データではこの前提が成り立たないこともある。順位はデータごとに測り直す",
]


def build_models() -> list[tuple[str, object]]:
    """比べるモデルを 1 か所で定義する。乱数の種は全部そろえる（本書の規約）。"""
    return [
        (BASELINE_NAME, DummyClassifier(strategy="most_frequent", random_state=RANDOM_STATE)),
        (LINEAR_NAME, LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE)),
        (TREE_NAMES[0], RandomForestClassifier(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, n_jobs=1)),
        (TREE_NAMES[1], LGBMClassifier(n_estimators=N_ESTIMATORS, learning_rate=0.1, random_state=RANDOM_STATE, verbose=-1)),
        (TREE_NAMES[2], LGBMClassifier(n_estimators=N_ESTIMATORS, learning_rate=0.05, random_state=RANDOM_STATE, verbose=-1)),
        (TREE_NAMES[3], LGBMClassifier(n_estimators=50, learning_rate=0.05, random_state=RANDOM_STATE, verbose=-1)),
    ]


def step1_scores(X_train, X_test, y_train, y_test) -> list[dict]:
    """同じ分割・同じ前処理で 6 行の表を作る（条件を 1 つだけ変える・セッション15）。"""
    print(f"■ 1. 同じ分割・同じ前処理で並べる（訓練 {len(y_train):,} 件 / 評価 {len(y_test):,} 件）")
    rows: list[dict] = []
    for name, model in build_models():
        scores = fit_and_score(model, X_train, y_train, X_test, y_test)
        rows.append({"name": name, **scores})
        print(f"  {name}: accuracy {scores['accuracy']:.4f} / ROC AUC {scores['roc_auc']:.4f}")
    return rows


def step2_ranking(rows: list[dict]) -> list[dict]:
    """ROC AUC の順位を付ける。accuracy の順位とずれることがある（セッション20 へ続く話）。"""
    ranked = sorted(rows, key=lambda r: r["roc_auc"], reverse=True)
    print("■ 2. ROC AUC の順位")
    for position, row in enumerate(ranked, start=1):
        print(f"  {position} 位: {row['name']} {row['roc_auc']:.4f}")
    return ranked


def step3_checks(rows: list[dict], ranked: list[dict]) -> None:
    """順位の読み方を検算する（自分の目で見比べて終わりにしない）。"""
    by_name = {row["name"]: row for row in rows}
    best_tree = max((by_name[name] for name in TREE_NAMES), key=lambda r: r["roc_auc"])
    default_lgbm, linear, baseline = by_name[TREE_NAMES[1]], by_name[LINEAR_NAME], by_name[BASELINE_NAME]

    print("■ 3. 検算")
    print(f"  ROC AUC の 1 位: {ranked[0]['name']}")
    print(f"  accuracy の 1 位: {max(rows, key=lambda r: r['accuracy'])['name']}")
    print(f"  LightGBM の既定（{default_lgbm['roc_auc']:.4f}）より良い設定があった: {best_tree['roc_auc'] > default_lgbm['roc_auc']}")
    print(
        f"  木モデルの最良（{best_tree['roc_auc']:.4f}）がロジスティック回帰（{linear['roc_auc']:.4f}）に届かない: "
        f"{best_tree['roc_auc'] < linear['roc_auc']}"
    )
    print(f"  すべてのモデルがベースラインの ROC AUC {baseline['roc_auc']:.4f} を上回る: {min(r['roc_auc'] for r in rows if r['name'] != BASELINE_NAME) > baseline['roc_auc']}")
    print(f"  木の本数を 200 から 50 に減らしても良くなった: {by_name[TREE_NAMES[3]]['roc_auc'] > by_name[TREE_NAMES[2]]['roc_auc']}")


def step4_reasons() -> None:
    """順位の理由をデータの構造から言葉にする（ここが本題）。"""
    print("■ 4. なぜ線形モデルが勝つのか（データの構造から）")
    for number, reason in enumerate(REASONS, start=1):
        print(f"  ({number}) {reason}")


def step5_figure(ranked: list[dict]) -> None:
    """順位を 1 枚の図にする。ベースラインの 0.5 を必ず描き込む（セッション8）。"""
    names = [row["name"] for row in ranked][::-1]  # 横棒は下から積まれるので逆順にする
    values = [row["roc_auc"] for row in ranked][::-1]
    colors = ["#4c78a8" if name == LINEAR_NAME else "#9ecae9" for name in names]

    fig, ax = plt.subplots(figsize=(8, 4))
    bars = ax.barh(names, values, color=colors)
    ax.axvline(0.5, color="#e45756", linestyle="--", label="ベースライン（0.5）")
    ax.set_xlim(0.45, 0.90)
    ax.set_xlabel("ROC AUC（評価データ 3,543 件）")
    ax.set_title("同じ分割・同じ前処理で比べた ROC AUC")
    ax.bar_label(bars, fmt="%.4f", padding=3, fontsize=9)
    ax.legend(loc="lower right")
    fig.tight_layout()
    save_fig(fig, "review02_model_ranking.png")


def main() -> None:
    df = load_review_table()
    X_train, X_test, y_train, y_test = split_classification(df)
    rows = step1_scores(X_train, X_test, y_train, y_test)
    ranked = step2_ranking(rows)
    step3_checks(rows, ranked)
    step4_reasons()
    step5_figure(ranked)


if __name__ == "__main__":
    main()
