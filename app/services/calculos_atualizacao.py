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


def _get_indice_para_data(periodos_correcao: list, data_valor: date, data_final: date) -> str:
    """
    Retorna o índice a aplicar para um dado lançamento com base nos
    períodos de correção configurados.

    Cada período tem apenas data_fim (opcional). A data de início
    é sempre a data do lançamento — portanto aplica o índice cujo
    data_fim é >= data_valor, na ordem em que foram cadastrados.
    Se não houver períodos ou nenhum casar, usa tjdft.
    """
    if not periodos_correcao:
        return "tjdft"

    for p in periodos_correcao:
        df = parse_date(p.get("data_fim")) or data_final
        if data_valor <= df:
            return p.get("indice") or "tjdft"

    # Se passou de todos os períodos, usa o último
    return periodos_correcao[-1].get("indice") or "tjdft"


def _calcular_juros_periodo(
    valor_corrigido: Decimal,
    periodo: dict,
    data_valor: date,
    data_final: date,
) -> tuple[Decimal, Decimal]:
    """
    Calcula juros de um único período.
    Retorna (valor_juros, percentual_total).
    """
    tipo       = periodo.get("tipo") or "sem"
    percentual = parse_decimal(periodo.get("percentual"))
    incidencia = periodo.get("incidencia") or "data_valor"
    data_fim   = parse_date(periodo.get("data_fim")) or data_final

    # Data de início
    if incidencia == "data_fixa":
        data_inicio = parse_date(periodo.get("data_inicio"))
        if not data_inicio:
            return Decimal("0"), Decimal("0")
    else:
        # data_valor = data do lançamento
        data_inicio = data_valor

    if tipo == "sem" or not data_inicio:
        return Decimal("0"), Decimal("0")

    if data_fim > data_final:
        data_fim = data_final
    if data_fim <= data_inicio:
        return Decimal("0"), Decimal("0")

    if tipo == "percentual" and percentual > 0:
        dias   = max((data_fim - data_inicio).days, 0)
        meses  = Decimal(dias) / Decimal("30")
        pct    = percentual * meses
        valor  = _q(valor_corrigido * (pct / Decimal("100")))
        return valor, pct

    elif tipo == "um_porcento":
        dias   = max((data_fim - data_inicio).days, 0)
        meses  = Decimal(dias) / Decimal("30")
        pct    = Decimal("1") * meses
        valor  = _q(valor_corrigido * (pct / Decimal("100")))
        return valor, pct

    elif tipo == "legal":
        valor, pct = calcular_juros_legais(valor_corrigido, data_inicio, data_fim)
        return _q(valor), pct

    return Decimal("0"), Decimal("0")


def _montar_descricao_juros(periodos_juros: list) -> str:
    labels = {
        "sem":         "Sem juros",
        "um_porcento": "1% a.m.",
        "legal":       "Taxa Legal",
        "percentual":  "% a.m.",
    }
    partes = []
    for p in periodos_juros:
        tipo = p.get("tipo","sem")
        if tipo == "sem":
            continue
        pct   = f" {p.get('percentual','')}" if tipo == "percentual" else ""
        di    = br_date(parse_date(p.get("data_inicio"))) or "?"
        df    = br_date(parse_date(p.get("data_fim"))) if p.get("data_fim") else "data final"
        partes.append(f"{labels.get(tipo,tipo)}{pct} ({di} a {df})")
    return " | ".join(partes) if partes else "Sem juros"


