"""課題8: Pipeline まるごと保存し、読み込んで 1 件だけ推論する。

保存するのは「モデル」ではなく **前処理を含んだ Pipeline とメタデータの組**です。
前処理だけ別に書き直すと、必ずどこかで学習時と食い違います。

使い方:
    docker compose exec lab python src/final01/serve.py
"""

from __future__ import annotations

import numpy as np

from common import (
    FEATURES,
    MODEL_PATH,
    OPERATING_THRESHOLD,
    build_meta,
    compare_versions,
    dataset,
    decide,
    fitted,
    load_model,
    predict_one,
    record_digest,
    sample_record,
    save_model,
    validate_record,
)


def store() -> dict:
    """学習済みの Pipeline とメタデータを保存する。"""
    bundle = fitted("lgbm")
    meta = build_meta("lgbm")
    info = save_model(bundle["model"], meta)
    return {**info, "meta": meta, "steps": [name for name, _ in bundle["model"].steps]}


def restore() -> dict:
    """保存したファイルを読み込み、学習直後のモデルと同じ予測が出るか確かめる。"""
    model, meta, differences = load_model(MODEL_PATH)
    data = dataset()
    before = fitted("lgbm")["proba"]
    after = model.predict_proba(data["X_test"])[:, 1]
    return {
        "meta": meta,
        "differences": differences,
        "steps": [name for name, _ in model.steps],
        "allclose": bool(np.allclose(before, after)),
        "max_difference": float(np.abs(before - after).max()),
        "model": model,
    }


def broken_records(record: dict) -> list[tuple[str, dict]]:
    """わざと壊した入力を 4 通り作る（検証の順番どおりに並べる）。"""
    missing = {name: value for name, value in record.items() if name != "recency"}
    return [
        ("列が足りない（recency を消した）", missing),
        ("数値のはずが文字列（n_orders = '7'）", {**record, "n_orders": "7"}),
        ("範囲から外れている（mean_discount = 1.5）", {**record, "mean_discount": 1.5}),
        ("学習時になかったカテゴリ（channel = 'テレビCM'）", {**record, "channel": "テレビCM"}),
    ]


def try_predict(model, record: dict) -> tuple[float | None, str]:
    """推論を試し、落ちたら例外の型名と文面を返す（落ちること自体を確かめるため）。"""
    try:
        return predict_one(model, record), ""
    except ValueError as exc:
        return None, f"{type(exc).__name__}: {exc}"


def analyze() -> dict:
    """保存・読み込み・1 件推論・入力検証の結果をまとめて返す（検証スクリプト用）。"""
    saved = store()
    restored = restore()
    record = sample_record()
    proba = predict_one(restored["model"], record)
    nullable, _ = try_predict(restored["model"], {**record, "region": None})
    return {
        "kb": saved["kb"],
        "steps": saved["steps"],
        "meta_keys": sorted(saved["meta"].keys()),
        "n_versions": len(saved["meta"]["versions"]),
        "restored_steps": restored["steps"],
        "n_differences": len(restored["differences"]),
        "allclose": restored["allclose"],
        "max_difference": restored["max_difference"],
        "proba": proba,
        "decision": decide(proba),
        "messages": [try_predict(restored["model"], broken)[1] for _, broken in broken_records(record)],
        "region_missing_ok": nullable is not None,
        "n_clean_columns": len(validate_record(record)),
    }


def main() -> None:
    saved = store()
    print("■ 1. 保存する")
    print(f"保存先: outputs/{saved['name']}")
    print(f"ファイルサイズ: {saved['kb']:.1f} KB")
    print(f"保存した Pipeline のステップ: {saved['steps']}")
    print(f"メタデータの項目数: {len(saved['meta'])}（バージョンの記録 {len(saved['meta']['versions'])} 件を含む）")
    print()

    restored = restore()
    print("■ 2. 読み込んで、同じ予測が出ることを確かめる")
    print(f"読み込んだステップ: {restored['steps']}")
    print(f"バージョンの食い違い: {len(restored['differences'])} 件")
    print(f"np.allclose で一致: {restored['allclose']}（最大の差 {restored['max_difference']:.1e}）")
    for row in compare_versions(restored["meta"]):
        print(f"    {row['name']}: 保存時 {row['saved']} / 現在 {row['current']} → 一致 {row['same']}")
    print()

    record = sample_record()
    proba = predict_one(restored["model"], record)
    print("■ 3. 1 件だけ推論する")
    print(f"入力の要点: {record_digest(record)}")
    print(f"（このほかに {len(record) - 3} 列が同じ dict に入っています。渡す列は全部で {len(FEATURES)} 列）")
    print(f"再購入確率: {proba:.4f}")
    print(f"閾値 {OPERATING_THRESHOLD:.1f} との比較 → {decide(proba)}")
    print()

    print("■ 4. おかしな入力は predict の前に落とす")
    for index, (label, broken) in enumerate(broken_records(record), start=1):
        _, message = try_predict(restored["model"], broken)
        print(f"[{index}] {label}")
        print(f"    {message}")
    print()

    print("■ 5. 欠損を許す列は、欠損のまま受け取る")
    nullable, _ = try_predict(restored["model"], {**record, "region": None})
    print(f"region を None にしても推論できたか: {nullable is not None}")
    print(f"検証を通したあとの列の数: {len(validate_record(record))}")
    print()
    print("判断: Pipeline ごと保存すれば、推論する側は『dict を渡す』だけで済みます。")
    print("      前処理を書き直さないことが、いちばん確実なリーク対策でもあります。")


if __name__ == "__main__":
    main()
