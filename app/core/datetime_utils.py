from datetime import datetime
from zoneinfo import ZoneInfo

TZ_BR = ZoneInfo("America/Sao_Paulo")

def now_br():
    return datetime.now(TZ_BR).replace(tzinfo=None)