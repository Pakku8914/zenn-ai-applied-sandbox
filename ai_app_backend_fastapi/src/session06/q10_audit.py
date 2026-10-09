"""後半の練習問題3：SSE の応答ヘッダが、プロキシの後ろでも少しずつ届く形になっているかを点検する。"""

from __future__ import annotations

from collections.abc import Mapping


def audit_sse_headers(headers: Mapping[str, str]) -> list[str]:
    """足りないものを文の列で返す（空なら問題なし）。headers は大文字小文字を区別しない辞書を想定する。"""
    problems: list[str] = []
    if not headers.get("content-type", "").startswith("text/event-stream"):
        problems.append("content-type が text/event-stream ではない")
    if "no-cache" not in headers.get("cache-control", ""):
        problems.append("cache-control に no-cache が無い")
    if headers.get("x-accel-buffering") != "no":
        problems.append("x-accel-buffering: no が無い")
    return problems
