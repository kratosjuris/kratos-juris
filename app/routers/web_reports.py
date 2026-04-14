from io import BytesIO
from datetime import date, datetime

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.responses import StreamingResponse

from sqlalchemy.orm import Session

from app.core.datetime_utils import now_br
from app.core.database import get_db
from app.models.client import Client
from app.models.process_item import ProcessItem
from app.models.pericia_models import PericiaDiligencia

# ReportLab
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# =====================================================
# Helpers gerais
# =====================================================
def _fmt_date(dt):
    if not dt:
        return ""
    if isinstance(dt, (datetime, date)):
        return dt.strftime("%d/%m/%Y")
    return str(dt)


def _get_office_id(request: Request) -> int:
    office_id = request.session.get("office_id")
    if not office_id:
        raise HTTPException(status_code=403, detail="Usuário sem escritório vinculado.")
    return int(office_id)


def _pdf_response(filename: str, build_func):
    buffer = BytesIO()

    # Margens menores para ganhar área útil
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=10,
        leftMargin=10,
        topMargin=18,
        bottomMargin=18,
        title=filename,
    )

    story = []
    build_func(doc, story)
    doc.build(story)

    buffer.seek(0)
    headers = {"Content-Disposition": f'inline; filename="{filename}"'}
    return StreamingResponse(buffer, media_type="application/pdf", headers=headers)


def _build_table(data_rows, col_widths):
    table = Table(data_rows, colWidths=col_widths, repeatRows=1)
    table.hAlign = "LEFT"  # evita “centralizar” e perder borda

    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),

                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),

                # alinhamentos
                ("ALIGN", (0, 0), (0, -1), "LEFT"),     # Nº Processo sempre à esquerda
                ("ALIGN", (1, 0), (2, -1), "LEFT"),     # Parte/Vara à esquerda
                ("ALIGN", (3, 1), (6, -1), "CENTER"),   # colunas curtas centralizadas

                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),

                # paddings
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _header(story, title: str, subtitle: str | None = None):
    styles = getSampleStyleSheet()
    story.append(Paragraph(f"<b>{title}</b>", styles["Title"]))
    if subtitle:
        story.append(Paragraph(subtitle, styles["Normal"]))
    story.append(Spacer(1, 12))


# =====================================================
# Página inicial /relatorios
# =====================================================
@router.get("/relatorios", response_class=HTMLResponse)
def relatorios_index(request: Request):
    return templates.TemplateResponse(
        "relatorios/index.html",
        {"request": request, "title": "Relatórios"},
    )


# =====================================================
# PDF – CLIENTES
# =====================================================
@router.get("/relatorios/clientes/pdf")
def relatorio_clientes_pdf(request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)

    rows = (
        db.query(Client)
        .filter(Client.office_id == office_id)
        .order_by(Client.nome.asc())
        .all()
    )

    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "normal_small",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        wordWrap="CJK",
    )

    def P(txt):
        return Paragraph((txt or ""), normal)

    def build(doc, story):
        _header(
            story,
            "Relatório — Cadastro de Clientes",
            f"Gerado em: {_fmt_date(now_br().date())} | Total: {len(rows)}",
        )

        data = [["Nome", "Telefone", "Nascimento", "Observações"]]
        for c in rows:
            data.append(
                [
                    P(getattr(c, "nome", "") or ""),
                    P(getattr(c, "telefone", "") or ""),
                    _fmt_date(getattr(c, "nascimento", None)),
                    P(getattr(c, "obs", "") or getattr(c, "observacao", "") or ""),
                ]
            )

        story.append(_build_table(data, col_widths=[260, 130, 90, 300]))

    return _pdf_response("relatorio_clientes.pdf", build)


# =====================================================
# Helpers PROCESSOS
# =====================================================
def _processos_por_aba(db: Session, aba: str, office_id: int):
    return (
        db.query(ProcessItem)
        .filter(
            ProcessItem.aba == aba,
            ProcessItem.office_id == office_id,
        )
        .order_by(ProcessItem.vencimento.asc().nulls_last(), ProcessItem.parte_autora.asc())
        .all()
    )


def _processos_pdf(db: Session, aba: str, titulo: str, filename: str, office_id: int):
    rows = _processos_por_aba(db, aba, office_id)

    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "normal_small",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        wordWrap="CJK",
    )

    def P(txt):
        return Paragraph((txt or ""), normal)

    def build(doc, story):
        _header(
            story,
            f"Relatório — {titulo}",
            f"Gerado em: {_fmt_date(now_br().date())} | Total: {len(rows)}",
        )

        data = [["Nº Processo", "Parte", "Vara", "Int.", "Prazo", "Venc.", "Status", "Obs"]]

        for p in rows:
            data.append(
                [
                    P(getattr(p, "numero_processo", "") or ""),
                    P(getattr(p, "parte_autora", "") or ""),
                    P(getattr(p, "vara", "") or ""),
                    _fmt_date(getattr(p, "data_intimacao", None)),
                    str(getattr(p, "prazo_dias", "") or ""),
                    _fmt_date(getattr(p, "vencimento", None)),
                    getattr(p, "cumprimento", "") or "",
                    P(getattr(p, "obs", "") or ""),
                ]
            )

        col_widths = [
            150,  # Nº Processo
            170,  # Parte
            150,  # Vara
            45,   # Int.
            35,   # Prazo
            50,   # Venc.
            60,   # Status
            152,  # Obs
        ]

        story.append(_build_table(data, col_widths=col_widths))

    return _pdf_response(filename, build)


