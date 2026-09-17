"""問題1 の解答: Pipeline ごと保存し、読み込んで予測が一致することを確かめる。

使い方:
    docker compose exec lab python src/session28/q1_save_load.py
"""

from __future__ import annotations

import joblib
import numpy as np

from common import OUT_DIR, build_meta, load_model, repeat_bundle, save_model

Q1_PATH = OUT_DIR / "s28_q1_model.joblib"


def analyze() -> dict:
    """保存 → 読み込み → 予測の一致を 1 つの辞書にまとめる。"""
    bundle = repeat_bundle()
    info = save_model(bundle["model"], build_meta(bundle), Q1_PATH)

    model, meta, differences = load_model(Q1_PATH)
    restored = model.predict_proba(bundle["X_test"])[:, 1]
    original_class = bundle["model"].predict(bundle["X_test"])
    restored_class = model.predict(bundle["X_test"])

    payload = joblib.load(Q1_PATH)  # 中身の形を確かめる（自分で保存したファイルだけ読む）
    return {
        "name": info["name"],
        "kb": info["kb"],
        "n_test": int(len(bundle["X_test"])),
        "allclose": bool(np.allclose(restored, bundle["proba"])),
        "max_difference": float(np.max(np.abs(restored - bundle["proba"]))),
        "same_class": int((original_class == restored_class).sum()),
        "n_version_differences": len(differences),
        "payload_type": type(payload).__name__,
        "payload_size": len(payload),
        "model_type": type(payload[0]).__name__,
        "meta_type": type(payload[1]).__name__,
        "meta_keys": len(meta),
    }


def main() -> None:
    result = analyze()

    print("■ 1. 保存する")
    print(f"保存先: outputs/{result['name']}")
    print(f"ファイルサイズ: {result['kb']:.1f} KB")
    print()

    print("■ 2. 読み込んで比べる")
    print(f"評価データ: {result['n_test']:,} 件")
    print(f"np.allclose : {result['allclose']}")
    print(f"最大の差    : {result['max_difference']:.1e}")
    print(f"クラスの一致: {result['same_class']:,} / {result['n_test']:,} 件")
    print(f"バージョンの食い違い: {result['n_version_differences']} 件")
    print()

    print("■ 3. 読み込んだものの形")
    print(f"中身の型: {result['payload_type']}（要素 {result['payload_size']} 個）")
    print(f"1 つ目: {result['model_type']}")
    print(f"2 つ目: {result['meta_type']}（キー {result['meta_keys']} 個）")
    print()

    print("■ 4. なぜ Pipeline ごと保存するのか（3 文）")
    print("前処理を別に保存すると、推論する側で同じ手順を書き直すことになります。")
    print("書き直した手順は必ずどこかでずれ、ずれても例外は出ないので気づけません。")
    print("Pipeline ごと保存すれば、推論側の仕事は predict_proba を呼ぶだけになります。")


if __name__ == "__main__":
    main()
