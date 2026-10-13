"""faster-whisper のモデルを取得して、名前付きボリューム（/models）にキャッシュする。2回目以降はダウンロードしない。

    docker compose exec api python tools/fetch_whisper.py          # 設定（WHISPER_MODEL）のモデル
    docker compose exec api python tools/fetch_whisper.py tiny base small
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from kondate import stt
from kondate.settings import get_settings


def size_mib(path: str) -> float:
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file()) / 2**20


def main(names: list[str]) -> int:
    for name in names or [get_settings().whisper_model]:
        cached = stt.is_cached(name)
        started = time.perf_counter()
        path = stt.model_path(name)
        elapsed = time.perf_counter() - started
        state = "キャッシュ済み" if cached else f"ダウンロード {elapsed:.1f} 秒"
        print(f"{name}: {size_mib(path):.0f}MiB（{state}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
