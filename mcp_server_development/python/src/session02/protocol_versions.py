"""Python SDK が持っているプロトコルバージョン定数を読み出す

SDK の改訂で定数名や置き場所が変わってもスクリプト自体は落ちないように、
importlib と getattr で「探しに行く」書き方にしています。
陳腐化に強い確認スクリプトの書き方の練習でもあります。

実行: docker compose exec python python src/session02/protocol_versions.py
"""

from __future__ import annotations

import importlib
from importlib.metadata import version as package_version
from types import ModuleType

# (モジュール名, 定数名) の組。SDK の構成が変わったらここだけ直す
TARGETS: list[tuple[str, str]] = [
    ("mcp.types", "LATEST_PROTOCOL_VERSION"),
    ("mcp.server.runner", "LATEST_MODERN_VERSION"),
]


def load(module_name: str) -> ModuleType | None:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError:
        return None


def main() -> None:
    print(f"mcp パッケージのバージョン: {package_version('mcp')}")

    for module_name, attr in TARGETS:
        module = load(module_name)
        if module is None:
            print(f"{module_name}.{attr} = （モジュールが見つかりません）")
            continue
        value = getattr(module, attr, None)
        if value is None:
            print(f"{module_name}.{attr} = （定数が見つかりません。改名された可能性があります）")
        else:
            print(f"{module_name}.{attr} = {value}")

    # 定数名が変わっていても見つけられるように、VERSION を含む名前を総なめする
    seen: list[str] = []
    for module_name, _ in TARGETS:
        if module_name not in seen:
            seen.append(module_name)

    for module_name in seen:
        module = load(module_name)
        if module is None:
            continue
        names = sorted(
            name
            for name in dir(module)
            if "VERSION" in name.upper() and not name.startswith("_")
        )
        print(f"\n{module_name} の VERSION を含む名前: {names}")
        for name in names:
            print(f"  {name} = {getattr(module, name)}")


if __name__ == "__main__":
    main()
