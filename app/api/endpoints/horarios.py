import math
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, Response, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Horario, HorarioStatus, HorarioStep
from app.schemas import (
    HorarioCreate, HorarioResponse, HorarioListResponse, TimetableResponse
)
from app.services.visualizer import parse_allocations, render_html_timetable, render_html_input_data

router = APIRouter(prefix="/horarios", tags=["Horários"])


def _to_response(h: Horario) -> HorarioResponse:
    soft_conflicts_list = h.soft_conflicts if isinstance(h.soft_conflicts, list) else []
    return HorarioResponse(
        id=h.id,
        nome=h.nome,
        status=h.status,
        current_step=h.current_step,
        has_activities_xml=bool(h.activities_xml),
        has_output_fet=bool(h.output_fet),
        soft_conflicts_count=len(soft_conflicts_list),
        soft_conflicts=soft_conflicts_list,
        solver_version=h.solver_version,
        error_message=h.error_message,
        started_at=h.started_at,
        finished_at=h.finished_at,
        execution_time_seconds=h.execution_time_seconds,
        created_at=h.created_at,
        updated_at=h.updated_at,
    )


def _dispatch_celery_task(horario_id: str, timeout_seconds: int = 60):
    try:
        from app.worker import solve_timetable_task
        solve_timetable_task.delay(horario_id, timeout_seconds)
    except Exception:
        # Se Celery/Redis não estiver acessível (ex: ambiente de teste unitário sem redis), ignora
        pass


@router.post("", response_model=HorarioResponse, status_code=status.HTTP_202_ACCEPTED)
def create_horario(
    payload: Optional[HorarioCreate] = None,
    file: Optional[UploadFile] = File(None),
    nome: Optional[str] = Form(None),
    timeout_seconds: int = Form(60),
    db: Session = Depends(get_db)
):
    """
    Cria um novo job de horário a partir de JSON ou Upload de arquivo .fet.
    Dispara a resolução na Fila de Tarefas Assíncronas.
    """
    fet_content = ""
    job_nome = nome
    timeout = timeout_seconds

    if payload:
        fet_content = payload.fet_data
        job_nome = payload.nome or job_nome
        timeout = payload.timeout_seconds or timeout
    elif file:
        content_bytes = file.file.read()
        fet_content = content_bytes.decode("utf-8-sig", errors="ignore")
        if not job_nome:
            job_nome = file.filename

    if not fet_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum arquivo ou conteúdo .fet foi fornecido"
        )

    horario = Horario(
        nome=job_nome,
        fet_data=fet_content,
        status=HorarioStatus.PENDING,
        current_step=HorarioStep.ENFILEIRADO
    )
    db.add(horario)
    db.commit()
    db.refresh(horario)

    # Disparar Worker Celery
    _dispatch_celery_task(horario.id, timeout)

    return _to_response(horario)


@router.post("/{id}/solve", response_model=HorarioResponse, status_code=status.HTTP_202_ACCEPTED)
def solve_horario(
    id: str,
    timeout_seconds: int = 60,
    db: Session = Depends(get_db)
):
    """Reenfileira e dispara o cálculo para um registro de horário já existente pelo ID."""
    horario = db.query(Horario).filter(Horario.id == id).first()
    if not horario:
        raise HTTPException(status_code=404, detail="Horário não encontrado")

    horario.status = HorarioStatus.PENDING
    horario.current_step = HorarioStep.ENFILEIRADO
    horario.error_message = None
    db.commit()
    db.refresh(horario)

    _dispatch_celery_task(horario.id, timeout_seconds)
    return _to_response(horario)


@router.post("/{id}/cancel", response_model=HorarioResponse)
def cancel_horario(id: str, db: Session = Depends(get_db)):
    """Cancela a execução de um job de horário em andamento ou enfileirado."""
    horario = db.query(Horario).filter(Horario.id == id).first()
    if not horario:
        raise HTTPException(status_code=404, detail="Horário não encontrado")

    horario.status = HorarioStatus.CANCELLED
    horario.current_step = HorarioStep.CANCELADO
    db.commit()
    db.refresh(horario)

    try:
        from app.worker import celery_app
        celery_app.control.revoke(id, terminate=True)
    except Exception:
        pass

    return _to_response(horario)


