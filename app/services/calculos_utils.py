from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import calendar
import re


def br_money(value) -> str:
    try:
        v = Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        v = Decimal("0.00")

    s = f"{v:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def parse_money(value) -> Decimal:
    if value is None:
        return Decimal("0.00")

    s = str(value).strip()
    if not s:
        return Decimal("0.00")

    s = s.replace("R$", "").replace(" ", "")
    s = s.replace(".", "").replace(",", ".")

    try:
        return Decimal(s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def parse_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0.00")

    s = str(value).strip().replace("%", "").replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0.00")


def parse_date(value) -> date | None:
    if not value:
        return None

    s = str(value).strip()

    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass

    return None


def br_date(d: date | datetime | None) -> str:
    if not d:
        return ""

    if isinstance(d, datetime):
        d = d.date()

    return d.strftime("%d/%m/%Y")


def sanitize_filename(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]+', "-", name)
    name = re.sub(r"\s+", " ", name)
    return name or "documento"


def add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def is_business_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False

    fixed_holidays = {
        (1, 1),
        (4, 21),
        (5, 1),
        (9, 7),
        (10, 12),
        (11, 2),
        (11, 15),
        (11, 20),
        (12, 25),
    }

    if (d.month, d.day) in fixed_holidays:
        return False

    if (d.month == 12 and d.day >= 20) or (d.month == 1 and d.day <= 20):
        return False

    return True