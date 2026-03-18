from datetime import datetime, date, timedelta
from typing import List, Optional
import os
import urllib.parse
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func  # ✅ NOVO: func para contadores
from sqlalchemy.exc import IntegrityError  # ✅ CORREÇÃO: proteção no commit

from app.core.database import get_db
from app.models.hearing import Hearing
from app.models.hearing_contact import HearingContact
from app.models.client import Client

from app.services.hearing_import import extract_hearings_from_file, extract_hearings_from_archive
from app.services.whatsapp import build_client_message, build_wa_me_link

# ✅ PDF service (novo)
from app.services.hearing_pdf import build_hearing_orientations_pdf

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix="/audiencias", tags=["Audiências"])


def _app_tz() -> ZoneInfo:
    """
    Timezone padrão do sistema.
    Pode sobrescrever por variável de ambiente:
    APP_TIMEZONE=America/Sao_Paulo
    """
    tz_name = os.getenv("APP_TIMEZONE", "America/Sao_Paulo").strip() or "America/Sao_Paulo"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("America/Sao_Paulo")


def _now_local_naive() -> datetime:
    """
    Retorna o 'agora' no fuso local do sistema, porém sem tzinfo,
    para comparar com campos DATETIME naive do banco.
    """
    return datetime.now(_app_tz()).replace(tzinfo=None)


def _today_local() -> date:
    """
    Data atual no fuso local do sistema.
    """
    return datetime.now(_app_tz()).date()


def _norm_name(s: str) -> str:
    return " ".join((s or "").strip().upper().split())


def _safe_strip(v: str | None) -> str:
    return (v or "").strip()


def _client_display_name(c: Client) -> str:
    """
    Compatível com seu model atual:
    - Client.nome (padrão do seu sistema)
    - Client.name (se algum dia existir)
    """
    return _norm_name(getattr(c, "nome", None) or getattr(c, "name", None) or "")


def _find_client_by_name(db: Session, name_guess: str) -> Optional[Client]:
    """
    ✅ CORRIGIDO:
    Seu Client usa 'nome'. Antes você buscava por 'name', então quase nunca vinculava.
    Agora:
    - tenta match exato (nome normalizado)
    - tenta match parcial (contém)
    """
    ng = (name_guess or "").strip()
    if len(ng) < 4:
        return None

    target = _norm_name(ng)
    clients = db.query(Client).all()

    # 1) match exato
    for c in clients:
        if _client_display_name(c) == target:
            return c

    # 2) match parcial
    for c in clients:
        cname = _client_display_name(c)
        if target in cname or cname in target:
            return c

    return None


def _has_is_performed() -> bool:
    """Se o model Hearing ainda não tem a coluna, não usamos Hearing.is_performed."""
    return hasattr(Hearing, "is_performed")


def _has_manual_phone() -> bool:
    """Se o model Hearing ainda não tem a coluna, não usamos Hearing.manual_phone."""
    return hasattr(Hearing, "manual_phone")


def _has_client_rel() -> bool:
    """Protege caso o model Hearing não tenha relationship 'client'."""
    return hasattr(Hearing, "client")


# =========================
# ✅ CONTADORES (TOP BAR) — igual "Controle de Prazos"
# =========================
def _week_bounds(d: date) -> tuple[date, date]:
    """
    Retorna (inicio_semana, fim_semana) considerando semana SEG-DOM.
    """
    start = d - timedelta(days=d.weekday())  # segunda
    end = start + timedelta(days=6)          # domingo
    return start, end