@router.get("", response_model=HorarioListResponse)
def list_horarios(
    page: int = Query(1, ge=1, description="Número da página"),
    limit: int = Query(20, ge=1, le=100, description="Itens por página"),
    status: Optional[str] = Query(None, description="Filtrar por status"),
    db: Session = Depends(get_db)
):
    """Lista horários cadastrados com paginação e filtro por status."""
    query = db.query(Horario)
    if status:
        query = query.filter(Horario.status == status.upper())

    total = query.count()
    pages = math.ceil(total / limit) if total > 0 else 1
    offset = (page - 1) * limit

    items = query.order_by(Horario.created_at.desc()).offset(offset).limit(limit).all()
    response_items = [_to_response(h) for h in items]

    return HorarioListResponse(
        items=response_items,
        total=total,
        page=page,
        limit=limit,
        pages=pages
    )


@router.get("/{id}", response_model=HorarioResponse)
def get_horario_detail(id: str, db: Session = Depends(get_db)):
    """Retorna os detalhes e o status atual do processamento de um horário."""
    horario = db.query(Horario).filter(Horario.id == id).first()
    if not horario:
        raise HTTPException(status_code=404, detail="Horário não encontrado")
    return _to_response(horario)


@router.get("/{id}/xml")
def get_horario_xml(id: str, db: Session = Depends(get_db)):
    """Retorna o arquivo activities.xml gravado no banco de dados para o ID."""
    horario = db.query(Horario).filter(Horario.id == id).first()
    if not horario:
        raise HTTPException(status_code=404, detail="Horário não encontrado")

    if not horario.activities_xml:
        raise HTTPException(
            status_code=404, 
            detail=f"A grade para o horário {id} ainda não foi gerada (Status atual: {horario.status})"
        )

    return Response(content=horario.activities_xml, media_type="application/xml")


@router.get("/{id}/timetable", response_model=TimetableResponse)
def get_horario_timetable(id: str, db: Session = Depends(get_db)):
    """Retorna a grade de alocações de horários parseada em formato JSON."""
    horario = db.query(Horario).filter(Horario.id == id).first()
    if not horario:
        raise HTTPException(status_code=404, detail="Horário não encontrado")

    allocations = parse_allocations(horario.fet_data, horario.activities_xml)
    allocated_count = sum(1 for a in allocations if a.day and a.hour)

    return TimetableResponse(
        horario_id=horario.id,
        status=horario.status,
        allocated_count=allocated_count,
        total_count=len(allocations),
        allocations=allocations
    )


@router.get("/{id}/view", response_class=HTMLResponse)
def get_horario_view(id: str, db: Session = Depends(get_db)):
    """Retorna a visualização HTML interativa da grade horária (Por Turma / Por Professor)."""
    horario = db.query(Horario).filter(Horario.id == id).first()
    if not horario:
        raise HTTPException(status_code=404, detail="Horário não encontrado")

    html_content = render_html_timetable(
        horario_nome=horario.nome or horario.id,
        fet_xml=horario.fet_data,
        activities_xml=horario.activities_xml,
        output_fet=horario.output_fet
    )
    return HTMLResponse(content=html_content)


@router.get("/{id}/viewdata", response_class=HTMLResponse)
@router.get("/{id}/view-input", response_class=HTMLResponse)
def get_horario_viewdata(id: str, db: Session = Depends(get_db)):
    """Retorna a visualização HTML dos dados de entrada do .fet (currículo, disponibilidade, turmas, carga horária)."""
    horario = db.query(Horario).filter(Horario.id == id).first()
    if not horario:
        raise HTTPException(status_code=404, detail="Horário não encontrado")

    html_content = render_html_input_data(
        horario_nome=horario.nome or horario.id,
        fet_xml=horario.fet_data
    )
    return HTMLResponse(content=html_content)


@router.get("/{id}/download")
def download_horario_file(
    id: str,
    format: str = Query("xml", description="Formato de download: 'xml' (activities.xml) ou 'fet' (data_and_timetable.fet)"),
    db: Session = Depends(get_db)
):
    """Permite realizar o download dos arquivos de saída gerados pelo FET."""
    horario = db.query(Horario).filter(Horario.id == id).first()
    if not horario:
        raise HTTPException(status_code=404, detail="Horário não encontrado")

    if format.lower() == "xml":
        if not horario.activities_xml:
            raise HTTPException(status_code=404, detail="Arquivo activities.xml ainda não está disponível")
        return Response(
            content=horario.activities_xml,
            media_type="application/xml",
            headers={"Content-Disposition": f"attachment; filename={horario.id}_activities.xml"}
        )
    elif format.lower() == "fet":
        if not horario.output_fet:
            raise HTTPException(status_code=404, detail="Arquivo data_and_timetable.fet ainda não está disponível")
        return Response(
            content=horario.output_fet,
            media_type="application/xml",
            headers={"Content-Disposition": f"attachment; filename={horario.id}_data_and_timetable.fet"}
        )
    else:
        raise HTTPException(status_code=400, detail="Formato inválido. Use 'xml' ou 'fet'.")
