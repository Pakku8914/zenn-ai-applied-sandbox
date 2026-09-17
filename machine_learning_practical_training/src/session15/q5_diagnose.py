"""問題5 の解答：訓練と評価のスコアから、未学習・過学習を判定する道具を作る。

使い方:
    docker compose exec lab python src/session15/q5_diagnose.py
"""

from __future__ import annotations

from collections import Counter

from sklearn.dummy import DummyClassifier
from sklearn.metrics import roc_auc_score

from common import DEPTHS, RANDOM_STATE, depth_table, load_review_features, pad, pipeline_for, split_features

LOW_TRAIN_AUC = 0.70  # 訓練データでこれに届かないなら、まだ学習しきれていない
GAP_LIMIT = 0.05  # 訓練と評価の差がこれを超えたら過学習

UNDERFIT = "未学習（バイアスが大きい）"
OVERFIT = "過学習（バリアンスが大きい）"
BALANCED = "釣り合っている"

# 診断ごとの次の打ち手（この対応が決まっていれば、毎回悩まずに動ける）
NEXT_ACTIONS = {
    UNDERFIT: "モデルを複雑にする・特徴量を足す（データを増やしても効かない）",
    BALANCED: "この設定を採用し、別のモデルや特徴量と比べる",
    OVERFIT: "モデルを単純にする（深さの制限など）・データを増やす",
}


def diagnose(train_auc: float, eval_auc: float) -> str:
    """訓練と評価のスコアの組から 3 つの状態のどれかを返す（自分で書く）。"""
    if train_auc < LOW_TRAIN_AUC:
        return UNDERFIT
    if train_auc - eval_auc > GAP_LIMIT:
        return OVERFIT
    return BALANCED


def main() -> None:
    X_train, X_test, y_train, y_test = split_features(load_review_features())

    print(f"■ 判定の閾値 : 訓練 AUC < {LOW_TRAIN_AUC} なら未学習 / "
          f"訓練 - 評価 > {GAP_LIMIT} なら過学習")
    print()

    # ベースラインは「何も学習していない」の見本。訓練データでも 0.5000 にしかならない
    dummy = pipeline_for(DummyClassifier(strategy="most_frequent", random_state=RANDOM_STATE))
    dummy.fit(X_train, y_train)
    base_train = float(roc_auc_score(y_train, dummy.predict_proba(X_train)[:, 1]))
    base_eval = float(roc_auc_score(y_test, dummy.predict_proba(X_test)[:, 1]))
    print("■ ベースライン（多数クラス予測）")
    print(f"訓練 AUC {base_train:.4f} / 評価 AUC {base_eval:.4f} → {diagnose(base_train, base_eval)}")
    print()

    table = depth_table(X_train, y_train, X_test, y_test, DEPTHS)
    print("■ 決定木の深さごとの診断")
    print(f"{pad('深さ', 8)} | 訓練 AUC | 評価 AUC | 診断")
    labels = []
    for row in table:
        label = diagnose(row["train_auc"], row["test_auc"])
        labels.append(label)
        print(f"{pad(row['label'], 8)} | {row['train_auc']:>8.4f} | {row['test_auc']:>8.4f} | {label}")
    print()

    counts = Counter(labels)
    print("■ 診断の件数")
    for name in (UNDERFIT, BALANCED, OVERFIT):
        print(f"{pad(name, 28)} : {counts[name]} 件")
    print()

    print("■ 診断ごとの次の打ち手")
    for name in (UNDERFIT, BALANCED, OVERFIT):
        print(f"{pad(name, 28)} → {NEXT_ACTIONS[name]}")
    print()

    print("■ 深さをテストデータで選ぶと何が問題か")
    print("7 つの深さをテストデータで比べて 5 を選ぶと、その 0.7867 は「テストデータに")
    print("いちばん合う設定を選んだ結果」です。未知のデータではここまで出ません。")
    print("設定を選ぶ作業は検証データか交差検証で行い、テストは最後に 1 回だけ使います。")


if __name__ == "__main__":
    main()
