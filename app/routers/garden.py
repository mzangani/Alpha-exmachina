"""Endpoint principali del gioco: analisi dello spazio e gestione giardino."""

import logging

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import models
from app.agents.advisor import analizza_spazio
from app.catalogo import pianta_per_id
from app.database import get_db
from app.imaging import prepara_immagine
from app.schemas import AnalyzeResponse, GardenPlan

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
