"""Pipeline ごと保存し、読み込んで同じ予測が出ることを確かめる（本文 1〜2 節）。

使い方:
    docker compose exec lab python src/session28/save_and_load.py
"""

from __future__ import annotations

import numpy as np

from common import (
    AS_OF,
    CUTOFF,
    LABEL_START,
    MODEL_PATH,
    build_meta,
    load_model,
    repeat_bundle,
    save_model,
)


def save() -> dict:
    """学習済みの Pipeline とメタデータを 1 つのファイルにする。"""
    bundle = repeat_bundle()
    info = save_model(bundle["model"], build_meta(bundle))
    return {
        "n_rows": int(len(bundle["df"])),
        "n_positive": int(bundle["y"].sum()),
        "positive_rate": float(bundle["y"].mean()),
        "n_train": int(len(bundle["X_train"])),
        "n_test": int(len(bundle["X_test"])),
        "steps": list(bundle["model"].named_steps),
        **info,
    }


def reload() -> dict:
    """読み込んだモデルの予測が、いま手元にあるモデルの予測と一致するかを確かめる。"""
    bundle = repeat_bundle()
    model, meta, differences = load_model(MODEL_PATH)
    restored = model.predict_proba(bundle["X_test"])[:, 1]
    difference = float(np.max(np.abs(restored - bundle["proba"])))
    return {
        "steps": list(model.named_steps),
        "n_test": int(len(bundle["X_test"])),
        "allclose": bool(np.allclose(restored, bundle["proba"])),
        "max_difference": difference,
        "n_version_differences": len(differences),
        "meta_keys": list(meta),
    }


def main() -> None:
    saved = save()

    print("■ 1. 学習して保存する")
    print(f"対象顧客: {saved['n_rows']:,} 人（{CUTOFF.date()} までに有効注文がある顧客）")
    print(
        f"再購入した顧客: {saved['n_positive']:,} 人"
        f"（{LABEL_START.date()}〜{AS_OF.date()}）"
        f" → 正例率 {saved['positive_rate']:.4f}"
    )
    print(f"訓練 {saved['n_train']:,} 件 / 評価 {saved['n_test']:,} 件")
    print()
    print(f"保存しました: outputs/{saved['name']}")
    print(f"ファイルサイズ: {saved['kb']:.1f} KB")
    print("中身: (Pipeline, メタデータ) のタプル")
    print(f"Pipeline のステップ: {saved['steps']}")
    print()

    restored = reload()
    print("■ 2. 読み込んで、同じ予測が出るか確かめる")
    print(f"読み込んだモデルのステップ: {restored['steps']}")
    print(f"評価データ {restored['n_test']:,} 件の予測を比べる")
    print(f"  np.allclose: {restored['allclose']}")
    print(f"  最大の差   : {restored['max_difference']:.1e}")
    print(f"バージョンの食い違い: {restored['n_version_differences']} 件")
    print()
    print("判断: 保存と読み込みでモデルは一切変わっていません。")
    print("      前処理も含めて 1 つのファイルに入っているので、推論する側は")
    print("      predict_proba を呼ぶだけで済みます（同じ前処理を書き直さない）。")


if __name__ == "__main__":
    main()
