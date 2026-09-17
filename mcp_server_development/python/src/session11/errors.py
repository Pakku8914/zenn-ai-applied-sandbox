"""構造化エラーの共通部品（Python 版）

TypeScript 版（node/src/session11/errors.ts）と同じ 3 要素を持たせます。
Python では「例外を投げる」ことが isError: true に対応するため、
ToolFailure を包む例外クラスを用意します。

このファイルはサーバープロセスの中で動くので print() は使いません（stdout は通信路）。
ログは stderr へ出します。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

ERROR_CODES = (
    "not_found",
    "invalid_state",
    "invalid_argument",
    "forbidden",
    "upstream_unavailable",
    "internal",
)


@dataclass(frozen=True)
class ToolFailure:
    """what（何が起きたか）/ next（どう直すか）/ retryable（再試行の可否）を強制する"""

    code: str
    what: str
    next: str
    retryable: bool
    retry_after_seconds: int | None = None

    def text(self) -> str:
        if self.retryable:
            retry = (
                f"再試行: 可（{self.retry_after_seconds or 1} 秒ほど待ってから"
                "同じ引数で呼び直してください）"
            )
        else:
            retry = "再試行: 不可（引数か対象の状態を変えないと結果は変わりません）"
        return f"[{self.code}] {self.what}\n次の一手: {self.next}\n{retry}"

    def payload(self) -> dict[str, object]:
        """機械可読な error オブジェクト（辞書で返すツール用）"""
        data: dict[str, object] = {"code": self.code, "retryable": self.retryable}
        if self.retry_after_seconds is not None:
            data["retryAfterSeconds"] = self.retry_after_seconds
        return data


class ToolFailureError(Exception):
    """投げると SDK が isError: true のツール結果に変換する"""

    def __init__(self, failure: ToolFailure) -> None:
        super().__init__(failure.text())
        self.failure = failure


def internal_failure(context: str, error: BaseException) -> ToolFailure:
    """例外の中身は stderr にだけ出し、返すのは参照番号だけ"""
    reference = f"E-{abs(hash(context)) % 1000:03d}"
    print(f"[internal] {reference} {context}: {error!r}", file=sys.stderr)
    return ToolFailure(
        code="internal",
        what=f"処理中に内部エラーが発生しました（参照番号 {reference}）。",
        next=(
            "同じ引数で呼び直しても同じ結果になります。"
            "参照番号をユーザーに伝えて、サーバー管理者に確認してもらってください。"
        ),
        retryable=False,
    )
