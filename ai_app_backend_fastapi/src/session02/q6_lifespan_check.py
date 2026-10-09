"""練習問題6：起動時に共通データを検査し、壊れていたら起動を止める lifespan。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
from fastapi import FastAPI

from kondate.data import EXPECTED_SHA12, sha12
from kondate.settings import get_settings
from src.session02.deps import StoreDep
from src.session02.errors import install_error_handlers
from src.session02.store import DataStore


def check_data(data_dir: Path) -> None:
    for name, expected in EXPECTED_SHA12.items():
        path = data_dir / name
        if not path.exists():
            raise RuntimeError(f"共通データが見つかりません：{name}")
        if sha12(path) != expected:
            raise RuntimeError(f"共通データのハッシュが一致しません：{name}")


def load_store(data_dir: Path) -> DataStore:
    def read(name: str) -> list[dict]:
        return json.loads((data_dir / name).read_text(encoding="utf-8"))

    return DataStore.from_rows(read("recipes.json"), read("users.json"))


def create_app(data_dir: Path) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        check_data(data_dir)  # ① 何かを開く前に検査する（失敗しても閉じ忘れが起きない）
        app.state.store = load_store(data_dir)
        app.state.http = httpx2.AsyncClient(timeout=2.0)
        try:
            yield
        finally:
            await app.state.http.aclose()  # ② yield のあとは、開いたものを閉じる

    app = FastAPI(title="こんだてAI（練習問題6）", lifespan=lifespan)
    install_error_handlers(app)

    @app.get("/health")
    async def health(store: StoreDep) -> dict[str, object]:
        return {"status": "ok", "recipes": len(store.recipes)}

    return app


app = create_app(Path(get_settings().data_dir))
