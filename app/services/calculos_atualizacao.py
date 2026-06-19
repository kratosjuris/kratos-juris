from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.services.calculos_utils import (
    br_date,
    br_money,
    parse_date,
    parse_decimal,
    parse_money,
)
from app.services.indices_monetarios import (
    calcular_fator_correcao,
    get_indice_nome,
    calcular_juros_legais,
    obter_detalhamento_indices,
)


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _indice_curto(indice: str) -> str:
    mapa = {"tjdft": "INPC/IPCA", "inpc": "INPC", "ipca": "IPCA"}
    return mapa.get(indice, indice.upper())


def calcular_atualizacao(payload: dict) -> dict:
    data_final = parse_date(payload.get("data_final_calculo")) or date.today()
    indice = payload.get("indice_correcao") or "tjdft"

    juros_tipo        = payload.get("juros_tipo") or "sem"
    juros_percentual  = parse_decimal(payload.get("juros_percentual"))
    juros_incidencia  = payload.get("juros_incidencia") or "data_valor"
    juros_data_base   = parse_date(payload.get("juros_data_base"))

    # Descrição e período dos juros — montados APÓS parse de juros_data_base
    _pct_str = payload.get("juros_percentual") or "?"
    _juros_desc_map = {
        "sem":         "Sem juros",
        "percentual":  f"Percentual fixo de {_pct_str}% ao mês",
        "um_porcento": "1% ao mês",
        "legal":       "Taxa Legal (Lei 14.905/2024 — SELIC − IPCA)",
    }
    juros_descricao = _juros_desc_map.get(juros_tipo, juros_tipo)

    _data_base_str = br_date(juros_data_base) if juros_data_base else "?"
    _incid_map = {
        "data_valor": "A partir da data de cada valor",
        "citacao":    f"A partir da citação ou outra data — {_data_base_str} até {br_date(data_final)}",
        "data_fixa":  f"A partir de {_data_base_str} até {br_date(data_final)}",
    }
    juros_incidencia_desc = _incid_map.get(juros_incidencia, juros_incidencia) if juros_tipo != "sem" else ""

    lancamentos = payload.get("lancamentos") or []
    deducoes    = payload.get("deducoes") or []

    itens = []

    total_original  = Decimal("0.00")
    total_corrigido = Decimal("0.00")
    total_juros     = Decimal("0.00")

    datas_correcao = []
    datas_juros    = []

    for row in lancamentos:
        data_valor     = parse_date(row.get("data"))
        valor_original = parse_money(row.get("valor"))
        descricao      = row.get("descricao") or ""
        tipo           = row.get("tipo") or "Outro"

        if not data_valor or valor_original <= 0:
            continue

        fator           = calcular_fator_correcao(data_valor, data_final, indice)
        valor_corrigido = _q(valor_original * fator)

        # --- data de início dos juros ---
        data_inicio_juros = data_valor

        if juros_incidencia == "citacao":
            if juros_data_base and data_valor < juros_data_base:
                data_inicio_juros = juros_data_base
            else:
                data_inicio_juros = data_valor
        elif juros_incidencia == "data_fixa":
            data_inicio_juros = juros_data_base or data_valor

        juros_valor            = Decimal("0.00")
        juros_percentual_total = Decimal("0.00")

        if juros_tipo == "percentual" and juros_percentual > 0:
            dias = max((data_final - data_inicio_juros).days, 0)
            meses = Decimal(dias) / Decimal("30")
            juros_percentual_total = juros_percentual * meses
            juros_valor = _q(valor_corrigido * (juros_percentual_total / Decimal("100")))

        elif juros_tipo == "um_porcento":
            dias = max((data_final - data_inicio_juros).days, 0)
            meses = Decimal(dias) / Decimal("30")
            juros_percentual_total = Decimal("1") * meses
            juros_valor = _q(valor_corrigido * (juros_percentual_total / Decimal("100")))

        elif juros_tipo == "legal":
            juros_valor, juros_percentual_total = calcular_juros_legais(
                valor_corrigido, data_inicio_juros, data_final
            )
            juros_valor = _q(juros_valor)

        total_linha = _q(valor_corrigido + juros_valor)

        total_original  += valor_original
        total_corrigido += valor_corrigido
        total_juros     += juros_valor

        datas_correcao.append(data_valor)
        if juros_tipo != "sem":
            datas_juros.append(data_inicio_juros)

        _valor_atualizacao = _q(valor_corrigido - valor_original)

        itens.append({
            "data":                   br_date(data_valor),
            "tipo":                   tipo,
            "descricao":              descricao,
            "valor_original":         br_money(valor_original),
            "fator":                  str(fator),
            "valor_atualizacao":      br_money(_valor_atualizacao),
            "valor_corrigido":        br_money(valor_corrigido),
            "data_inicio_juros":      br_date(data_inicio_juros),
            "juros_percentual_total": f"{juros_percentual_total:.2f}%",
            "juros":                  br_money(juros_valor),
            "total":                  br_money(total_linha),
        })

    # --- custas (sempre valor fixo) ---
    custas = parse_money(payload.get("custas_valor"))

    # --- base para cálculo percentual ---
    base_acessorios = _q(total_corrigido + total_juros)

    # --- multas: lista com descrição, tipo e valor/percentual ---
    multas_lista = payload.get("multas") or []
    multas_resultado = []
    multa = Decimal("0.00")
    multa_label = ""

    for m in multas_lista:
        m_tipo = m.get("tipo") or "valor"
        m_desc = m.get("descricao") or "Multa"
        m_pct  = parse_decimal(m.get("percentual"))
        m_val  = parse_money(m.get("valor"))
        if m_tipo == "percentual" and m_pct > 0:
            m_calculado = _q(base_acessorios * (m_pct / Decimal("100")))
            m_ref = f"{m_pct:.2f}%"
        else:
            m_calculado = m_val
            m_ref = br_money(m_val)
        if m_calculado <= 0:
            continue
        multa += m_calculado
        multas_resultado.append({
            "descricao": m_desc,
            "tipo": "Percentual" if m_tipo == "percentual" else "Valor fixo",
            "referencia": m_ref,
            "valor": br_money(m_calculado),
        })

    if multas_resultado:
        multa_label = "; ".join(m["descricao"] for m in multas_resultado)

    # --- honorários: lista com descrição, tipo e valor/percentual ---
    honorarios_lista = payload.get("honorarios_lista") or []
    honorarios_resultado = []
    honorarios = Decimal("0.00")
    honorarios_label = ""

    for h in honorarios_lista:
        h_tipo = h.get("tipo") or "valor"
        h_desc = h.get("descricao") or "Honorários"
        h_pct  = parse_decimal(h.get("percentual"))
        h_val  = parse_money(h.get("valor"))
        if h_tipo == "percentual" and h_pct > 0:
            h_calculado = _q(base_acessorios * (h_pct / Decimal("100")))
            h_ref = f"{h_pct:.2f}%"
        else:
            h_calculado = h_val
            h_ref = br_money(h_val)
        if h_calculado <= 0:
            continue
        honorarios += h_calculado
        honorarios_resultado.append({
            "descricao": h_desc,
            "tipo": "Percentual" if h_tipo == "percentual" else "Valor fixo",
            "referencia": h_ref,
            "valor": br_money(h_calculado),
        })

    if honorarios_resultado:
        honorarios_label = "; ".join(h["descricao"] for h in honorarios_resultado)

    multa_percentual      = Decimal("0")
    honorarios_percentual = Decimal("0")
    multa_tipo            = "valor"
    honorarios_tipo       = "valor"

    # --- total bruto ---
    total_bruto = _q(total_corrigido + total_juros + multa + honorarios + custas)

    # --- deduções ---
    deducoes_resultado = []
    total_deducoes     = Decimal("0.00")

    for d in deducoes:
        nome       = d.get("nome") or "Dedução"
        tipo       = d.get("tipo") or "valor"
        valor      = parse_money(d.get("valor"))
        percentual = parse_decimal(d.get("percentual"))

        if tipo == "percentual":
            deduzido  = _q(total_bruto * (percentual / Decimal("100")))
            descricao = f"{percentual}%"
        else:
            deduzido  = valor
            descricao = br_money(valor)

        if deduzido <= 0:
            continue

        total_deducoes += deduzido
        deducoes_resultado.append({
            "nome":           nome,
            "tipo":           "Percentual" if tipo == "percentual" else "Valor fixo",
            "referencia":     descricao,
            "valor_deduzido": br_money(deduzido),
        })

    total_liquido = _q(total_bruto - total_deducoes)
    if total_liquido < 0:
        total_liquido = Decimal("0.00")

    # --- detalhamento de índices ---
    detalhamento_indices = []
    if datas_correcao:
        data_inicio_min = min(datas_correcao)
        detalhamento_indices = obter_detalhamento_indices(
            indice=indice,
            data_inicio=data_inicio_min,
            data_final=data_final,
            juros_tipo=juros_tipo,
            data_inicio_juros=min(datas_juros) if datas_juros else None,
        )

    memoria_texto = montar_memoria_texto(
        itens=itens,
        total_original=total_original,
        total_corrigido=total_corrigido,
        total_juros=total_juros,
        multa=multa,
        multa_label=multa_label,
        honorarios=honorarios,
        honorarios_label=honorarios_label,
        custas=custas,
        total_bruto=total_bruto,
        deducoes=deducoes_resultado,
        total_deducoes=total_deducoes,
        total_liquido=total_liquido,
    )

    return {
        "processo":            payload.get("processo") or "",
        "vara":                payload.get("vara") or "",
        "exequente":           payload.get("exequente") or "",
        "executado":           payload.get("executado") or "",
        "data_calculo":        br_date(data_final),
        "indice_correcao":     get_indice_nome(indice),
        "indice_correcao_curto": _indice_curto(indice),
        "juros_tipo":          juros_tipo,
        "juros_descricao":     juros_descricao,
        "juros_periodo":       juros_incidencia_desc,
        "itens":               itens,
        "deducoes":            deducoes_resultado,
        "detalhamento_indices": detalhamento_indices,
        "valor_original":      br_money(total_original),
        "valor_corrigido":     br_money(total_corrigido),
        "juros":               br_money(total_juros),
        "multa":               br_money(multa),
        "multa_label":         multa_label,
        "multa_percentual_display": "",
        "multas_lista":        multas_resultado,
        "honorarios":          br_money(honorarios),
        "honorarios_label":    honorarios_label,
        "honorarios_percentual_display": "",
        "honorarios_lista":    honorarios_resultado,
        "custas":              br_money(custas),
        "total_bruto":         br_money(total_bruto),
        "total_deducoes":      br_money(total_deducoes),
        "total_liquido":       br_money(total_liquido),
        "total_principal":     br_money(_q(total_corrigido + total_juros)),
        "tem_acessorios":      (honorarios > Decimal("0") or multa > Decimal("0") or custas > Decimal("0")),
        "total_acessorios":    br_money(_q(honorarios + multa + custas)),
        "memoria_calculo":     memoria_texto,
    }


