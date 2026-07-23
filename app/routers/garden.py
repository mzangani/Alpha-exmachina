"""Endpoint principali del gioco: analisi dello spazio e gestione giardino."""

import json
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from datetime import datetime, timezone

from app import models
from app.agents.advisor import analizza_spazio
from app.agents.tracker import valuta_crescita
from app.catalogo import pianta_per_id
from app.database import get_db
from app.game.badges import SOGLIA_COERENZA, check_badges
from app.game.companions import analizza_consociazioni
from app.game.scoring import punteggio_biodiversita
from app.imaging import prepara_immagine
from app.schemas import (
    AnalyzeResponse,
    BadgeOut,
    ContainerOut,
    GardenPlan,
    GardenStateOut,
    PlantStateOut,
    Posizione,
    UpdateResponse,
)

logger = logging.getLogger("microgarden.garden")

router = APIRouter(prefix="/api", tags=["garden"])


def _salva_piano(db: Session, plan: GardenPlan, citta: str) -> models.Garden:
    """Trasforma il GardenPlan dell'Advisor nello stato del gioco sul DB."""
    garden = models.Garden(
        tipo_spazio=plan.spazio.tipo,
        luce_stimata=plan.spazio.luce_stimata,
        note_analisi=plan.spazio.note_analisi,
        citta=citta,
    )
    db.add(garden)
    db.flush()  # assegna garden.id senza chiudere la transazione

    # Contenitori: mappa codice ("vaso_1") → riga DB, per collegare le piante
    per_codice: dict[str, models.Container] = {}
    for c in plan.contenitori_rilevati:
        cont = models.Container(
            garden_id=garden.id,
            codice=c.id,
            tipo=c.tipo,
            diametro_cm=c.diametro_cm_stimato,
            pos_x=c.posizione.x,
            pos_z=c.posizione.z,
        )
        db.add(cont)
        per_codice[c.id] = cont
    db.flush()

    # Piante consigliate: scartiamo (con log) quelle con riferimenti errati
    # invece di far fallire tutto: l'AI può sbagliare un id su dieci.
    for p in plan.piante_consigliate:
        if pianta_per_id(p.plant_id) is None:
            logger.warning("Advisor ha proposto specie inesistente: %s — scartata", p.plant_id)
            continue
        cont = per_codice.get(p.contenitore_id)
        if cont is None:
            logger.warning(
                "Advisor ha proposto contenitore inesistente: %s — scartata %s",
                p.contenitore_id, p.plant_id,
            )
            continue
        db.add(
            models.Plant(
                garden_id=garden.id,
                container_id=cont.id,
                species_id=p.plant_id,
                motivo=p.motivo,
                quando_piantare=p.quando_piantare,
            )
        )

    db.commit()
    db.refresh(garden)
    return garden


@router.post("/garden/analyze", response_model=AnalyzeResponse)
async def analyze(
    foto: UploadFile,
    citta: str = Form(""),
    orientamento: str = Form(""),
    ore_sole: str = Form(""),
    minuti_settimana: str = Form(""),
    preferenze: str = Form(""),
    db: Session = Depends(get_db),
) -> AnalyzeResponse:
    """Foto dello spazio + questionario → Agente 1 → giardino salvato nel DB."""
    foto_b64, media_type = await prepara_immagine(foto)

    plan = analizza_spazio(
        foto_b64=foto_b64,
        media_type=media_type,
        citta=citta,
        orientamento=orientamento,
        ore_sole=ore_sole,
        minuti_settimana=minuti_settimana,
        preferenze=preferenze,
    )

    if not plan.contenitori_rilevati:
        raise HTTPException(
            status_code=422,
            detail="L'Advisor non ha rilevato contenitori nella foto: prova con una foto più ampia dello spazio.",
        )

    garden = _salva_piano(db, plan, citta)
    return AnalyzeResponse(garden_id=garden.id, plan=plan)


# ---------------------------------------------------------------------------
# Stato del giardino (per il rendering voxel)
# ---------------------------------------------------------------------------


def _carica_garden(db: Session, garden_id: int) -> models.Garden:
    """Il giardino richiesto, o 404 con messaggio chiaro."""
    garden = db.get(models.Garden, garden_id)
    if garden is None:
        raise HTTPException(status_code=404, detail=f"Giardino {garden_id} non trovato.")
    return garden


def _stato_pianta(plant: models.Plant) -> PlantStateOut:
    """Combina la scheda della specie con l'ultimo GrowthLog registrato."""
    scheda = pianta_per_id(plant.species_id) or {}
    stato = PlantStateOut(
        plant_id=plant.id,
        species_id=plant.species_id,
        nome=scheda.get("nome", plant.species_id),
        categoria=scheda.get("categoria", ""),
        colore_voxel=scheda.get("colore_voxel", "#3a7d2c"),
        container_id=plant.container_id,
        motivo=plant.motivo,
        n_aggiornamenti=len(plant.growth_logs),
    )
    if plant.growth_logs:
        ultimo = plant.growth_logs[-1]  # relationship ordinata per created_at
        stato.stadio = ultimo.stadio
        stato.salute = ultimo.salute
        stato.frutti_visibili = ultimo.frutti_visibili
        stato.problemi = json.loads(ultimo.problemi_json)
        stato.consigli = json.loads(ultimo.consigli_json)
        stato.giorni_al_raccolto_stimati = ultimo.giorni_al_raccolto_stimati
        stato.flagged = ultimo.flagged
    return stato


