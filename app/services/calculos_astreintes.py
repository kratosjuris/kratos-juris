from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.services.calculos_utils import (
    br_date,
    br_money,
    daterange,
    is_business_day,
    parse_date,
    parse_money,
)


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular_astreintes(payload: dict) -> dict:
    processo = payload.get("processo") or ""
    vara = payload.get("vara") or ""
    exequente = payload.get("exequente") or ""
    executado = payload.get("executado") or ""
    tipo_contagem = payload.get("tipo_contagem") or "corridos"

    data_inicial = parse_date(payload.get("data_inicial"))
    data_final = parse_date(payload.get("data_final"))
    valor_diario = parse_money(payload.get("valor_diario"))

    itens = []
    acumulado = Decimal("0.00")

    if data_inicial and data_final and data_final >= data_inicial and valor_diario > 0:
        contador = 0

        for d in daterange(data_inicial, data_final):
            if tipo_contagem == "uteis" and not is_business_day(d):
                continue

            contador += 1
            acumulado = _q(acumulado + valor_diario)

            itens.append(
                {
                    "dia": contador,
                    "data": br_date(d),
                    "valor_diario": br_money(valor_diario),
                    "acumulado": br_money(acumulado),
                }
            )

    return {
        "processo": processo,
        "vara": vara,
        "exequente": exequente,
        "executado": executado,
        "tipo_contagem": "Dias úteis" if tipo_contagem == "uteis" else "Dias corridos",
        "data_inicial": br_date(data_inicial),
        "data_final": br_date(data_final),
        "valor_diario": br_money(valor_diario),
        "quantidade_dias": len(itens),
        "total": br_money(acumulado),
        "itens": itens,
    }