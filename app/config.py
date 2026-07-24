"""Configurazione dell'applicazione.

Legge le variabili d'ambiente dal file `.env` (o dall'ambiente di sistema)
usando pydantic-settings. Tutto il resto del codice importa `settings`
da qui: c'è UN solo punto in cui si decide la configurazione.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Cartella radice del progetto (quella che contiene `app/`, `data/`, ecc.)
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Tutte le impostazioni dell'app, con i loro valori di default."""

    # Chiave API di Anthropic. Vuota di default: obbligatoria solo
    # quando MOCK_MODE è false (viene controllato in app/agents/base.py).
    anthropic_api_key: str = ""

    # Modello Claude usato dagli agenti.
    model_name: str = "claude-sonnet-4-6"

    # Se true gli agenti NON chiamano l'API e usano i file
    # in tests/fixtures/ come risposte finte (sviluppo gratis).
    mock_mode: bool = True

    # Stringa di connessione al database SQLite.
    database_url: str = "sqlite:///./microgarden.db"

    # Dice a pydantic-settings di leggere il file .env nella radice
    # del progetto, ignorando eventuali variabili non dichiarate qui.
    # protected_namespaces=(): il campo `model_name` inizia per "model_",
    # prefisso che Pydantic riserva ai suoi metodi interni (model_dump,
    # model_validate, ...); qui è solo il nome di un nostro campo, quindi
    # disattiviamo l'avviso.
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
    )


@lru_cache
def get_settings() -> Settings:
    """Ritorna le impostazioni (calcolate una volta sola, poi in cache)."""
    return Settings()


# Istanza condivisa, importabile ovunque: `from app.config import settings`
settings = get_settings()