def montar_memoria_texto(
    itens,
    total_original,
    total_corrigido,
    total_juros,
    multa,
    multa_label,
    honorarios,
    honorarios_label,
    custas,
    total_bruto,
    deducoes,
    total_deducoes,
    total_liquido,
) -> str:
    linhas = []

    linhas.append("MEMORIAL DE CÁLCULO")
    linhas.append("")
    linhas.append("VALORES DEVIDOS:")

    for i, item in enumerate(itens, start=1):
        linhas.append(
            f"{i}. {item['data']} - {item['tipo']} - {item['descricao']} - "
            f"Valor original: {item['valor_original']} - "
            f"Valor corrigido: {item['valor_corrigido']} - "
            f"Juros: {item['juros']} - Total: {item['total']}"
        )

    linhas.append("")
    linhas.append(f"Valor original: {br_money(total_original)}")
    linhas.append(f"Valor corrigido: {br_money(total_corrigido)}")
    linhas.append(f"Juros: {br_money(total_juros)}")

    if multa_label:
        linhas.append(f"Multa ({multa_label}): {br_money(multa)}")
    else:
        linhas.append(f"Multa: {br_money(multa)}")

    if honorarios_label:
        linhas.append(f"Honorários ({honorarios_label}): {br_money(honorarios)}")
    else:
        linhas.append(f"Honorários: {br_money(honorarios)}")

    linhas.append(f"Custas: {br_money(custas)}")
    linhas.append(f"Total bruto: {br_money(total_bruto)}")

    if deducoes:
        linhas.append("")
        linhas.append("DEDUÇÕES:")
        for d in deducoes:
            linhas.append(
                f"- {d['nome']} ({d['tipo']} - {d['referencia']}): {d['valor_deduzido']}"
            )

    linhas.append(f"Total de deduções: {br_money(total_deducoes)}")
    linhas.append(f"TOTAL LÍQUIDO DEVIDO: {br_money(total_liquido)}")

    return "\n".join(linhas)