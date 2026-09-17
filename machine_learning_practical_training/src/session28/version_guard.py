"""モデルとバージョンの結びつきを管理する（本文 3 節）。

保存時のバージョンをメタデータに書き残し、読み込むときに突き合わせます。
実務でいちばん多い事故が「作ったときと違うバージョンで読み込む」ことなので、
ここは丁寧に作ります。

使い方:
    docker compose exec lab python src/session28/version_guard.py
"""

from __future__ import annotations

from common import (
    MODEL_PATH,
    OLD_MODEL_PATH,
    build_meta,
    compare_versions,
    load_model,
    repeat_bundle,
    save_model,
    tamper_versions,
)

# 「古いバージョンで作ったモデル」のふりをさせる記録（実際には存在しない組み合わせ）
OLD_VERSIONS = {"scikit-learn": "1.6.1", "lightgbm": "4.5.0"}


def describe_meta() -> dict:
    """メタデータに何を書いたかを取り出す。"""
    bundle = repeat_bundle()
    meta = build_meta(bundle)
    save_model(bundle["model"], meta, MODEL_PATH)  # 本文 1 節と同じファイルを作り直す
    return meta


def audit(meta: dict) -> list[dict]:
    """保存時と現在のバージョンを 1 項目ずつ突き合わせる。"""
    return compare_versions(meta)


def guard_demo(meta: dict) -> dict:
    """記録を古いバージョンに書き換えたファイルを作り、照合が働くかを試す。"""
    bundle = repeat_bundle()
    old_meta = tamper_versions(meta, **OLD_VERSIONS)
    save_model(bundle["model"], old_meta, OLD_MODEL_PATH)

    message = ""
    try:
        load_model(OLD_MODEL_PATH, strict=True)
    except ValueError as exc:  # 期待どおり止まる
        message = f"{type(exc).__name__}: {exc}"

    _, _, differences = load_model(OLD_MODEL_PATH, strict=False)
    return {
        "strict_message": message,
        "differences": differences,
        "n_differences": len(differences),
    }


def print_versions(rows: list[dict]) -> None:
    """突き合わせた結果を表として表示する。"""
    print("ライブラリ    | 保存時  | 現在    | 一致")
    for row in rows:
        mark = "○" if row["same"] else "×"
        print(f"{row['name']:<14}| {str(row['saved']):<8}| {row['current']:<8}| {mark}")


def main() -> None:
    meta = describe_meta()

    print("■ 1. メタデータに何を書いたか")
    print(f"model_name       : {meta['model_name']}")
    print(f"cutoff           : {meta['cutoff']}（特徴量はこの日までの履歴だけで作った）")
    print(f"as_of            : {meta['as_of']}（データの基準日）")
    print(f"horizon_days     : {meta['horizon_days']}（この先何日の再購入を当てるか）")
    print(f"target           : {meta['target']}")
    print(f"numeric          : {len(meta['numeric'])} 列")
    print(f"categorical      : {len(meta['categorical'])} 列（{' / '.join(meta['categorical'])}）")
    print(f"nullable         : {meta['nullable']}（推論でも欠損を受け付ける列）")
    print(f"n_train / n_test : {meta['n_train']:,} 件 / {meta['n_test']:,} 件")
    print(f"positive_rate    : {meta['positive_rate']:.4f}")
    print(f"保存時の性能     : ROC AUC {meta['roc_auc_test']:.4f} / PR-AUC {meta['pr_auc_test']:.4f}")
    print()

    rows = audit(meta)
    print("■ 2. 保存時のバージョンと、いまのバージョンを突き合わせる")
    print_versions(rows)
    print(f"食い違い: {sum(1 for row in rows if not row['same'])} 件")
    print()

    result = guard_demo(meta)
    print("■ 3. 記録を古いバージョンに書き換えて、照合が働くか試す")
    print(f"書き換えた記録: {' / '.join(f'{k} {v}' for k, v in OLD_VERSIONS.items())}")
    print("strict=True で読み込む → 例外で止まる")
    print(f"  {result['strict_message']}")
    print(f"strict=False で読み込む → 読み込めるが、食い違い {result['n_differences']} 件が返る")
    for row in result["differences"]:
        print(f"  {row['name']}: 保存時 {row['saved']} → 現在 {row['current']}")
    print()
    print("判断: バージョンが違っても joblib は黙って読み込むことがあります。")
    print("      『読み込めた』は『同じ予測が出る』の保証ではありません。")
    print("      だから照合は自分で書く必要があります。")


if __name__ == "__main__":
    main()
