from datetime import datetime, timezone
from celery import Celery
from app.config import settings
from app.database import SessionLocal
from app.models import Horario, HorarioStatus, HorarioStep
from app.services.fet_runner import run_fet_pipeline

celery_app = Celery(
    "horarios_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)


@celery_app.task(name="app.worker.solve_timetable_task", bind=True)
def solve_timetable_task(self, horario_id: str, timeout_seconds: int = 60):
    """Task assíncrona do Celery para execução da solução do FET por ID."""
    db = SessionLocal()
    try:
        horario = db.query(Horario).filter(Horario.id == horario_id).first()
        if not horario:
            return {"error": f"Horário ID {horario_id} não encontrado"}

        # Se já tiver sido cancelado antes de iniciar
        if horario.status == HorarioStatus.CANCELLED:
            return {"status": HorarioStatus.CANCELLED}

        # Transição 1: PENDING -> RUNNING (Etapa: PREPARANDO)
        horario.status = HorarioStatus.RUNNING
        horario.current_step = HorarioStep.PREPARANDO
        horario.started_at = datetime.now(timezone.utc)
        db.commit()

        # Etapa: EXECUTANDO_FET
        horario.current_step = HorarioStep.EXECUTANDO_FET
        db.commit()

        # Execução do FET Runner em diretório temporário isolado
        res = run_fet_pipeline(
            fet_data=horario.fet_data,
            timeout_seconds=timeout_seconds,
            fet_cl_path=settings.FET_CL_PATH
        )

        # Recarregar do banco para verificar se houve cancelamento durante a execução
        db.refresh(horario)
        if horario.status == HorarioStatus.CANCELLED:
            horario.current_step = HorarioStep.CANCELADO
            db.commit()
            return {"status": HorarioStatus.CANCELLED}

        # Etapa: PROCESSANDO_SAIDA & SALVANDO_RESULTADOS
        horario.current_step = HorarioStep.PROCESSANDO_SAIDA
        db.commit()

        horario.activities_xml = res["activities_xml"]
        horario.output_fet = res["output_fet"]
        horario.soft_conflicts = res["soft_conflicts"]
        horario.solver_log = res["solver_log"]
        horario.solver_version = res["solver_version"]
        horario.status = res["status"]
        horario.error_message = res["error_message"]
        horario.execution_time_seconds = res["execution_time_seconds"]
        horario.finished_at = datetime.now(timezone.utc)
        horario.current_step = HorarioStep.CONCLUIDO
        db.commit()

        return {"status": horario.status, "execution_time": horario.execution_time_seconds}

    except Exception as e:
        db.rollback()
        # Tratamento de exceções inesperadas
        horario = db.query(Horario).filter(Horario.id == horario_id).first()
        if horario:
            horario.status = HorarioStatus.FAILED
            horario.current_step = HorarioStep.ERRO
            horario.error_message = f"Exceção interna do Worker: {str(e)}"
            horario.solver_log = (horario.solver_log or "") + f"\n\n--- EXCEÇÃO DO WORKER ---\n{str(e)}"
            horario.finished_at = datetime.now(timezone.utc)
            db.commit()
        raise e
    finally:
        db.close()
