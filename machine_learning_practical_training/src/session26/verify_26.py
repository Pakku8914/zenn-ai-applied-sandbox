"""セッション 26 の検証スクリプト。

「セッション26：モデルの解釈 ― importance と SHAP」の本文・練習問題・解答に載せた
数値と挙動が、いまこの環境で再現できるかを確認します。
期待値と一致しない場合は非 0 で終了します。

使い方:
    docker compose exec lab python src/session26/verify_26.py
"""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path

import interpretation_checklist
import numpy as np
import partial_dependence_plot
import permutation_train_vs_test
import q1_impurity_ranks
import q2_permutation_eval
import q3_train_vs_eval
import q4_random_id_audit
import q5_one_customer_report
import q6_pdp_and_causality
import random_id_trap
import shap_local
import three_importances
from common import (
    DATA_DIR,
    NUMERIC,
    OUT_DIR,
    RANDOM_ID,
    fitted,
    impurity_table,
    pdp_int_error,
    pdp_table,
    permutation_table,
    shap_bundle,
    shap_local_check,
    shap_mean_abs,
)

TOLERANCE = 0.005  # 指標・SHAP 値の許容誤差（本書共通）

EXPECTED_COUNTS = {"n_rows": 14169, "n_train": 10626, "n_test": 3543}

# 不純度（split ＝ 分割に使われた回数）。9 列すべてを厳密一致で見る
EXPECTED_SPLIT = {
    "body_length": 2669,
    "unit_price": 1327,
    "pages": 1161,
    "published_year": 576,
    "category_実用書": 103,
    "category_児童書": 69,
    "category_ビジネス": 49,
    "category_小説": 25,
    "category_技術書": 21,
}
EXPECTED_SPLIT_TOTAL = 6000  # 木 200 本 × 1 本あたり 30 分割
# gain は上位 5 件を int()（切り捨て）で厳密一致
EXPECTED_GAIN_TOP = [
    ("unit_price", 9185),
    ("body_length", 8792),
    ("pages", 2678),
    ("published_year", 1206),
    ("category_実用書", 1092),
]
# permutation importance（評価データ）の平均と標準偏差
EXPECTED_PERM_TEST = [
    ("unit_price", 0.1908),
    ("category", 0.0969),
    ("body_length", 0.0706),
    ("pages", 0.0303),
    ("published_year", -0.0004),
]
EXPECTED_PERM_TEST_STD = {
    "unit_price": 0.0042,
    "pages": 0.0030,
    "published_year": 0.0023,
    "body_length": 0.0052,
    "category": 0.0117,
}
# 同じ計算を訓練データで行うと全体に大きく出る
EXPECTED_PERM_TRAIN = [
    ("unit_price", 0.3023),
    ("body_length", 0.1886),
    ("category", 0.1481),
    ("pages", 0.1140),
    ("published_year", 0.0344),
]
# 意味のない random_id を足したときの見え方
EXPECTED_RANDOM_ID = {
    "n_columns": 10,
    "split": 1599,
    "split_rank": 2,
    "gain": 4268,
    "gain_rank": 3,
    "top_split_feature": "body_length",
    "top_split": 1644,
    "perm_test": 0.0031,
    "perm_train": 0.0940,
    "roc_auc_plain": 0.7966,
    "roc_auc_noisy": 0.7985,
    "auc_diff_text": "+0.002",
}
# SHAP（数値 4 列・全 14,169 件で学習した木 50 本のモデル・先頭 100 行）
EXPECTED_SHAP = {
    "shape": (100, 4),
    "base": 2.1601,
    "mean_abs": {"unit_price": 1.3602, "body_length": 0.5482, "pages": 0.2446, "published_year": 0.0589},
    "row0_values": {"unit_price": 880, "pages": 113, "published_year": 2017, "body_length": 43},
    "row0_shap": {"unit_price": 3.0823, "body_length": 0.5170, "published_year": 0.0702, "pages": -0.2421},
    "total": 3.4274,
    "logit": 5.5874,
    "proba": 0.9963,
}
# 部分依存（grid_resolution=5・訓練データ 10,626 件で平均）
EXPECTED_PDP = {
    "unit_price": {
        "grid_text": ["800", "1,508", "2,215", "2,922", "3,630"],
        "average": [0.9929, 0.8705, 0.7416, 0.6885, 0.5446],
    },
    "body_length": {
        "grid_text": ["20", "66", "112", "158", "204"],
        "average": [0.9269, 0.8426, 0.7905, 0.7469, 0.6167],
    },
}
FIGURES = [
    "s26_importance_compare.png",
    "s26_random_id.png",
    "s26_shap_local.png",
    "s26_partial_dependence.png",
    "s26_q6_pdp.png",
]

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual}")
    if not ok:
        print(f"     期待値: {expected}")
        failures.append(label)


