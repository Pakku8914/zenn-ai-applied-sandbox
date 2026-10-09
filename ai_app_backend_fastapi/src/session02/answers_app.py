"""練習問題1・2・4・5の解答をまとめて載せたアプリ。

起動：APP_MODULE=src.session02.answers_app:app docker compose up -d api
"""

from __future__ import annotations

from fastapi import FastAPI

from src.session02 import q1_users, q2_filters, q4_fixed, q5_domain_errors
from src.session02.app import lifespan
from src.session02.errors import install_error_handlers


def build_app() -> FastAPI:
    app = FastAPI(title="こんだてAI（Session 2 解答）", lifespan=lifespan)
    install_error_handlers(app)
    q5_domain_errors.install_domain_handlers(app)
    for module in (q1_users, q2_filters, q4_fixed, q5_domain_errors):
        app.include_router(module.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}  # compose の healthcheck 用

    return app


app = build_app()
