"""契約テストの土台（Python 版）"""

from __future__ import annotations

import json
import os
import warnings
from pathlib import Path
from typing import Any

SNAPSHOT_DIR = Path(__file__).resolve().parent / "__snapshots__"


def compare_baseline(name: str, actual: Any) -> None:
    """生のスナップショットをベースラインファイルと比較する。

    初回は作成して警告のみ。CI（SNAPSHOT_CI=1）では作成を失敗にする。
    """
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    file = SNAPSHOT_DIR / f"{name}.json"
    # sort_keys=True でキーの並びを固定する（並び順の揺れで落ちないように）
    serialized = json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    if not file.exists():
        if os.environ.get("SNAPSHOT_CI") == "1":
            raise AssertionError(
                f"ベースラインがありません: {file}（CI では新規作成を許可しません）"
            )
        file.write_text(serialized, encoding="utf-8")
        warnings.warn(f"[snapshot] ベースラインを新規作成しました: {file}", stacklevel=2)
        return

    baseline = json.loads(file.read_text(encoding="utf-8"))
    assert actual == baseline, (
        f"tools/list がベースラインと一致しません（{file}）。"
        "意図した変更なら schema_dump.py で更新し、差分をレビューに載せてください。"
    )


async def call_expecting_failure(client: Any, name: str, arguments: dict[str, Any]) -> str:
    """失敗を「例外」でも「isError」でも受け取れるようにする。

    TypeScript 版は必ず isError で返りますが、Python 側は SDK の版によって
    例外（ToolError / MCPError）で表れることがあります。この差をヘルパー 1 か所に
    閉じ込めておくと、各テストは「失敗すること」だけを素直に書けます。
    """
    try:
        result = await client.call_tool(name, arguments)
    except Exception as error:  # noqa: BLE001 ― 失敗の表現形式を問わず受け止めるのが目的
        return str(error)

    assert result.is_error is True, f"失敗するはずの呼び出しが成功しました: {name} {arguments}"
    return "\n".join(getattr(block, "text", "") or "" for block in result.content)
