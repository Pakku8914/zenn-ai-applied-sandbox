"""問題6 の解答: 雑音だけの 500 列で、特徴量選択のリークを自分の手で再現する。

実行:
    docker compose exec lab python src/session22/q6_noise_leak.py
"""

from __future__ import annotations

from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import Pipeline

from common import MAX_ITER, RANDOM_STATE, SCORING, TEST_SIZE, load_review_table, stratified_cv, summarize
from noise_selection_leak import CHANCE_AUC, K_SELECT, make_noise

CV_TOLERANCE = 0.03  # 交差検証の平均が「当て推量とほぼ同じ」と言える幅


def make_pipeline() -> Pipeline:
    """特徴量選択とモデルをひとまとめにする（fit が訓練データに閉じる形）。"""
    return Pipeline(
        [
            ("select", SelectKBest(f_classif, k=K_SELECT)),
            ("model", LogisticRegression(max_iter=MAX_ITER)),
        ]
    )


def split(X, y):
    return train_test_split(X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)


def analyze(df) -> dict[str, object]:
    """リークあり・リークなし・交差検証の 3 通りで、雑音 500 列の実力を測る。"""
    y = df["is_high"]
    X_noise = make_noise(len(df))

    # ① 分割前に全データを見て 10 列を選ぶ（リーク）
    selector = SelectKBest(f_classif, k=K_SELECT).fit(X_noise, y)
    leaked_columns = list(X_noise.columns[selector.get_support()])
    X_train, X_test, y_train, y_test = split(X_noise.loc[:, selector.get_support()], y)
    leaked_model = LogisticRegression(max_iter=MAX_ITER).fit(X_train, y_train)
    leaked = float(roc_auc_score(y_test, leaked_model.predict_proba(X_test)[:, 1]))

    # ② 分割してから訓練データだけで選ぶ（正しい手順）
    X_train, X_test, y_train, y_test = split(X_noise, y)
    honest_model = make_pipeline().fit(X_train, y_train)
    honest = float(roc_auc_score(y_test, honest_model.predict_proba(X_test)[:, 1]))
    honest_columns = list(X_train.columns[honest_model.named_steps["select"].get_support()])

    # ③ ② を交差検証で 5 回繰り返す（1 回の分割の運を取り除く）
    cv_scores = cross_val_score(make_pipeline(), X_noise, y, cv=stratified_cv(), scoring=SCORING)
    cv_mean, cv_std = summarize(cv_scores)

    # 目的変数との相関がいちばん強い列でも、相関はほとんど無い
    correlations = X_noise.corrwith(y).abs()

    return {
        "shape": X_noise.shape,
        "leaked": leaked,
        "honest": honest,
        "gap": leaked - honest,
        "cv_mean": cv_mean,
        "cv_std": cv_std,
        "max_abs_corr": float(correlations.max()),
        "overlap": len(set(leaked_columns) & set(honest_columns)),
        "leaked_beats_chance": bool(leaked - CHANCE_AUC > 0.05),
        "honest_is_chance": bool(abs(honest - CHANCE_AUC) < 0.01),
        "cv_is_chance": bool(abs(cv_mean - CHANCE_AUC) < CV_TOLERANCE),
    }


def main() -> None:
    result = analyze(load_review_table())

    print("■ 1. 作ったノイズ列")
    print(f"形（行数・列数）            : {result['shape']}")
    print(f"目的変数との相関の最大（絶対値）: {result['max_abs_corr']:.4f}")
    print()

    print("■ 2. ROC AUC")
    print(f"① 分割前に全データで選ぶ（リーク）: {result['leaked']:.4f}")
    print(f"② 訓練データだけで選ぶ（正しい）  : {result['honest']:.4f}")
    print(f"③ ② を層化 5 分割で 5 回繰り返す  : 平均 {result['cv_mean']:.4f} / 標準偏差 {result['cv_std']:.4f}")
    print(f"④ 当て推量                        : {CHANCE_AUC:.4f}")
    print(f"⑤ ① − ②（選び方だけで生まれた差）: {result['gap']:+.4f}")
    print(f"⑥ ① と ② で選ばれた列の重なり    : {result['overlap']} / {K_SELECT} 列")
    print()

    print("■ 3. 判定")
    print(f"① は当て推量を 0.05 以上上回ったか  : {result['leaked_beats_chance']}")
    print(f"② は当て推量から 0.01 以内か        : {result['honest_is_chance']}")
    print(f"③ は当て推量から {CV_TOLERANCE} 以内か      : {result['cv_is_chance']}")
    print()

    print("■ 4. 説明例")
    print("500 回くじを引けば、偶然よく当たって見える列が必ず何本か出てきます。")
    print("評価データまで含めて選ぶと、その「偶然の当たり」が評価データでも当たり続けます。")
    print("訓練データだけで選べば、偶然の当たりは評価データに引き継がれず、実力どおり 0.5 付近に戻ります。")
    print("このリークは列の中身を見ても分かりません。手順を見ないと見つけられない型のリークです。")


if __name__ == "__main__":
    main()
