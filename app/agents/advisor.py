"""Agente 1 — GARDEN ADVISOR.

Riceve la foto dello spazio (balcone/terrazzo/davanzale) e le risposte
del questionario, e produce un `GardenPlan`: contenitori rilevati,
piante consigliate (SOLO dal catalogo) e consigli pratici.
"""

from datetime import datetime

from app.agents.base import call_agent
from app.catalogo import carica_catalogo
from app.schemas import GardenPlan

MESI_IT = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


def _catalogo_sintetico() -> str:
    """Una riga per pianta: le informazioni minime che servono all'AI
    per scegliere bene (id, esigenze, consociazioni). Passare tutto il
    JSON sprecherebbe token senza aggiungere valore."""
    righe = []
    for p in carica_catalogo():
        righe.append(
            f"- {p['id']} ({p['nome']}, {p['categoria']}): sole={p['sole']}, "
            f"vaso min {p['litri_vaso_min']} L, semina nei mesi {p['mesi_semina']}, "
            f"raccolto in ~{p['giorni_raccolto']} gg, amici={p['amici']}, nemici={p['nemici']}"
        )
    return "\n".join(righe)


def _system_prompt() -> str:
    return f"""Sei un agronomo esperto di orti su balcone e micro-coltivazioni urbane in clima mediterraneo.

Il tuo compito: analizzare la FOTO dello spazio dell'utente e le sue risposte al questionario, e progettare un piccolo giardino che massimizzi biodiversità e autoconsumo.

COME PROCEDERE:
1. Osserva la foto: individua i contenitori visibili (vasi, fioriere, cassette) o lo spazio dove potrebbero starci. Stima il diametro in cm di ciascuno confrontandolo con oggetti riconoscibili (ringhiere, piastrelle, porte). Assegna a ogni contenitore un id breve (es. "vaso_1", "fioriera_1") e una posizione su una griglia: x cresce verso destra, z verso il fondo, celle intere a partire da 0. Se nella foto non ci sono contenitori, proponine 2-4 realistici per lo spazio che vedi.
2. Valuta la luce dello spazio combinando ciò che vedi (ombre, esposizione, tende) con l'orientamento e le ore di sole dichiarate dall'utente.
3. Scegli le piante SOLO dall'elenco del CATALOGO qui sotto, usando ESATTAMENTE gli id indicati. Mai inventare piante o id.
4. Rispetta questi vincoli:
   - stagionalità: privilegia piante seminabili nel mese corrente o nei 1-2 mesi successivi;
   - luce: non proporre piante da pieno_sole in spazi in ombra;
   - dimensioni: il contenitore deve rispettare i litri minimi della pianta (regola pratica: un vaso di diametro D cm contiene circa D²/100 litri, quindi un vaso da 30 cm ≈ 9 L);
   - consociazioni: non mettere piante "nemiche" nello stesso contenitore o in contenitori adiacenti; se possibile affianca piante "amiche";
   - tempo dell'utente: se ha pochi minuti a settimana, privilegia piante a bassa manutenzione (aromatiche);
   - gusti: dai priorità a ciò che l'utente ama mangiare, ma includi almeno un fiore se possibile (impollinatori).
5. Scrivi al massimo 3 consigli generali pratici e concreti per QUESTO spazio.

CATALOGO PIANTE DISPONIBILI:
{_catalogo_sintetico()}

FORMATO DELLA RISPOSTA — OBBLIGATORIO:
Rispondi SOLO con un oggetto JSON valido conforme a questo schema, senza alcun testo prima o dopo, senza recinzioni markdown, senza backtick:
{{
  "spazio": {{"tipo": "balcone|terrazzo|davanzale|giardino", "luce_stimata": "pieno_sole|mezz_ombra|ombra", "note_analisi": "cosa hai visto nella foto e perché"}},
  "contenitori_rilevati": [{{"id": "vaso_1", "tipo": "vaso|fioriera|cassetta|terra", "diametro_cm_stimato": 30, "posizione": {{"x": 0, "z": 0}}}}],
  "piante_consigliate": [{{"plant_id": "id_dal_catalogo", "contenitore_id": "vaso_1", "motivo": "perché questa pianta qui", "quando_piantare": "es. aprile-giugno"}}],
  "consigli_generali": ["max 3 consigli"]
}}"""


def analizza_spazio(
    foto_b64: str,
    media_type: str,
    citta: str,
    orientamento: str,
    ore_sole: str,
    minuti_settimana: str,
    preferenze: str,
) -> GardenPlan:
    """Esegue l'Agente 1 e ritorna il piano del giardino validato."""
    oggi = datetime.now()
    mese = MESI_IT[oggi.month - 1]

    questionario = (
        f"QUESTIONARIO DELL'UTENTE:\n"
        f"- Città: {citta or 'non indicata'}\n"
        f"- Orientamento dello spazio: {orientamento or 'non indicato'}\n"
        f"- Ore di sole dirette stimate al giorno: {ore_sole or 'non indicate'}\n"
        f"- Minuti a settimana dedicabili alla cura: {minuti_settimana or 'non indicati'}\n"
        f"- Cosa ama mangiare/coltivare: {preferenze or 'non indicato'}\n"
        f"- Mese corrente: {mese}\n\n"
        f"Analizza la foto allegata e produci il piano del giardino in JSON."
    )

    user_content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": foto_b64},
        },
        {"type": "text", "text": questionario},
    ]

    return call_agent(
        system_prompt=_system_prompt(),
        user_content=user_content,
        schema=GardenPlan,
        fixture_name="garden_plan_mock.json",
    )
