from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.tarefa import Tarefa
from app.models.user import User
from app.models.process_item import ProcessItem
from app.services import tarefa_service

router = APIRouter(prefix="/tarefas")
templates = Jinja2Templates(directory="app/templates")


# =========================
# HELPERS
# =========================
def _get_office_id(request: Request) -> int:
    office_id = request.session.get("office_id")
    if not office_id:
        raise HTTPException(status_code=403, detail="Usuario sem escritorio vinculado.")
    return int(office_id)


def _get_current_user(request: Request) -> User:
    user = getattr(request.state, "current_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Usuario nao autenticado.")
    return user


def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    y, m, d = value.split("-")
    return date(int(y), int(m), int(d))


def _redirect_denied():
    return RedirectResponse(url="/acesso-negado", status_code=303)


# =========================
# LISTA (lista / kanban / calendario)
# =========================
@router.get("", response_class=HTMLResponse)
def tarefas_list(
    request: Request,
    view: str = "kanban",
    status: str = "",
    prioridade: str = "",
    responsavel: str = "",
    db: Session = Depends(get_db),
):
    office_id = _get_office_id(request)
    current_user = _get_current_user(request)

    query = db.query(Tarefa).filter(
        Tarefa.office_id == office_id,
    )
    if status:
        query = query.filter(Tarefa.status == status)
    if prioridade:
        query = query.filter(Tarefa.prioridade == prioridade)
    if responsavel:
        query = query.filter(Tarefa.responsavel_id == int(responsavel))

    tarefas = query.order_by(Tarefa.prazo.asc().nulls_last()).all()

    # lista de usuarios do escritorio para o filtro
    usuarios_escritorio = db.query(User).filter(
        User.office_id == office_id, User.is_active.is_(True)
    ).order_by(User.nome).all()

    if view == "kanban":
        colunas = {
            "pendente_aceite": [],
            "em_execucao": [],
            "concluida": [],
            "validada": [],
        }
        for t in tarefas:
            if t.status in colunas:
                colunas[t.status].append(t)

        return templates.TemplateResponse(
            "tasks/kanban.html",
            {
                "request": request,
                "title": "Gerenciador de Tarefas",
                "colunas": colunas,
                "usuarios_escritorio": usuarios_escritorio,
                "responsavel": responsavel,
            },
        )

    if view == "calendario":
        return templates.TemplateResponse(
            "tasks/calendar.html",
            {"request": request, "title": "Gerenciador de Tarefas", "tarefas": tarefas, "hoje": date.today()},
        )

    return templates.TemplateResponse(
        "tasks/list.html",
        {
            "request": request,
            "title": "Gerenciador de Tarefas",
            "tarefas": tarefas,
            "status": status,
            "prioridade": prioridade,
            "usuarios_escritorio": usuarios_escritorio,
            "responsavel": responsavel,
        },
    )


# =========================
# CRIAR
# =========================
@router.get("/nova", response_class=HTMLResponse)
def tarefas_nova_form(request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)

    usuarios = db.query(User).filter(User.office_id == office_id, User.is_active.is_(True)).order_by(User.nome).all()
    processos = db.query(ProcessItem).filter(ProcessItem.office_id == office_id).order_by(ProcessItem.numero_processo).all()

    return templates.TemplateResponse(
        "tasks/form.html",
        {
            "request": request,
            "title": "Nova tarefa",
            "modo": "criar",
            "tarefa": None,
            "usuarios": usuarios,
            "processos": processos,
            "erro": None,
        },
    )


