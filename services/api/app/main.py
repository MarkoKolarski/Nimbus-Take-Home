from fastapi import FastAPI
from sqlalchemy import text

from app.api.routes.auth import router as auth_router
from app.api.routes.datasources import router as datasources_router
from app.core.db import engine

app = FastAPI(title="Nimbus API")
app.include_router(auth_router)
app.include_router(datasources_router)


@app.get("/health")
def health() -> dict:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
