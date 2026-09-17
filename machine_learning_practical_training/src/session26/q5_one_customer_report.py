"""問題5: SHAP 値から「このお客さま 1 人への説明文」を組み立てて検算する。

使い方:
    docker compose exec lab python src/session26/q5_one_customer_report.py
"""

from __future__ import annotations

from common import shap_bundle, shap_local, shap_local_check

ROW = 0  # 説明する行（先頭のレビュー）

# 読み手に通じる日本語の名前（列名をそのまま見せない）
LABELS = {
    "unit_price": "本の単価",
    "pages": "ページ数",
    "published_year": "出版年",
    "body_length": "レビュー本文の長さ",
}


def report(row: int = ROW) -> dict:
    """1 件の予測の説明文（4 文）と、検算に使う数値をまとめて返す。"""
    table = shap_local(row)
    check = shap_local_check(row)
    plus = table.iloc[0]  # いちばん押し上げた特徴量
    minus = table.iloc[-1]  # いちばん引き下げた特徴量

    sentences = [
        f"このレビューが高評価（星 4 以上）になる確率を {check['proba_from_model']:.4f} と予測しました。",
        f"最も効いたのは{LABELS[plus.feature]}が {int(plus.value):,} であることで、"
        f"対数オッズを {plus.shap:+.4f} 動かしています。",
        f"逆に{LABELS[minus.feature]}が {int(minus.value):,} であることは {minus.shap:+.4f} と、"
        "確率を下げる向きに働きました。",
        f"4 つの寄与の合計 {check['total']:.4f} に基準値 {check['base']:.4f} を足すと {check['logit']:.4f} になり、"
        f"シグモイド関数に通すと {check['proba_from_shap']:.4f} ＝ モデルの出力と一致します。",
    ]
    return {
        "sentences": sentences,
        "table": table,
        "check": check,
        "plus": str(plus.feature),
        "minus": str(minus.feature),
        "n_positive": int((table["shap"] > 0).sum()),
        "n_negative": int((table["shap"] < 0).sum()),
    }


def main() -> None:
    bundle = shap_bundle()
    result = report()

    print("■ 1. 説明したい 1 行の中身")
    for name, value in bundle["frame"].iloc[ROW].items():
        # 出版年に桁区切りを入れたくないので、ここは , を付けない
        print(f"{LABELS[name]}（{name}）: {int(value)}")
    print()

    print("■ 2. SHAP 値の内訳（対数オッズをどれだけ動かしたか）")
    print(f"{'特徴量':<16}{'値':>6}{'SHAP 値':>10}  向き")
    for row in result["table"].itertuples(index=False):
        direction = "押し上げ" if row.shap > 0 else "引き下げ"
        print(f"{row.feature:<16}{int(row.value):>6}{row.shap:>+10.4f}  {direction}")
    print(f"押し上げた列 {result['n_positive']} 個 / 引き下げた列 {result['n_negative']} 個")
    print()

    print("■ 3. お客さま 1 人への説明文")
    for sentence in result["sentences"]:
        print(sentence)
    print()

    check = result["check"]
    print("■ 4. 検算")
    print(f"SHAP の合計 ＋ 基準値 = {check['logit']:.4f}")
    print(f"シグモイド関数で確率  = {check['proba_from_shap']:.4f}")
    print(f"predict_proba の値    = {check['proba_from_model']:.4f}")
    print(f"一致するか            = {check['matches']}")


if __name__ == "__main__":
    main()
