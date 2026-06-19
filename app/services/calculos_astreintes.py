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


def _calcular_periodo(
    descricao: str,
    data_inicial,
    data_final,
    valor_diario: Decimal,
    limite: Decimal,
    tipo_contagem: str,
    numero: int,
) -> dict:
    """Calcula um único período de astreintes."""
    itens = []
    acumulado = Decimal("0.00")

    for d in daterange(data_inicial, data_final):
        if tipo_contagem == "uteis" and not is_business_day(d):
            continue

        acumulado = _q(acumulado + valor_diario)

        # Aplica limite máximo se informado
        if limite > 0 and acumulado > limite:
            acumulado = limite

        itens.append({
            "data": br_date(d),
            "valor_diario": br_money(valor_diario),
            "acumulado": br_money(acumulado),
        })

        # Para de acumular se atingiu o limite
        if limite > 0 and acumulado >= limite:
            break

    return {
        "numero":       numero,
        "descricao":    descricao or f"Período {numero}",
        "data_inicial": br_date(data_inicial),
        "data_final":   br_date(data_final),
        "valor_diario": br_money(valor_diario),
        "limite":       br_money(limite) if limite > 0 else "Sem limite",
        "quantidade_dias": len(itens),
        "total":        br_money(acumulado),
        "itens":        itens,
    }


def calcular_astreintes(payload: dict) -> dict:
    processo      = payload.get("processo") or ""
    vara          = payload.get("vara") or ""
    exequente     = payload.get("exequente") or ""
    executado     = payload.get("executado") or ""
    tipo_contagem = payload.get("tipo_contagem") or "corridos"

    # Suporte ao formato antigo (campo único) e novo (lista de períodos)
    periodos_raw = payload.get("periodos") or []

    # Compatibilidade com formato antigo (um único período via campos diretos)
    if not periodos_raw:
        data_inicial = parse_date(payload.get("data_inicial"))
        data_final   = parse_date(payload.get("data_final"))
        valor_diario = parse_money(payload.get("valor_diario"))
        if data_inicial and data_final and valor_diario > 0:
            periodos_raw = [{
                "descricao":    "Período único",
                "data_inicial": payload.get("data_inicial"),
                "data_final":   payload.get("data_final"),
                "valor":        payload.get("valor_diario"),
                "limite":       "",
            }]

    periodos_resultado = []
    total_geral = Decimal("0.00")

    for i, p in enumerate(periodos_raw, start=1):
        data_inicial = parse_date(p.get("data_inicial"))
        data_final   = parse_date(p.get("data_final"))
        valor_diario = parse_money(p.get("valor"))
        limite       = parse_money(p.get("limite") or "0")
        descricao    = p.get("descricao") or f"Período {i}"

        if not data_inicial or not data_final:
            continue
        if data_final < data_inicial:
            continue
        if valor_diario <= 0:
            continue

        periodo = _calcular_periodo(
            descricao=descricao,
            data_inicial=data_inicial,
            data_final=data_final,
            valor_diario=valor_diario,
            limite=limite,
            tipo_contagem=tipo_contagem,
            numero=i,
        )
        periodos_resultado.append(periodo)
        total_geral = _q(total_geral + parse_money(periodo["total"]))

    # Dados do primeiro período para compatibilidade com template antigo
    primeiro = periodos_resultado[0] if periodos_resultado else {}

    return {
        "processo":      processo,
        "vara":          vara,
        "exequente":     exequente,
        "executado":     executado,
        "tipo_contagem": "Dias úteis" if tipo_contagem == "uteis" else "Dias corridos",
        "periodos":      periodos_resultado,
        "total_geral":   br_money(total_geral),
        "total_periodos": len(periodos_resultado),
        # Campos legados para compatibilidade
        "data_inicial":    primeiro.get("data_inicial", ""),
        "data_final":      primeiro.get("data_final", ""),
        "valor_diario":    primeiro.get("valor_diario", ""),
        "quantidade_dias": sum(p["quantidade_dias"] for p in periodos_resultado),
        "total":           br_money(total_geral),
        "itens":           [i for p in periodos_resultado for i in p["itens"]],
    }