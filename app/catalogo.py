"""Accesso al catalogo piante (data/plants.json).

Il catalogo è l'unica fonte di verità sulle caratteristiche botaniche:
il DB salva solo l'id della specie, tutto il resto si legge da qui.
"""

import json
from functools import lru_cache

from app.config import BASE_DIR

PLANTS_PATH = BASE_DIR / "data" / "plants.json"

# Condiviso da advisor.py (mese corrente) e dai router (quando_piantare
# calcolato senza AI per le piante aggiunte manualmente).
MESI_IT = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


@lru_cache
def carica_catalogo() -> list[dict]:
    """Legge e restituisce l'intero catalogo (in cache dopo la prima lettura)."""
    with open(PLANTS_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def catalogo_per_id() -> dict[str, dict]:
    """Il catalogo indicizzato per id: {"basilico": {...}, ...}."""
    return {p["id"]: p for p in carica_catalogo()}


def pianta_per_id(species_id: str) -> dict | None:
    """La scheda di una singola specie, o None se l'id non esiste."""
    return catalogo_per_id().get(species_id)


def descrivi_mesi_semina(mesi: list[int]) -> str:
    """Trasforma [3, 4, 5] in 'marzo, aprile, maggio' per mostrarlo all'utente
    senza dover chiedere all'AI di riformularlo (è solo una lookup)."""
    return ", ".join(MESI_IT[m - 1] for m in sorted(mesi))
