"""Il cuore riutilizzabile degli agenti: la funzione `call_agent()`.

Questo è L'UNICO punto del codice in cui si decide se parlare con l'AI
vera (API Anthropic) o con una risposta finta (MOCK_MODE + fixtures).
Tutto il resto dell'app chiama `call_agent()` e riceve un modello
Pydantic già validato: non sa (e non deve sapere) da dove arriva.

Flusso in modalità reale:
    prompt + foto ──▶ client.messages.create() ──▶ testo
    ──▶ pulizia backtick ──▶ json.loads ──▶ validazione Pydantic
    └─ se fallisce: 1 SOLO retry chiedendo al modello di correggersi
       └─ se fallisce ancora: HTTP 502 con messaggio chiaro
"""

import json
import logging
from pathlib import Path
from typing import TypeVar

import anthropic
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from app.config import BASE_DIR, settings

logger = logging.getLogger("microgarden.agents")

FIXTURES_DIR = BASE_DIR / "tests" / "fixtures"

# Tipo generico: call_agent ritorna un'istanza dello schema che gli passi
# (GardenPlan per l'Advisor, GrowthReport per il Tracker).
SchemaT = TypeVar("SchemaT", bound=BaseModel)

# Client creato pigramente (solo alla prima chiamata reale) e riusato.
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Ritorna il client Anthropic, verificando prima che la chiave esista."""
    global _client
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=500,
            detail=(
                "ANTHROPIC_API_KEY mancante. Crea una chiave su "
                "https://platform.claude.com (sezione API Keys), incollala nel "
                "file .env alla riga ANTHROPIC_API_KEY=... e riavvia il server. "
                "In alternativa imposta MOCK_MODE=true per lavorare senza API."
            ),
        )
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _estrai_json(testo: str) -> dict:
    """Estrae un oggetto JSON dal testo del modello.

    I modelli a volte avvolgono la risposta in recinzioni markdown
    (```json ... ```) o aggiungono una frase prima/dopo: qui togliamo
    le recinzioni e isoliamo il blocco tra la prima '{' e l'ultima '}'.
    """
    pulito = testo.strip()
    if pulito.startswith("```"):
        # Rimuove la prima riga (``` o ```json) e l'eventuale ``` finale
        righe = pulito.splitlines()
        righe = righe[1:]
        if righe and righe[-1].strip().startswith("```"):
            righe = righe[:-1]
        pulito = "\n".join(righe)
    inizio = pulito.find("{")
    fine = pulito.rfind("}")
    if inizio == -1 or fine == -1 or fine < inizio:
        raise ValueError("nessun oggetto JSON trovato nella risposta")
    return json.loads(pulito[inizio : fine + 1])


def _testo_da_risposta(risposta: anthropic.types.Message) -> str:
    """Concatena i blocchi di testo della risposta (ignora altri tipi)."""
    return "".join(b.text for b in risposta.content if b.type == "text")


def _chiama_api(system_prompt: str, messages: list[dict]) -> anthropic.types.Message:
    """Una singola chiamata all'API, con gli errori tradotti in HTTP chiari."""
    client = _get_client()
    try:
        return client.messages.create(
            model=settings.model_name,
            max_tokens=2000,
            system=system_prompt,
            messages=messages,
        )
    except anthropic.AuthenticationError as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "La chiave API non è valida (401 dall'API Anthropic). Controlla "
                "ANTHROPIC_API_KEY nel file .env: forse è stata revocata o copiata male."
            ),
        ) from e
    except anthropic.RateLimitError as e:
        raise HTTPException(
            status_code=503,
            detail="L'API Anthropic sta limitando le richieste (429). Riprova tra qualche secondo.",
        ) from e
    except anthropic.APIConnectionError as e:
        raise HTTPException(
            status_code=502,
            detail="Impossibile raggiungere l'API Anthropic: controlla la connessione di rete.",
        ) from e
    except anthropic.APIStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Errore dall'API Anthropic ({e.status_code}): {e.message}",
        ) from e


