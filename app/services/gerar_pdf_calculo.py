"""
gerar_pdf_calculo.py
====================
Gera a minuta de cálculo em PDF reproduzindo exatamente o layout
do relatorio_atualizacao.html (tela do sistema).

Dependência: pip install reportlab
"""
from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

# ---------------------------------------------------------------------------
# Cores
# ---------------------------------------------------------------------------
COR_PRIMARIA   = colors.HexColor("#cfe2ff")   # table-primary Bootstrap
COR_BORDA      = colors.HexColor("#dee2e6")
COR_ZEBRA      = colors.HexColor("#f8f9fa")
COR_TFOOT      = colors.HexColor("#f1f3f5")
COR_TOTAL      = colors.HexColor("#cfe2ff")
COR_MUTED      = colors.HexColor("#6c757d")
COR_DANGER     = colors.HexColor("#dc3545")
COR_TEXTO      = colors.HexColor("#212529")
COR_VERDE      = colors.HexColor("#37b24d")
COR_AZUL_INFO  = colors.HexColor("#228be6")
COR_AMARELO    = colors.HexColor("#f0ad4e")
COR_CYAN       = colors.HexColor("#48c7dc")
BRANCO         = colors.white

# ---------------------------------------------------------------------------
# Estilos
# ---------------------------------------------------------------------------
def _S(name, **kw):
    d = dict(fontName="Helvetica", fontSize=8.5, leading=9.5,
             textColor=COR_TEXTO, alignment=TA_LEFT)
    d.update(kw)
    return ParagraphStyle(name, **d)

E = {
    "titulo":    _S("titulo", fontName="Helvetica-Bold", fontSize=17, leading=18),
    "subtitulo": _S("subtitulo", fontSize=9, textColor=COR_MUTED),
    "secao":     _S("secao", fontName="Helvetica-Bold", fontSize=11,
                    leading=12, alignment=TA_CENTER),
    "label":     _S("label", fontSize=7.5, textColor=COR_MUTED, leading=8),
    "valor":     _S("valor", fontSize=8.5, leading=9),
    "valor_b":   _S("valor_b", fontName="Helvetica-Bold", fontSize=8.5, leading=9),
    "info_t":    _S("info_t", fontName="Helvetica-Bold", fontSize=9.5,
                    textColor=COR_TEXTO, leading=11),
    "info_c":    _S("info_c", fontSize=8, leading=9, textColor=colors.HexColor("#555")),
    "th":        _S("th", fontName="Helvetica-Bold", fontSize=7.8,
                    leading=8.5, alignment=TA_CENTER),
    "td":        _S("td", fontSize=7.8, leading=8.5),
    "td_c":      _S("td_c", fontSize=7.8, leading=8.5, alignment=TA_CENTER),
    "td_r":      _S("td_r", fontSize=7.8, leading=8.5, alignment=TA_RIGHT),
    "td_b":      _S("td_b", fontName="Helvetica-Bold", fontSize=7.8, leading=8.5),
    "td_br":     _S("td_br", fontName="Helvetica-Bold", fontSize=7.8,
                    leading=8.5, alignment=TA_RIGHT),
    "danger_r":  _S("danger_r", fontSize=7.8, leading=8.5,
                    alignment=TA_RIGHT, textColor=COR_DANGER),
    "total_l":   _S("total_l", fontName="Helvetica-Bold", fontSize=11,
                    leading=12, alignment=TA_RIGHT),
    "total_v":   _S("total_v", fontName="Helvetica-Bold", fontSize=11,
                    leading=12, alignment=TA_RIGHT),
    "nota":      _S("nota", fontSize=7.5, textColor=COR_MUTED, leading=8.5),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _v(r, k, d="—"):
    v = r.get(k)
    return str(v) if v else d

def _nz(v):
    return bool(v) and v not in ("R$ 0,00","R$0,00","—","")

def _p(t, e):
    t = "—" if not t else str(t)
    # Escapa apenas & < > — NÃO escapa tags HTML intencionais
    t = t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    return Paragraph(t, e)

def _tbl_style(n, header=True, footer=False):
    c = [
        ("GRID",          (0,0),(-1,-1), 0.4, COR_BORDA),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0),(-1,-1), 3),
        ("BOTTOMPADDING", (0,0),(-1,-1), 3),
        ("LEFTPADDING",   (0,0),(-1,-1), 4),
        ("RIGHTPADDING",  (0,0),(-1,-1), 4),
    ]
    if header:
        c += [
            ("BACKGROUND", (0,0),(-1,0), COR_PRIMARIA),
            ("FONTNAME",   (0,0),(-1,0), "Helvetica-Bold"),
            ("ALIGN",      (0,0),(-1,0), "CENTER"),
        ]
        z0 = 1
    else:
        z0 = 0
    lim = n-1 if footer else n
    for i in range(z0, lim):
        if (i-z0) % 2 == 0:
            c.append(("BACKGROUND",(0,i),(-1,i), COR_ZEBRA))
    if footer:
        c += [
            ("BACKGROUND", (0,-1),(-1,-1), COR_TFOOT),
            ("FONTNAME",   (0,-1),(-1,-1), "Helvetica-Bold"),
            ("LINEABOVE",  (0,-1),(-1,-1), 1.0, colors.HexColor("#adb5bd")),
        ]
    return c

