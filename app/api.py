from pathlib import Path

import asyncpg
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

from app.config import LaunchConfig, Settings
from app.initdata import InvalidInitData, validate_init_data
from app.stats import collect

INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"


def create_app(pool: asyncpg.Pool, settings: Settings, cfg: LaunchConfig) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None)

    def check_access(authorization: str) -> None:
        if settings.dashboard_dev and not authorization:
            return
        scheme, _, init_data = authorization.partition(" ")
        if scheme != "tma" or not init_data:
            raise HTTPException(401, "Откройте дашборд из Telegram")
        try:
            user = validate_init_data(init_data, settings.bot_token)
        except InvalidInitData:
            raise HTTPException(401, "Подпись Telegram не прошла проверку")
        if user.get("id") not in settings.admins:
            raise HTTPException(403, "Нет доступа: ваш id не в ADMIN_IDS")

    @app.get("/api/stats")
    async def stats(authorization: str = Header("")):
        check_access(authorization)
        return await collect(pool, cfg)

    @app.get("/healthz")
    async def healthz():
        await pool.fetchval("SELECT 1")
        return {"ok": True}

    @app.get("/")
    async def index():
        return FileResponse(INDEX, headers={"Cache-Control": "no-store"})

    return app
