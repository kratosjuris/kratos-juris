"""
gerar_pdf_astreintes.py
=======================
Gera o PDF do relatório de astreintes usando reportlab.
Reproduz o layout do relatorio_astreintes.html com cabeçalho de
datas/valor antes de cada demonstrativo diário.

Dependência: pip install reportlab
"""
from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, PageBreak
)

# ---------------------------------------------------------------------------
# Cores
# ---------------------------------------------------------------------------
COR_PRIMARIA  = colors.HexColor("#0d6efd")
COR_AZUL_CLR  = colors.HexColor("#cfe2ff")
COR_BORDA     = colors.HexColor("#dee2e6")
COR_ZEBRA     = colors.HexColor("#f8f9fa")
COR_CINZA_HDR = colors.HexColor("#f8f9fa")
COR_MUTED     = colors.HexColor("#6c757d")
COR_TEXTO     = colors.HexColor("#212529")
BRANCO        = colors.white

# ---------------------------------------------------------------------------
# Estilos
# ---------------------------------------------------------------------------
def _S(name, **kw):
    d = dict(fontName="Helvetica", fontSize=8, leading=10,
             textColor=COR_TEXTO, alignment=TA_LEFT)
    d.update(kw)
    return ParagraphStyle(name, **d)

E = {
    "titulo":   _S("titulo", fontName="Helvetica-Bold", fontSize=14, leading=16),
    "subtit":   _S("subtit", fontSize=8, textColor=COR_MUTED),
    "secao":    _S("secao",  fontName="Helvetica-Bold", fontSize=9, leading=11,
                   alignment=TA_CENTER),
    "periodo_titulo": _S("periodo_titulo", fontName="Helvetica-Bold",
                         fontSize=10, leading=12),
    "periodo_valor":  _S("periodo_valor", fontName="Helvetica-Bold",
                         fontSize=10, leading=12, textColor=COR_PRIMARIA,
                         alignment=TA_RIGHT),
    "label":    _S("label", fontSize=7, textColor=COR_MUTED, leading=8.5),
    "valor":    _S("valor", fontName="Helvetica-Bold", fontSize=8, leading=10),
    "th":       _S("th",    fontName="Helvetica-Bold", fontSize=7.5,
                   leading=9, alignment=TA_CENTER),
    "td":       _S("td",    fontSize=7.5, leading=9),
    "td_r":     _S("td_r",  fontSize=7.5, leading=9, alignment=TA_RIGHT),
    "td_br":    _S("td_br", fontName="Helvetica-Bold", fontSize=7.5,
                   leading=9, alignment=TA_RIGHT),
    "total_l":  _S("total_l", fontName="Helvetica-Bold", fontSize=10,
                   leading=12, textColor=COR_MUTED),
    "total_v":  _S("total_v", fontName="Helvetica-Bold", fontSize=12,
                   leading=14, textColor=COR_PRIMARIA, alignment=TA_RIGHT),
    "nota":     _S("nota",  fontSize=7, textColor=COR_MUTED, leading=9),
}

def _v(r, k, d="—"):
    v = r.get(k)
    return str(v) if v else d

def _p(t, e):
    return Paragraph(str(t or "—").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;"), e)

def _cell_kv(label, valor, w, bold_val=True):
    ev = E["valor"] if bold_val else E["td"]
    return Table(
        [[_p(label, E["label"])], [_p(valor, ev)]],
        colWidths=[w],
        style=TableStyle([
            ("TOPPADDING",   (0,0),(-1,-1), 0),
            ("BOTTOMPADDING",(0,0),(-1,-1), 0),
            ("LEFTPADDING",  (0,0),(-1,-1), 0),
            ("RIGHTPADDING", (0,0),(-1,-1), 0),
        ])
    )

def _tbl_style(n, header=True):
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
            ("BACKGROUND", (0,0),(-1,0), COR_AZUL_CLR),
            ("FONTNAME",   (0,0),(-1,0), "Helvetica-Bold"),
            ("ALIGN",      (0,0),(-1,0), "CENTER"),
        ]
    for i in range(1 if header else 0, n):
        if (i - (1 if header else 0)) % 2 == 0:
            c.append(("BACKGROUND",(0,i),(-1,i), COR_ZEBRA))
    return c

# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------
def gerar_pdf_astreintes(resultado: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.2*cm, rightMargin=1.2*cm,
        topMargin=1.0*cm,  bottomMargin=1.0*cm,
        title=f"Astreintes — {resultado.get('processo','')}",
    )
    w = doc.width
    story = []

    processo     = _v(resultado, "processo")
    vara         = _v(resultado, "vara")
    exequente    = _v(resultado, "exequente")
    executado    = _v(resultado, "executado")
    contagem     = _v(resultado, "tipo_contagem")
    total_geral  = _v(resultado, "total_geral")
    qtd_dias     = str(resultado.get("quantidade_dias","—"))
    total_periodos = str(resultado.get("total_periodos","—"))
    periodos     = resultado.get("periodos") or []

    # ── Título ──────────────────────────────────────────────────────────────
    story.append(_p("Relatório de Astreintes", E["titulo"]))
    story.append(_p("Demonstrativo da multa diária por descumprimento.", E["subtit"]))
    story.append(Spacer(1, 8))

    # ── Dados do processo ────────────────────────────────────────────────────
    cw4 = [w/4]*4
    tbl_proc1 = Table(
        [[_cell_kv("Processo", processo, w/4),
          _cell_kv("Vara", vara, w/4),
          _cell_kv("Exequente", exequente, w/4),
          _cell_kv("Executado", executado, w/4)]],
        colWidths=cw4,
        style=TableStyle([
            ("BOX",          (0,0),(-1,-1), 0.5, COR_BORDA),
            ("GRID",         (0,0),(-1,-1), 0.4, COR_BORDA),
            ("TOPPADDING",   (0,0),(-1,-1), 5),
            ("BOTTOMPADDING",(0,0),(-1,-1), 5),
            ("LEFTPADDING",  (0,0),(-1,-1), 6),
            ("RIGHTPADDING", (0,0),(-1,-1), 6),
        ])
    )
    tbl_proc2 = Table(
        [[_cell_kv("Tipo de contagem", contagem, w/4),
          _cell_kv("Total de períodos", total_periodos, w/4),
          _cell_kv("Total de dias", qtd_dias, w/4),
          _cell_kv("TOTAL GERAL", total_geral, w/4)]],
        colWidths=cw4,
        style=TableStyle([
            ("BOX",          (0,0),(-1,-1), 0.5, COR_BORDA),
            ("GRID",         (0,0),(-1,-1), 0.4, COR_BORDA),
            ("BACKGROUND",   (0,0),(-1,-1), COR_AZUL_CLR),
            ("TOPPADDING",   (0,0),(-1,-1), 5),
            ("BOTTOMPADDING",(0,0),(-1,-1), 5),
            ("LEFTPADDING",  (0,0),(-1,-1), 6),
            ("RIGHTPADDING", (0,0),(-1,-1), 6),
        ])
    )
    story.append(tbl_proc1)
    story.append(Spacer(1, 2))
    story.append(tbl_proc2)
    story.append(Spacer(1, 12))

    # ── Períodos ─────────────────────────────────────────────────────────────
    for periodo in periodos:
        num     = periodo.get("numero","")
        desc    = periodo.get("descricao","")
        di      = periodo.get("data_inicial","—")
        df      = periodo.get("data_final","—")
        vd      = periodo.get("valor_diario","—")
        limite  = periodo.get("limite","Sem limite")
        qtd     = str(periodo.get("quantidade_dias","—"))
        total_p = periodo.get("total","—")
        itens   = periodo.get("itens") or []

        # Cabeçalho do período
        hdr_row = Table(
            [[_p(f"{num}. {desc}", E["periodo_titulo"]),
              _p(total_p, E["periodo_valor"])]],
            colWidths=[w*0.7, w*0.3],
            style=TableStyle([
                ("BACKGROUND",   (0,0),(-1,-1), COR_CINZA_HDR),
                ("BOX",          (0,0),(-1,-1), 0.5, COR_BORDA),
                ("TOPPADDING",   (0,0),(-1,-1), 5),
                ("BOTTOMPADDING",(0,0),(-1,-1), 5),
                ("LEFTPADDING",  (0,0),(-1,-1), 8),
                ("RIGHTPADDING", (0,0),(-1,-1), 8),
                ("VALIGN",       (0,0),(-1,-1), "MIDDLE"),
            ])
        )
        story.append(hdr_row)

        # Detalhes do período (datas, valor, limite)
        cw6 = [w/6]*6
        det_row = Table(
            [[_cell_kv("Data inicial",   di,      w/6),
              _cell_kv("Data final",     df,      w/6),
              _cell_kv("Valor diário",   vd,      w/6),
              _cell_kv("Limite máximo",  limite,  w/6),
              _cell_kv("Dias computados",qtd,     w/6),
              _cell_kv("Total período",  total_p, w/6)]],
            colWidths=cw6,
            style=TableStyle([
                ("BOX",          (0,0),(-1,-1), 0.5, COR_BORDA),
                ("GRID",         (0,0),(-1,-1), 0.4, COR_BORDA),
                ("TOPPADDING",   (0,0),(-1,-1), 4),
                ("BOTTOMPADDING",(0,0),(-1,-1), 4),
                ("LEFTPADDING",  (0,0),(-1,-1), 6),
                ("RIGHTPADDING", (0,0),(-1,-1), 6),
            ])
        )
        story.append(det_row)
        story.append(Spacer(1, 4))

        # Demonstrativo diário
        if itens:
            cols = ["Data", "Valor diário", "Acumulado"]
            cw_d = [w*0.4, w*0.3, w*0.3]
            rows = [[_p(c, E["th"]) for c in cols]]
            for item in itens:
                rows.append([
                    _p(item.get("data",""),        E["td"]),
                    _p(item.get("valor_diario",""), E["td_r"]),
                    _p(item.get("acumulado",""),    E["td_br"]),
                ])
            n = len(rows)
            story.append(Table(rows, colWidths=cw_d,
                               style=TableStyle(_tbl_style(n)), repeatRows=1))

        story.append(Spacer(1, 12))

    # ── Totalizador final ─────────────────────────────────────────────────────
    tbl_final = Table(
        [[_p("TOTAL GERAL DAS ASTREINTES:", E["total_l"]),
          _p(total_geral, E["total_v"])]],
        colWidths=[w*0.6, w*0.4],
        style=TableStyle([
            ("BOX",          (0,0),(-1,-1), 1.0, COR_PRIMARIA),
            ("BACKGROUND",   (0,0),(-1,-1), COR_AZUL_CLR),
            ("TOPPADDING",   (0,0),(-1,-1), 8),
            ("BOTTOMPADDING",(0,0),(-1,-1), 8),
            ("LEFTPADDING",  (0,0),(-1,-1), 10),
            ("RIGHTPADDING", (0,0),(-1,-1), 10),
            ("VALIGN",       (0,0),(-1,-1), "MIDDLE"),
        ])
    )
    story.append(tbl_final)
    story.append(Spacer(1, 8))

    # ── Nota ─────────────────────────────────────────────────────────────────
    story.append(Table(
        [[_p("O relatório considera os períodos informados pelo usuário e o tipo de contagem selecionado. "
             "Os valores são de responsabilidade do usuário — confira antes de utilizar em petição.", E["nota"])]],
        colWidths=[w],
        style=TableStyle([
            ("BOX",          (0,0),(-1,-1), 0.5, COR_BORDA),
            ("TOPPADDING",   (0,0),(-1,-1), 5),
            ("BOTTOMPADDING",(0,0),(-1,-1), 5),
            ("LEFTPADDING",  (0,0),(-1,-1), 8),
            ("RIGHTPADDING", (0,0),(-1,-1), 8),
        ])
    ))

    doc.build(story)
    return buf.getvalue()