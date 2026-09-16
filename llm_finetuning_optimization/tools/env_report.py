#!/usr/bin/env python3
"""実行環境のレポート。本文に書く実測値の「測定環境」として引用する。"""

from __future__ import annotations

import os
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SANDBOX = Path(__file__).resolve().parent.parent


def read_meminfo_gb(key: str = "MemTotal:") -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith(key):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        return None
    return None


def main() -> None:
    print("=== 実行環境 ===")
    print(f"Python           : {platform.python_version()}")
    print(f"アーキテクチャ   : {platform.machine()}")
    print(f"CPU 数           : {os.cpu_count()}")
    total = read_meminfo_gb()
    avail = read_meminfo_gb("MemAvailable:")
    print(f"メモリ           : 合計 {total:.1f} GB / 利用可能 {avail:.1f} GB"
          if total and avail else "メモリ           : 取得できません")
    print(f"OMP_NUM_THREADS  : {os.environ.get('OMP_NUM_THREADS', '未設定')}")

    print("\n=== 主要ライブラリ ===")
    for module_name, dist_name in (
        ("torch", "torch"), ("transformers", "transformers"), ("peft", "peft"),
        ("trl", "trl"), ("datasets", "datasets"), ("onnxruntime", "onnxruntime"),
        ("numpy", "numpy"),
    ):
        try:
            __import__(module_name)
            print(f"{module_name:<16}: {version(dist_name)}")
        except (ImportError, PackageNotFoundError):
            print(f"{module_name:<16}: 未インストール")

    try:
        import torch

        print(f"{'torch (CPU版か)':<16}: {'+cpu' in torch.__version__ or not torch.cuda.is_available()}"
              f"（{torch.__version__}）")
    except ImportError:
        pass

    print("\n=== データセット ===")
    data = SANDBOX / "data"
    if data.exists():
        for path in sorted(data.glob("*.jsonl")):
            count = sum(1 for line in path.open(encoding="utf-8") if line.strip())
            print(f"{path.name:<18}: {count} 件")
    else:
        print("data/ が未作成（python tools/make_dataset.py を実行してください）")

    print("\n=== モデルキャッシュ ===")
    hf_home = Path(os.environ.get("HF_HOME", "/models"))
    if hf_home.exists():
        size = sum(f.stat().st_size for f in hf_home.rglob("*") if f.is_file())
        print(f"{hf_home}: {size / 1024 / 1024:.0f} MB")
    else:
        print(f"{hf_home}: 未作成（初回実行時にダウンロードされます）")

    print("\n=== 生成物 ===")
    for name in ("runs", "export", "gguf", "onnx"):
        path = SANDBOX / name
        if path.exists():
            files = list(path.rglob("*"))
            size = sum(f.stat().st_size for f in files if f.is_file())
            print(f"{name:<10}: {len([f for f in files if f.is_file()]):>4} ファイル "
                  f"{size / 1024 / 1024:>8.1f} MB")


if __name__ == "__main__":
    main()