def check_close(label: str, actual: float, expected: float, tol: float = TOLERANCE) -> None:
    ok = abs(actual - expected) <= tol
    print(f"{'OK  ' if ok else 'NG  '} {label}: {actual:.4f}")
    if not ok:
        print(f"     期待値: {expected:.4f} ± {tol}")
        failures.append(label)


missing = [name for name in ("books", "orders", "reviews") if not (Path(DATA_DIR) / f"{name}.csv").exists()]
if missing:
    print(f"NG   データが未生成です: {missing}")
    print("     先に `python tools/make_datasets.py` を実行してください。")
    raise SystemExit(1)

# ------------------------------------------------------------------
# 1. 母集団と分割（src/verify_setup.py の 5 節と同じ条件・同じ並び）
# ------------------------------------------------------------------
bundle = fitted()
check("行数", len(bundle["df"]), EXPECTED_COUNTS["n_rows"])
check("訓練データの件数", len(bundle["X_train"]), EXPECTED_COUNTS["n_train"])
check("評価データの件数", len(bundle["X_test"]), EXPECTED_COUNTS["n_test"])
check("特徴量（変換前）", bundle["features"], ["unit_price", "pages", "published_year", "body_length", "category"])
check("変換後の列数", len(bundle["names"]), 9)
check_close("LightGBM の ROC AUC", bundle["roc_auc"], 0.7966)

# ------------------------------------------------------------------
# 2. 不純度ベースの重要度（split と gain）
# ------------------------------------------------------------------
impurity = impurity_table()
split_map = dict(zip(impurity["feature"], impurity["split"].astype("int64")))
check("split の列名がそろっていること", sorted(split_map), sorted(EXPECTED_SPLIT))
for name, expected in EXPECTED_SPLIT.items():
    check(f"split: {name}", int(split_map[name]), expected)
check("split の合計", int(impurity["split"].sum()), EXPECTED_SPLIT_TOTAL)

gain_sorted = impurity.sort_values("gain", ascending=False)
for rank, (name, expected) in enumerate(EXPECTED_GAIN_TOP, start=1):
    row = gain_sorted.iloc[rank - 1]
    check(f"gain {rank} 位の列", str(row["feature"]), name)
    check(f"gain {rank} 位の値（int で切り捨て）", int(row["gain"]), expected)

split_order = list(impurity.sort_values("split", ascending=False)["feature"])
check("split の 1 位は body_length", split_order[0], "body_length")
check("split と gain で 1 位が入れ替わること", split_order[0] != EXPECTED_GAIN_TOP[0][0], True)
check(
    "gain の 6 位以下が category の列だけであること",
    all(str(name).startswith("category_") for name in gain_sorted["feature"].iloc[5:]),
    True,
)

# ------------------------------------------------------------------
# 3. permutation importance（評価データ／訓練データ）
# ------------------------------------------------------------------
perm_test = permutation_table("test")
check("permutation の行数（category は 1 行にまとまる）", len(perm_test), 5)
for rank, (name, expected) in enumerate(EXPECTED_PERM_TEST, start=1):
    check(f"permutation（評価）{rank} 位の列", str(perm_test.iloc[rank - 1]["feature"]), name)
    check_close(f"permutation（評価）{name}", float(perm_test.iloc[rank - 1]["mean"]), expected)
std_map = dict(zip(perm_test["feature"], perm_test["std"]))
for name, expected in EXPECTED_PERM_TEST_STD.items():
    check_close(f"permutation（評価）の標準偏差 {name}", float(std_map[name]), expected)
