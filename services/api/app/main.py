from fastapi import FastAPI
from sqlalchemy import text

from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.datasources import router as datasources_router
from app.api.routes.directories import router as directories_router
from app.api.routes.documents import router as documents_router
from app.api.routes.sync import router as sync_router
from app.core.db import engine

app = FastAPI(title="Nimbus API")
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(datasources_router)
app.include_router(directories_router)
app.include_router(documents_router)
app.include_router(sync_router)


@app.get("/health")
def health() -> dict:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
