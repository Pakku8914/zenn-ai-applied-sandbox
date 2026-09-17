"""問題7 の解答: 4 種類のリークを見つけ、正しい手順と並べて差を測り、設計を監査する。

実行:
    docker compose exec lab python src/review03/q7_leak_hunt.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

from common import (
    CHANCE_AUC,
    FUTURE_LEAK_AUC,
    FUTURE_LEAK_PR_AUC,
    TOLERANCE,
    leak_experiments,
    load_review_table,
)

JUMP_LIMIT = 0.45  # ベースラインからこれ以上跳ねたら「うますぎる」と疑う


@dataclass
class Spec:
    """1 つの実験の設計。チェックリストはこの紙 1 枚だけを読んで判定する。

    データを読み直したりモデルを学習し直したりしないので、**実験を思いついた時点**で使えます。
    """

    name: str
    auc: float
    baseline: float = CHANCE_AUC
    fit_inside_split: bool = True                                   # 前処理・選抜・対応表の fit が分割の内側か
    target_derived: list[str] = field(default_factory=list)         # 目的変数から作った列
    unknown_at_prediction: list[str] = field(default_factory=list)  # 予測時点では決まっていない列
    group_repeats: bool = False                                     # 同じ人・同じ商品の行が複数あるか
    group_note: str = ""


def check_target(spec: Spec) -> tuple[bool, str]:
    """Q1 目的変数そのもの、またはそこから計算した列が特徴量に入っていないか。"""
    return bool(spec.target_derived), f"該当列: {spec.target_derived or 'なし'}"


def check_unknown(spec: Spec) -> tuple[bool, str]:
    """Q2 予測したい時点では、まだ値が決まっていない列が入っていないか。"""
    return bool(spec.unknown_at_prediction), f"該当列: {spec.unknown_at_prediction or 'なし'}"


def check_fit_scope(spec: Spec) -> tuple[bool, str]:
    """Q3 前処理・特徴量選択・エンコーディングの fit が、分割の内側に閉じているか。"""
    reason = "Pipeline の中で fit している" if spec.fit_inside_split else "分割の外で fit している"
    return (not spec.fit_inside_split), reason


def check_group(spec: Spec) -> tuple[bool, str]:
    """Q4 同じ人・同じ商品の行が、訓練と評価の両方に入らない分割になっているか。"""
    return spec.group_repeats, spec.group_note or "重複なし"


def check_jump(spec: Spec) -> tuple[bool, str]:
    """Q5 ベースラインからの上がり幅が、不自然に大きくないか。"""
    jump = spec.auc - spec.baseline
    return bool(jump > JUMP_LIMIT), f"ベースライン {spec.baseline:.4f} → {spec.auc:.4f}（+{jump:.4f}）"


CHECKS = [
    ("Q1 目的変数から作った列", check_target),
    ("Q2 予測時点では未確定の列", check_unknown),
    ("Q3 分割の外での fit", check_fit_scope),
    ("Q4 同じ人・同じ商品の重複", check_group),
    ("Q5 うますぎる改善幅", check_jump),
]


def audit(spec: Spec) -> list[dict[str, object]]:
    """5 つの問いを順に当てて、危ないところとその根拠を並べる。"""
    rows = []
    for label, check in CHECKS:
        risky, reason = check(spec)
        rows.append({"label": label, "risky": risky, "reason": reason})
    return rows


def build_specs(rows: list[dict], group_note: str) -> list[Spec]:
    """実験の結果（リークしたときの ROC AUC）を設計として書き起こす。"""
    by_label = {row["label"]: row for row in rows}
    common = {"group_repeats": True, "group_note": group_note}
    return [
        Spec(
            name="① 標準化を分割前に当てる",
            auc=by_label["① 標準化を分割前に当てる"]["leaked"],
            fit_inside_split=False,
            **common,
        ),
        Spec(
            name="② 雑音 500 列から分割前に選抜",
            auc=by_label["② 雑音 500 列から分割前に選抜"]["leaked"],
            fit_inside_split=False,
            **common,
        ),
        Spec(
            name="③ book_id の対応表を全データで作る",
            auc=by_label["③ book_id の対応表を全データで作る"]["leaked"],
            fit_inside_split=False,
            target_derived=["book_id_target"],
            **common,
        ),
        Spec(
            name="④ body_length を使う",
            auc=by_label["④ body_length（投稿後に決まる）を使う"]["leaked"],
            unknown_at_prediction=["body_length"],
            **common,
        ),
        # ⑤ は「セッション14：特徴量エンジニアリング」で測った値を書き写したもの。
        # ここでは学習し直さない（この節の主題は設計の監査なので）
        Spec(
            name="⑤ キャンセル予測に全期間のキャンセル数",
            auc=FUTURE_LEAK_AUC,
            target_derived=["all_time_cancels"],
            unknown_at_prediction=["all_time_cancels"],
            group_repeats=True,
            group_note="1 顧客が複数の注文を持つ（セッション14 の表）",
        ),
    ]


FIXES = [
    ("①", "`StandardScaler` を Pipeline の中に入れ、fold ごとに訓練データだけで fit する"),
    ("②", "`SelectKBest` も「学習」なので Pipeline に入れ、選抜を fold の内側に閉じ込める"),
    ("③", "対応表は訓練データの平均だけで作り、表に無い水準は訓練データ全体の平均で埋める"),
    ("④", "投稿前に分かる 3 列だけで学習し、報告する数値も 4 列版ではなくそちらにする"),
    ("⑤", "集計の期間を予測時点より前で切る（`shift(1)` で自分の行を除いた累積和にする）"),
]


def main() -> None:
    df = load_review_table()
    rows = leak_experiments()
    counts = df["customer_id"].value_counts()
    group_note = f"顧客 {counts.size:,} 人 / レビュー {len(df):,} 件 / 最大 {int(counts.max())} 件"

    print("■ 1. 同じデータ・同じモデルで、手順だけを変えて測る")
    print("実験                                 | 正しい手順 | リーク  | 差      | 持ち上がったか")
    for row in rows:
        print(
            f"{row['label']:<36} |   {row['correct']:.4f}   | {row['leaked']:.4f} |"
            f" {row['gap']:+.4f} | {row['fooled']}"
        )
    print()

    lifted = [row["label"] for row in rows if row["fooled"]]
    print("■ 2. 持ち上がった実験と、持ち上がらなかった実験")
    print(f"許容誤差 {TOLERANCE} を超えて持ち上がった実験: {len(lifted)} / {len(rows)} 件")
    for row in rows:
        verdict = "持ち上がった" if row["fooled"] else "動かなかった（それでもリークはリーク）"
        print(f"  {row['label']}（{row['kind']}）: {verdict}")
    print("→ リークは必ず数値を持ち上げるとは限りません。①は差 0.0000 でも手順としては誤りです")
    print()

    print("■ 3. 設計だけを見て監査する（データを読み直さない）")
    for spec in build_specs(rows, group_note):
        results = audit(spec)
        risky = [row["label"] for row in results if row["risky"]]
        print(f"● {spec.name}   ROC AUC {spec.auc:.4f}")
        for row in results:
            mark = "要確認" if row["risky"] else "OK  "
            print(f"    [{mark}] {row['label']:<24} {row['reason']}")
        print(f"    → 要確認 {len(risky)} 件: {risky}")
    print()

    print("■ 4. 直し方")
    for number, fix in FIXES:
        print(f"{number} {fix}")
    print()

    print("■ 5. 報告してよい数値")
    body = next(row for row in rows if row["kind"] == "未来情報")
    print(f"body_length と rating の相関: {body['corr']:+.4f}（本文が長いほど星が低い）")
    print(f"投稿後の情報まで使った場合 : {body['leaked']:.4f}")
    print(f"投稿前に分かる列だけの場合 : {body['correct']:.4f} ← 報告してよいのはこちら")
    print(
        f"⑤ の 0.9664 は性能ではなく設計の不備の表れです"
        f"（PR-AUC も {FUTURE_LEAK_PR_AUC:.4f} まで跳ねます）"
    )


if __name__ == "__main__":
    main()
