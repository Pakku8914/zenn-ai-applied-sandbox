#!/usr/bin/env python3
"""実行環境のレポート。本文に書く実測値の「測定環境」として引用する。"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def read_meminfo_gb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        return None
    return None


def main() -> None:
    print("=== 実行環境 ===")
    print(f"Python           : {platform.python_version()}")
    print(f"プラットフォーム : {platform.platform()}")
    print(f"アーキテクチャ   : {platform.machine()}")
    print(f"CPU 数           : {os.cpu_count()}")
    mem = read_meminfo_gb()
    print(f"メモリ           : {mem:.1f} GB" if mem else "メモリ           : 取得できません")

    print("\n=== 主要ライブラリ ===")
    from importlib.metadata import PackageNotFoundError, version

    # モジュールに __version__ が無いパッケージ（qdrant-client など）もあるため
    # パッケージのメタデータから取る
    for module_name, dist_name in (
        ("torch", "torch"),
        ("transformers", "transformers"),
        ("sentence_transformers", "sentence-transformers"),
        ("qdrant_client", "qdrant-client"),
        ("janome", "janome"),
        ("numpy", "numpy"),
    ):
        try:
            __import__(module_name)
        except ImportError:
            print(f"{module_name:<22}: 未インストール")
            continue
        try:
            print(f"{module_name:<22}: {version(dist_name)}")
        except PackageNotFoundError:
            print(f"{module_name:<22}: 不明")

    print("\n=== Qdrant ===")
    try:
        from ragkit.dense import DenseIndex

        client = DenseIndex("dummy").client
        cols = [c.name for c in client.get_collections().collections]
        print(f"接続             : OK（{os.environ.get('QDRANT_URL')}）")
        print(f"コレクション     : {cols or 'なし'}")
        for name in cols:
            info = client.get_collection(name)
            print(f"  - {name}: points={info.points_count}")
    except Exception as exc:  # noqa: BLE001
        print(f"接続             : NG（{type(exc).__name__}: {exc}）")

    print("\n=== モデルキャッシュ ===")
    hf_home = Path(os.environ.get("HF_HOME", "/models"))
    if hf_home.exists():
        total = sum(f.stat().st_size for f in hf_home.rglob("*") if f.is_file())
        print(f"{hf_home}      : {total / 1024 / 1024:.0f} MB")
    else:
        print(f"{hf_home}      : 未作成（初回実行時にダウンロードされます）")


if __name__ == "__main__":
    main()
