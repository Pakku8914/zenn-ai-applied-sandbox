"""Session 2：FastAPI と async の基礎（LLM はまだ呼ばない）。

起動：APP_MODULE=src.session02.app:app docker compose up -d api
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx2
from fastapi import FastAPI, Path, Query

from src.session02.demo import router as demo_router
from src.session02.deps import ClockDep, HttpDep, SettingsDep, StoreDep
from src.session02.errors import ApiError, ErrorResponse, install_error_handlers
from src.session02.models import ConsultationIn, ConsultationOut, RecipeDetail, RecipeList, RecipeQuery
from src.session02.store import DataStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 起動時：リクエストを受け付ける前に1回だけ動く
    app.state.store = DataStore.load()
    app.state.http = httpx2.AsyncClient(timeout=2.0)
    try:
        yield
    finally:
        # 終了時：受け付けを止めたあとに1回だけ動く
        await app.state.http.aclose()


app = FastAPI(title="こんだてAI（Session 2）", lifespan=lifespan)
install_error_handlers(app)
app.include_router(demo_router)

NOT_FOUND = {404: {"model": ErrorResponse, "description": "見つからない"}}


@app.get("/health")
async def health(store: StoreDep) -> dict[str, object]:
    return {"status": "ok", "recipes": len(store.recipes), "users": len(store.users)}


@app.get("/health/upstream")
async def health_upstream(http: HttpDep, settings: SettingsDep) -> dict[str, str]:
    try:
        r = await http.get(f"{settings.mockllm_url}/_mock/health")
        r.raise_for_status()
    except httpx2.HTTPError:
        raise ApiError(503, "upstream_unavailable", "AI が一時的に利用できません。時間をおいて再度お試しください。") from None
    return {"mockllm": "ok"}


@app.get("/api/recipes", response_model=RecipeList)
async def list_recipes(q: Annotated[RecipeQuery, Query()], store: StoreDep) -> dict[str, object]:
    hits = store.find_recipes(ingredient=q.ingredient, max_minutes=q.max_minutes, tags=q.tag)
    # 辞書のまま返しても、response_model（RecipeList）に載っている項目だけが応答に出る
    return {"total": len(hits), "recipes": hits[: q.limit]}


@app.get("/api/recipes/{recipe_id}", response_model=RecipeDetail, responses=NOT_FOUND)
async def get_recipe(recipe_id: Annotated[str, Path(pattern=r"^R\d{3}$")], store: StoreDep) -> dict:
    recipe = store.get_recipe(recipe_id)
    if recipe is None:
        raise ApiError(404, "not_found", f"レシピが見つかりません：{recipe_id}")
    return recipe


@app.post("/api/consultations", status_code=201, response_model=ConsultationOut, responses=NOT_FOUND)
async def create_consultation(body: ConsultationIn, store: StoreDep, clock: ClockDep) -> ConsultationOut:
    user = store.get_user(body.user_id)
    if user is None:
        raise ApiError(404, "not_found", f"ユーザーが見つかりません：{body.user_id}")
    return ConsultationOut(
        user_id=body.user_id,
        household_size=user["household_size"],
        allergies=user["allergies"],
        message=body.message,
        max_minutes=body.max_minutes,
        received_at=clock.now(),
    )
