"""問題5：start の store_audio に5通りの値を送り、ready の store_audio と保存した WAV の数を表にする。

    docker compose exec api python -m src.session13.solutions.q5_consent_cases
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from src.session13.app import app
from src.session13.logmask import masked_handler
from src.session13.testkit import Collect, count_files, sandboxed, voice_turn

OUT = Path("out/s13/q5")
CASES = [
    ("store_audio なし", {}),
    ("store_audio=false", {"store_audio": False}),
    ('store_audio="true"', {"store_audio": "true"}),
    ("store_audio=1", {"store_audio": 1}),
    ("store_audio=true", {"store_audio": True}),
]


async def run() -> list[str]:
    logging.getLogger("src.session13").handlers[:] = [masked_handler(Collect())]   # 表を見やすくするためログは集めるだけ
    lines = []
    async with app.router.lifespan_context(app):
        for label, extra in CASES:
            with sandboxed(app, OUT) as state:              # 1件ごとに、台帳と置き場所を新しくする
                log, _ = await voice_turn(app, {"type": "start", "sample_rate": 16000, **extra})
                saved = count_files(state.voice_dir)
            lines.append(f"{label} → ready.store_audio={log[0]['store_audio']}・保存 {saved} 件")
    return lines


if __name__ == "__main__":
    print("\n".join(asyncio.run(run())))
