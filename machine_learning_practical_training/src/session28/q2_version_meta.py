"""問題2 の解答: メタデータを付けて保存し、読み込み時にバージョンを照合する。

使い方:
    docker compose exec lab python src/session28/q2_version_meta.py
"""

from __future__ import annotations

from common import (
    OUT_DIR,
    build_meta,
    compare_versions,
    load_model,
    repeat_bundle,
    save_model,
    tamper_versions,
)

Q2_PATH = OUT_DIR / "s28_q2_model.joblib"
Q2_OLD_PATH = OUT_DIR / "s28_q2_model_old.joblib"
OLD_SKLEARN = "1.6.1"  # 「記録だけを古くする」ための値


def analyze() -> dict:
    """正しい記録での照合と、書き換えた記録での照合を両方試す。"""
    bundle = repeat_bundle()
    meta = build_meta(bundle)
    save_model(bundle["model"], meta, Q2_PATH)

    rows = compare_versions(meta)
    _, loaded_meta, differences = load_model(Q2_PATH, strict=True)

    old_meta = tamper_versions(meta, **{"scikit-learn": OLD_SKLEARN})
    save_model(bundle["model"], old_meta, Q2_OLD_PATH)
    message = ""
    try:
        load_model(Q2_OLD_PATH, strict=True)
    except ValueError as exc:
        message = f"{type(exc).__name__}: {exc}"
    _, _, old_differences = load_model(Q2_OLD_PATH, strict=False)

    return {
        "meta_keys": list(loaded_meta),
        "rows": rows,
        "n_differences": len(differences),
        "saved_sklearn": meta["versions"]["scikit-learn"],
        "strict_message": message,
        "old_differences": old_differences,
        "n_old_differences": len(old_differences),
    }


def main() -> None:
    result = analyze()

    print(f"■ 1. メタデータのキー（{len(result['meta_keys'])} 個）")
    print(" / ".join(result["meta_keys"]))
    print()

    print(f"■ 2. 記録したバージョン（{len(result['rows'])} 項目）")
    print("ライブラリ    | 保存時  | 現在    | 一致")
    for row in result["rows"]:
        print(f"{row['name']:<14}| {str(row['saved']):<8}| {row['current']:<8}| {'○' if row['same'] else '×'}")
    print(f"食い違い: {result['n_differences']} 件 → そのまま使ってよい")
    print()

    print("■ 3. 記録を書き換えたファイルで照合する")
    print(f"書き換え: scikit-learn {result['saved_sklearn']} → {OLD_SKLEARN}（記録だけを古くする）")
    print(f"strict=True : {result['strict_message']}")
    print(f"strict=False: 読み込めた（食い違い {result['n_old_differences']} 件）")
    for row in result["old_differences"]:
        print(f"  {row['name']}: 保存時 {row['saved']} → 現在 {row['current']}")
    print()

    print("■ 4. バージョンが違うと何が起きるか（3 文）")
    print("読み込めないことも、読み込めても別の答えを返すことも、どちらもあります。")
    print("後者のほうが危険で、例外も警告も出ないまま予測だけが静かにずれます。")
    print("だから「保存時のバージョンを記録して、読み込み時に照合する」を必ず入れます。")


if __name__ == "__main__":
    main()