check(
    "published_year の permutation が負であること",
    bool(float(perm_test.iloc[-1]["mean"]) < 0),
    True,
)
check(
    "ばらつきが最大の列は category",
    str(perm_test.loc[perm_test["std"].idxmax(), "feature"]),
    "category",
)

perm_train = permutation_table("train")
for rank, (name, expected) in enumerate(EXPECTED_PERM_TRAIN, start=1):
    check(f"permutation（訓練）{rank} 位の列", str(perm_train.iloc[rank - 1]["feature"]), name)
    check_close(f"permutation（訓練）{name}", float(perm_train.iloc[rank - 1]["mean"]), expected)
train_map = dict(zip(perm_train["feature"], perm_train["mean"]))
test_map = dict(zip(perm_test["feature"], perm_test["mean"]))
check(
    "すべての列で訓練データのほうが大きく出ること",
    all(float(train_map[name]) > float(test_map[name]) for name in train_map),
    True,
)

# ------------------------------------------------------------------
# 4. 意味のない random_id（この章の山場）
# ------------------------------------------------------------------
noisy = fitted(True)
check("random_id を足した後の特徴量の数", len(noisy["features"]), 6)
check("random_id が数値列の末尾にあること", noisy["numeric"][-1], RANDOM_ID)
check(
    "random_id は分割前に 1 回だけ振られていること（訓練と評価に同じ列が分かれている）",
    len(noisy["X_train"]) + len(noisy["X_test"]),
    EXPECTED_COUNTS["n_rows"],
)
check(
    "random_id の値が元の表と一致すること（分割後に振り直していない）",
    bool(
        noisy["X_train"][RANDOM_ID].equals(noisy["df"].loc[noisy["X_train"].index, RANDOM_ID])
        and noisy["X_test"][RANDOM_ID].equals(noisy["df"].loc[noisy["X_test"].index, RANDOM_ID])
    ),
    True,
)
check("random_id の最小値が 0 以上", bool(noisy["df"][RANDOM_ID].min() >= 0), True)
check("random_id の最大値が 9,999 以下", bool(noisy["df"][RANDOM_ID].max() <= 9999), True)

audit = random_id_trap.audit()
check("random_id 入りの変換後の列数", audit["n_columns"], EXPECTED_RANDOM_ID["n_columns"])
check("random_id の split", audit["split"], EXPECTED_RANDOM_ID["split"])
check("random_id の split 順位", audit["split_rank"], EXPECTED_RANDOM_ID["split_rank"])
check("random_id の gain（int で切り捨て）", audit["gain"], EXPECTED_RANDOM_ID["gain"])
check("random_id の gain 順位", audit["gain_rank"], EXPECTED_RANDOM_ID["gain_rank"])
check("split の 1 位の列", audit["top_split_feature"], EXPECTED_RANDOM_ID["top_split_feature"])
check("split の 1 位の値", audit["top_split"], EXPECTED_RANDOM_ID["top_split"])
check_close("random_id の permutation（評価）", audit["perm_test"], EXPECTED_RANDOM_ID["perm_test"])
check_close("random_id の permutation（訓練）", audit["perm_train"], EXPECTED_RANDOM_ID["perm_train"])
check_close("random_id なしの ROC AUC", audit["roc_auc_plain"], EXPECTED_RANDOM_ID["roc_auc_plain"])
check_close("random_id ありの ROC AUC", audit["roc_auc_noisy"], EXPECTED_RANDOM_ID["roc_auc_noisy"])
check(
    "本文に載せた AUC の差の表示",
    f"{audit['roc_auc_noisy'] - audit['roc_auc_plain']:+.3f}",
    EXPECTED_RANDOM_ID["auc_diff_text"],
)
check(
    "評価データの permutation が訓練データより 1 桁小さいこと",
    bool(audit["perm_test"] * 10 < audit["perm_train"]),
    True,
)

