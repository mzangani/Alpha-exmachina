"""Punto d'ingresso dell'applicazione FastAPI.

Avvio in sviluppo:
    uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, settings
from app.database import init_db

# Logging di base: gli agenti e gli endpoint scrivono qui i loro log.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Codice eseguito all'avvio (prima riga) e allo spegnimento (dopo yield)."""
    init_db()  # crea le tabelle SQLite se non esistono
    yield


app = FastAPI(
    title="MicroGarden",
    description="Il tuo balcone diventa un giardino voxel, con due agenti AI.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict:
    """Verifica rapida che il server sia vivo e in quale modalità gira."""
    return {"status": "ok", "mock_mode": settings.mock_mode}


# Il frontend è UNA sola pagina statica servita da /static/index.html
app.mount("/static", StaticFiles(directory=BASE_DIR / "static", html=True), name="static")
