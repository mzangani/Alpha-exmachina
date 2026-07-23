"""Validazione e preparazione delle foto caricate dall'utente.

Prima di mandare una foto all'API:
1. verifichiamo che sia davvero un'immagine (content-type + magic bytes);
2. rifiutiamo file oltre 8 MB;
3. la ridimensioniamo a max 1568 px sul lato lungo e la ricomprimiamo
   in JPEG: oltre quella soglia l'API ridurrebbe comunque l'immagine,
   quindi manderemmo solo token (e tempo) sprecati.
"""

import base64
import io

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

MAX_BYTES = 8 * 1024 * 1024          # 8 MB
LATO_MASSIMO = 1568                  # px sul lato lungo (soglia ottimale API)

# Firme binarie ("magic bytes") dei formati accettati: il content-type
# dichiarato dal browser si può falsificare, i primi byte del file no.
MAGIC_BYTES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",           # RIFF....WEBP (controllato sotto)
    b"GIF8": "image/gif",
}

CONTENT_TYPES_OK = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _rileva_formato(dati: bytes) -> str | None:
    """Riconosce il formato reale del file dai primi byte, o None."""
    for firma, mime in MAGIC_BYTES.items():
        if dati.startswith(firma):
            if mime == "image/webp" and dati[8:12] != b"WEBP":
                continue  # è un RIFF ma non un WebP
            return mime
    return None


async def prepara_immagine(foto: UploadFile) -> tuple[str, str]:
    """Valida e ridimensiona la foto; ritorna (base64, media_type).

    Solleva HTTPException 400 con messaggio chiaro se il file non va bene.
    """
    # ── Content-type dichiarato dal client ────────────────────────────
    if foto.content_type not in CONTENT_TYPES_OK:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Formato non supportato ({foto.content_type}). "
                "Carica una foto JPEG, PNG, WebP o GIF."
            ),
        )

    # ── Dimensione massima ────────────────────────────────────────────
    dati = await foto.read()
    if len(dati) > MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"La foto pesa {len(dati) / 1024 / 1024:.1f} MB: il massimo è 8 MB.",
        )
    if not dati:
        raise HTTPException(status_code=400, detail="Il file caricato è vuoto.")

    # ── Magic bytes: il contenuto è davvero un'immagine? ──────────────
    if _rileva_formato(dati) is None:
        raise HTTPException(
            status_code=400,
            detail="Il file non sembra un'immagine valida (firma binaria sconosciuta).",
        )

    # ── Apertura + ridimensionamento con Pillow ───────────────────────
    try:
        img = Image.open(io.BytesIO(dati))
        img.load()
    except UnidentifiedImageError as e:
        raise HTTPException(
            status_code=400,
            detail="Impossibile leggere l'immagine: il file è corrotto?",
        ) from e

    # Converte in RGB (i JPEG non supportano trasparenza/palette)
    if img.mode != "RGB":
        img = img.convert("RGB")

    lato_lungo = max(img.size)
    if lato_lungo > LATO_MASSIMO:
        fattore = LATO_MASSIMO / lato_lungo
        nuova = (round(img.width * fattore), round(img.height * fattore))
        img = img.resize(nuova, Image.LANCZOS)

    # Ricomprime sempre in JPEG: formato compatto e accettato dall'API
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    b64 = base64.standard_b64encode(buffer.getvalue()).decode("ascii")
    return b64, "image/jpeg"
