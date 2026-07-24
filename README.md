# 🌱 MicroGarden

Fotografa il tuo balcone → un **agente AI** ti dice cosa coltivare → il tuo spazio diventa un
**giardino voxel 3D** nel browser (stile Minecraft) → carichi foto reali delle piante e un
**secondo agente AI** ne stima crescita e salute, aggiornando il gemello digitale e
sbloccando badge **solo con progressi verificati dalle foto**.

Questo progetto è pensato anche come **esercizio didattico**: il codice è commentato in
italiano e in fondo trovi la sezione [Come funziona un agente AI in questo progetto](#-come-funziona-un-agente-ai-in-questo-progetto).

---

## Prerequisiti

- **Python 3.11+** (`python3 --version` per controllare)
- Un browser moderno (Chrome, Firefox, Safari)
- *(Facoltativo)* Una chiave API di Anthropic — serve solo per usare l'AI vera.
  In **MOCK_MODE** (il default) tutto funziona **gratis** con risposte finte.

## Setup in 5 comandi

```bash
python3 -m venv .venv && source .venv/bin/activate   # 1. ambiente virtuale
pip install -r requirements.txt                      # 2. dipendenze
cp .env.example .env                                 # 3. configurazione
uvicorn app.main:app --reload                        # 4. avvia il server
open http://localhost:8000/static/index.html         # 5. apri l'app (o incolla l'URL nel browser)
```

Verifica rapida che il server sia vivo:

```bash
curl http://localhost:8000/health
# → {"status":"ok","mock_mode":true}
```

## MOCK_MODE: sviluppare gratis

Nel file `.env`:

```
MOCK_MODE=true    # gli agenti NON chiamano l'API: rispondono con tests/fixtures/*.json
MOCK_MODE=false   # gli agenti chiamano davvero Claude (serve ANTHROPIC_API_KEY)
```

C'è **un unico punto** nel codice in cui si decide mock/reale: la funzione
`call_agent()` in `app/agents/base.py`. Tutto il resto dell'app non sa nemmeno
se l'AI è vera o finta — è così che si costruisce software testabile.

Per usare l'AI vera:
1. crea una chiave su <https://platform.claude.com> → *API Keys*;
2. incollala in `.env` alla riga `ANTHROPIC_API_KEY=...`;
3. imposta `MOCK_MODE=false` e riavvia il server.

## Architettura

```
FOTO SPAZIO ──▶ [Agente 1: GARDEN ADVISOR] ──▶ GardenPlan (JSON) ──▶ DB (stato del gioco)
                        ▲                                                    │
                 risposte questionario                                       ▼
                                                                   RENDERING VOXEL (browser)
                                                                             ▲
FOTO PROGRESSO ──▶ [Agente 2: GROWTH TRACKER] ──▶ GrowthReport (JSON) ──▶ DB + BADGE
```

**Regola d'oro del progetto:** l'AI fa solo ciò che richiede *intelligenza percettiva*
(guardare foto, stimare crescita, dare consigli). Tutta la logica deterministica —
punteggi, badge, streak, consociazioni — è **Python puro** in `app/game/`, che legge
`data/plants.json` e il database. Mai chiedere all'AI ciò che il codice può calcolare:
costa meno, è testabile ed è affidabile.

### Struttura del progetto

```
├── .env.example          # configurazione commentata riga per riga
├── requirements.txt
├── data/
│   └── plants.json       # catalogo di 20 piante (unica fonte di verità botanica)
├── app/
│   ├── main.py           # FastAPI: monta /static e include i router
│   ├── config.py         # legge .env (pydantic-settings)
│   ├── database.py       # engine SQLAlchemy + init SQLite
│   ├── models.py         # tabelle: Garden, Container, Plant, GrowthLog, Badge
│   ├── schemas.py        # contratti JSON (Pydantic) — la fonte di verità
│   ├── catalogo.py       # accesso a plants.json
│   ├── imaging.py        # validazione + ridimensionamento foto
│   ├── agents/
│   │   ├── base.py       # call_agent(): API/mock, parsing JSON, retry, logging
│   │   ├── advisor.py    # Agente 1: analizza lo spazio e propone il giardino
│   │   └── tracker.py    # Agente 2: stima crescita/salute + anti-cheat
│   ├── game/             # gamification: Python puro, ZERO AI
│   │   ├── badges.py     # 5 regole badge
│   │   ├── scoring.py    # punteggio biodiversità
│   │   └── companions.py # warning/bonus consociazioni
│   └── routers/
│       ├── garden.py     # analyze, stato giardino, update/move piante, share
│       └── plants.py     # catalogo piante per il frontend
├── static/
│   └── index.html        # TUTTO il frontend: Three.js da CDN + vanilla JS
└── tests/
    └── fixtures/         # risposte finte degli agenti per MOCK_MODE
```

### Perché queste scelte (spiegate a chi inizia)

- **FastAPI + Pydantic**: ogni dato che entra o esce passa da uno schema tipato.
  Se l'AI (o il browser) manda dati sbagliati, l'errore scoppia SUBITO al confine,
  non in mezzo alla logica.
- **SQLite**: zero configurazione, un file `microgarden.db` e via. Per un MVP
  monoutente è perfetto; lo schema è già pronto per il multi-utente (`user_id`).
- **Un solo file HTML**: niente build step, niente framework. Il browser fa solo
  due cose: disegnare cubi (Three.js) e chiamare le API (`fetch`). Tutta
  l'intelligenza sta nel backend Python.
- **Due viste sullo stesso stato**: il pulsante "📋 Vista lista" nell'HUD alterna
  tra la scena voxel e una vista classica a schede (un contenitore, le sue
  piante, i bottoni azione) — utile su schermi piccoli o quando serve
  precisione (aggiungere una pianta, spostarla, aggiornarne la crescita) senza
  affidarsi al click nella scena 3D. Sono la stessa pagina e lo stesso stato:
  cambiando vista non si ricarica nulla, solo cosa viene mostrato.
- **Contratti JSON per gli agenti**: i system prompt IMPONGONO all'AI di rispondere
  solo con JSON conforme agli schemi di `app/schemas.py`. Il testo libero è
  simpatico nelle chat, ma un'app ha bisogno di dati strutturati.

## Le API

| Metodo | Rotta | Cosa fa |
|---|---|---|
| POST | `/api/garden/analyze` | foto (facoltativa) + questionario → Agente 1 → salva il giardino → `GardenPlan` |
| GET | `/api/garden/{garden_id}` | stato completo per il rendering (piante, badge, punteggio, consociazioni) |
| POST | `/api/plant/{plant_id}/update` | foto progresso → Agente 2 → `GrowthLog` + eventuali nuovi badge |
| PATCH | `/api/plant/{plant_id}/move` | sposta la pianta in un altro contenitore (ricalcolo consociazioni, zero AI) |
| POST | `/api/garden/{garden_id}/containers` | aggiunge un contenitore a mano (posizione auto-assegnata, zero AI) |
| POST | `/api/garden/{garden_id}/plants` | aggiunge una pianta dal catalogo a un contenitore esistente (zero AI) |
| GET | `/api/plants/catalog` | il contenuto di `data/plants.json` |
| POST | `/api/garden/{garden_id}/share` | *(stub futuro)* snapshot JSON pubblico del giardino |
| GET | `/health` | `{"status": "ok", "mock_mode": true/false}` |

Esempio con `curl` (in MOCK_MODE va bene qualunque immagine):

```bash
curl -s -X POST http://localhost:8000/api/garden/analyze \
  -F "foto=@la_tua_foto.jpg" \
  -F "citta=Milano" -F "orientamento=sud" -F "ore_sole=6" \
  -F "minuti_settimana=60" -F "preferenze=pomodori e basilico"
```

**Non hai una foto a portata di mano?** Il campo `foto` è facoltativo: puoi
descrivere i tuoi contenitori a parole nel campo `descrizione_spazio` (nel
frontend è la textarea "Descrivi i tuoi contenitori"). Serve almeno uno dei
due — foto o descrizione — altrimenti l'Advisor non avrebbe nulla su cui
ragionare e l'API risponde 422 con un messaggio chiaro. Senza foto il piano è
necessariamente più prudente (contenitori "tipici" invece di quelli visti
davvero): l'Advisor lo dichiara esplicitamente in `note_analisi`.

```bash
curl -s -X POST http://localhost:8000/api/garden/analyze \
  -F "citta=Milano" -F "descrizione_spazio=2 vasi da 30 cm e una fioriera lunga" \
  -F "orientamento=sud" -F "ore_sole=6" -F "minuti_settimana=60"
```

## Gamification (Python puro)

**Badge** (`app/game/badges.py`) — assegnati solo se la foto è credibile (`coerenza ≥ 0.5`):

| id | nome | condizione |
|---|---|---|
| `primo_raccolto` | Primo raccolto! | primo report con `frutti_visibili=true` |
| `pollice_verde` | Pollice verde | 4 aggiornamenti foto in 4 settimane consecutive sulla stessa pianta |
| `biodiversita_5` | Custode di biodiversità | ≥5 specie diverse nel giardino |
| `salvataggio` | Salvataggio in extremis | salute da `sofferente/critica` a `buona/ottima` tra due report |
| `impollinatore` | Amico degli impollinatori | ≥2 piante di categoria `fiore` |

**Punteggio biodiversità** (`app/game/scoring.py`):

```
punteggio = (n_specie_diverse × 2)
          + (n_categorie_diverse × 1)
          + (2 se c'è almeno un fiore)
          + somma dei punti_biodiversita delle specie presenti
```

**Anti-cheat**: l'Agente 2 riceve anche il report precedente e la sua data, e valuta
se la nuova foto è plausibile (stessa pianta? progressione credibile?). Sotto
`coerenza 0.5` lo stato si aggiorna comunque, ma il report è `flagged` e **nessun
badge viene assegnato**.

## Costi stimati (MOCK_MODE=false)

Con `claude-sonnet-4-6` (input $3 / output $15 per milione di token):

| Chiamata | Token tipici | Costo indicativo |
|---|---|---|
| Analisi spazio (Advisor) | ~2.500 in + ~700 out | ~1,8 ¢ |
| Foto progresso (Tracker) | ~2.000 in + ~400 out | ~1,2 ¢ |

Le foto vengono ridimensionate a max 1568 px sul lato lungo **prima** dell'invio
(`app/imaging.py`): oltre quella soglia l'API riduce comunque l'immagine, quindi
manderemmo solo byte (e tempo) sprecati.

---

## 🤖 Come funziona un agente AI in questo progetto

Se stai imparando a costruire agenti, questo progetto ne contiene due, volutamente
semplici. Un "agente" qui è: **un prompt ben scritto + dati di contesto + un contratto
JSON + codice che valida la risposta**. Niente magia.

### 1. Il cuore: `call_agent()` in `app/agents/base.py`

Ogni agente passa da un'unica funzione che fa, in ordine:

1. **Mock o reale?** Se `MOCK_MODE=true` legge un file JSON da `tests/fixtures/`
   e lo valida con lo stesso schema Pydantic della risposta vera. Così sviluppi
   l'intera app senza spendere un centesimo.
2. **Chiamata API**: `client.messages.create(...)` con l'SDK `anthropic`.
   Le foto viaggiano come blocchi `{"type": "image", "source": {"type": "base64", ...}}`.
3. **Parsing**: estrae il testo, toglie eventuali recinzioni markdown (```json),
   fa `json.loads` e valida con Pydantic.
4. **Retry**: se il JSON non è valido, rimanda al modello il SUO output insieme
   all'errore e chiede di correggerlo. **Un solo retry**: se fallisce ancora,
   l'API risponde 502 con un messaggio chiaro. Mai loop infiniti sui retry.
5. **Logging**: ogni chiamata logga una sintesi del prompt, i token usati e l'esito.

### 2. Il prompt è un contratto, non una conversazione

I system prompt (in `advisor.py` e `tracker.py`) dicono al modello:
- CHI è ("sei un agronomo esperto di orti su balcone...");
- COSA riceve (foto, questionario, catalogo piante, mese corrente);
- COSA può scegliere (SOLO piante dall'elenco fornito — mai inventare id);
- COME rispondere (SOLO JSON conforme allo schema, senza testo prima o dopo).

### 3. La divisione dei compiti (la parte più importante)

| Compito | Chi lo fa | Perché |
|---|---|---|
| "In questa foto vedo 3 vasi da ~30 cm" | AI | serve percezione visiva |
| "Il basilico sta al 60% di maturazione" | AI | serve giudizio percettivo |
| "Questa foto non sembra la stessa pianta" | AI | serve confronto percettivo |
| punteggio biodiversità | Python | è una formula |
| badge e streak | Python | sono regole esatte |
| amici/nemici tra piante | Python | è una lookup in plants.json |

Quando progetti un agente, chiediti sempre: *"questa cosa richiede davvero
intelligenza, o è un `if`?"* — ogni compito spostato dal modello al codice è
più economico, più veloce, testabile e deterministico.

### 4. Anti-cheat con l'AI come giudice

Il Tracker riceve la foto nuova **e** il report precedente con la sua data. Il prompt
gli chiede un punteggio di `coerenza`: è la stessa pianta? La crescita è plausibile
nel tempo trascorso? La decisione su cosa farne (`flagged`, niente badge) è invece
**Python puro** in `routers/garden.py` — l'AI giudica, il codice applica le regole.
