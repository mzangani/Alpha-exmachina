"""Endpoint sul catalogo piante."""

from fastapi import APIRouter

from app.catalogo import carica_catalogo

router = APIRouter(prefix="/api/plants", tags=["plants"])


@router.get("/catalog")
def catalog() -> list[dict]:
    """Il contenuto di data/plants.json, usato dal frontend per nomi,
    colori voxel e schede delle piante."""
    return carica_catalogo()
