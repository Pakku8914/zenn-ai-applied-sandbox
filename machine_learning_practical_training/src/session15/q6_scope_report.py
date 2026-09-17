"""問題6 の解答：ベースラインから過学習の確認まで、1 枚の報告書にまとめる。

使い方:
    docker compose exec lab python src/session15/q6_scope_report.py
"""

from __future__ import annotations

from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression

from common import (
    MAX_ITER,
    RANDOM_STATE,
    TARGET,
    TEST_SIZE,
    depth_table,
    fit_and_score,
    load_review_features,
    split_features,
)

AUC_MARGIN = 0.30  # ベースラインに対して ROC AUC でこれだけ上回っていれば「学習できている」
GAP_LIMIT = 0.05  # 訓練と評価の差の上限

OUT_OF_SCOPE = [
    "深層学習（ニューラルネット）: 表形式データでは線形モデルや木のアンサンブルが互角以上に"
    "なることが多い。本書の実測でもロジスティック回帰（ROC AUC 0.8265）が LightGBM（0.7966）を上回る",
    "GPU を前提にした学習: 本書は追加費用なしで CPU だけで完走する方針。14,169 件は深層学習が"
    "力を発揮する規模ではない",
    "画像・音声・自然言語の生データ: 姉妹教材の担当範囲。本書は前処理・評価・解釈を厚くする",
]

BEFORE_PRODUCTION = [
    "特徴量が予測したい時点で手に入るか（データリークの確認）",
    "ベースラインに対する改善幅が、運用のコストに見合うか",
    "時間が経ってから測り直しても同じ性能が出るか（劣化の監視）",
]


def build_report() -> dict:
    """報告書に載せる数値を集める。"""
    df = load_review_features()
    X_train, X_test, y_train, y_test = split_features(df)
    base = fit_and_score(
        DummyClassifier(strategy="most_frequent", random_state=RANDOM_STATE),
        X_train, y_train, X_test, y_test,
    )
    model = fit_and_score(
        LogisticRegression(max_iter=MAX_ITER, random_state=RANDOM_STATE),
        X_train, y_train, X_test, y_test,
    )
    table = depth_table(X_train, y_train, X_test, y_test, [5, None])
    return {
        "rows": len(df),
        "train_rows": len(X_train),
        "test_rows": len(X_test),
        "rate_all": float(df[TARGET].mean()),
        "rate_train": float(y_train.mean()),
        "rate_test": float(y_test.mean()),
        "base": base,
        "model": model,
        "shallow": table[0],
        "deep": table[1],
    }


def print_report(report: dict) -> None:
    """集めた数値を報告書の形に並べる。"""
    line = "=" * 64
    print(line)
    print("高評価レビューの分類 ― 報告書（セッション15）")
    print(line)
    print("1. 目的")
    print("   レビューが高評価（星 4 以上）かどうかを、本文の長さと書籍の属性から予測する")
    print()
    print("2. データと分割")
    print(f"   母集団 {report['rows']:,} 件 / 訓練 {report['train_rows']:,} 件 / "
          f"評価 {report['test_rows']:,} 件（test_size={TEST_SIZE}・random_state={RANDOM_STATE}・層化）")
    print(f"   正例率 : 全体 {report['rate_all']:.4f} / 訓練 {report['rate_train']:.4f} / "
          f"評価 {report['rate_test']:.4f}")
    print()
    print("3. ベースライン（必ず先に置く）")
    print(f"   多数クラス予測 : accuracy {report['base']['accuracy']:.4f} / "
          f"ROC AUC {report['base']['roc_auc']:.4f}")
    print()
    print("4. 採用したモデル")
    print(f"   ロジスティック回帰 : accuracy {report['model']['accuracy']:.4f} / "
          f"ROC AUC {report['model']['roc_auc']:.4f} / log loss {report['model']['log_loss']:.4f}")
    print(f"   改善幅 : accuracy {report['model']['accuracy'] - report['base']['accuracy']:+.4f} / "
          f"ROC AUC {report['model']['roc_auc'] - report['base']['roc_auc']:+.4f}")
    print()
    print("5. 過学習の確認（決定木で深さを変えて確かめた）")
    for key, name in [("shallow", "深さ 5    "), ("deep", "制限なし  ")]:
        row = report[key]
        print(f"   {name} : 訓練 AUC {row['train_auc']:.4f} / 評価 AUC {row['test_auc']:.4f} / "
              f"葉 {row['leaves']:,} 枚")
    print("   → 深さを制限しないと訓練だけが上がり、評価は当て推量へ近づく")
    print()
    print("6. 本書で扱わない範囲")
    for i, text in enumerate(OUT_OF_SCOPE, start=1):
        print(f"   ({i}) {text}")
    print()
    print("7. 本番に出す前に必ず確認すること")
    for i, text in enumerate(BEFORE_PRODUCTION, start=1):
        print(f"   ({i}) {text}")
    print(line)


def main() -> None:
    report = build_report()
    print_report(report)
    print()
    print("■ 判定")
    base, model = report["base"], report["model"]
    print(f"accuracy がベースラインを上回るか : {model['accuracy'] > base['accuracy']}")
    print(f"ROC AUC がベースラインより {AUC_MARGIN} 以上高いか : "
          f"{model['roc_auc'] - base['roc_auc'] >= AUC_MARGIN}")
    print(f"報告書に ROC AUC と log loss が含まれているか : "
          f"{'roc_auc' in model and 'log_loss' in model}")
    print(f"深さ 5 の決定木の訓練と評価の差が {GAP_LIMIT} 未満か : "
          f"{report['shallow']['train_auc'] - report['shallow']['test_auc'] < GAP_LIMIT}")
    print(f"深さを制限しない決定木の差が {GAP_LIMIT} を超えるか : "
          f"{report['deep']['train_auc'] - report['deep']['test_auc'] > GAP_LIMIT}")


if __name__ == "__main__":
    main()