def _carica_fixture(fixture_name: str, schema: type[SchemaT]) -> SchemaT:
    """MOCK_MODE: legge la risposta finta da tests/fixtures e la valida."""
    percorso: Path = FIXTURES_DIR / fixture_name
    if not percorso.exists():
        raise HTTPException(
            status_code=500,
            detail=f"MOCK_MODE attivo ma la fixture {percorso} non esiste.",
        )
    with open(percorso, encoding="utf-8") as f:
        dati = json.load(f)
    try:
        risultato = schema.model_validate(dati)
    except ValidationError as e:
        raise HTTPException(
            status_code=500,
            detail=f"La fixture {fixture_name} non rispetta lo schema {schema.__name__}: {e}",
        ) from e
    logger.info("MOCK_MODE: risposta letta da %s (schema %s)", fixture_name, schema.__name__)
    return risultato


def call_agent(
    system_prompt: str,
    user_content: list[dict],
    schema: type[SchemaT],
    fixture_name: str,
) -> SchemaT:
    """Esegue un agente e ritorna la risposta validata.

    Parametri:
        system_prompt: le istruzioni fisse dell'agente (in italiano).
        user_content:  i blocchi del messaggio utente — testo e/o immagini
                       base64 nel formato dell'API Anthropic.
        schema:        lo schema Pydantic atteso (GardenPlan o GrowthReport).
        fixture_name:  il file in tests/fixtures usato quando MOCK_MODE=true.
    """
    # ── 1. Modalità mock: nessuna chiamata, nessun costo ──────────────
    if settings.mock_mode:
        return _carica_fixture(fixture_name, schema)

    # ── 2. Chiamata reale ─────────────────────────────────────────────
    n_immagini = sum(1 for b in user_content if b.get("type") == "image")
    testo_prompt = " ".join(
        b.get("text", "") for b in user_content if b.get("type") == "text"
    )
    logger.info(
        "Chiamata agente (%s): %d immagini, prompt utente: %.120s…",
        schema.__name__, n_immagini, testo_prompt,
    )

    messages = [{"role": "user", "content": user_content}]
    risposta = _chiama_api(system_prompt, messages)
    testo = _testo_da_risposta(risposta)
    logger.info(
        "Risposta ricevuta: %d token in, %d token out",
        risposta.usage.input_tokens, risposta.usage.output_tokens,
    )

    # ── 3. Parsing + validazione, con 1 solo retry ────────────────────
    try:
        return schema.model_validate(_estrai_json(testo))
    except (ValueError, ValidationError) as errore:
        logger.warning("JSON non valido al primo tentativo: %s — retry", errore)
        # Python cancella il binding di `errore` all'uscita dell'except
        # (PEP 3110): lo salviamo qui per poterlo usare più sotto.
        messaggio_errore = str(errore)

    # Retry: rimandiamo al modello il SUO output e l'errore, chiedendo
    # di rispondere di nuovo SOLO con JSON valido conforme allo schema.
    messages_retry = messages + [
        {"role": "assistant", "content": testo},
        {
            "role": "user",
            "content": (
                "La tua risposta precedente non era JSON valido conforme allo "
                f"schema richiesto. Errore: {messaggio_errore}. Rispondi di nuovo SOLO con "
                "l'oggetto JSON corretto, senza testo prima o dopo e senza "
                "recinzioni markdown."
            ),
        },
    ]
    risposta2 = _chiama_api(system_prompt, messages_retry)
    testo2 = _testo_da_risposta(risposta2)
    logger.info(
        "Retry: %d token in, %d token out",
        risposta2.usage.input_tokens, risposta2.usage.output_tokens,
    )
    try:
        return schema.model_validate(_estrai_json(testo2))
    except (ValueError, ValidationError) as errore2:
        logger.error("JSON non valido anche dopo il retry: %s", errore2)
        raise HTTPException(
            status_code=502,
            detail=(
                "L'agente AI non ha prodotto un JSON valido nemmeno dopo un "
                f"tentativo di correzione ({schema.__name__}): {errore2}. "
                "Riprova: se l'errore persiste, potrebbe esserci un problema "
                "con il modello configurato in MODEL_NAME."
            ),
        ) from errore2