@router.post("/nova")
def tarefas_nova(
    request: Request,
    db: Session = Depends(get_db),
    titulo: str = Form(...),
    descricao: str = Form(""),
    tipo: str = Form("juridica"),
    prioridade: str = Form("media"),
    prazo: str = Form(""),
    processo_id: str = Form(""),
    responsavel_id: str = Form(""),
):
    office_id = _get_office_id(request)
    current_user = _get_current_user(request)

    tarefa_service.criar_tarefa(
        db,
        office_id=office_id,
        titulo=titulo.strip(),
        descricao=descricao.strip() or None,
        tipo=tipo,
        prioridade=prioridade,
        prazo=_parse_date(prazo),
        processo_id=int(processo_id) if processo_id else None,
        criado_por_id=current_user.id,
        responsavel_id=int(responsavel_id) if responsavel_id else None,
    )
    return RedirectResponse(url="/tarefas", status_code=303)


# =========================
# EDITAR
# =========================
@router.get("/{tarefa_id}/editar", response_class=HTMLResponse)
def tarefas_editar_form(tarefa_id: int, request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)

    tarefa = db.query(Tarefa).filter(Tarefa.id == tarefa_id, Tarefa.office_id == office_id).first()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")

    usuarios = db.query(User).filter(User.office_id == office_id, User.is_active.is_(True)).order_by(User.nome).all()
    processos = db.query(ProcessItem).filter(ProcessItem.office_id == office_id).order_by(ProcessItem.numero_processo).all()

    return templates.TemplateResponse(
        "tasks/form.html",
        {
            "request": request,
            "title": "Editar tarefa",
            "modo": "editar",
            "tarefa": tarefa,
            "usuarios": usuarios,
            "processos": processos,
            "erro": None,
        },
    )


@router.post("/{tarefa_id}/editar")
def tarefas_editar(
    tarefa_id: int,
    request: Request,
    db: Session = Depends(get_db),
    titulo: str = Form(...),
    descricao: str = Form(""),
    tipo: str = Form("juridica"),
    prioridade: str = Form("media"),
    prazo: str = Form(""),
    processo_id: str = Form(""),
):
    office_id = _get_office_id(request)

    tarefa = db.query(Tarefa).filter(Tarefa.id == tarefa_id, Tarefa.office_id == office_id).first()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")

    tarefa.titulo = titulo.strip()
    tarefa.descricao = descricao.strip() or None
    tarefa.tipo = tipo
    tarefa.prioridade = prioridade
    tarefa.prazo = _parse_date(prazo)
    tarefa.processo_id = int(processo_id) if processo_id else None

    db.add(tarefa)
    db.commit()

    return RedirectResponse(url=f"/tarefas/{tarefa.id}", status_code=303)


# =========================
# DETALHE
# =========================
@router.get("/{tarefa_id}", response_class=HTMLResponse)
def tarefas_detalhe(tarefa_id: int, request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)

    tarefa = db.query(Tarefa).filter(Tarefa.id == tarefa_id, Tarefa.office_id == office_id).first()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")

    usuarios = db.query(User).filter(User.office_id == office_id, User.is_active.is_(True)).order_by(User.nome).all()

    return templates.TemplateResponse(
        "tasks/detail.html",
        {"request": request, "title": tarefa.titulo, "tarefa": tarefa, "usuarios": usuarios},
    )


