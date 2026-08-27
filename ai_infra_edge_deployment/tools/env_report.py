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
    total, avail = read_meminfo_gb(), read_meminfo_gb("MemAvailable:")
    print(f"メモリ           : 合計 {total:.1f} GB / 利用可能 {avail:.1f} GB"
          if total and avail else "メモリ           : 取得できません")

    print("\n=== 主要ライブラリ ===")
    for module_name, dist_name in (("httpx", "httpx"), ("fastapi", "fastapi"),
                                   ("onnxruntime", "onnxruntime"), ("numpy", "numpy")):
        try:
            __import__(module_name)
            print(f"{module_name:<14}: {version(dist_name)}")
        except (ImportError, PackageNotFoundError):
            print(f"{module_name:<14}: 未インストール")

    print("\n=== モデル ===")
    gguf = SANDBOX / "models" / "gguf"
    if gguf.exists() and any(gguf.glob("*.gguf")):
        for path in sorted(gguf.glob("*.gguf")):
            print(f"{path.name:<28}{path.stat().st_size / 1024 / 1024:>9.1f} MB")
    else:
        print("GGUF が未作成（README の手順で作成してください）")
    onnx = SANDBOX / "models" / "onnx"
    if onnx.exists() and any(onnx.glob("*.onnx")):
        for path in sorted(onnx.glob("*.onnx")):
            print(f"{path.name:<28}{path.stat().st_size / 1024 / 1024:>9.2f} MB")

    print("\n=== 推論サーバ ===")
    try:
        from infrakit.client import LlamaClient

        client = LlamaClient()
        if client.health():
            props = client.props()
            gen = props.get("default_generation_settings", {})
            print(f"接続             : OK（{client.base_url}）")
            print(f"モデル           : {Path(str(props.get('model_path', ''))).name}")
            print(f"コンテキスト     : {gen.get('n_ctx')}（スロットあたり）")
            print(f"スロット数       : {len(client.slots())}")
        else:
            print(f"接続             : NG（{client.base_url} に届きません）")
    except Exception as exc:  # noqa: BLE001
        print(f"接続             : NG（{type(exc).__name__}: {exc}）")


if __name__ == "__main__":
    main()