def calcular_atualizacao(payload: dict) -> dict:
    data_final          = parse_date(payload.get("data_final_calculo")) or date.today()
    periodos_correcao   = payload.get("periodos_correcao") or []
    periodos_juros_glob = payload.get("periodos_juros") or []

    # Índice padrão (para relatório e detalhamento)
    indice_padrao = periodos_correcao[0].get("indice") if periodos_correcao else "tjdft"

    # Descrição de juros para o cabeçalho
    juros_descricao     = _montar_descricao_juros(periodos_juros_glob)
    juros_tipo_global   = periodos_juros_glob[0].get("tipo") if periodos_juros_glob else "sem"
    juros_incidencia_desc = ""
    if periodos_juros_glob:
        partes = []
        for p in periodos_juros_glob:
            di = br_date(parse_date(p.get("data_inicio"))) if p.get("data_inicio") else "data de cada valor"
            df = br_date(parse_date(p.get("data_fim"))) if p.get("data_fim") else "data final"
            partes.append(f"{di} a {df}")
        juros_incidencia_desc = " | ".join(partes)

    lancamentos = payload.get("lancamentos") or []
    deducoes    = payload.get("deducoes") or []

    itens           = []
    total_original  = Decimal("0.00")
    total_corrigido = Decimal("0.00")
    total_juros     = Decimal("0.00")
    datas_correcao  = []
    datas_juros     = []

    for row in lancamentos:
        data_valor     = parse_date(row.get("data"))
        valor_original = parse_money(row.get("valor"))
        descricao      = row.get("descricao") or ""
        tipo           = row.get("tipo") or "Outro"

        if not data_valor or valor_original <= 0:
            continue

        # Índice para este lançamento
        indice_lancamento = _get_indice_para_data(periodos_correcao, data_valor, data_final)
        fator             = calcular_fator_correcao(data_valor, data_final, indice_lancamento)
        valor_corrigido   = _q(valor_original * fator)
        _valor_atualizacao = _q(valor_corrigido - valor_original)

        # Juros: soma de todos os períodos configurados
        juros_valor            = Decimal("0.00")
        juros_percentual_total = Decimal("0.00")
        data_inicio_juros_exib = data_final

        for p in periodos_juros_glob:
            v, pct = _calcular_juros_periodo(valor_corrigido, p, data_valor, data_final)
            juros_valor            += v
            juros_percentual_total += pct
            di = parse_date(p.get("data_inicio")) if p.get("incidencia") == "data_fixa" else data_valor
            if di and di < data_inicio_juros_exib:
                data_inicio_juros_exib = di

        juros_valor = _q(juros_valor)

        if periodos_juros_glob:
            datas_juros.append(data_inicio_juros_exib)

        total_linha      = _q(valor_corrigido + juros_valor)
        total_original  += valor_original
        total_corrigido += valor_corrigido
        total_juros     += juros_valor
        datas_correcao.append(data_valor)

        itens.append({
            "data":                   br_date(data_valor),
            "tipo":                   tipo,
            "descricao":              descricao,
            "valor_original":         br_money(valor_original),
            "fator":                  str(fator),
            "valor_atualizacao":      br_money(_valor_atualizacao),
            "valor_corrigido":        br_money(valor_corrigido),
            "data_inicio_juros":      br_date(data_inicio_juros_exib),
            "juros_percentual_total": f"{juros_percentual_total:.2f}%",
            "juros":                  br_money(juros_valor),
            "total":                  br_money(total_linha),
        })

    # --- custas ---
    custas = parse_money(payload.get("custas_valor"))

    # --- base acessórios ---
    base_acessorios = _q(total_corrigido + total_juros)

    # --- multas ---
    multas_lista     = payload.get("multas") or []
    multas_resultado = []
    multa            = Decimal("0.00")
    multa_label      = ""
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
        multas_resultado.append({"descricao": m_desc, "tipo": "Percentual" if m_tipo=="percentual" else "Valor fixo", "referencia": m_ref, "valor": br_money(m_calculado)})
    if multas_resultado:
        multa_label = "; ".join(m["descricao"] for m in multas_resultado)

    # --- honorários ---
    honorarios_lista     = payload.get("honorarios_lista") or []
    honorarios_resultado = []
    honorarios           = Decimal("0.00")
    honorarios_label     = ""
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
        honorarios_resultado.append({"descricao": h_desc, "tipo": "Percentual" if h_tipo=="percentual" else "Valor fixo", "referencia": h_ref, "valor": br_money(h_calculado)})
    if honorarios_resultado:
        honorarios_label = "; ".join(h["descricao"] for h in honorarios_resultado)

    # --- total bruto ---
    total_bruto = _q(total_corrigido + total_juros + multa + honorarios + custas)

    # --- deduções ---
    deducoes_resultado = []
    total_deducoes     = Decimal("0.00")
    for d in deducoes:
        nome       = d.get("nome") or "Dedução"
        tipo_d     = d.get("tipo") or "valor"
        valor      = parse_money(d.get("valor"))
        percentual = parse_decimal(d.get("percentual"))
        if tipo_d == "percentual":
            deduzido   = _q(total_bruto * (percentual / Decimal("100")))
            desc_d     = f"{percentual}%"
        else:
            deduzido   = valor
            desc_d     = br_money(valor)
        if deduzido <= 0:
            continue
        total_deducoes += deduzido
        deducoes_resultado.append({"nome": nome, "tipo": "Percentual" if tipo_d=="percentual" else "Valor fixo", "referencia": desc_d, "valor_deduzido": br_money(deduzido)})

    total_liquido = _q(total_bruto - total_deducoes)
    if total_liquido < 0:
        total_liquido = Decimal("0.00")

    # --- detalhamento de índices ---
    detalhamento_indices = []
    if datas_correcao:
        data_inicio_min = min(datas_correcao)
        detalhamento_indices = obter_detalhamento_indices(
            indice=indice_padrao,
            data_inicio=data_inicio_min,
            data_final=data_final,
            juros_tipo=juros_tipo_global,
            data_inicio_juros=min(datas_juros) if datas_juros else None,
        )

    memoria_texto = montar_memoria_texto(
        itens=itens,
        total_original=total_original,
        total_corrigido=total_corrigido,
        total_juros=total_juros,
        multa=multa, multa_label=multa_label,
        honorarios=honorarios, honorarios_label=honorarios_label,
        custas=custas, total_bruto=total_bruto,
        deducoes=deducoes_resultado,
        total_deducoes=total_deducoes,
        total_liquido=total_liquido,
    )

    # Monta descrição do índice para o relatório
    if periodos_correcao:
        indice_nome = " | ".join(
            f"{get_indice_nome(p.get('indice','tjdft'))}"
            + (f" até {br_date(parse_date(p.get('data_fim')))}" if p.get("data_fim") else "")
            + (f" — {p.get('descricao')}" if p.get("descricao") else "")
            for p in periodos_correcao
        )
    else:
        indice_nome = get_indice_nome("tjdft")

    return {
        "processo":              payload.get("processo") or "",
        "vara":                  payload.get("vara") or "",
        "exequente":             payload.get("exequente") or "",
        "executado":             payload.get("executado") or "",
        "data_calculo":          br_date(data_final),
        "indice_correcao":       indice_nome,
        "indice_correcao_curto": _indice_curto(indice_padrao),
        "juros_tipo":            juros_tipo_global,
        "juros_descricao":       juros_descricao,
        "juros_periodo":         juros_incidencia_desc,
        "itens":                 itens,
        "deducoes":              deducoes_resultado,
        "detalhamento_indices":  detalhamento_indices,
        "valor_original":        br_money(total_original),
        "valor_corrigido":       br_money(total_corrigido),
        "juros":                 br_money(total_juros),
        "multa":                 br_money(multa),
        "multa_label":           multa_label,
        "multa_percentual_display": "",
        "multas_lista":          multas_resultado,
        "honorarios":            br_money(honorarios),
        "honorarios_label":      honorarios_label,
        "honorarios_percentual_display": "",
        "honorarios_lista":      honorarios_resultado,
        "custas":                br_money(custas),
        "total_bruto":           br_money(total_bruto),
        "total_deducoes":        br_money(total_deducoes),
        "total_liquido":         br_money(total_liquido),
        "total_principal":       br_money(_q(total_corrigido + total_juros)),
        "tem_acessorios":        (honorarios > Decimal("0") or multa > Decimal("0") or custas > Decimal("0")),
        "total_acessorios":      br_money(_q(honorarios + multa + custas)),
        "memoria_calculo":       memoria_texto,
    }


