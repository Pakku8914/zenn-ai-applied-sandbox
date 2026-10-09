"""練習問題5：HTTP を知らないドメイン例外を、例外ハンドラで共通のエラー本文に変える。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, FastAPI, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.session02.deps import StoreDep
from src.session02.errors import ErrorResponse, error_response
from src.session02.store import DataStore

router = APIRouter(tags=["q5"])


class RecipeNotFoundError(LookupError):
    """データ層の例外。HTTP の状態コードを知らない。"""

    def __init__(self, recipe_id: str) -> None:
        super().__init__(recipe_id)
        self.recipe_id = recipe_id


def find_recipe_or_raise(store: DataStore, recipe_id: str) -> dict:
    recipe = store.get_recipe(recipe_id)
    if recipe is None:
        raise RecipeNotFoundError(recipe_id)
    return recipe


async def _on_recipe_not_found(request: Request, exc: RecipeNotFoundError) -> JSONResponse:
    return error_response(request, 404, "not_found", f"レシピが見つかりません：{exc.recipe_id}")


def install_domain_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RecipeNotFoundError, _on_recipe_not_found)


class RecipeSteps(BaseModel):
    id: str
    name: str
    steps: list[str]


@router.get("/api/recipes/{recipe_id}/steps", response_model=RecipeSteps, responses={404: {"model": ErrorResponse}})
async def get_steps(recipe_id: Annotated[str, Path(pattern=r"^R\d{3}$")], store: StoreDep) -> dict:
    return find_recipe_or_raise(store, recipe_id)
