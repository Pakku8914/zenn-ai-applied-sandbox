"""課題4 の解答: 特徴量を 1 段階ずつ足して、毎回測る（増分実験）。

セッション14 と同じ 7 段階をもう一度組み立てます。⑦ だけは「やってはいけない例」で、
その注文自身の結果を含む列（all_time_cancels）を混ぜたときに何が起きるかを見ます。

実行:
    docker compose exec lab python src/mid02/features.py
"""

from __future__ import annotations

import pandas as pd

from common import evaluate_features, load_order_table

# 「境目」の定義には名前を付けて 1 か所に集める（式の中に数字を直接書かない）
NEW_CUSTOMER_DAYS = 7     # 登録から 7 日未満（0〜6 日）を「登録直後」とする
BIG_DISCOUNT_RATE = 0.20  # 20% 以上の値引きを「大きな値引き」とする
AGE_BASE_YEAR = 2026      # 年齢の基準年。固定しないと毎年結果が変わる

LEAK_COLUMN = "all_time_cancels"  # データリークの実演にだけ使う列


def add_amount_and_age(df: pd.DataFrame) -> pd.DataFrame:
    """既にある列を組み合わせて作る特徴量（金額と年齢）を足す。"""
    out = df.copy()
    # 売上規約どおり行ごとには丸めない（合計してから整数にする）
    out["amount"] = out["unit_price"] * out["quantity"] * (1 - out["discount_rate"])
    out["age"] = AGE_BASE_YEAR - out["birth_year"]
    return out


def add_datetime_features(df: pd.DataFrame) -> pd.DataFrame:
    """日時の列を部品に分解して足す（曜日・月・週末フラグ）。"""
    out = df.copy()
    out["weekday"] = out["ordered_at"].dt.dayofweek  # 月曜 = 0 ... 日曜 = 6
    out["month"] = out["ordered_at"].dt.month
    out["is_weekend"] = (out["ordered_at"].dt.dayofweek >= 5).astype("int64")
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
    """全期間のキャンセル数を足す。**データリークの実演にだけ使う列です。**"""
    out = df.copy()
    # transform("sum") はその行自身の is_canceled も足してしまう（＝答えを見ている）
    out[LEAK_COLUMN] = out.groupby("customer_id")["is_canceled"].transform("sum")
    return out


def add_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """①〜⑦の実験で使う列をまとめて足す（段階ごとに使う列だけを選んで学習する）。"""
    out = add_amount_and_age(df)
    out = add_datetime_features(out)
    out = add_domain_flags(out)
    out = add_past_features(out)
    return add_leak_feature(out)


# 増分実験の設計。各段階で「前の段階に何を足すか」だけを書く
STEP_PLAN: list[tuple[str, str, list[str], list[str]]] = [
    ("①", "素の 3 列", ["unit_price", "quantity", "discount_rate"], []),
    ("②", "+ 経過日数と流入経路（基準モデル）", ["days_since_signup"], ["channel"]),
    ("③", "+ 金額と年齢", ["amount", "age"], ["channel"]),
    ("④", "+ 日時（曜日・月・週末）", ["weekday", "month", "is_weekend"], ["channel"]),
    ("⑤", "+ ドメイン知識のフラグ", ["is_new_customer", "is_big_discount"], ["channel"]),
    ("⑥", "+ 過去だけの集計", ["past_orders", "past_cancels"], ["channel"]),
    ("⑦", "+ 全期間のキャンセル数（リーク）", [LEAK_COLUMN], ["channel"]),
]
BASE_STEP = "②"  # 基準モデルの段階


def cumulative_steps() -> list[tuple[str, str, list[str], list[str]]]:
    """STEP_PLAN の「追加分」を積み上げて、各段階が使う特徴量の一覧に展開する。"""
    numeric: list[str] = []
    steps: list[tuple[str, str, list[str], list[str]]] = []
    for key, label, added, categorical in STEP_PLAN:
        numeric = numeric + added  # 前の段階を壊さずに増やす
        steps.append((key, label, numeric, categorical))
    return steps


def run_steps(df: pd.DataFrame | None = None) -> list[dict[str, object]]:
    """①〜⑦を順に学習し、基準モデル（②）を上回ったかどうかまで判定して返す。"""
    table = add_all_features(load_order_table()) if df is None else df
    results = [
        {"key": key, "label": f"{key} {label}", **evaluate_features(table, numeric, categorical)}
        for key, label, numeric, categorical in cumulative_steps()
    ]
    base_pr = next(r["pr_auc"] for r in results if r["key"] == BASE_STEP)
    for result in results:
        # 許容誤差 0.005 を超えて上回った段階だけを「良くなった」と数える
        result["beats_base"] = bool(result["pr_auc"] > base_pr + 0.005)
    return results


def rate_report(df: pd.DataFrame | None = None) -> dict[str, object]:
    """特徴量を足す候補を決めた根拠（キャンセル率の内訳）。セッション14 の再掲。"""
    table = add_datetime_features(load_order_table()) if df is None else df
    by_channel = table.groupby("channel")["is_canceled"].mean().sort_values(ascending=False)
    weekday = table.groupby("weekday")["is_canceled"].mean()
    is_new = table["days_since_signup"] < NEW_CUSTOMER_DAYS
    return {
        "overall": float(table["is_canceled"].mean()),
        "by_channel": {str(k): float(v) for k, v in by_channel.items()},
        "new": float(table.loc[is_new, "is_canceled"].mean()),
        "not_new": float(table.loc[~is_new, "is_canceled"].mean()),
        "big_discount": float(
            table.loc[table["discount_rate"] >= BIG_DISCOUNT_RATE, "is_canceled"].mean()
        ),
        "weekday_min": float(weekday.min()),
        "weekday_max": float(weekday.max()),
    }


def main() -> None:
    df = add_all_features(load_order_table())
    results = run_steps(df)

    print("■ 1. 増分実験（1 段階ずつ足して、毎回測る）")
    for result in results:
        print(f"{result['label']} : {result['n_features']:>2} 列"
              f" / ROC AUC {result['roc_auc']:.4f} / PR-AUC {result['pr_auc']:.4f}")
    print()

    print("■ 2. 判定")
    beats = [result["key"] for result in results if result["beats_base"]]
    print(f"基準モデル（{BASE_STEP}）の PR-AUC を上回った段階: {' '.join(beats)}")
    print("⑦ は全期間のキャンセル数（その注文自身の結果を含む列）を使っているので採用できません")
    print(f"→ 採用するのは {BASE_STEP} の 5 列。③〜⑥ は足しても良くならないので戻します")
    print()

    rates = rate_report(df)  # df には曜日の列も入っているのでそのまま渡せる
    print("■ 3. 特徴量を足す前に見た「率」（足す候補を決めた根拠）")
    print(f"全体のキャンセル率    : {rates['overall']:.2%}")
    channels = " / ".join(f"{name} {rate:.2%}" for name, rate in rates["by_channel"].items())
    print(f"流入経路別            : {channels}")
    print(f"登録 7 日以内の注文   : {rates['new']:.2%}（それ以外 {rates['not_new']:.2%}）")
    print(f"値引き 20% 以上の注文 : {rates['big_discount']:.2%}")
    print(f"曜日別                : {rates['weekday_min']:.2%} 〜 {rates['weekday_max']:.2%}"
          "（ばらつきが小さい）")


if __name__ == "__main__":
    main()
