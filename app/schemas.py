"""Contratti JSON dell'applicazione (modelli Pydantic v2).

Questa è la FONTE DI VERITÀ dei dati che circolano tra:
- gli agenti AI (che DEVONO rispondere con JSON conforme a questi schemi),
- il database (che li salva),
- il frontend (che li disegna).

Se un giorno cambi qualcosa qui, stai cambiando il contratto per tutti.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Output dell'Agente 1 — GARDEN ADVISOR
# ---------------------------------------------------------------------------


class Posizione(BaseModel):
    """Coordinate (colonna x, riga z) sulla griglia del giardino voxel."""

    x: int
    z: int


class Spazio(BaseModel):
    """Che spazio è, quanta luce riceve, e cosa ha visto l'AI nella foto."""

    tipo: Literal["balcone", "terrazzo", "davanzale", "giardino"]
    luce_stimata: Literal["pieno_sole", "mezz_ombra", "ombra"]
    note_analisi: str


class ContenitoreRilevato(BaseModel):
    """Un contenitore individuato dall'AI nella foto dello spazio."""

    id: str  # es. "vaso_1"
    tipo: Literal["vaso", "fioriera", "cassetta", "terra"]
    diametro_cm_stimato: int = Field(ge=5, le=300)
    posizione: Posizione


class PiantaConsigliata(BaseModel):
    """Una pianta proposta dall'Advisor per un contenitore specifico."""

    plant_id: str          # deve essere un id presente in data/plants.json
    contenitore_id: str    # deve riferirsi a un id in contenitori_rilevati
    motivo: str
    quando_piantare: str


class GardenPlan(BaseModel):
    """Il piano completo del giardino prodotto dall'Agente 1."""

    spazio: Spazio
    contenitori_rilevati: list[ContenitoreRilevato]
    piante_consigliate: list[PiantaConsigliata]
    consigli_generali: list[str]

    @field_validator("consigli_generali")
    @classmethod
    def massimo_tre_consigli(cls, v: list[str]) -> list[str]:
        """Il prompt chiede max 3 consigli: se l'AI esagera, teniamo i primi 3
        invece di far fallire tutta la richiesta."""
        return v[:3]


# ---------------------------------------------------------------------------
# Output dell'Agente 2 — GROWTH TRACKER
# ---------------------------------------------------------------------------


class GrowthReport(BaseModel):
    """La valutazione di una foto di progresso prodotta dall'Agente 2."""

    # 0.0 = appena piantata, 1.0 = matura/pronta al raccolto.
    # È il valore che il frontend mappa sugli "stadi" voxel.
    stadio: float = Field(ge=0.0, le=1.0)
    salute: Literal["ottima", "buona", "sofferente", "critica"]
    problemi: list[str]
    consigli: list[str]
    frutti_visibili: bool
    giorni_al_raccolto_stimati: Optional[int] = None

    # Anti-cheat: 1.0 = foto perfettamente plausibile rispetto alla
    # precedente; sotto 0.5 il report viene marcato "flagged" e non
    # assegna badge né streak.
    coerenza: float = Field(ge=0.0, le=1.0)
    note_coerenza: str

    @field_validator("consigli")
    @classmethod
    def massimo_tre_consigli(cls, v: list[str]) -> list[str]:
        return v[:3]


# ---------------------------------------------------------------------------
# Schemi di risposta delle API (backend → frontend)
# ---------------------------------------------------------------------------


class AnalyzeResponse(BaseModel):
    """Risposta di POST /api/garden/analyze."""

    garden_id: int
    plan: GardenPlan


class BadgeOut(BaseModel):
    """Un badge sbloccato, come lo vede il frontend."""

    badge_id: str
    nome: str


class ConsociazioneOut(BaseModel):
    """Un messaggio di consociazione (amici o nemici) tra due piante vicine."""

    tipo: Literal["amici", "nemici"]
    piante: list[str]      # nomi leggibili delle due piante coinvolte
    messaggio: str


class PlantStateOut(BaseModel):
    """Lo stato corrente di una pianta per il rendering voxel."""

    plant_id: int          # id numerico nel DB (usato dagli endpoint update/move)
    species_id: str        # id della specie in plants.json
    nome: str
    categoria: str
    colore_voxel: str
    container_id: int
    # Ultimo GrowthReport registrato (None se mai fotografata)
    stadio: float = 0.0
    salute: str = "buona"
    frutti_visibili: bool = False
    problemi: list[str] = []
    consigli: list[str] = []
    giorni_al_raccolto_stimati: Optional[int] = None
    flagged: bool = False
    motivo: str = ""
    n_aggiornamenti: int = 0


class ContainerOut(BaseModel):
    """Un contenitore per il rendering voxel."""

    container_id: int
    codice: str
    tipo: str
    diametro_cm: int
    posizione: Posizione


class GardenStateOut(BaseModel):
    """Risposta di GET /api/garden/{id}: tutto ciò che serve al frontend."""

    garden_id: int
    tipo_spazio: str
    luce_stimata: str
    note_analisi: str
    citta: str
    containers: list[ContainerOut]
    plants: list[PlantStateOut]
    punteggio_biodiversita: int
    badges: list[BadgeOut]
    consociazioni: list[ConsociazioneOut]


class UpdateResponse(BaseModel):
    """Risposta di POST /api/plant/{id}/update."""

    report: GrowthReport
    flagged: bool
    nuovi_badge: list[BadgeOut]
    punteggio_biodiversita: int


class MoveRequest(BaseModel):
    """Body di PATCH /api/plant/{id}/move."""

    container_id: int


class MoveResponse(BaseModel):
    """Risposta di PATCH /api/plant/{id}/move."""

    plant_id: int
    container_id: int
    consociazioni: list[ConsociazioneOut]
