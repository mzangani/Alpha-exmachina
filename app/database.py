"""Connessione al database SQLite con SQLAlchemy 2.

Espone:
- `engine`: la connessione al file SQLite
- `SessionLocal`: la "fabbrica" di sessioni (una sessione = una conversazione col DB)
- `Base`: la classe base da cui ereditano tutte le tabelle (vedi models.py)
- `get_db()`: dependency di FastAPI che apre/chiude una sessione per ogni richiesta
- `init_db()`: crea le tabelle al primo avvio
"""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# `check_same_thread=False` serve perché FastAPI può gestire la stessa
# richiesta su thread diversi; SQLite di default non lo permetterebbe.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Classe base per tutti i modelli ORM (le tabelle)."""


def get_db() -> Generator[Session, None, None]:
    """Dependency FastAPI: apre una sessione DB e la chiude a fine richiesta.

    Si usa negli endpoint così:  db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _aggiungi_colonne_mancanti() -> None:
    """Piccola auto-migrazione per SQLite.

    `Base.metadata.create_all()` crea le tabelle che NON esistono ancora,
    ma non aggiunge colonne nuove a tabelle già esistenti. Se un `git pull`
    porta un modello con un campo in più (es. `manuale` su GrowthLog) e
    l'utente ha già un `microgarden.db` locale creato con una versione
    precedente del codice, la prima query fallirebbe con "no such column".
    Qui controlliamo ed eventualmente aggiungiamo le colonne mancanti,
    così un DB esistente continua a funzionare senza doverlo cancellare.
    """
    colonne_da_garantire = {
        "growth_logs": [("manuale", "BOOLEAN DEFAULT 0")],
    }
    with engine.connect() as conn:
        for tabella, colonne in colonne_da_garantire.items():
            esistenti = {
                riga[1] for riga in conn.execute(text(f"PRAGMA table_info({tabella})")).fetchall()
            }
            if not esistenti:
                continue  # la tabella non esiste ancora: create_all() l'ha già creata completa
            for nome_colonna, definizione in colonne:
                if nome_colonna not in esistenti:
                    conn.execute(text(f"ALTER TABLE {tabella} ADD COLUMN {nome_colonna} {definizione}"))
        conn.commit()


def init_db() -> None:
    """Crea tutte le tabelle definite in models.py (se non esistono già)."""
    # L'import è qui dentro per evitare import circolari:
    # models.py importa Base da questo file.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _aggiungi_colonne_mancanti()
