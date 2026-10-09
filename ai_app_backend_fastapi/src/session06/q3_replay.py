"""後半の練習問題1：Last-Event-ID から、再送する範囲を選ぶ。"""

from __future__ import annotations

from .resume import parse_last_event_id


def replay_slice(entries: list[dict], raw: str | None) -> list[dict]:
    """entries（id は "1" から連番）のうち、Last-Event-ID より後ろを返す。

    - ヘッダなし・空・"0" → 全部
    - 保存済みの最後の id より大きい → ValueError（別のストリームの id か、壊れた値）
    - 数字以外（全角数字・負の数・小数を含む）→ ValueError
    """
    after = parse_last_event_id(raw)  # 形式の検査は本文の関数に任せる（ASCII の数字 1〜9 桁だけ通す）
    last = int(entries[-1]["id"]) if entries else 0
    if after > last:
        raise ValueError(f"Last-Event-ID {after} は保存済みの最後の id {last} より大きい")
    return [e for e in entries if int(e["id"]) > after]
