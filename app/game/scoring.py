"""Punteggio biodiversità del giardino — Python puro, zero AI.

FORMULA (documentata anche nel README):

    punteggio = (numero di specie diverse × 2)
              + (numero di categorie diverse × 1)
              + (2 se è presente almeno un fiore)
              + somma dei punti_biodiversita di ciascuna specie presente

Nota: i punti_biodiversita si sommano UNA volta per specie presente,
non per ogni esemplare (due basilici non valgono doppio).
"""

from app import models
from app.catalogo import pianta_per_id


def punteggio_biodiversita(plants: list[models.Plant]) -> int:
    """Calcola il punteggio a partire dalle piante di un giardino."""
    specie_presenti: set[str] = set()
    categorie_presenti: set[str] = set()

    for plant in plants:
        scheda = pianta_per_id(plant.species_id)
        if scheda is None:
            continue  # specie sconosciuta (non dovrebbe accadere): ignorata
        specie_presenti.add(scheda["id"])
        categorie_presenti.add(scheda["categoria"])

    punti = len(specie_presenti) * 2
    punti += len(categorie_presenti) * 1
    if "fiore" in categorie_presenti:
        punti += 2
    punti += sum(pianta_per_id(s)["punti_biodiversita"] for s in specie_presenti)
    return punti
