"""課題7: SHAP で 1 人分の予測を分解し、日本語の説明文にする。

「確率 0.4067」だけでは誰も納得しません。**その顧客のどの情報が確率を押し上げ、
どの情報が押し下げたのか**を並べて初めて、人に説明できる形になります。

使い方:
    docker compose exec lab python src/final01/explain.py
"""

from __future__ import annotations

from common import (
    OPERATING_THRESHOLD,
    decide,
    record_digest,
    sample_record,
    shap_additivity,
    shap_bundle,
    shap_global,
    shap_local,
)

TOP_N = 5  # 説明文に使う寄与の数（多すぎると読めない）


def sentence(row: int = 0) -> str:
    """寄与の大きい順に上位を並べ、そのまま報告に貼れる 1 文にする。"""
    local = shap_local(row).head(TOP_N)
    check = shap_additivity(row)
    pushed_up = [item for item in local.itertuples() if item.shap > 0]
    pushed_down = [item for item in local.itertuples() if item.shap <= 0]
    up = "、".join(f"{item.feature}（値 {item.value}）" for item in pushed_up) or "なし"
    down = "、".join(f"{item.feature}（値 {item.value}）" for item in pushed_down) or "なし"
    verb = "上回った" if check["proba_from_model"] >= OPERATING_THRESHOLD else "下回った"
    return (
        f"この顧客の再購入確率は {check['proba_from_model']:.4f} で、運用の閾値 "
        f"{OPERATING_THRESHOLD:.1f} を{verb}ため「{decide(check['proba_from_model'])}」と判断しました。"
        f"確率を押し上げた要因は {up}、押し下げた要因は {down} です"
        f"（寄与の大きい上位 {TOP_N} 件）。"
    )


def main() -> None:
    bundle = shap_bundle()
    record = sample_record()

    print("■ 1. TreeExplainer に渡すもの")
    print(f"前処理後の行列の形: {bundle['matrix'].shape}")
    print(f"shap_values の形  : {bundle['values'].shape}")
    print(f"expected_value    : dtype {bundle['base_dtype']} / 形 {bundle['base_shape']}")
    print(f"列名の数          : {len(bundle['names'])}（One-Hot で増えた列も 1 列ずつ説明される）")
    print()

    print("■ 2. 出た警告（隠さずに読む）")
    print(f"TreeExplainer に関する警告の数: {len(bundle['warnings'])}")
    for message in bundle["warnings"]:
        print(f"    {message}")
    print("（返り値の形が版によって変わったことを知らせる警告です。形を自分で確かめる合図になります）")
    print()

    print("■ 3. 全体としてどの列が効いたか（SHAP 値の平均絶対値・上位 5 列）")
    for item in shap_global().head(5).itertuples():
        print(f"    {item.feature}: {item.mean_abs:.4f}")
    print()

    print("■ 4. 1 人分の予測を分解する")
    print(f"対象の顧客: {record_digest(record)}")
    for item in shap_local().head(TOP_N).itertuples():
        direction = "押し上げ" if item.shap > 0 else "押し下げ"
        print(f"    {item.feature}（値 {item.value}）: {item.shap:+.4f}（{direction}）")
    print()

    print("■ 5. 加法性の確認（分解が足し算として合っているか）")
    check = shap_additivity()
    print(f"SHAP 値の合計 {check['total']:+.4f} + 基準値 {check['base']:.4f} = 対数オッズ {check['logit']:+.4f}")
    print(f"シグモイド関数を通した確率: {check['proba_from_shap']:.4f}")
    print(f"モデルが直接返す確率      : {check['proba_from_model']:.4f}")
    print(f"一致したか: {check['matches']}")
    print()

    print("■ 6. 報告に貼る説明文")
    print(sentence())


if __name__ == "__main__":
    main()