# =====================================================
# PDFs PROCESSOS
# =====================================================
@router.get("/relatorios/processos/procedentes/pdf")
def relatorio_procedentes_pdf(request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)
    return _processos_pdf(
        db,
        "PROCEDENTE",
        "Ações Procedentes",
        "relatorio_acoes_procedentes.pdf",
        office_id,
    )


@router.get("/relatorios/processos/execucao/pdf")
def relatorio_execucao_pdf(request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)
    return _processos_pdf(
        db,
        "EXECUCAO",
        "Ações em Execução",
        "relatorio_acoes_execucao.pdf",
        office_id,
    )


# =====================================================
# PDF – PRAZOS (SEPARA PENDENTES x CUMPRIDOS + QUANTIDADES)
# =====================================================
@router.get("/relatorios/prazos/pdf")
def relatorio_prazos_pdf(request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)

    pendentes = (
        db.query(ProcessItem)
        .filter(
            ProcessItem.aba == "PRAZOS",
            ProcessItem.office_id == office_id,
        )
        .filter(ProcessItem.cumprimento != "CUMPRIDO")
        .order_by(ProcessItem.vencimento.asc().nulls_last(), ProcessItem.parte_autora.asc())
        .all()
    )

    cumpridos = (
        db.query(ProcessItem)
        .filter(
            ProcessItem.aba == "PRAZOS",
            ProcessItem.office_id == office_id,
        )
        .filter(ProcessItem.cumprimento == "CUMPRIDO")
        .order_by(ProcessItem.vencimento.asc().nulls_last(), ProcessItem.parte_autora.asc())
        .all()
    )

    total = len(pendentes) + len(cumpridos)

    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "normal_small",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        wordWrap="CJK",
    )

    def P(txt):
        return Paragraph((txt or ""), normal)

    col_widths = [
        150,  # Nº Processo
        170,  # Parte
        150,  # Vara
        45,   # Int.
        35,   # Prazo
        50,   # Venc.
        60,   # Status
        152,  # Obs
    ]

    def _tabela(rows):
        data = [["Nº Processo", "Parte", "Vara", "Int.", "Prazo", "Venc.", "Status", "Obs"]]
        for p in rows:
            data.append(
                [
                    P(getattr(p, "numero_processo", "") or ""),
                    P(getattr(p, "parte_autora", "") or ""),
                    P(getattr(p, "vara", "") or ""),
                    _fmt_date(getattr(p, "data_intimacao", None)),
                    str(getattr(p, "prazo_dias", "") or ""),
                    _fmt_date(getattr(p, "vencimento", None)),
                    getattr(p, "cumprimento", "") or "",
                    P(getattr(p, "obs", "") or ""),
                ]
            )
        return _build_table(data, col_widths=col_widths)

    def build(doc, story):
        _header(
            story,
            "Relatório — Controle de Prazos",
            f"Gerado em: {_fmt_date(now_br().date())} | Total: {total} | Pendentes: {len(pendentes)} | Cumpridos: {len(cumpridos)}",
        )

        story.append(Paragraph(f"<b>PENDENTES</b> (Quantidade: {len(pendentes)})", styles["Heading2"]))
        story.append(Spacer(1, 8))
        if pendentes:
            story.append(_tabela(pendentes))
        else:
            story.append(Paragraph("Nenhum prazo pendente.", styles["Normal"]))

        story.append(PageBreak())

        story.append(Paragraph(f"<b>CUMPRIDOS</b> (Quantidade: {len(cumpridos)})", styles["Heading2"]))
        story.append(Spacer(1, 8))
        if cumpridos:
            story.append(_tabela(cumpridos))
        else:
            story.append(Paragraph("Nenhum prazo cumprido.", styles["Normal"]))

    return _pdf_response("relatorio_controle_prazos.pdf", build)


# =====================================================
# PDF – PERÍCIAS / DILIGÊNCIAS
# =====================================================
@router.get("/relatorios/pericias/pdf")
def relatorio_pericias_pdf(request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)

    rows = (
        db.query(PericiaDiligencia)
        .filter(PericiaDiligencia.office_id == office_id)
        .order_by(PericiaDiligencia.data_evento.asc())
        .all()
    )

    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "normal_small",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        wordWrap="CJK",
    )

    def P(txt):
        return Paragraph((txt or ""), normal)

    def build(doc, story):
        _header(
            story,
            "Relatório — Perícias e Diligências",
            f"Gerado em: {_fmt_date(now_br().date())} | Total: {len(rows)}",
        )

        data = [["Nº Processo", "Parte", "Observação", "Local", "Data", "Concluído"]]

        for p in rows:
            data.append(
                [
                    P(getattr(p, "numero_processo", "") or ""),
                    P(getattr(p, "nome_parte", "") or ""),
                    P(getattr(p, "observacao", "") or ""),
                    P(getattr(p, "local", "") or ""),
                    _fmt_date(getattr(p, "data_evento", None)),
                    "SIM" if bool(getattr(p, "concluido", False)) else "NÃO",
                ]
            )

        story.append(_build_table(data, col_widths=[160, 170, 260, 180, 70, 70]))

    return _pdf_response("relatorio_pericias.pdf", build)