def montar_memoria_texto(
    itens, total_original, total_corrigido, total_juros,
    multa, multa_label, honorarios, honorarios_label,
    custas, total_bruto, deducoes, total_deducoes, total_liquido,
) -> str:
    linhas = ["MEMORIAL DE CÁLCULO", "", "VALORES DEVIDOS:"]
    for i, item in enumerate(itens, start=1):
        linhas.append(
            f"{i}. {item['data']} - {item['tipo']} - {item['descricao']} - "
            f"Original: {item['valor_original']} - Corrigido: {item['valor_corrigido']} - "
            f"Juros: {item['juros']} - Total: {item['total']}"
        )
    linhas += [
        "",
        f"Valor original: {br_money(total_original)}",
        f"Valor corrigido: {br_money(total_corrigido)}",
        f"Juros: {br_money(total_juros)}",
        f"Multa ({multa_label}): {br_money(multa)}" if multa_label else f"Multa: {br_money(multa)}",
        f"Honorários ({honorarios_label}): {br_money(honorarios)}" if honorarios_label else f"Honorários: {br_money(honorarios)}",
        f"Custas: {br_money(custas)}",
        f"Total bruto: {br_money(total_bruto)}",
    ]
    if deducoes:
        linhas.append("")
        linhas.append("DEDUÇÕES:")
        for d in deducoes:
            linhas.append(f"- {d['nome']} ({d['tipo']} - {d['referencia']}): {d['valor_deduzido']}")
    linhas.append(f"Total de deduções: {br_money(total_deducoes)}")
    linhas.append(f"TOTAL LÍQUIDO DEVIDO: {br_money(total_liquido)}")
    return "\n".join(linhas)