def _build_hearing_stats(db: Session, now: datetime) -> dict:
    """
    Contadores para o painel:
    - total
    - a_realizar (futuras e (se existir) não marcadas como realizadas)
    - realizadas (passadas OU marcadas como realizadas, se existir flag)
    - hoje
    - essa_semana
    - semana_que_vem

    OBS: Sem "atrasadas", conforme solicitado.
    """
    today = now.date()

    # limites de hoje
    today_start = datetime.combine(today, datetime.min.time())
    tomorrow_start = today_start + timedelta(days=1)

    # limites da semana
    w_start, w_end = _week_bounds(today)
    week_start_dt = datetime.combine(w_start, datetime.min.time())
    week_end_dt_excl = datetime.combine(w_end + timedelta(days=1), datetime.min.time())

    # semana que vem
    next_w_start = w_end + timedelta(days=1)
    next_w_end = next_w_start + timedelta(days=6)
    next_week_start_dt = datetime.combine(next_w_start, datetime.min.time())
    next_week_end_dt_excl = datetime.combine(next_w_end + timedelta(days=1), datetime.min.time())

    has_flag = _has_is_performed()

    # ✅ total (tudo)
    total = (
        db.query(func.count(Hearing.id))
        .filter(Hearing.starts_at.isnot(None))
        .scalar()
        or 0
    )

    # ✅ realizadas
    if has_flag:
        realizadas = (
            db.query(func.count(Hearing.id))
            .filter(
                Hearing.starts_at.isnot(None),
                or_(Hearing.starts_at < now, Hearing.is_performed == True),  # type: ignore[attr-defined]
            )
            .scalar()
            or 0
        )
    else:
        realizadas = (
            db.query(func.count(Hearing.id))
            .filter(
                Hearing.starts_at.isnot(None),
                Hearing.starts_at < now,
            )
            .scalar()
            or 0
        )

    # ✅ base das "a realizar" (futuras)
    q_future = db.query(Hearing.id).filter(
        Hearing.starts_at.isnot(None),
        Hearing.starts_at >= now,
    )
    if has_flag:
        q_future = q_future.filter(Hearing.is_performed == False)  # type: ignore[attr-defined]

    a_realizar = q_future.count()

    # ✅ HOJE (dentro de hoje, e não realizadas se flag existir)
    q_today = db.query(Hearing.id).filter(
        Hearing.starts_at.isnot(None),
        Hearing.starts_at >= today_start,
        Hearing.starts_at < tomorrow_start,
    )
    if has_flag:
        q_today = q_today.filter(Hearing.is_performed == False)  # type: ignore[attr-defined]
    else:
        q_today = q_today.filter(Hearing.starts_at >= now)  # apenas as que ainda vão acontecer hoje

    hoje = q_today.count()

    # ✅ ESSA SEMANA (SEG-DOM), a realizar
    q_week = db.query(Hearing.id).filter(
        Hearing.starts_at.isnot(None),
        Hearing.starts_at >= week_start_dt,
        Hearing.starts_at < week_end_dt_excl,
    )
    if has_flag:
        q_week = q_week.filter(Hearing.is_performed == False)  # type: ignore[attr-defined]
    else:
        q_week = q_week.filter(Hearing.starts_at >= now)

    essa_semana = q_week.count()

    # ✅ SEMANA QUE VEM (SEG-DOM), a realizar
    q_next_week = db.query(Hearing.id).filter(
        Hearing.starts_at.isnot(None),
        Hearing.starts_at >= next_week_start_dt,
        Hearing.starts_at < next_week_end_dt_excl,
    )
    if has_flag:
        q_next_week = q_next_week.filter(Hearing.is_performed == False)  # type: ignore[attr-defined]
    # se não tem flag, semana que vem já é naturalmente futura, não precisa starts_at >= now

    semana_que_vem = q_next_week.count()

    return {
        "total": int(total),
        "a_realizar": int(a_realizar),
        "realizadas": int(realizadas),
        "hoje": int(hoje),
        "essa_semana": int(essa_semana),
        "semana_que_vem": int(semana_que_vem),
    }


# =========================
# ✅ ENVIO PARA ADVOGADOS (RESUMO DO PRÓXIMO DIA ÚTIL)
# =========================
def _normalize_phone_br(phone: str | None) -> str | None:
    """Normaliza telefone para wa.me (remove não-numéricos e adiciona DDI 55 se faltar)."""
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        return None
    if digits.startswith("55"):
        return digits
    return "55" + digits


def _next_business_day(d: date) -> date:
    """
    Próximo dia útil (mesma regra prática do dashboard):
    - sexta -> segunda
    - sábado -> segunda
    - domingo -> segunda
    - demais -> amanhã
    """
    wd = d.weekday()  # 0=seg ... 4=sex ... 5=sab ... 6=dom
    if wd == 4:   # sexta
        return d + timedelta(days=3)
    if wd == 5:   # sábado
        return d + timedelta(days=2)
    if wd == 6:   # domingo
        return d + timedelta(days=1)
    return d + timedelta(days=1)


