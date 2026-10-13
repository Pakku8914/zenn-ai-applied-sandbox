"""問題3：上限付きで読む read_capped() と、全部読んでから測る版の比較。

    docker compose exec api python -m src.session02.solutions.p3_read_capped
"""

from __future__ import annotations

import asyncio
import io

from fastapi import UploadFile

MiB = 1024 * 1024
LIMIT = 1 * MiB


class TooLarge(Exception):
    pass


async def read_all_then_check(upload: UploadFile, limit: int) -> bytes:
    """Bad：全部読んでから測る。"""
    raw = await upload.read()
    if len(raw) > limit:
        raise TooLarge(limit)
    return raw


async def read_capped(upload: UploadFile, limit: int) -> bytes:
    """Good：上限より1バイトだけ多く読み、読めてしまったら上限超え。"""
    raw = await upload.read(limit + 1)
    if len(raw) > limit:
        raise TooLarge(limit)
    return raw


class CountingFile(io.BytesIO):
    """read() で取り出したバイト数を数える BytesIO（メモリに載せた量の目安）。"""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.consumed = 0

    def read(self, size: int | None = -1) -> bytes:
        chunk = super().read(size)
        self.consumed += len(chunk)
        return chunk


LABELS = {read_all_then_check: "全部読んでから測る", read_capped: "上限+1だけ読む"}
CASES = [("ちょうど上限", LIMIT), ("上限+1バイト", LIMIT + 1), ("5MiB", 5 * MiB)]


async def _run() -> list[str]:
    lines = []
    for label, size in CASES:
        for fn, name in LABELS.items():
            f = CountingFile(b"x" * size)
            try:
                await fn(UploadFile(file=f, filename="upload.bin"), LIMIT)
                result = "受け付け"
            except TooLarge:
                result = "TooLarge"
            lines.append(f"{label}／{name} → {result}（読んだ {f.consumed:,} バイト）")
    return lines


def run() -> list[str]:
    return asyncio.run(_run())


if __name__ == "__main__":
    print("\n".join(run()))