def _secao(txt, w):
    return Table(
        [[_p(txt, E["secao"])]],
        colWidths=[w],
        style=TableStyle([
            ("BOX",           (0,0),(-1,-1), 0.5, COR_BORDA),
            ("BACKGROUND",    (0,0),(-1,-1), BRANCO),
            ("TOPPADDING",    (0,0),(-1,-1), 5),
            ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ])
    )

# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------
def gerar_pdf_calculo(resultado: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=1.0*cm, rightMargin=1.0*cm,
        topMargin=0.8*cm, bottomMargin=0.8*cm,
        title=f"Cálculo — {resultado.get('processo','')}",
    )
    w = doc.width
    story = []

    # dados
    processo   = _v(resultado,"processo")
    vara       = _v(resultado,"vara")
    exequente  = _v(resultado,"exequente")
    executado  = _v(resultado,"executado")
    data_calc  = _v(resultado,"data_calculo")
    indice     = _v(resultado,"indice_correcao")
    indice_c   = _v(resultado,"indice_correcao_curto", indice)
    juros_desc = _v(resultado,"juros_descricao","Sem juros")
    juros_per  = _v(resultado,"juros_periodo","")
    juros_tipo = resultado.get("juros_tipo","sem")
    itens      = resultado.get("itens") or []
    deducoes   = resultado.get("deducoes") or []
    det_ind    = resultado.get("detalhamento_indices") or []

    valor_original  = _v(resultado,"valor_original")
    valor_corrigido = _v(resultado,"valor_corrigido")
    juros_total     = _v(resultado,"juros","R$ 0,00")
    total_principal = _v(resultado,"total_principal", valor_corrigido)
    honorarios      = _v(resultado,"honorarios","R$ 0,00")
    hon_label       = resultado.get("honorarios_label") or ""
    hon_pct         = resultado.get("honorarios_percentual_display") or "—"
    multa           = _v(resultado,"multa","R$ 0,00")
    mul_label       = resultado.get("multa_label") or ""
    mul_pct         = resultado.get("multa_percentual_display") or "—"
    custas          = _v(resultado,"custas","R$ 0,00")
    tem_ac          = bool(resultado.get("tem_acessorios"))
    total_ac        = _v(resultado,"total_acessorios","—")
    total_bruto     = _v(resultado,"total_bruto")
    total_liquido   = _v(resultado,"total_liquido")

    # ── Cabeçalho ────────────────────────────────────────────────────────
    hdr = Table(
        [[
            _p("KRATOS JURIS", E["titulo"]),
            Table(
                [[_p("Sistema de Gestão Jurídica", E["subtitulo"])],
                 [_p("RELATÓRIO DE ATUALIZAÇÃO MONETÁRIA", E["valor_b"])]],
                colWidths=[w - 5*cm],
                style=TableStyle([
                    ("TOPPADDING",   (0,0),(-1,-1), 0),
                    ("BOTTOMPADDING",(0,0),(-1,-1), 0),
                    ("LEFTPADDING",  (0,0),(-1,-1), 0),
                    ("RIGHTPADDING", (0,0),(-1,-1), 0),
                ])
            )
        ]],
        colWidths=[5*cm, w-5*cm],
        style=TableStyle([
            ("VALIGN",      (0,0),(-1,-1), "MIDDLE"),
            ("LINEBELOW",   (0,0),(-1,-1), 0.8, COR_BORDA),
            ("BOTTOMPADDING",(0,0),(-1,-1), 8),
            ("LEFTPADDING", (0,0),(-1,-1), 0),
            ("RIGHTPADDING",(0,0),(-1,-1), 0),
        ])
    )
    story.append(hdr)
    story.append(Spacer(1, 6))

    # ── Dados do processo ─────────────────────────────────────────────────
    proc_tbl = Table(
        [
            [_p("Processo:", E["label"]),  _p(processo,  E["valor"])],
            [_p("Polo ativo:", E["label"]),  _p(exequente, E["valor"])],
            [_p("Polo passivo:", E["label"]), _p(executado, E["valor"])],
            [_p("Vara:", E["label"]),      _p(vara,      E["valor"])],
        ],
        colWidths=[2.5*cm, w-2.5*cm],
        style=TableStyle([
            ("LINEABOVE",  (0,0),(-1,0),  0.5, COR_BORDA),
            ("LINEBELOW",  (0,-1),(-1,-1), 0.5, COR_BORDA),
            ("LINEBEFORE", (0,0),(0,-1),   2.5, COR_CYAN),
            ("LEFTPADDING",(0,0),(-1,-1),  8),
            ("TOPPADDING", (0,0),(-1,-1),  2),
            ("BOTTOMPADDING",(0,0),(-1,-1),2),
            ("VALIGN",     (0,0),(-1,-1), "MIDDLE"),
        ])
    )
    story.append(proc_tbl)
    story.append(Spacer(1, 6))

    # ── Blocos Moeda / Atualização / Juros ────────────────────────────────
    iw = w / 3

    def _card(cor_barra, titulo, linhas):
        rows = [[_p(titulo, E["info_t"])]]
        for l in linhas:
            rows.append([_p(l, E["info_c"])])
        return Table(rows, colWidths=[iw],
            style=TableStyle([
                ("LINEABOVE",  (0,0),(-1,0),  0.5, COR_BORDA),
                ("LINEBELOW",  (0,-1),(-1,-1), 0.5, COR_BORDA),
                ("LINEBEFORE", (0,0),(0,-1),   2.5, cor_barra),
                ("LEFTPADDING",(0,0),(-1,-1),  8),
                ("RIGHTPADDING",(0,0),(-1,-1), 8),
                ("TOPPADDING", (0,0),(-1,-1),  3),
                ("BOTTOMPADDING",(0,0),(-1,-1),3),
                ("VALIGN",     (0,0),(-1,-1), "TOP"),
            ])
        )

    juros_per_txt = f"Período: {juros_per}" if juros_per and juros_per != "—" else ""

    cards = Table(
        [[
            _card(COR_VERDE, "Moeda",
                  ["Valores em Real (R$).",
                   "Relatório gerado com base nas informações fornecidas pelo usuário."]),
            _card(COR_AZUL_INFO, f"Atualização monetária até {data_calc}",
                  [f"Data final do cálculo: {data_calc}",
                   "Índices de atualização monetária:",
                   indice]),
            _card(COR_AMARELO, "Juros",
                  [f"Tipo de juros: {juros_desc}",
                   juros_per_txt] if juros_per_txt else
                  [f"Tipo de juros: {juros_desc}"]),
        ]],
        colWidths=[iw, iw, iw],
        style=TableStyle([
            ("LINEAFTER",  (0,0),(1,0), 0.5, COR_BORDA),
            ("TOPPADDING", (0,0),(-1,-1), 0),
            ("BOTTOMPADDING",(0,0),(-1,-1), 0),
            ("LEFTPADDING",(0,0),(-1,-1), 0),
            ("RIGHTPADDING",(0,0),(-1,-1), 0),
            ("VALIGN",     (0,0),(-1,-1), "TOP"),
        ])
    )
    story.append(cards)
    story.append(Spacer(1, 8))

    # ── Demonstrativo dos valores principais ──────────────────────────────
    story.append(_secao("Demonstrativo dos valores principais", w))

    # Calcula valor_atualizacao_total somando de cada item
    from decimal import Decimal, InvalidOperation
    def _dec(s):
        try:
            return Decimal(str(s).replace("R$","").replace(".","").replace(",",".").strip())
        except (InvalidOperation, AttributeError):
            return Decimal("0")

    soma_atualizacao = sum(_dec(i.get("valor_atualizacao","0")) for i in itens)
    from decimal import ROUND_HALF_UP
    soma_atu_fmt = f"R$ {soma_atualizacao.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}".replace(",","X").replace(".",",").replace("X",".")

    cw = [1.8*cm, 3.5*cm, 2.0*cm, 4.2*cm, 2.0*cm, 2.0*cm, 2.0*cm, 2.0*cm, 2.0*cm, 2.2*cm]
    cols = ["Data","Descrição","Valor","Índices de\natualização",
            "Fator da\natualização","Correção\nmonetária",
            "Valor\natualizado","% de juros\nacumulado",
            "Valor dos\njuros","Total"]

    rows = [[_p(c, E["th"]) for c in cols]]
    for item in itens:
        desc = item.get("tipo","")
        if item.get("descricao"):
            desc += f" — {item['descricao']}"
        rows.append([
            _p(item.get("data",""),          E["td_c"]),
            _p(desc,                          E["td"]),
            _p(item.get("valor_original",""), E["td_r"]),
            _p(indice_c,                      E["td"]),
            _p(item.get("fator",""),          E["td_r"]),
            _p(item.get("valor_atualizacao","—"), E["td_r"]),
            _p(item.get("valor_corrigido",""),E["td_r"]),
            _p(item.get("juros_percentual_total",""), E["td_r"]),
            _p(item.get("juros",""),          E["td_r"]),
            _p(item.get("total",""),          E["td_br"]),
        ])

    if not itens:
        rows.append([_p("Nenhum lançamento informado.", E["td_c"])] + [""]*9)

    rows.append([
        _p("Total valores", E["td_br"]), "",
        _p(valor_original,  E["td_br"]),
        "", "",
        _p(soma_atu_fmt,    E["td_br"]),
        _p(valor_corrigido, E["td_br"]),
        "",
        _p(juros_total,     E["td_br"]),
        _p(f"{total_principal} (A)", E["td_br"]),
    ])

    n = len(rows)
    st = _tbl_style(n, header=True, footer=True)
    st += [("SPAN",(0,n-1),(1,n-1))]
    if not itens:
        st.append(("SPAN",(0,1),(-1,1)))

    # Ajusta colWidths para preencher exatamente a largura disponível
    _soma_cw = sum(cw)
    _fator = w / _soma_cw
    cw = [c * _fator for c in cw]
    story.append(Table(rows, colWidths=cw, style=TableStyle(st), repeatRows=1))
    story.append(Spacer(1, 8))

    # ── Demonstrativo dos valores acessórios ─────────────────────────────
    if tem_ac:
        story.append(_secao("Demonstrativo dos valores acessórios", w))
        cw_ac = [7.5*cm, 4.0*cm, 2.8*cm, 3.0*cm, 2.5*cm, 3.4*cm]
        cols_ac = ["Descrição","Base de cálculo","Percentual","Principal","Juros","Total"]
        rows_ac = [[_p(c, E["th"]) for c in cols_ac]]
        letra = ord("B")

        if _nz(honorarios):
            d = f"Honorários{' — ' + hon_label if hon_label else ''}"
            rows_ac.append([
                _p(d, E["td"]),
                _p(f"{total_principal} (A)", E["td_r"]),
                _p(hon_pct, E["td_r"]),
                _p(honorarios, E["td_r"]),
                _p("—", E["td_r"]),
                _p(f"{honorarios} ({chr(letra)})", E["td_br"]),
            ])
            letra += 1

        if _nz(multa):
            d = f"Multa{' — ' + mul_label if mul_label else ''}"
            rows_ac.append([
                _p(d, E["td"]),
                _p(f"{total_principal} (A)", E["td_r"]),
                _p(mul_pct, E["td_r"]),
                _p(multa, E["td_r"]),
                _p("—", E["td_r"]),
                _p(f"{multa} ({chr(letra)})", E["td_br"]),
            ])
            letra += 1

        if _nz(custas):
            rows_ac.append([
                _p("Custas/despesas", E["td"]),
                _p("—", E["td_r"]), _p("—", E["td_r"]),
                _p(custas, E["td_r"]),
                _p("—", E["td_r"]),
                _p(custas, E["td_br"]),
            ])

        rows_ac.append([
            _p("Total acessórios", E["td_br"]), "", "",
            _p(total_ac, E["td_br"]),
            _p("—", E["td_r"]),
            _p(total_ac, E["td_br"]),
        ])

        n_ac = len(rows_ac)
        st_ac = _tbl_style(n_ac, header=True, footer=True)
        st_ac += [("SPAN",(0,n_ac-1),(2,n_ac-1))]
        _soma_cw_ac = sum(cw_ac)
        _fator_ac = w / _soma_cw_ac
        cw_ac = [c * _fator_ac for c in cw_ac]
        story.append(Table(rows_ac, colWidths=cw_ac, style=TableStyle(st_ac), repeatRows=1))
        story.append(Spacer(1, 8))

    # ── Agrupamento dos valores apurados ──────────────────────────────────
    story.append(_secao("Agrupamento dos valores apurados", w))

    rows_ag = []
    rows_ag.append([_p("Montante principal em favor do(a)s credor(a)(es)", E["td"]),
                    _p(total_principal, E["td_r"])])

    if _nz(honorarios):
        d = f"Honorários advocatícios{' — ' + hon_label if hon_label else ''}"
        rows_ag.append([_p(d, E["td"]), _p(honorarios, E["td_r"])])
        rows_ag.append([_p("Total dos Honorários advocatícios", E["td_b"]),
                        _p(honorarios, E["td_br"])])

    if _nz(multa):
        d = f"Multa{' — ' + mul_label if mul_label else ''}"
        rows_ag.append([_p(d, E["td"]), _p(multa, E["td_r"])])

    if _nz(custas):
        rows_ag.append([_p("Custas/despesas processuais", E["td"]),
                        _p(custas, E["td_r"])])

    rows_ag.append([_p("Subtotal bruto do cálculo", E["td"]),
                    _p(total_bruto, E["td_r"])])

    for d in deducoes:
        rows_ag.append([
            _p(f"Dedução — {d.get('nome','')} ({d.get('referencia','')})", E["td"]),
            _p(f"— {d.get('valor_deduzido','')}", E["danger_r"]),
        ])

    rows_ag.append([_p("Total do cálculo:", E["total_l"]),
                    _p(total_liquido, E["total_v"])])

    n_ag = len(rows_ag)
    st_ag = [
        ("GRID",          (0,0),(-1,-1), 0.4, COR_BORDA),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0),(-1,-1), 4),
        ("BOTTOMPADDING", (0,0),(-1,-1), 4),
        ("LEFTPADDING",   (0,0),(-1,-1), 5),
        ("RIGHTPADDING",  (0,0),(-1,-1), 5),
        ("BACKGROUND",    (0,n_ag-1),(-1,n_ag-1), COR_TOTAL),
        ("FONTNAME",      (0,n_ag-1),(-1,n_ag-1), "Helvetica-Bold"),
        ("FONTSIZE",      (0,n_ag-1),(-1,n_ag-1), 10),
    ]
    for i in range(n_ag-1):
        if i % 2 == 0:
            st_ag.append(("BACKGROUND",(0,i),(-1,i), COR_ZEBRA))

    story.append(Table(rows_ag, colWidths=[w-4.5*cm, 4.5*cm],
                       style=TableStyle(st_ag)))
    story.append(Spacer(1, 8))

    # ── Memória de índices aplicados ──────────────────────────────────────
    if det_ind:
        story.append(_secao("Memória de índices aplicados", w))
        tem_j = juros_tipo != "sem"
        if tem_j:
            cols_i = ["Mês/Ano","Índice de correção","Taxa correção",
                      "Índice de juros","Taxa juros"]
            cw_i = [3.5*cm, 5.5*cm, 3.5*cm, 5.5*cm, 5.4*cm]
        else:
            cols_i = ["Mês/Ano","Índice de correção","Taxa correção"]
            cw_i   = [4.0*cm, 9.0*cm, 9.9*cm]

        rows_i = [[_p(c, E["th"]) for c in cols_i]]
        for linha in det_ind:
            row = [
                _p(linha.get("mes",""),       E["td_c"]),
                _p(linha.get("indice_nome",""),E["td_c"]),
                _p(linha.get("correcao",""),   E["td_r"]),
            ]
            if tem_j:
                j = linha.get("juros","—")
                row.append(_p(linha.get("juros_nome","") if j != "—" else "—", E["td_c"]))
                row.append(_p(j, E["td_r"]))
            rows_i.append(row)

        n_i = len(rows_i)
        _soma_cw_i = sum(cw_i)
        _fator_i = w / _soma_cw_i
        cw_i = [c * _fator_i for c in cw_i]
        story.append(Table(rows_i, colWidths=cw_i,
                           style=TableStyle(_tbl_style(n_i)), repeatRows=1))
        story.append(Spacer(1, 8))

    # ── Nota final ────────────────────────────────────────────────────────
    story.append(Table(
        [[_p("O presente relatório é gerado com base nas informações fornecidas pelo usuário. "
             "Confira os dados antes de utilizar em petição ou protocolo.", E["nota"])]],
        colWidths=[w],
        style=TableStyle([
            ("BOX",           (0,0),(-1,-1), 0.5, COR_BORDA),
            ("TOPPADDING",    (0,0),(-1,-1), 5),
            ("BOTTOMPADDING", (0,0),(-1,-1), 5),
            ("LEFTPADDING",   (0,0),(-1,-1), 8),
            ("RIGHTPADDING",  (0,0),(-1,-1), 8),
        ])
    ))

    doc.build(story)
    return buf.getvalue()