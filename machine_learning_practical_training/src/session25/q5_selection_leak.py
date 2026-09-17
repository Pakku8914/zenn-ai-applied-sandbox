"""問題5 の解答: ノイズ 500 列の特徴量選択を、Pipeline の外と中で比べる。

実行:
    docker compose exec lab python src/session25/q5_selection_leak.py
"""

from __future__ import annotations

from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.linear_model import LogisticRegression

from common import (
    MAX_ITER,
    RANDOM_STATE,
    auc_of,
    cv_auc,
    fmt_scores,
    load_review_table,
    split,
    summarize,
)
from leak_by_design import CHANCE_AUC, CV_TOLERANCE, K_SELECT, make_noise, selection_pipeline


def analyze(df) -> dict[str, object]:
    """同じノイズ・同じ分割で、選ぶ場所だけを変えて 3 通り測る。"""
    y = df["is_high"]
    X_noise = make_noise(len(df))

    # ① Pipeline の外で選ぶ（分割の前に全データを見てしまう）
    selector = SelectKBest(f_classif, k=K_SELECT).fit(X_noise, y)
    leaked_columns = [str(c) for c in X_noise.columns[selector.get_support()]]
    X_train, X_test, y_train, y_test = split(X_noise.loc[:, selector.get_support()], y)
    leaked_model = LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE).fit(X_train, y_train)
    leaked = auc_of(leaked_model, X_test, y_test)

    # ② Pipeline の中で選ぶ（fit が訓練データに閉じる）
    X_train, X_test, y_train, y_test = split(X_noise, y)
    pipeline = selection_pipeline().fit(X_train, y_train)
    correct = auc_of(pipeline, X_test, y_test)
    correct_columns = [str(c) for c in X_train.columns[pipeline.named_steps["select"].get_support()]]

    # ③ ② をそのまま交差検証に渡す（fold ごとに選び直される）
    scores = cv_auc(selection_pipeline(), X_noise, y)
    cv_mean, cv_std = summarize(scores)

    return {
        "shape": X_noise.shape,
        "leaked": leaked,
        "correct": correct,
        "gap": leaked - correct,
        "overlap": len(set(leaked_columns) & set(correct_columns)),
        "scores": [float(s) for s in scores],
        "cv_mean": cv_mean,
        "cv_std": cv_std,
        "leaked_beats_chance": bool(leaked - CHANCE_AUC > 0.05),
        "correct_is_chance": bool(abs(correct - CHANCE_AUC) < 0.01),
        "cv_is_chance": bool(abs(cv_mean - CHANCE_AUC) < CV_TOLERANCE),
    }


def main() -> None:
    result = analyze(load_review_table())

    print("■ 1. ノイズ列")
    print(f"形（行数・列数）                  : {result['shape']}")
    print()

    print("■ 2. ROC AUC")
    print(f"① Pipeline の外で選ぶ（リーク）   : {result['leaked']:.4f}")
    print(f"② Pipeline の中で選ぶ（正しい）   : {result['correct']:.4f}")
    print(f"③ ② を層化 5 分割で繰り返す       : {fmt_scores(result['scores'])}")
    print(f"   平均 / 標準偏差                : {result['cv_mean']:.4f} / {result['cv_std']:.4f}")
    print(f"④ 当て推量                        : {CHANCE_AUC:.4f}")
    print(f"⑤ ① − ②                          : {result['gap']:+.4f}")
    print(f"⑥ ① と ② で選ばれた列の重なり    : {result['overlap']} / {K_SELECT} 列")
    print()

    print("■ 3. 判定")
    print(f"① は当て推量を 0.05 以上上回った  : {result['leaked_beats_chance']}")
    print(f"② は当て推量から 0.01 以内        : {result['correct_is_chance']}")
    print(f"③ の平均は当て推量から {CV_TOLERANCE} 以内 : {result['cv_is_chance']}")
    print()

    print("■ 4. 説明例")
    print("500 本もくじを引けば、偶然よく当たって見える列が必ず何本か混じります。")
    print("評価データまで見て選ぶと、その「偶然の当たり」が評価データでも当たり続けます。")
    print("Pipeline の中に選択を入れると、選ぶ工程が fit の内側に移り、訓練データだけで選ばれます。")
    print("だから評価データでは実力どおり当て推量の近くに戻ります。")


if __name__ == "__main__":
    main()
