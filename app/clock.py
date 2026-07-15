"""Reloj de pared en la zona horaria de la oficina.

El dominio trata los datetimes naive como hora local de America/Montevideo
(ver doc/DECISIONS.md, D10/D15). `datetime.now()` a secas lee la zona del
proceso, que es UTC en el contenedor, así que acá fijamos la zona explícita y
sacamos el offset para mantener la convención naive-local del resto del código.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

OFFICE_TZ = ZoneInfo("America/Montevideo")


def now_local() -> datetime:
    """Hora de pared actual en la zona de la oficina, como datetime naive."""
    return datetime.now(OFFICE_TZ).replace(tzinfo=None)
