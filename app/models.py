"""Tabelle del database (modelli ORM SQLAlchemy 2).

Rappresentano lo STATO DEL GIOCO, cioè il gemello digitale del giardino:

    Garden ──< Container ──< Plant ──< GrowthLog
       │
       └────< Badge

Nota multi-utente: l'MVP ha un solo utente, ma ogni Garden porta già
un campo `user_id` (default "local") così in futuro basterà filtrare
per utente senza cambiare lo schema.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def adesso() -> datetime:
    """Data/ora corrente in UTC (usata come default per i timestamp)."""
    return datetime.now(timezone.utc)


class Garden(Base):
    """Un giardino: lo spazio reale analizzato dall'Agente 1."""

    __tablename__ = "gardens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Predisposto per il multi-utente futuro: oggi è sempre "local".
    user_id: Mapped[str] = mapped_column(String(64), default="local", index=True)

    # Cosa ha capito l'Advisor guardando la foto
    tipo_spazio: Mapped[str] = mapped_column(String(20))       # balcone | terrazzo | davanzale | giardino
    luce_stimata: Mapped[str] = mapped_column(String(20))      # pieno_sole | mezz_ombra | ombra
    note_analisi: Mapped[str] = mapped_column(Text, default="")

    # Dati del questionario utile a ri-contestualizzare in futuro
    citta: Mapped[str] = mapped_column(String(80), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=adesso)

    containers: Mapped[list["Container"]] = relationship(
        back_populates="garden", cascade="all, delete-orphan"
    )
    plants: Mapped[list["Plant"]] = relationship(
        back_populates="garden", cascade="all, delete-orphan"
    )
    badges: Mapped[list["Badge"]] = relationship(
        back_populates="garden", cascade="all, delete-orphan"
    )


class Container(Base):
    """Un contenitore (vaso, fioriera, cassetta o terra piena) nel giardino."""

    __tablename__ = "containers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    garden_id: Mapped[int] = mapped_column(ForeignKey("gardens.id"), index=True)

    # Codice leggibile assegnato dall'Advisor, es. "vaso_1"
    codice: Mapped[str] = mapped_column(String(40))
    tipo: Mapped[str] = mapped_column(String(20))              # vaso | fioriera | cassetta | terra
    diametro_cm: Mapped[int] = mapped_column(Integer, default=30)

    # Posizione sulla griglia del rendering voxel
    pos_x: Mapped[int] = mapped_column(Integer, default=0)
    pos_z: Mapped[int] = mapped_column(Integer, default=0)

    garden: Mapped["Garden"] = relationship(back_populates="containers")
    plants: Mapped[list["Plant"]] = relationship(back_populates="container")


class Plant(Base):
    """Una pianta coltivata in un contenitore.

    `species_id` è l'id della specie in data/plants.json (es. "basilico"):
    le caratteristiche botaniche NON sono duplicate nel DB, si leggono
    sempre dal catalogo JSON (unica fonte di verità).
    """

    __tablename__ = "plants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    garden_id: Mapped[int] = mapped_column(ForeignKey("gardens.id"), index=True)
    container_id: Mapped[int] = mapped_column(ForeignKey("containers.id"), index=True)

    species_id: Mapped[str] = mapped_column(String(40), index=True)
    motivo: Mapped[str] = mapped_column(Text, default="")        # perché l'Advisor l'ha consigliata
    quando_piantare: Mapped[str] = mapped_column(String(60), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=adesso)

    garden: Mapped["Garden"] = relationship(back_populates="plants")
    container: Mapped["Container"] = relationship(back_populates="plants")
    growth_logs: Mapped[list["GrowthLog"]] = relationship(
        back_populates="plant", cascade="all, delete-orphan", order_by="GrowthLog.created_at"
    )


class GrowthLog(Base):
    """Un aggiornamento di crescita: il GrowthReport dell'Agente 2 salvato.

    Le liste (problemi, consigli) sono salvate come stringhe JSON:
    per un MVP su SQLite è la scelta più semplice e leggibile.
    """

    __tablename__ = "growth_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), index=True)

    stadio: Mapped[float] = mapped_column(Float)                 # 0.0 → 1.0
    salute: Mapped[str] = mapped_column(String(20))              # ottima | buona | sofferente | critica
    problemi_json: Mapped[str] = mapped_column(Text, default="[]")
    consigli_json: Mapped[str] = mapped_column(Text, default="[]")
    frutti_visibili: Mapped[bool] = mapped_column(Boolean, default=False)
    giorni_al_raccolto_stimati: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Anti-cheat: quanto è plausibile la foto rispetto alla precedente.
    # Se coerenza < 0.5 il report viene marcato flagged e NON genera badge.
    coerenza: Mapped[float] = mapped_column(Float, default=1.0)
    note_coerenza: Mapped[str] = mapped_column(Text, default="")
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)

    # True se l'utente ha impostato stadio/salute a mano, senza foto né AI.
    # Un log manuale ha SEMPRE coerenza 0.0 e flagged True (vedi
    # routers/garden.py): non deve mai contare per badge o streak, esattamente
    # come una foto che l'AI ha giudicato poco plausibile.
    manuale: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=adesso)

    plant: Mapped["Plant"] = relationship(back_populates="growth_logs")


class Badge(Base):
    """Un badge sbloccato in un giardino. Mai assegnato due volte
    (vincolo di unicità su garden_id + badge_id)."""

    __tablename__ = "badges"
    __table_args__ = (UniqueConstraint("garden_id", "badge_id", name="uq_garden_badge"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    garden_id: Mapped[int] = mapped_column(ForeignKey("gardens.id"), index=True)

    badge_id: Mapped[str] = mapped_column(String(40))            # es. "primo_raccolto"
    nome: Mapped[str] = mapped_column(String(80))                # es. "Primo raccolto!"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=adesso)

    garden: Mapped["Garden"] = relationship(back_populates="badges")