def _fmt_hearing_line(h: Hearing) -> str:
    """
    ✅ AGORA INCLUI O CÓDIGO DE EXTENSÃO (extension_code) NO TEXTO DOS ADVOGADOS
    """
    hhmm = h.starts_at.strftime("%H:%M") if h.starts_at else "??:??"
    pn = (h.process_number or "").strip()
    prom = (h.promovente or "").strip()
    prov = (h.promovido or "").strip()
    mod = (h.modalidade or "").strip()
    ext = (getattr(h, "extension_code", None) or "").strip()

    parts = [f"{hhmm} — {pn}"]

    if prom or prov:
        if prom and prov:
            parts.append(f"{prom} x {prov}")
        else:
            parts.append(prom or prov)

    if mod:
        parts.append(f"({mod})")

    if ext:
        parts.append(f"Código: {ext}")

    return " | ".join([p for p in parts if p])


def _build_lawyer_daily_message(hearings: List[Hearing], when: date) -> str:
    header = f"Prezados (as) advogados (as), segue a pauta de *Audiências do dia {when.strftime('%d/%m/%Y')}*"
    if not hearings:
        return header + "\n\n✅ Sem audiências cadastradas para este dia.\n\n— Kratos Juris"

    lines = [header, ""]
    for h in hearings:
        lines.append("• " + _fmt_hearing_line(h))
    lines.append("")
    lines.append("— Kratos Juris")
    return "\n".join(lines)


@router.get("/enviar-advogados", response_class=HTMLResponse)
def enviar_advogados(request: Request, db: Session = Depends(get_db)):
    """
    Envia SEMPRE as audiências do PRÓXIMO DIA ÚTIL (para o advogado se programar).

    Regra:
    - Seg–Qui: amanhã
    - Sexta: segunda (engloba sábado e domingo)
    - Sáb/Dom: segunda
    """
    today = _today_local()
    target_date = _next_business_day(today)

    start = datetime.combine(target_date, datetime.min.time())
    end = start + timedelta(days=1)

    hearings = (
        db.query(Hearing)
        .filter(Hearing.starts_at.isnot(None), Hearing.starts_at >= start, Hearing.starts_at < end)
        .order_by(Hearing.starts_at.asc())
        .all()
    )

    contacts = db.query(HearingContact).order_by(HearingContact.name.asc()).all()
    enabled = [c for c in contacts if getattr(c, "is_enabled", True)]

    msg = _build_lawyer_daily_message(hearings, target_date)
    encoded_msg = urllib.parse.quote(msg, safe="", encoding="utf-8")

    links = []
    for c in enabled:
        phone = _normalize_phone_br(getattr(c, "phone", None))
        if not phone:
            continue
        wa = f"https://wa.me/{phone}?text={encoded_msg}"
        links.append({"name": c.name, "phone": c.phone, "wa_link": wa})

    return templates.TemplateResponse(
        "audiencias/enviar_advogados.html",
        {
            "request": request,
            "today": today,
            "target_date": target_date,
            "hearings": hearings,
            "links": links,
            "msg_preview": msg,
        },
    )


