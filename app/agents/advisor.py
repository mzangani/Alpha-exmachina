"""Agente 1 — GARDEN ADVISOR.

Riceve la foto dello spazio (balcone/terrazzo/davanzale) e le risposte
del questionario, e produce un `GardenPlan`: contenitori rilevati,
piante consigliate (SOLO dal catalogo) e consigli pratici.

La foto è FACOLTATIVA: se l'utente non la carica, l'Advisor lavora solo
sul testo del questionario e su una descrizione libera dei contenitori
(campo `descrizione_spazio`). In questo caso non c'è alcuna percezione
visiva reale, quindi il piano è necessariamente meno preciso — il
system prompt istruisce l'AI a dichiararlo esplicitamente in
`note_analisi` invece di far finta di aver "visto" qualcosa.
"""

from datetime import datetime

from app.agents.base import call_agent
from app.catalogo import MESI_IT, carica_catalogo
from app.schemas import GardenPlan


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

Il tuo compito: analizzare lo spazio dell'utente (foto e/o descrizione testuale) e le sue risposte al questionario, e progettare un piccolo giardino che massimizzi biodiversità e autoconsumo.

NOTA SULLA FOTO — a volte NON riceverai alcuna immagine, solo un messaggio che inizia con "NESSUNA FOTO FORNITA" seguito da una descrizione testuale scritta dall'utente. In quel caso:
- non hai nulla da "osservare": basa la stima SOLO sul testo fornito;
- se la descrizione è vaga o assente, proponi 2-4 contenitori standard e realistici per il tipo di spazio dichiarato (es. per un balcone: un paio di vasi da 30-35 cm e una fioriera da 60-80 cm), senza inventare dettagli che l'utente non ti ha dato;
- in `note_analisi` dichiara ESPLICITAMENTE che la stima si basa solo sul testo e non su un'osservazione visiva, e consiglia di caricare una foto per un piano più preciso in futuro. Non scrivere mai frasi come "vedo" o "nella foto" se non hai ricevuto un'immagine.

COME PROCEDERE:
1. Se hai una foto: individua i contenitori visibili (vasi, fioriere, cassette) o lo spazio dove potrebbero starci. Stima il diametro in cm di ciascuno confrontandolo con oggetti riconoscibili (ringhiere, piastrelle, porte). Se NON hai una foto, usa la descrizione testuale dell'utente (vedi nota sopra). In entrambi i casi assegna a ogni contenitore un id breve (es. "vaso_1", "fioriera_1") e una posizione su una griglia: x cresce verso destra, z verso il fondo, celle intere a partire da 0. Se non ci sono contenitori evidenti, proponine 2-4 realistici per lo spazio descritto.
2. Valuta la luce dello spazio combinando ciò che eventualmente vedi (ombre, esposizione, tende) con l'orientamento e le ore di sole dichiarate dall'utente.
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
    foto_b64: str | None,
    media_type: str | None,
    citta: str,
    orientamento: str,
    ore_sole: str,
    minuti_settimana: str,
    preferenze: str,
    descrizione_spazio: str = "",
) -> GardenPlan:
    """Esegue l'Agente 1 e ritorna il piano del giardino validato.

    `foto_b64`/`media_type` sono `None` quando l'utente non ha caricato
    una foto: in quel caso l'Advisor ragiona solo su `descrizione_spazio`
    (e sul resto del questionario), senza alcuna percezione visiva.
    """
    oggi = datetime.now()
    mese = MESI_IT[oggi.month - 1]

    questionario = (
        f"QUESTIONARIO DELL'UTENTE:\n"
        f"- Città: {citta or 'non indicata'}\n"
        f"- Orientamento dello spazio: {orientamento or 'non indicato'}\n"
        f"- Ore di sole dirette stimate al giorno: {ore_sole or 'non indicate'}\n"
        f"- Minuti a settimana dedicabili alla cura: {minuti_settimana or 'non indicati'}\n"
        f"- Cosa ama mangiare/coltivare: {preferenze or 'non indicato'}\n"
        f"- Mese corrente: {mese}\n"
    )

    if foto_b64 is not None:
        questionario += "\nAnalizza la foto allegata e produci il piano del giardino in JSON."
        user_content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": foto_b64},
            },
            {"type": "text", "text": questionario},
        ]
        fixture_name = "garden_plan_mock.json"
    else:
        questionario += (
            f"\nNESSUNA FOTO FORNITA. Descrizione dello spazio scritta dall'utente: "
            f"{descrizione_spazio.strip() or '(nessuna descrizione fornita)'}\n\n"
            "Produci comunque il piano del giardino in JSON, seguendo le istruzioni "
            "per il caso senza foto."
        )
        user_content = [{"type": "text", "text": questionario}]
        fixture_name = "garden_plan_mock_no_foto.json"

    return call_agent(
        system_prompt=_system_prompt(),
        user_content=user_content,
        schema=GardenPlan,
        fixture_name=fixture_name,
    )
