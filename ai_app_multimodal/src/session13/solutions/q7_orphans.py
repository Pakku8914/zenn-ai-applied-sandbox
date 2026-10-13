"""問題7：再起動で台帳が消えても、ディスクに残った古いファイル（孤児）を消す。

台帳（PersonalStore）はメモリにあるので、プロセスを再起動すると「どのファイルがいつまでか」が分からなくなる。
そこで起動時に、台帳に無いファイルを更新時刻（mtime）で判定し、保持期限を過ぎたものを消す。

    docker compose exec api python -m src.session13.solutions.q7_orphans
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from kondate.clock import FixedClock
from src.session13.privacy import RETENTION, PersonalStore

OUT = Path("out/s13/q7")


def sweep_orphans(directory: Path, known: set[Path], now: datetime, max_age: timedelta) -> list[str]:
    """台帳に無いファイルのうち、更新から max_age を過ぎたものを消し、消した名前を返す（名前順）。"""
    removed: list[str] = []
    if not directory.is_dir():
        return removed
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path in known:     # 台帳にあるものは、台帳の期限（sweep）に任せる
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=now.tzinfo)
        if now - modified >= max_age:
            path.unlink(missing_ok=True)
            removed.append(path.name)
    return removed


def startup_sweep(state: Any) -> dict[str, list[str]]:
    """起動時に1回呼ぶ。アップロードは24時間、音声は7日で判定する。"""
    now, known = state.clock.now(), state.data.paths()
    return {
        "uploads": sweep_orphans(state.upload_dir, known, now, RETENTION["upload"]),
        "voice": sweep_orphans(state.voice_dir, known, now, RETENTION["voice"]),
    }


def touch(path: Path, at: datetime) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    os.utime(path, (at.timestamp(), at.timestamp()))   # 更新時刻を、注入した時計の時刻に合わせる
    return path


def run() -> list[str]:
    shutil.rmtree(OUT, ignore_errors=True)
    clock = FixedClock()
    now = clock.now()
    uploads, voice = OUT / "uploads", OUT / "voice"
    touch(uploads / "up_old.jpg", now - timedelta(hours=25))       # 台帳に無い・期限切れ → 消す
    touch(uploads / "up_new.jpg", now - timedelta(hours=1))        # 台帳に無い・期限内 → 残す
    known = touch(uploads / "up_known.jpg", now - timedelta(hours=25))  # 台帳にある → 触らない
    touch(voice / "vc_old.wav", now - timedelta(days=8))
    store = PersonalStore(clock)
    store.add("upload", "up_known", "u001", path=known)
    state = type("State", (), {"clock": clock, "data": store, "upload_dir": uploads, "voice_dir": voice})()
    removed = startup_sweep(state)
    left = sorted(p.name for d in (uploads, voice) for p in d.iterdir())
    return [f"削除（uploads）: {removed['uploads']}", f"削除（voice）: {removed['voice']}", f"残す: {left}"]


if __name__ == "__main__":
    print("\n".join(run()))