# ------------------------------------------------------------------
# 5. SHAP（形・基準値・平均絶対値・1 行の分解・加法性）
# ------------------------------------------------------------------
shap_data = shap_bundle()
check("shap_values の形", shap_data["values"].shape, EXPECTED_SHAP["shape"])
check("expected_value の dtype", shap_data["base_dtype"], "float64")
check("expected_value がスカラーであること", shap_data["base_shape"], ())
check_close("expected_value", shap_data["base"], EXPECTED_SHAP["base"])
check("TreeExplainer の警告が 1 件以上捕まえられていること", len(shap_data["warnings"]) >= 1, True)
check(
    "警告の冒頭が本文に載せた文と一致すること",
    shap_data["warnings"][0] if shap_data["warnings"] else "",
    "UserWarning: LightGBM binary classifier with TreeExplainer shap values output has changed to ...",
)

mean_abs = dict(zip(shap_mean_abs()["feature"], shap_mean_abs()["mean_abs"]))
for name, expected in EXPECTED_SHAP["mean_abs"].items():
    check_close(f"SHAP の平均絶対値 {name}", float(mean_abs[name]), expected)
check(
    "SHAP の平均絶対値の 1 位は unit_price",
    str(shap_mean_abs().iloc[0]["feature"]),
    "unit_price",
)

row0 = shap_data["frame"].iloc[0]
for name, expected in EXPECTED_SHAP["row0_values"].items():
    check(f"1 行目の {name}", int(row0[name]), expected)
row0_shap = dict(zip(NUMERIC, shap_data["values"][0]))
for name, expected in EXPECTED_SHAP["row0_shap"].items():
    check_close(f"1 行目の SHAP 値 {name}", float(row0_shap[name]), expected)

local = shap_local_check(0)
check_close("SHAP 値の合計", local["total"], EXPECTED_SHAP["total"])
check_close("合計 ＋ 基準値（対数オッズ）", local["logit"], EXPECTED_SHAP["logit"])
check_close("シグモイドで確率に直した値", local["proba_from_shap"], EXPECTED_SHAP["proba"])
check_close("predict_proba の値", local["proba_from_model"], EXPECTED_SHAP["proba"])
check("加法性が成り立つこと（差が 1e-6 未満）", local["matches"], True)
check(
    "合計が 4 列の SHAP 値の和と一致すること",
    bool(abs(local["total"] - float(np.sum(shap_data["values"][0]))) < 1e-12),
    True,
)

# ------------------------------------------------------------------
# 6. 部分依存（int を拒否すること・値）
# ------------------------------------------------------------------
message = pdp_int_error("unit_price")
check("partial_dependence が int 型を拒否すること", "contains integer data" in message, True)
check("エラー文面に列名が含まれること", "unit_price" in message, True)
check(
    "本文に載せたエラーの冒頭が一致すること",
    f"ValueError: {message.split(':', 1)[0]}: ...",
    "ValueError: The column 'unit_price' contains integer data. "
    "Partial dependence plots are not supported for integer data: ...",
)

for feature, expected in EXPECTED_PDP.items():
    table = pdp_table(feature)
    check(f"{feature} の部分依存の点の数", len(table), 5)
    check(
        f"{feature} の部分依存のグリッドの表示",
        [f"{value:,.0f}" for value in table["grid"]],
        expected["grid_text"],
    )
    for index, value in enumerate(expected["average"]):
        check_close(f"{feature} の部分依存 {index + 1} 番目", float(table["average"].iloc[index]), value)
    check(
        f"{feature} は値が大きくなるほど確率が下がること",
        bool(table["average"].iloc[0] > table["average"].iloc[-1]),
        True,
    )

# ------------------------------------------------------------------
# 7. 練習問題の解答コード
# ------------------------------------------------------------------
q1 = q1_impurity_ranks.summary()
check("問題1 の split の合計", q1["split_total"], EXPECTED_SPLIT_TOTAL)
check("問題1 の split の 1 位", q1["split_order"][0], "body_length")
check("問題1 の gain の 1 位", q1["gain_order"][0], "unit_price")
check("問題1 の 1 位が同じかの判定", q1["same_first"], False)
check("問題1 の並びが同じかの判定", q1["same_order"], False)

q2 = q2_permutation_eval.summary()
check("問題2 の 1 位", q2["top"], "unit_price")
check("問題2 の負の列", q2["negative"], ["published_year"])
check("問題2 のばらつき最大の列", q2["widest"], "category")
check("問題2 の『効いている』列", q2["solid"], ["unit_price", "category", "body_length", "pages"])
check("問題2 の評価データの件数", q2["n_test"], EXPECTED_COUNTS["n_test"])

