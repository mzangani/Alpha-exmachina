"""Agente 2 — GROWTH TRACKER.

Riceve la foto nuova di una pianta e il contesto (specie, giorni attesi
al raccolto, report precedente con la sua data) e produce un
`GrowthReport`: stadio 0-1, salute, problemi, consigli, frutti visibili
e il punteggio di coerenza anti-cheat.
"""

import json
from datetime import datetime, timezone

from app.agents.base import call_agent
from app.schemas import GrowthReport


def _system_prompt() -> str:
    return """Sei un agronomo esperto nella valutazione visiva dello stato di piante coltivate in vaso.

Il tuo compito: osservare la FOTO di una pianta e produrre una valutazione onesta e prudente del suo stadio di crescita e stato di salute.

COME VALUTARE:
1. `stadio`: numero tra 0.0 e 1.0. 0.0 = appena piantata/germoglio appena visibile; 0.3 = piantina giovane; 0.6 = pianta sviluppata ma non matura; 0.8+ = vicina alla maturazione; 1.0 = matura/pronta al raccolto. Tara la stima sui giorni tipici al raccolto della specie indicati nel contesto.
2. `salute`: "ottima" (vigorosa, colore pieno), "buona" (sana con difetti minori), "sofferente" (ingiallimenti, afflosciamenti, parassiti visibili), "critica" (danni estesi, rischio di morte).
3. `problemi`: elenca SOLO problemi effettivamente visibili nella foto (es. "foglie gialle in basso"). Lista vuota se non ne vedi.
4. `consigli`: massimo 3 consigli pratici e specifici per questa pianta in questo stato.
5. `frutti_visibili`: true solo se nella foto vedi frutti, bacche o parti raccoglibili chiaramente formate.
6. `giorni_al_raccolto_stimati`: stima intera dei giorni mancanti al raccolto (0 se già raccoglibile).

ANTI-CHEAT — `coerenza` (tra 0.0 e 1.0):
Se il contesto include un report precedente con la sua data, confronta e valuta quanto è PLAUSIBILE questa foto:
- sembra la stessa pianta e lo stesso vaso/contesto della descrizione precedente?
- la progressione è credibile nel tempo trascorso? (una pianta non passa da germoglio a matura in 2 giorni, e non regredisce senza segni di danno)
- la foto sembra autentica (non uno schermo fotografato, non un'immagine stampata)?
1.0 = perfettamente plausibile; 0.5 = dubbi seri; sotto 0.5 = quasi certamente non è la stessa pianta o la progressione è impossibile.
Se NON c'è un report precedente (prima foto), usa coerenza 1.0 salvo segni evidenti di foto non autentica.
Spiega sempre la tua valutazione in `note_coerenza`.

FORMATO DELLA RISPOSTA — OBBLIGATORIO:
Rispondi SOLO con un oggetto JSON valido conforme a questo schema, senza alcun testo prima o dopo, senza recinzioni markdown, senza backtick:
{
  "stadio": 0.6,
  "salute": "ottima|buona|sofferente|critica",
  "problemi": ["..."],
  "consigli": ["max 3"],
  "frutti_visibili": false,
  "giorni_al_raccolto_stimati": 20,
  "coerenza": 0.9,
  "note_coerenza": "..."
}"""


def valuta_crescita(
    foto_b64: str,
    media_type: str,
    nome_pianta: str,
    categoria: str,
    giorni_raccolto_attesi: int,
    giorni_dalla_messa_a_dimora: int,
    report_precedente: dict | None,
    data_report_precedente: datetime | None,
) -> GrowthReport:
    """Esegue l'Agente 2 e ritorna la valutazione validata."""
    contesto = (
        f"CONTESTO DELLA PIANTA:\n"
        f"- Specie: {nome_pianta} (categoria: {categoria})\n"
        f"- Giorni tipici dalla semina al raccolto per questa specie: {giorni_raccolto_attesi}\n"
        f"- Giorni trascorsi da quando è stata piantata (secondo l'app): {giorni_dalla_messa_a_dimora}\n"
    )

    if report_precedente is not None and data_report_precedente is not None:
        # SQLite restituisce datetime "naive": li trattiamo come UTC
        # (è così che li scriviamo in models.adesso()) per confrontarli
        # sempre con un now() altrettanto UTC-aware.
        if data_report_precedente.tzinfo is None:
            data_report_precedente = data_report_precedente.replace(tzinfo=timezone.utc)
        giorni_fa = (datetime.now(timezone.utc) - data_report_precedente).days
        contesto += (
            f"\nREPORT PRECEDENTE (di {giorni_fa} giorni fa, "
            f"{data_report_precedente.date().isoformat()}):\n"
            f"{json.dumps(report_precedente, ensure_ascii=False, indent=2)}\n"
        )
    else:
        contesto += "\nNessun report precedente: questa è la PRIMA foto della pianta.\n"

    contesto += "\nValuta la foto allegata e rispondi in JSON."

    user_content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": foto_b64},
        },
        {"type": "text", "text": contesto},
    ]

    return call_agent(
        system_prompt=_system_prompt(),
        user_content=user_content,
        schema=GrowthReport,
        fixture_name="growth_report_mock.json",
    )