@router.post("/{tarefa_id}/excluir")
def tarefas_excluir(tarefa_id: int, request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)
    try:
        tarefa_service.excluir_tarefa(db, tarefa_id, office_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    return RedirectResponse(url="/tarefas", status_code=303)


# =========================
# FLUXO DE DELEGACAO
# =========================
@router.post("/{tarefa_id}/delegar")
def tarefas_delegar(
    tarefa_id: int,
    request: Request,
    db: Session = Depends(get_db),
    novo_responsavel_id: int = Form(...),
):
    office_id = _get_office_id(request)
    current_user = _get_current_user(request)

    try:
        tarefa_service.delegar_tarefa(db, tarefa_id, office_id, novo_responsavel_id, current_user.id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")

    return RedirectResponse(url=f"/tarefas/{tarefa_id}", status_code=303)


@router.post("/{tarefa_id}/responder")
def tarefas_responder(
    tarefa_id: int,
    request: Request,
    db: Session = Depends(get_db),
    resposta: str = Form(...),
    justificativa: str = Form(""),
):
    office_id = _get_office_id(request)
    current_user = _get_current_user(request)

    try:
        tarefa_service.responder_delegacao(
            db, tarefa_id, office_id, current_user.id,
            aceitar=(resposta == "aceitar"),
            justificativa=justificativa.strip() or None,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")

    return RedirectResponse(url="/tarefas", status_code=303)


@router.post("/{tarefa_id}/concluir")
def tarefas_concluir(tarefa_id: int, request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)
    current_user = _get_current_user(request)

    try:
        tarefa_service.concluir_tarefa(db, tarefa_id, office_id, current_user.id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")

    return RedirectResponse(url=f"/tarefas/{tarefa_id}", status_code=303)


@router.post("/{tarefa_id}/validar")
def tarefas_validar(
    tarefa_id: int,
    request: Request,
    db: Session = Depends(get_db),
    resultado: str = Form(...),
    observacao: str = Form(""),
):
    office_id = _get_office_id(request)
    current_user = _get_current_user(request)

    try:
        tarefa_service.validar_tarefa(
            db, tarefa_id, office_id, current_user.id,
            aprovado=(resultado == "aprovar"),
            observacao=observacao.strip() or None,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")

    return RedirectResponse(url=f"/tarefas/{tarefa_id}", status_code=303)


@router.post("/{tarefa_id}/reabrir")
def tarefas_reabrir(tarefa_id: int, request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)
    current_user = _get_current_user(request)

    try:
        tarefa_service.reabrir_para_execucao(db, tarefa_id, office_id, current_user.id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")

    return RedirectResponse(url=f"/tarefas/{tarefa_id}", status_code=303)


@router.post("/{tarefa_id}/comentar")
def tarefas_comentar(
    tarefa_id: int,
    request: Request,
    db: Session = Depends(get_db),
    texto: str = Form(...),
):
    office_id = _get_office_id(request)
    current_user = _get_current_user(request)

    if texto.strip():
        try:
            tarefa_service.adicionar_comentario(db, tarefa_id, office_id, current_user.id, texto.strip())
        except ValueError:
            raise HTTPException(status_code=404, detail="Tarefa nao encontrada")

    return RedirectResponse(url=f"/tarefas/{tarefa_id}", status_code=303)


# =========================
# API leve — kanban (drag-and-drop)
# =========================
@router.patch("/api/{tarefa_id}/status")
async def tarefas_atualizar_status_api(tarefa_id: int, request: Request, db: Session = Depends(get_db)):
    office_id = _get_office_id(request)
    current_user = _get_current_user(request)

    body = await request.json()
    novo_status = body.get("status")

    transicoes_validas = {
        "pendente_aceite": ["em_execucao"],
        "em_execucao": ["concluida"],
        "concluida": ["validada", "reprovada"],
    }

    tarefa = db.query(Tarefa).filter(Tarefa.id == tarefa_id, Tarefa.office_id == office_id).first()
    if not tarefa:
        return JSONResponse({"ok": False, "erro": "Tarefa nao encontrada"}, status_code=404)

    if novo_status not in transicoes_validas.get(tarefa.status, []):
        return JSONResponse({"ok": False, "erro": "Transicao de status nao permitida"}, status_code=400)

    if novo_status == "em_execucao":
        tarefa_service.responder_delegacao(db, tarefa_id, office_id, current_user.id, aceitar=True)
    elif novo_status == "concluida":
        tarefa_service.concluir_tarefa(db, tarefa_id, office_id, current_user.id)
    elif novo_status == "validada":
        tarefa_service.validar_tarefa(db, tarefa_id, office_id, current_user.id, aprovado=True)
    elif novo_status == "reprovada":
        tarefa_service.validar_tarefa(db, tarefa_id, office_id, current_user.id, aprovado=False)

    return JSONResponse({"ok": True})