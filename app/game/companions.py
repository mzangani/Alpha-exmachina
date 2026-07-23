"""Consociazioni tra piante — Python puro, zero AI.

Per ogni coppia di piante nello STESSO contenitore o in contenitori
ADIACENTI (distanza sulla griglia ≤ 1, diagonali comprese):
- se le specie sono "amiche"  → messaggio positivo (bonus);
- se sono "nemiche"           → warning.

La distanza usata è quella di Chebyshev: max(|dx|, |dz|) ≤ 1, cioè le
otto celle attorno più la cella stessa.
"""

from app import models
from app.catalogo import pianta_per_id
from app.schemas import ConsociazioneOut


def _vicini(c1: models.Container, c2: models.Container) -> bool:
    """True se i due contenitori sono lo stesso o adiacenti sulla griglia."""
    if c1.id == c2.id:
        return True
    return max(abs(c1.pos_x - c2.pos_x), abs(c1.pos_z - c2.pos_z)) <= 1


def analizza_consociazioni(plants: list[models.Plant]) -> list[ConsociazioneOut]:
    """Esamina tutte le coppie di piante vicine e ritorna bonus/warning.

    Le coppie di specie già segnalate non vengono ripetute (se hai tre
    basilici accanto a un pomodoro, il bonus compare una volta sola).
    """
    risultati: list[ConsociazioneOut] = []
    coppie_viste: set[tuple[str, str, str]] = set()

    for i, p1 in enumerate(plants):
        scheda1 = pianta_per_id(p1.species_id)
        if scheda1 is None:
            continue
        for p2 in plants[i + 1 :]:
            scheda2 = pianta_per_id(p2.species_id)
            if scheda2 is None or p1.species_id == p2.species_id:
                continue
            if not _vicini(p1.container, p2.container):
                continue

            # Chiave normalizzata (ordine alfabetico) per non duplicare
            chiave_specie = tuple(sorted([p1.species_id, p2.species_id]))

            stesso_vaso = p1.container_id == p2.container_id
            dove = "nello stesso contenitore" if stesso_vaso else "in contenitori vicini"

            if p2.species_id in scheda1["amici"]:
                chiave = (*chiave_specie, "amici")
                if chiave in coppie_viste:
                    continue
                coppie_viste.add(chiave)
                risultati.append(
                    ConsociazioneOut(
                        tipo="amici",
                        piante=[scheda1["nome"], scheda2["nome"]],
                        messaggio=(
                            f"{scheda1['nome']} e {scheda2['nome']} {dove}: "
                            "ottima consociazione, si aiutano a vicenda!"
                        ),
                    )
                )
            elif p2.species_id in scheda1["nemici"]:
                chiave = (*chiave_specie, "nemici")
                if chiave in coppie_viste:
                    continue
                coppie_viste.add(chiave)
                risultati.append(
                    ConsociazioneOut(
                        tipo="nemici",
                        piante=[scheda1["nome"], scheda2["nome"]],
                        messaggio=(
                            f"Attenzione: {scheda1['nome']} e {scheda2['nome']} {dove} "
                            "non vanno d'accordo. Meglio allontanarle."
                        ),
                    )
                )

    return risultati
