"""Endpoint principali del gioco: analisi dello spazio e gestione giardino."""

import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from datetime import datetime, timezone

from app import models
from app.agents.advisor import analizza_spazio
from app.agents.tracker import valuta_crescita
from app.catalogo import descrivi_mesi_semina, pianta_per_id
from app.database import get_db
from app.game.badges import SOGLIA_COERENZA, check_badges
from app.game.companions import analizza_consociazioni
from app.game.scoring import punteggio_biodiversita
from app.imaging import prepara_immagine
from app.schemas import (
    AddContainerRequest,
    AddPlantRequest,
    AnalyzeResponse,
    BadgeOut,
    ContainerOut,
    GardenPlan,
    GardenStateOut,
    MoveContainerRequest,
    MoveRequest,
    MoveResponse,
    PlantStateOut,
    Posizione,
    UpdateResponse,
)

# Diametro di default (cm) per contenitore aggiunto a mano, per tipo:
# l'utente della vista lista non deve stimare una misura se non vuole.
DIAMETRO_DEFAULT_CM = {"vaso": 30, "fioriera": 60, "cassetta": 50, "terra": 100}

logger = logging.getLogger("microgarden.garden")

router = APIRouter(prefix="/api", tags=["garden"])


def _salva_piano(db: Session, plan: GardenPlan, citta: str) -> models.Garden:
    """Trasforma il GardenPlan dell'Advisor nello stato del gioco sul DB.

    Modifica `plan.piante_consigliate` IN PLACE per allinearlo a ciò che è
    stato davvero salvato: così la risposta di /analyze e lo stato letto
    con GET /garden/{id} restano coerenti anche quando l'AI ha proposto
    riferimenti invalidi (id sbagliati, duplicati) che vengono scartati.
    """
    garden = models.Garden(
        tipo_spazio=plan.spazio.tipo,
        luce_stimata=plan.spazio.luce_stimata,
        note_analisi=plan.spazio.note_analisi,
        citta=citta,
    )
    db.add(garden)
    db.flush()  # assegna garden.id senza chiudere la transazione

    # Contenitori: mappa codice ("vaso_1") → riga DB, per collegare le piante.
    # Un codice duplicato nell'output AI viene scartato (si tiene il primo):
    # altrimenti la mappa lo sovrascriverebbe silenziosamente.
    per_codice: dict[str, models.Container] = {}
    contenitori_validi = []
    for c in plan.contenitori_rilevati:
        if c.id in per_codice:
            logger.warning("Advisor ha prodotto contenitore duplicato: %s — scartato", c.id)
            continue
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
        contenitori_validi.append(c)
    db.flush()
    plan.contenitori_rilevati = contenitori_validi

    # Piante consigliate: scartiamo (con log) quelle con riferimenti errati
    # invece di far fallire tutto: l'AI può sbagliare un id su dieci.
    piante_salvate = []
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
        piante_salvate.append(p)
    plan.piante_consigliate = piante_salvate

    db.commit()
    db.refresh(garden)
    return garden


