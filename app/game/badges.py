"""Regole dei badge — Python puro, zero AI.

`check_badges()` viene chiamata dopo OGNI aggiornamento foto e ritorna
SOLO i badge appena sbloccati (quelli già assegnati non si ripetono:
c'è un vincolo di unicità sul DB e un controllo qui).

REGOLA ANTI-CHEAT: se il report appena salvato ha coerenza < 0.5
(quindi è `flagged`), NESSUN badge viene assegnato per quell'update.
Lo stato della pianta si aggiorna comunque, ma il gioco premia solo
progressi che l'AI ritiene autentici.
"""

from datetime import date

from sqlalchemy.orm import Session

from app import models
from app.catalogo import pianta_per_id

# Soglia sotto la quale un report non conta per badge e streak
SOGLIA_COERENZA = 0.5

SALUTE_CATTIVA = {"sofferente", "critica"}
SALUTE_BUONA = {"buona", "ottima"}

# Definizione dei badge: id → nome mostrato all'utente
BADGES = {
    "primo_raccolto": "Primo raccolto!",
    "pollice_verde": "Pollice verde",
    "biodiversita_5": "Custode di biodiversità",
    "salvataggio": "Salvataggio in extremis",
    "impollinatore": "Amico degli impollinatori",
}


def _indice_settimana(giorno: date) -> int:
    """Numero progressivo della settimana (lunedì-domenica) dal 1970.

    Trasformare le date in interi consecutivi rende banale il controllo
    'settimane consecutive': basta cercare 4 numeri di fila.
    (Il 5 gennaio 1970 era un lunedì.)
    """
    return (giorno - date(1970, 1, 5)).days // 7


def _ha_streak_di_4_settimane(plant: models.Plant) -> bool:
    """True se la pianta ha aggiornamenti validi in 4 settimane consecutive."""
    settimane = {
        _indice_settimana(log.created_at.date())
        for log in plant.growth_logs
        if log.coerenza >= SOGLIA_COERENZA
    }
    return any(
        {s, s + 1, s + 2, s + 3} <= settimane
        for s in settimane
    )


def check_badges(
    db: Session,
    garden: models.Garden,
    plant: models.Plant,
    nuovo_log: models.GrowthLog,
) -> list[models.Badge]:
    """Valuta tutte le regole e assegna i badge appena sbloccati.

    Ritorna la lista dei NUOVI badge (vuota se niente di nuovo).
    """
    # Anti-cheat: un report poco plausibile non fa scattare nulla.
    if nuovo_log.coerenza < SOGLIA_COERENZA:
        return []

    gia_presi = {b.badge_id for b in garden.badges}
    nuovi: list[models.Badge] = []

    def sblocca(badge_id: str) -> None:
        if badge_id in gia_presi:
            return
        badge = models.Badge(garden_id=garden.id, badge_id=badge_id, nome=BADGES[badge_id])
        db.add(badge)
        gia_presi.add(badge_id)
        nuovi.append(badge)

    # ── primo_raccolto: primo report con frutti visibili ──────────────
    if nuovo_log.frutti_visibili:
        sblocca("primo_raccolto")

    # ── pollice_verde: 4 aggiornamenti in 4 settimane consecutive ─────
    if _ha_streak_di_4_settimane(plant):
        sblocca("pollice_verde")

    # ── biodiversita_5: almeno 5 specie diverse nel giardino ──────────
    specie = {p.species_id for p in garden.plants}
    if len(specie) >= 5:
        sblocca("biodiversita_5")

    # ── salvataggio: da sofferente/critica a buona/ottima ─────────────
    # Confrontiamo il nuovo report con quello immediatamente precedente
    # della stessa pianta (growth_logs è ordinata per data).
    log_precedenti = [l for l in plant.growth_logs if l.id != nuovo_log.id]
    if log_precedenti:
        precedente = log_precedenti[-1]
        if precedente.salute in SALUTE_CATTIVA and nuovo_log.salute in SALUTE_BUONA:
            sblocca("salvataggio")

    # ── impollinatore: almeno 2 piante di categoria "fiore" ───────────
    n_fiori = sum(
        1 for p in garden.plants
        if (pianta_per_id(p.species_id) or {}).get("categoria") == "fiore"
    )
    if n_fiori >= 2:
        sblocca("impollinatore")

    return nuovi
