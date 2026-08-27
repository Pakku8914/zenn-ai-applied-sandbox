#!/usr/bin/env python3
"""実行環境のレポート。本文に書く実測値の「測定環境」として引用する。"""

from __future__ import annotations

import os
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

QUEUE = Path(os.environ.get("RUNNER_QUEUE", "/workspace/runner_queue"))


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
    for module_name, dist_name in (("pytest", "pytest"), ("anthropic", "anthropic")):
        try:
            __import__(module_name)
            print(f"{module_name:<18}: {version(dist_name)}")
        except (ImportError, PackageNotFoundError):
            print(f"{module_name:<18}: 未インストール")

    print("\n=== 隔離実行ワーカー ===")
    print(f"依頼キュー       : {QUEUE}（存在: {QUEUE.exists()}）")
    try:
        from agentkit.sandbox import run_python

        res = run_python("print('pong')", timeout=8)
        print(f"疎通             : {'OK' if res.ok else 'NG'}"
              f"（{res.content.strip() or res.error}）")
    except Exception as exc:  # noqa: BLE001
        print(f"疎通             : NG（{type(exc).__name__}: {exc}）")

    print("\n=== データ ===")
    data = Path(__file__).resolve().parent.parent / "data"
    if data.exists():
        for path in sorted(data.glob("*.jsonl")):
            count = sum(1 for line in path.open(encoding="utf-8") if line.strip())
            print(f"{path.name:<18}: {count} 件")
    else:
        print("data/ が未作成（python tools/make_data.py を実行してください）")


if __name__ == "__main__":
    main()