@router.post("/garden/analyze", response_model=AnalyzeResponse)
async def analyze(
    foto: UploadFile | None = File(None),
    citta: str = Form(""),
    orientamento: str = Form(""),
    ore_sole: str = Form(""),
    minuti_settimana: str = Form(""),
    preferenze: str = Form(""),
    descrizione_spazio: str = Form(""),
    db: Session = Depends(get_db),
) -> AnalyzeResponse:
    """Foto dello spazio (facoltativa) + questionario → Agente 1 → giardino salvato nel DB.

    La foto NON è obbligatoria: se manca, l'Advisor lavora solo su
    `descrizione_spazio` e sul resto del questionario. Serve però almeno
    uno dei due, altrimenti l'AI non avrebbe alcuna base su cui ragionare.

    Nota tecnica: quando l'input file del form non ha un file selezionato,
    il browser lo invia comunque come parte multipart con nome file vuoto
    — non arriva `None`. Per questo il controllo "foto presente" è
    `foto is not None and foto.filename`, non un semplice `if foto`.
    """
    ha_foto = foto is not None and bool(foto.filename)
    if not ha_foto and not descrizione_spazio.strip():
        raise HTTPException(
            status_code=422,
            detail="Carica una foto dello spazio oppure descrivi i tuoi contenitori (vasi, fioriere, terra) nel campo apposito.",
        )

    foto_b64: str | None = None
    media_type: str | None = None
    if ha_foto:
        foto_b64, media_type = await prepara_immagine(foto)

    plan = analizza_spazio(
        foto_b64=foto_b64,
        media_type=media_type,
        citta=citta,
        orientamento=orientamento,
        ore_sole=ore_sole,
        minuti_settimana=minuti_settimana,
        preferenze=preferenze,
        descrizione_spazio=descrizione_spazio,
    )

    if not plan.contenitori_rilevati:
        raise HTTPException(
            status_code=422,
            detail=(
                "L'Advisor non ha rilevato contenitori nella foto: prova con una foto più ampia dello spazio."
                if ha_foto
                else "L'Advisor non è riuscito a proporre contenitori dalla descrizione: prova a essere più specifico (es. \"2 vasi da 30 cm e una fioriera\")."
            ),
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
        quando_piantare=plant.quando_piantare,
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
# Aggiunta manuale di contenitori e piante (zero AI)
#
# Una volta creato il giardino, l'utente deve poter continuare a lavorarci
# senza dover rifotografare tutto: qui sceglie lui i contenitori e le
# piante, direttamente dal catalogo — non serve alcuna percezione, quindi
# non serve l'AI.
# ---------------------------------------------------------------------------


def _prossima_posizione_libera(containers: list[models.Container]) -> tuple[int, int]:
    """Trova la prima cella libera scandendo la griglia per righe (max 6
    colonne), così chi lavora dalla vista lista non deve pensare in
    coordinate x/z: il posto nella scena voxel lo trova il backend."""
    occupate = {(c.pos_x, c.pos_z) for c in containers}
    z = 0
    while True:
        for x in range(6):
            if (x, z) not in occupate:
                return x, z
        z += 1


def _codice_libero(containers: list[models.Container], tipo: str) -> str:
    """Genera un codice leggibile tipo 'vaso_3', evitando collisioni con
    codici già presenti (anche quelli assegnati dall'Advisor)."""
    esistenti = {c.codice for c in containers}
    n = sum(1 for c in containers if c.tipo == tipo) + 1
    codice = f"{tipo}_{n}"
    while codice in esistenti:
        n += 1
        codice = f"{tipo}_{n}"
    return codice


@router.post("/garden/{garden_id}/containers", response_model=ContainerOut)
def add_container(
    garden_id: int,
    body: AddContainerRequest,
    db: Session = Depends(get_db),
) -> ContainerOut:
    """Aggiunge un contenitore a mano a un giardino esistente. Nessuna
    chiamata AI: posizione e codice sono calcolati dal backend."""
    garden = _carica_garden(db, garden_id)
    x, z = _prossima_posizione_libera(garden.containers)
    diametro = body.diametro_cm or DIAMETRO_DEFAULT_CM[body.tipo]

    cont = models.Container(
        garden_id=garden.id,
        codice=_codice_libero(garden.containers, body.tipo),
        tipo=body.tipo,
        diametro_cm=diametro,
        pos_x=x,
        pos_z=z,
    )
    db.add(cont)
    db.commit()
    db.refresh(cont)

    return ContainerOut(
        container_id=cont.id,
        codice=cont.codice,
        tipo=cont.tipo,
        diametro_cm=cont.diametro_cm,
        posizione=Posizione(x=cont.pos_x, z=cont.pos_z),
    )


@router.post("/garden/{garden_id}/plants", response_model=PlantStateOut)
def add_plant(
    garden_id: int,
    body: AddPlantRequest,
    db: Session = Depends(get_db),
) -> PlantStateOut:
    """Aggiunge al giardino una pianta scelta dal catalogo, in un
    contenitore esistente. Nessuna chiamata AI: l'utente sa già cosa vuole
    piantare, non c'è nulla da "percepire"."""
    garden = _carica_garden(db, garden_id)

    scheda = pianta_per_id(body.species_id)
    if scheda is None:
        raise HTTPException(
            status_code=400,
            detail=f"'{body.species_id}' non è una specie del catalogo (GET /api/plants/catalog per l'elenco).",
        )
    contenitore = next((c for c in garden.containers if c.id == body.container_id), None)
    if contenitore is None:
        raise HTTPException(
            status_code=400,
            detail="Il contenitore indicato non appartiene a questo giardino.",
        )

    plant = models.Plant(
        garden_id=garden.id,
        container_id=contenitore.id,
        species_id=body.species_id,
        motivo="Aggiunta manualmente dall'utente.",
        quando_piantare=descrivi_mesi_semina(scheda["mesi_semina"]),
    )
    db.add(plant)
    db.commit()
    db.refresh(plant)

    return _stato_pianta(plant)


@router.patch("/garden/{garden_id}/containers/{container_id}", response_model=ContainerOut)
def move_container(
    garden_id: int,
    container_id: int,
    body: MoveContainerRequest,
    db: Session = Depends(get_db),
) -> ContainerOut:
    """Sposta un contenitore in un'altra cella della griglia (trascinamento
    nella scena 3D, o coordinate inserite a mano dalla vista lista). Nessuna
    chiamata AI: è solo aggiornamento di stato."""
    garden = _carica_garden(db, garden_id)
    contenitore = next((c for c in garden.containers if c.id == container_id), None)
    if contenitore is None:
        raise HTTPException(
            status_code=404,
            detail=f"Contenitore {container_id} non trovato in questo giardino.",
        )

    occupata = any(
        c.id != container_id and c.pos_x == body.posizione.x and c.pos_z == body.posizione.z
        for c in garden.containers
    )
    if occupata:
        raise HTTPException(
            status_code=409,
            detail=f"La cella ({body.posizione.x}, {body.posizione.z}) è già occupata da un altro contenitore.",
        )

    contenitore.pos_x = body.posizione.x
    contenitore.pos_z = body.posizione.z
    db.commit()
    db.refresh(contenitore)

    return ContainerOut(
        container_id=contenitore.id,
        codice=contenitore.codice,
        tipo=contenitore.tipo,
        diametro_cm=contenitore.diametro_cm,
        posizione=Posizione(x=contenitore.pos_x, z=contenitore.pos_z),
    )


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


# ---------------------------------------------------------------------------
# Spostamento pianta (zero AI: solo ricalcolo consociazioni)
# ---------------------------------------------------------------------------


@router.patch("/plant/{plant_id}/move", response_model=MoveResponse)
def move_plant(
    plant_id: int,
    body: MoveRequest,
    db: Session = Depends(get_db),
) -> MoveResponse:
    """Sposta la pianta in un altro contenitore dello stesso giardino e
    ricalcola bonus/warning di consociazione. Nessuna chiamata AI."""
    plant = db.get(models.Plant, plant_id)
    if plant is None:
        raise HTTPException(status_code=404, detail=f"Pianta {plant_id} non trovata.")

    destinazione = db.get(models.Container, body.container_id)
    if destinazione is None or destinazione.garden_id != plant.garden_id:
        raise HTTPException(
            status_code=400,
            detail="Il contenitore di destinazione non esiste in questo giardino.",
        )

    plant.container_id = destinazione.id
    db.commit()
    db.refresh(plant)

    return MoveResponse(
        plant_id=plant.id,
        container_id=destinazione.id,
        consociazioni=analizza_consociazioni(plant.garden.plants),
    )


# ---------------------------------------------------------------------------
# Condivisione (stub per il futuro: nessuna feature social nell'MVP)
# ---------------------------------------------------------------------------


@router.post("/garden/{garden_id}/share")
def share_garden(garden_id: int, db: Session = Depends(get_db)) -> dict:
    """Stub: genera uno snapshot JSON "pubblico" del giardino.

    In futuro questo snapshot verrà salvato e servito a un URL condivisibile;
    per ora ritorna i soli dati non sensibili (niente città né note personali).
    """
    garden = _carica_garden(db, garden_id)
    stato = _stato_giardino(garden)
    return {
        "share_version": 1,
        "snapshot": {
            "tipo_spazio": stato.tipo_spazio,
            "punteggio_biodiversita": stato.punteggio_biodiversita,
            "badges": [b.model_dump() for b in stato.badges],
            "piante": [
                {"nome": p.nome, "categoria": p.categoria, "stadio": p.stadio, "salute": p.salute}
                for p in stato.plants
            ],
        },
    }