def _stato_giardino(garden: models.Garden) -> GardenStateOut:
    """Costruisce la risposta completa per il frontend: contenitori, piante
    con l'ultimo stadio, punteggio, badge e consociazioni."""
    return GardenStateOut(
        garden_id=garden.id,
        tipo_spazio=garden.tipo_spazio,
        luce_stimata=garden.luce_stimata,
        note_analisi=garden.note_analisi,
        citta=garden.citta,
        containers=[
            ContainerOut(
                container_id=c.id,
                codice=c.codice,
                tipo=c.tipo,
                diametro_cm=c.diametro_cm,
                posizione=Posizione(x=c.pos_x, z=c.pos_z),
            )
            for c in garden.containers
        ],
        plants=[_stato_pianta(p) for p in garden.plants],
        punteggio_biodiversita=punteggio_biodiversita(garden.plants),
        badges=[BadgeOut(badge_id=b.badge_id, nome=b.nome) for b in garden.badges],
        consociazioni=analizza_consociazioni(garden.plants),
    )


@router.get("/garden/{garden_id}", response_model=GardenStateOut)
def garden_state(garden_id: int, db: Session = Depends(get_db)) -> GardenStateOut:
    """Tutto ciò che serve al frontend per disegnare il giardino voxel."""
    return _stato_giardino(_carica_garden(db, garden_id))


# ---------------------------------------------------------------------------
# Aggiornamento crescita (Agente 2 + gamification)
# ---------------------------------------------------------------------------


def _report_da_log(log: models.GrowthLog) -> dict:
    """Ricostruisce il dizionario GrowthReport da un log salvato,
    per passarlo come contesto all'Agente 2 (confronto anti-cheat)."""
    return {
        "stadio": log.stadio,
        "salute": log.salute,
        "problemi": json.loads(log.problemi_json),
        "consigli": json.loads(log.consigli_json),
        "frutti_visibili": log.frutti_visibili,
        "giorni_al_raccolto_stimati": log.giorni_al_raccolto_stimati,
        "coerenza": log.coerenza,
        "note_coerenza": log.note_coerenza,
    }


@router.post("/plant/{plant_id}/update", response_model=UpdateResponse)
async def update_plant(
    plant_id: int,
    foto: UploadFile,
    db: Session = Depends(get_db),
) -> UpdateResponse:
    """Foto di progresso → Agente 2 → GrowthLog → badge (Python puro)."""
    plant = db.get(models.Plant, plant_id)
    if plant is None:
        raise HTTPException(status_code=404, detail=f"Pianta {plant_id} non trovata.")

    foto_b64, media_type = await prepara_immagine(foto)
    scheda = pianta_per_id(plant.species_id) or {}

    # Contesto per l'anti-cheat: ultimo report e la sua data (se esistono)
    ultimo_log = plant.growth_logs[-1] if plant.growth_logs else None
    creato = plant.created_at
    if creato.tzinfo is None:  # SQLite può restituire datetime "naive"
        creato = creato.replace(tzinfo=timezone.utc)
    giorni_a_dimora = (datetime.now(timezone.utc) - creato).days

    report = valuta_crescita(
        foto_b64=foto_b64,
        media_type=media_type,
        nome_pianta=scheda.get("nome", plant.species_id),
        categoria=scheda.get("categoria", ""),
        giorni_raccolto_attesi=scheda.get("giorni_raccolto", 60),
        giorni_dalla_messa_a_dimora=giorni_a_dimora,
        report_precedente=_report_da_log(ultimo_log) if ultimo_log else None,
        data_report_precedente=ultimo_log.created_at if ultimo_log else None,
    )

    # L'AI giudica, il codice decide: sotto soglia il report è "flagged"
    flagged = report.coerenza < SOGLIA_COERENZA

    log = models.GrowthLog(
        plant_id=plant.id,
        stadio=report.stadio,
        salute=report.salute,
        problemi_json=json.dumps(report.problemi, ensure_ascii=False),
        consigli_json=json.dumps(report.consigli, ensure_ascii=False),
        frutti_visibili=report.frutti_visibili,
        giorni_al_raccolto_stimati=report.giorni_al_raccolto_stimati,
        coerenza=report.coerenza,
        note_coerenza=report.note_coerenza,
        flagged=flagged,
    )
    db.add(log)
    db.flush()          # assegna log.id e lo rende visibile in plant.growth_logs
    db.refresh(plant)

    nuovi_badge = check_badges(db, plant.garden, plant, log)
    db.commit()

    return UpdateResponse(
        report=report,
        flagged=flagged,
        nuovi_badge=[BadgeOut(badge_id=b.badge_id, nome=b.nome) for b in nuovi_badge],
        punteggio_biodiversita=punteggio_biodiversita(plant.garden.plants),
    )
