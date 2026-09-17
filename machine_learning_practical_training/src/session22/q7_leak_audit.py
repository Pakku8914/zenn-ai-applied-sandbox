"""問題7 の解答: リーク点検チェックリストをコードにして、3 つの実験を監査する。

チェックリストは「実験の設計（Spec）」だけを見て判定します。データを読み直したり
モデルを学習し直したりしないので、実験を思いついた時点で使えます。

実行:
    docker compose exec lab python src/session22/q7_leak_audit.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

from body_length_leak import BEFORE_POSTING, compare
from common import FEATURES, load_review_table

CHANCE_AUC = 0.5      # 二値分類の当て推量
JUMP_LIMIT = 0.45     # ベースラインからこれ以上跳ねたら「うますぎる」と疑う


@dataclass
class Spec:
    """1 つの実験の設計。チェックリストはこの紙 1 枚だけを読んで判定する。"""

    name: str
    features: list[str]
    split: str                                    # "stratified" / "group" / "time"
    model_auc: float
    baseline_auc: float = CHANCE_AUC
    target_columns: list[str] = field(default_factory=list)        # 目的変数そのもの・その言い換え
    unknown_at_prediction: list[str] = field(default_factory=list)  # 予測時点では決まっていない列
    aggregated_all_time: list[str] = field(default_factory=list)    # 全期間を集約した列
    preprocess_in_pipeline: bool = True
    group_repeats: bool = False                   # 同じ人・同じ商品の行が複数あるか
    group_note: str = ""
    has_time_column: bool = False


def check_target(spec: Spec) -> tuple[bool, str]:
    """Q1 目的変数そのもの、またはその言い換えが特徴量に入っていないか。"""
    hit = [column for column in spec.features if column in spec.target_columns]
    return bool(hit), f"該当列: {hit if hit else 'なし'}"


def check_unknown(spec: Spec) -> tuple[bool, str]:
    """Q2 予測したい時点では、まだ値が決まっていない列が入っていないか。"""
    hit = [column for column in spec.features if column in spec.unknown_at_prediction]
    return bool(hit), f"該当列: {hit if hit else 'なし'}"


def check_group(spec: Spec) -> tuple[bool, str]:
    """Q3 同じ人・同じ商品の行が、訓練と評価の両方に入らない分割になっているか。"""
    risky = spec.group_repeats and spec.split != "group"
    return risky, f"{spec.group_note or '重複なし'}（分割は {spec.split}）"


def check_preprocess(spec: Spec) -> tuple[bool, str]:
    """Q4 前処理の fit が、分割の内側に閉じているか。"""
    reason = "Pipeline の中で fit している" if spec.preprocess_in_pipeline else "分割の外で fit している"
    return (not spec.preprocess_in_pipeline), reason


def check_aggregation(spec: Spec) -> tuple[bool, str]:
    """Q5 集約した特徴量が、その行より前のデータだけで作られているか。"""
    hit = [column for column in spec.features if column in spec.aggregated_all_time]
    return bool(hit), f"全期間を集約した列: {hit if hit else 'なし'}"


def check_time(spec: Spec) -> tuple[bool, str]:
    """Q6 評価データの期間が、訓練データより後になっているか。"""
    risky = spec.has_time_column and spec.split != "time"
    return risky, f"時刻の列あり: {spec.has_time_column}（分割は {spec.split}）"


def check_jump(spec: Spec) -> tuple[bool, str]:
    """Q7 ベースラインからの上がり幅が、不自然に大きくないか。"""
    jump = spec.model_auc - spec.baseline_auc
    return bool(jump > JUMP_LIMIT), f"ベースライン {spec.baseline_auc:.4f} → モデル {spec.model_auc:.4f}（+{jump:.4f}）"


CHECKS = [
    ("Q1 目的変数の混入", check_target),
    ("Q2 予測時点では未確定の列", check_unknown),
    ("Q3 同じ人・同じ商品の重複", check_group),
    ("Q4 分割の外での前処理", check_preprocess),
    ("Q5 未来まで含む集約", check_aggregation),
    ("Q6 時間をまたぐ分割", check_time),
    ("Q7 うますぎる改善幅", check_jump),
]


def audit(spec: Spec) -> list[dict[str, object]]:
    """7 つの問いを順に当てて、危ないところとその根拠を並べる。"""
    rows = []
    for label, check in CHECKS:
        risky, reason = check(spec)
        rows.append({"label": label, "risky": risky, "reason": reason})
    return rows


def make_cancel_spec() -> Spec:
    """実験 C（キャンセル予測に全期間のキャンセル数を足したもの）の設計。

    ROC AUC 0.9664 は「セッション14：特徴量エンジニアリング」で測った値を書き写したものです。
    ここでは LightGBM を学習し直しません（この問題の主題はチェックリストなので）。
    """
    return Spec(
        name="C キャンセル予測（全期間のキャンセル数あり）",
        features=["unit_price", "quantity", "discount_rate", "all_time_cancels", "channel"],
        split="stratified",
        model_auc=0.9664,
        target_columns=["is_canceled"],
        unknown_at_prediction=["all_time_cancels"],
        aggregated_all_time=["all_time_cancels"],
        group_repeats=True,
        group_note="1 顧客が複数の注文を持つ（セッション14 の表）",
        has_time_column=True,
    )


def build_specs(df) -> list[Spec]:
    """この章で扱った 3 つの実験を、設計として書き起こす。"""
    result = compare(df)  # body_length あり・なしの ROC AUC を測る
    counts = df["customer_id"].value_counts()

    common_kwargs = {
        "split": "stratified",
        "target_columns": ["rating", "is_high"],
        "unknown_at_prediction": ["body_length"],
        "group_repeats": bool(counts.max() > 1),
        "group_note": f"顧客 {counts.size} 人 / レビュー {len(df)} 件 / 最大 {int(counts.max())} 件",
        "has_time_column": True,
    }
    return [
        Spec(
            name="A 高評価予測（body_length あり）",
            features=FEATURES,
            model_auc=result["with_length"],
            **common_kwargs,
        ),
        Spec(
            name="B 高評価予測（body_length なし）",
            features=BEFORE_POSTING + ["category"],
            model_auc=result["without_length"],
            **common_kwargs,
        ),
        # C はセッション14 で測った値を書き写したもの（ここでは学習し直さない）。
        # unknown_at_prediction と aggregated_all_time の両方に all_time_cancels を挙げる
        make_cancel_spec(),
    ]


def main() -> None:
    df = load_review_table()
    specs = build_specs(df)

    for spec in specs:
        rows = audit(spec)
        risky = [row["label"] for row in rows if row["risky"]]
        print(f"■ {spec.name}   ROC AUC {spec.model_auc:.4f}")
        for row in rows:
            mark = "要確認" if row["risky"] else "OK  "
            print(f"  [{mark}] {row['label']:<24} {row['reason']}")
        print(f"  → 要確認 {len(risky)} 件: {risky}")
        print()

    print("■ 報告に使う数値の決め方")
    print("A の 0.8265 は「レビュー本文を読んだあとで高評価かを言い当てる」性能です。")
    print("投稿前に予測したいなら使える特徴量は B の 4 列だけで、報告してよいのは 0.7763 です。")
    print("C は要確認が 5 件。この設計のまま出てきた 0.9664 は、性能ではなく設計の不備の表れです。")


if __name__ == "__main__":
    main()