q3 = q3_train_vs_eval.summary()
check("問題3 の訓練で大きく出た列の数", q3["n_train_larger"], 5)
check("問題3 のすべての列で訓練が大きいかの判定", q3["all_train_larger"], True)
check("問題3 の訓練での 1 位", q3["train_top"], "unit_price")
check("問題3 の評価での 1 位", q3["test_top"], "unit_price")

q4 = q4_random_id_audit.audit()
check("問題4 の AUC が変わったかの判定", q4["auc_changed"], False)
check("問題4 の split が騙されたかの判定", q4["split_fooled"], True)
check("問題4 の gain が騙されたかの判定", q4["gain_fooled"], True)
check("問題4 の permutation（訓練）が騙されたかの判定", q4["perm_train_fooled"], True)
check("問題4 の permutation（評価）が騙されたかの判定", q4["perm_test_fooled"], False)
check("問題4 の split の値", q4["split"], EXPECTED_RANDOM_ID["split"])
check_close("問題4 の permutation（評価）", q4["perm_test"], EXPECTED_RANDOM_ID["perm_test"])

q5 = q5_one_customer_report.report()
check("問題5 の説明文の数", len(q5["sentences"]), 4)
check("問題5 のいちばん押し上げた列", q5["plus"], "unit_price")
check("問題5 のいちばん引き下げた列", q5["minus"], "pages")
check("問題5 の押し上げた列の数", q5["n_positive"], 3)
check("問題5 の引き下げた列の数", q5["n_negative"], 1)
check(
    "問題5 の説明文に予測確率が入っていること",
    "0.9963" in q5["sentences"][0],
    True,
)
check("問題5 の検算が一致すること", q5["check"]["matches"], True)

q6 = q6_pdp_and_causality.judge()
check("問題6 の判定表の行数", len(q6), 3)
check_close("問題6 の unit_price の permutation", q6[0]["permutation"], 0.1908)
check_close("問題6 の body_length の permutation", q6[1]["permutation"], 0.0706)
check_close("問題6 の published_year の permutation", q6[2]["permutation"], -0.0004)
check("問題6 で body_length が結果の一部だと判定されること", q6[1]["is_outcome"], "はい")
check("問題6 で published_year が介入できないと判定されること", q6[2]["can_act"], "いいえ")

check("チェックリストの項目数", len(interpretation_checklist.CHECKLIST), 5)
check_close("引用している p 値（セッション16）", interpretation_checklist.PUBLISHED_YEAR_P_VALUE, 0.2425)
year = interpretation_checklist.measures("published_year")
check("published_year の split が 0 でないこと", year["split"] > 0, True)
check_close("published_year の permutation がほぼ 0 であること", year["permutation"], 0.0, tol=0.01)

# ------------------------------------------------------------------
# 8. 全スクリプトが実行でき、図が保存され、フォントが欠けないこと
# ------------------------------------------------------------------
modules = [
    # 本文のスクリプト
    three_importances,
    permutation_train_vs_test,
    random_id_trap,
    shap_local,
    partial_dependence_plot,
    interpretation_checklist,
    # 練習問題の解答
    q1_impurity_ranks,
    q2_permutation_eval,
    q3_train_vs_eval,
    q4_random_id_audit,
    q5_one_customer_report,
    q6_pdp_and_causality,
]
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    with contextlib.redirect_stdout(io.StringIO()):  # 各スクリプトの出力は抑制する
        for module in modules:
            module.main()
glyph_warnings = [w for w in caught if "Glyph" in str(w.message) or "missing from" in str(w.message)]
check("図の描画で出たフォント欠落の警告の数", len(glyph_warnings), 0)

for name in FIGURES:
    path = Path(OUT_DIR) / name
    size = path.stat().st_size if path.exists() else 0
    print(f"---  {name}: {size:,} バイト")
    check(f"{name} が保存され、サイズが 0 より大きいこと", size > 0, True)

print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました: {failures}")
    raise SystemExit(1)
print("セッション 26 のすべての検証に成功しました。")
