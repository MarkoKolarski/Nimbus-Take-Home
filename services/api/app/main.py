from fastapi import FastAPI
from sqlalchemy import text

from app.core.db import engine

app = FastAPI(title="Nimbus API")


@app.get("/health")
def health() -> dict:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
