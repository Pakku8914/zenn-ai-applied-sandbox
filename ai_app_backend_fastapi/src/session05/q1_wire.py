"""練習問題1の解答：SSE の1ブロックを手で組み立てる。"""

from __future__ import annotations


def _single_line(name: str, value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError(f"{name} に改行を含めることはできません")
    return value


def encode_sse(data: str | None = None, *, event: str | None = None, id: str | None = None,
               retry: int | None = None) -> str:
    """id → event → data（改行ごとに1行）→ retry の順に並べ、空行で閉じる。"""
    lines: list[str] = []
    if id is not None:
        if "\0" in id:
            raise ValueError("id に NUL 文字を含めることはできません")  # ブラウザはこの id を無視する
        lines.append(f"id: {_single_line('id', id)}")
    if event is not None:
        lines.append(f"event: {_single_line('event', event)}")
    if data is not None:
        normalized = data.replace("\r\n", "\n").replace("\r", "\n")
        lines += [f"data: {part}" for part in normalized.split("\n")]
    if retry is not None:
        if isinstance(retry, bool) or not isinstance(retry, int) or retry < 0:
            raise ValueError("retry は 0 以上の整数（ミリ秒）です")
        lines.append(f"retry: {retry}")
    if not lines:
        raise ValueError("中身のないブロックは作れません")
    return "\n".join(lines) + "\n\n"


def encode_comment(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(f": {part}\n" for part in normalized.split("\n")) + "\n"