# =========================
# ✅ INDEX: a realizar + painel realizadas
# =========================
@router.get("", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    now = _now_local_naive()
    has_flag = _has_is_performed()

    # ✅ NOVO: stats do topo (igual Controle de Prazos)
    stats = _build_hearing_stats(db, now)

    q_future = db.query(Hearing).filter(
        Hearing.starts_at.isnot(None),
        Hearing.starts_at >= now,
    )
    if _has_client_rel():
        q_future = q_future.options(joinedload(Hearing.client))  # type: ignore[arg-type]

    if has_flag:
        q_future = q_future.filter(Hearing.is_performed == False)  # type: ignore[attr-defined]

    hearings = q_future.order_by(Hearing.starts_at.asc()).all()

    q_done = db.query(Hearing).filter(
        Hearing.starts_at.isnot(None),
        Hearing.starts_at < now,
    )
    if _has_client_rel():
        q_done = q_done.options(joinedload(Hearing.client))  # type: ignore[arg-type]

    if has_flag:
        q_done = db.query(Hearing).filter(
            Hearing.starts_at.isnot(None),
            or_(Hearing.starts_at < now, Hearing.is_performed == True),  # type: ignore[attr-defined]
        )
        if _has_client_rel():
            q_done = q_done.options(joinedload(Hearing.client))  # type: ignore[arg-type]

    performed_hearings = q_done.order_by(Hearing.starts_at.desc()).limit(250).all()

    contacts = db.query(HearingContact).order_by(HearingContact.name.asc()).all()

    try:
        msg = request.session.pop("audiencias_import_msg", None)
    except Exception:
        msg = None

    try:
        import_stats = request.session.pop("audiencias_import_stats", None)
    except Exception:
        import_stats = None

    return templates.TemplateResponse(
        "audiencias/index.html",
        {
            "request": request,
            "hearings": hearings,
            "performed_hearings": performed_hearings,
            "contacts": contacts,
            "msg": msg,
            "import_stats": import_stats,
            "now": now,
            "has_is_performed": has_flag,
            "has_manual_phone": _has_manual_phone(),
            "stats": stats,
        },
    )


# =========================
# ✅ IMPORTAÇÃO
# =========================
@router.post("/import")
async def import_files(
    request: Request,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    inserted = 0
    extracted_total = 0
    duplicated = 0
    files_ok = 0
    filenames: List[str] = []
    has_flag = _has_is_performed()

    # ✅ CORREÇÃO:
    # evita duplicidade dentro do mesmo lote de importação
    batch_seen_keys: set[tuple[str, datetime]] = set()

    for f in files:
        b = await f.read()
        name = (f.filename or "").lower().strip()

        if name.endswith(".zip") or name.endswith(".rar"):
            extracted = extract_hearings_from_archive(b, f.filename)
        else:
            extracted = extract_hearings_from_file(b, f.filename)

        files_ok += 1
        extracted_total += len(extracted)
        filenames.append(f.filename or "arquivo")

        for it in extracted:
            process_number = _safe_strip(it.get("process_number"))
            starts_at = it.get("starts_at")

            if not process_number or not starts_at:
                continue

            key = (process_number, starts_at)

            if key in batch_seen_keys:
                duplicated += 1
                continue

            batch_seen_keys.add(key)

            client = _find_client_by_name(db, it.get("client_name_guess") or "")
            if client:
                it["client_id"] = client.id

            it["process_number"] = process_number

            exists = (
                db.query(Hearing)
                .filter(
                    Hearing.process_number == process_number,
                    Hearing.starts_at == starts_at,
                )
                .first()
            )
            if exists:
                duplicated += 1
                continue

            if has_flag:
                it["is_performed"] = False

            db.add(Hearing(**it))
            inserted += 1

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        try:
            request.session["audiencias_import_stats"] = {
                "arquivos": files_ok,
                "extraidas": extracted_total,
                "inseridas": inserted,
                "duplicadas": duplicated,
                "filenames": filenames,
            }
            request.session["audiencias_import_msg"] = (
                "Importação concluída com conflito de duplicidade. "
                "O sistema ignorou registros repetidos já existentes."
            )
        except Exception:
            pass
        return RedirectResponse(url="/audiencias", status_code=303)

    stats = {
        "arquivos": files_ok,
        "extraidas": extracted_total,
        "inseridas": inserted,
        "duplicadas": duplicated,
        "filenames": filenames,
    }

    try:
        request.session["audiencias_import_stats"] = stats
        if extracted_total == 0:
            request.session["audiencias_import_msg"] = (
                f"Importação concluída, mas NÃO encontrei audiências nos arquivos. "
                f"(arquivos: {files_ok}). Possíveis causas: arquivo sem dados úteis, "
                f"frameset do Projudi (HTML índice), ou formato diferente do esperado."
            )
        else:
            request.session["audiencias_import_msg"] = (
                f"Importação concluída: arquivos={files_ok} | extraídas={extracted_total} | "
                f"inseridas={inserted} | duplicadas={duplicated}."
            )
    except Exception:
        pass

    return RedirectResponse(url="/audiencias", status_code=303)


# =========================
# ✅ CADASTRO MANUAL (reusa edit.html)
# =========================
@router.get("/novo", response_class=HTMLResponse)
def new_form(request: Request):
    return templates.TemplateResponse("audiencias/edit.html", {"request": request, "h": None})


@router.post("/create")
def create_save(
    request: Request,
    process_number: str = Form(...),
    starts_at: str = Form(...),
    modalidade: str = Form(""),
    promovente: str = Form(""),
    promovido: str = Form(""),
    extension_code: str = Form(""),
    notes: str = Form(""),
    manual_phone: str = Form(""),
    db: Session = Depends(get_db),
):
    pn = _safe_strip(process_number)
    if not pn:
        return RedirectResponse(url="/audiencias/novo", status_code=303)

    try:
        dt = datetime.fromisoformat(_safe_strip(starts_at))
    except Exception:
        return RedirectResponse(url="/audiencias/novo", status_code=303)

    exists = (
        db.query(Hearing)
        .filter(Hearing.process_number == pn, Hearing.starts_at == dt)
        .first()
    )
    if exists:
        try:
            request.session["audiencias_import_msg"] = (
                "Já existe uma audiência com este processo e esta data/hora. Nenhum cadastro foi feito."
            )
        except Exception:
            pass
        return RedirectResponse(url="/audiencias", status_code=303)

    data = dict(
        process_number=pn,
        starts_at=dt,
        modalidade=_safe_strip(modalidade) or None,
        promovente=_safe_strip(promovente) or None,
        promovido=_safe_strip(promovido) or None,
        extension_code=_safe_strip(extension_code) or None,
        notes=_safe_strip(notes) or None,
    )

    if _has_is_performed():
        data["is_performed"] = False

    if _has_manual_phone():
        data["manual_phone"] = _safe_strip(manual_phone) or None

    h = Hearing(**data)

    if not getattr(h, "client_id", None):
        client = _find_client_by_name(db, h.promovente or "")
        if client:
            h.client_id = client.id  # type: ignore[attr-defined]

    db.add(h)
    db.commit()
    return RedirectResponse(url="/audiencias", status_code=303)


# =========================
# ✅ EDITAR
# =========================
@router.get("/{hearing_id}/edit", response_class=HTMLResponse)
def edit_form(hearing_id: int, request: Request, db: Session = Depends(get_db)):
    h = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    return templates.TemplateResponse("audiencias/edit.html", {"request": request, "h": h})


@router.post("/{hearing_id}/edit")
def edit_save(
    hearing_id: int,
    process_number: str = Form(...),
    promovente: str = Form(""),
    promovido: str = Form(""),
    starts_at: str = Form(...),
    modalidade: str = Form(""),
    extension_code: str = Form(""),
    notes: str = Form(""),
    manual_phone: str = Form(""),
    db: Session = Depends(get_db),
):
    h = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not h:
        return RedirectResponse(url="/audiencias", status_code=303)

    pn = _safe_strip(process_number)
    try:
        dt = datetime.fromisoformat(_safe_strip(starts_at))
    except Exception:
        return RedirectResponse(url=f"/audiencias/{hearing_id}/edit", status_code=303)

    h.process_number = pn
    h.promovente = _safe_strip(promovente) or None
    h.promovido = _safe_strip(promovido) or None
    h.modalidade = _safe_strip(modalidade) or None
    h.extension_code = _safe_strip(extension_code) or None
    h.notes = _safe_strip(notes) or None
    h.starts_at = dt

    if _has_manual_phone():
        h.manual_phone = _safe_strip(manual_phone) or None  # type: ignore[attr-defined]

    if not getattr(h, "client_id", None):
        client = _find_client_by_name(db, h.promovente or "")
        if client:
            h.client_id = client.id  # type: ignore[attr-defined]

    db.commit()
    return RedirectResponse(url="/audiencias", status_code=303)


# =========================
# ✅ DELETE (individual)
# =========================
@router.post("/{hearing_id}/delete")
def delete(hearing_id: int, db: Session = Depends(get_db)):
    h = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if h:
        db.delete(h)
        db.commit()
    return RedirectResponse(url="/audiencias", status_code=303)


# =========================
# ✅ DELETE (lote)
# =========================
@router.post("/delete-batch")
def delete_batch(ids: str = Form(...), db: Session = Depends(get_db)):
    ids_list = [int(x) for x in (ids or "").split(",") if x.strip().isdigit()]
    if not ids_list:
        return RedirectResponse(url="/audiencias", status_code=303)

    db.query(Hearing).filter(Hearing.id.in_(ids_list)).delete(synchronize_session=False)
    db.commit()
    return RedirectResponse(url="/audiencias", status_code=303)


# =========================
# ✅ PDF ORIENTAÇÕES (DOWNLOAD)
# =========================
@router.get("/{hearing_id}/pdf-orientacoes")
def pdf_orientacoes(hearing_id: int, request: Request, db: Session = Depends(get_db)):
    q = db.query(Hearing)
    if _has_client_rel():
        q = q.options(joinedload(Hearing.client))  # type: ignore[arg-type]
    h = q.filter(Hearing.id == hearing_id).first()

    if not h:
        return RedirectResponse(url="/audiencias", status_code=303)

    client = getattr(h, "client", None)

    client_name = (
        (getattr(client, "nome", None) if client else None)
        or (getattr(client, "name", None) if client else None)
        or (h.promovente or "Cliente")
    )

    extension_code = getattr(h, "extension_code", None)
    if not (str(extension_code or "").strip()):
        extension_code = "Não informado"

    static_dir = os.path.join("app", "static")

    pdf_bytes = build_hearing_orientations_pdf(
        client_name=client_name,
        process_number=h.process_number or "",
        promovido=h.promovido or "",
        starts_at=h.starts_at,
        modalidade=h.modalidade or "",
        extension_code=str(extension_code),
        static_dir=static_dir,
    )

    filename = f"orientacoes_audiencia_{hearing_id}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return StreamingResponse(iter([pdf_bytes]), media_type="application/pdf", headers=headers)


# =========================
# ✅ WHATSAPP CLIENTE
# =========================
@router.get("/{hearing_id}/whatsapp")
def whatsapp_client(hearing_id: int, request: Request, db: Session = Depends(get_db)):
    q = db.query(Hearing)
    if _has_client_rel():
        q = q.options(joinedload(Hearing.client))  # type: ignore[arg-type]
    h = q.filter(Hearing.id == hearing_id).first()

    if not h:
        return RedirectResponse(url="/audiencias", status_code=303)

    client = getattr(h, "client", None)

    phone = None
    if client:
        phone = (
            getattr(client, "telefone", None)
            or getattr(client, "phone", None)
            or getattr(client, "celular", None)
        )

    if not phone:
        phone = getattr(h, "manual_phone", None)

    if not phone:
        try:
            request.session["audiencias_import_msg"] = (
                "Não foi possível enviar WhatsApp: cliente sem telefone cadastrado e audiência sem telefone manual."
            )
        except Exception:
            pass
        return RedirectResponse(url="/audiencias", status_code=303)

    public_base_url = str(request.base_url).rstrip("/")

    client_name = (
        (getattr(client, "nome", None) if client else None)
        or (getattr(client, "name", None) if client else None)
        or (h.promovente or "Cliente")
    )

    msg = build_client_message(
        client_name=client_name,
        process_number=h.process_number,
        promovido=h.promovido or "",
        starts_at=h.starts_at,
        modalidade=h.modalidade or "",
        extension_code=h.extension_code,
        public_base_url=public_base_url,
    )

    link = build_wa_me_link(phone, msg)
    return RedirectResponse(url=link, status_code=302)


@router.get("/{hearing_id}/create-client")
def create_client_redirect(hearing_id: int, db: Session = Depends(get_db)):
    h = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not h:
        return RedirectResponse(url="/audiencias", status_code=303)

    name = (h.promovente or getattr(h, "client_name_guess", None) or "").strip()
    return RedirectResponse(url=f"/clientes/novo?name={name}", status_code=303)


# =========================
# ✅ CONFIG DESTINATÁRIOS
# =========================
@router.get("/config", response_class=HTMLResponse)
def config(request: Request, db: Session = Depends(get_db)):
    contacts = db.query(HearingContact).order_by(HearingContact.name.asc()).all()
    return templates.TemplateResponse("audiencias/config.html", {"request": request, "contacts": contacts})


@router.post("/config/add")
def config_add(name: str = Form(...), phone: str = Form(...), db: Session = Depends(get_db)):
    db.add(HearingContact(name=name.strip(), phone=phone.strip(), is_enabled=True))
    db.commit()
    return RedirectResponse(url="/audiencias/config", status_code=303)


@router.post("/config/{contact_id}/toggle")
def config_toggle(contact_id: int, db: Session = Depends(get_db)):
    c = db.query(HearingContact).filter(HearingContact.id == contact_id).first()
    if c:
        c.is_enabled = not c.is_enabled
        db.commit()
    return RedirectResponse(url="/audiencias/config", status_code=303)


@router.post("/config/{contact_id}/delete")
def config_delete(contact_id: int, db: Session = Depends(get_db)):
    c = db.query(HearingContact).filter(HearingContact.id == contact_id).first()
    if c:
        db.delete(c)
        db.commit()
    return RedirectResponse(url="/audiencias/config", status_code=303)


# =========================
# ✅ MARCAR / DESMARCAR REALIZADAS (1 e lote)
# =========================
@router.post("/{hearing_id}/mark-performed")
def mark_performed(hearing_id: int, db: Session = Depends(get_db)):
    if not _has_is_performed():
        return RedirectResponse(url="/audiencias", status_code=303)

    h = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if h and not h.is_performed:  # type: ignore[attr-defined]
        h.is_performed = True  # type: ignore[attr-defined]
        db.commit()
    return RedirectResponse(url="/audiencias", status_code=303)


@router.post("/{hearing_id}/unmark-performed")
def unmark_performed(hearing_id: int, db: Session = Depends(get_db)):
    if not _has_is_performed():
        return RedirectResponse(url="/audiencias", status_code=303)

    h = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if h and h.is_performed:  # type: ignore[attr-defined]
        h.is_performed = False  # type: ignore[attr-defined]
        db.commit()
    return RedirectResponse(url="/audiencias", status_code=303)


@router.post("/mark-performed")
def mark_performed_batch(ids: str = Form(...), db: Session = Depends(get_db)):
    if not _has_is_performed():
        return RedirectResponse(url="/audiencias", status_code=303)

    ids_list = [int(x) for x in (ids or "").split(",") if x.strip().isdigit()]
    if not ids_list:
        return RedirectResponse(url="/audiencias", status_code=303)

    db.query(Hearing).filter(Hearing.id.in_(ids_list)).update(
        {Hearing.is_performed: True},  # type: ignore[attr-defined]
        synchronize_session=False,
    )
    db.commit()
    return RedirectResponse(url="/audiencias", status_code=303)


@router.post("/unmark-performed")
def unmark_performed_batch(ids: str = Form(...), db: Session = Depends(get_db)):
    if not _has_is_performed():
        return RedirectResponse(url="/audiencias", status_code=303)

    ids_list = [int(x) for x in (ids or "").split(",") if x.strip().isdigit()]
    if not ids_list:
        return RedirectResponse(url="/audiencias", status_code=303)

    db.query(Hearing).filter(Hearing.id.in_(ids_list)).update(
        {Hearing.is_performed: False},  # type: ignore[attr-defined]
        synchronize_session=False,
    )
    db.commit()
    return RedirectResponse(url="/audiencias", status_code=303)


@router.get("/realizadas", response_class=HTMLResponse)
def realizadas(request: Request, db: Session = Depends(get_db)):
    now = _now_local_naive()
    has_flag = _has_is_performed()

    if has_flag:
        performed_hearings = (
            db.query(Hearing)
            .filter(
                Hearing.starts_at.isnot(None),
                or_(Hearing.starts_at < now, Hearing.is_performed == True),  # type: ignore[attr-defined]
            )
            .order_by(Hearing.starts_at.desc())
            .all()
        )
    else:
        performed_hearings = (
            db.query(Hearing)
            .filter(
                Hearing.starts_at.isnot(None),
                Hearing.starts_at < now,
            )
            .order_by(Hearing.starts_at.desc())
            .all()
        )

    return templates.TemplateResponse(
        "audiencias/realizadas.html",
        {
            "request": request,
            "performed_hearings": performed_hearings,
            "now": now,
            "has_is_performed": has_flag,
        },
    )