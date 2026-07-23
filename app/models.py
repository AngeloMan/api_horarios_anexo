import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Float, DateTime, JSON, Index
from app.database import Base


class HorarioStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    IMPOSSIBLE = "IMPOSSIBLE"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class HorarioStep:
    ENFILEIRADO = "ENFILEIRADO"
    PREPARANDO = "PREPARANDO"
    EXECUTANDO_FET = "EXECUTANDO_FET"
    PROCESSANDO_SAIDA = "PROCESSANDO_SAIDA"
    SALVANDO_RESULTADOS = "SALVANDO_RESULTADOS"
    CONCLUIDO = "CONCLUIDO"
    CANCELADO = "CANCELADO"
    ERRO = "ERRO"


class Horario(Base):
    __tablename__ = "horarios"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    nome = Column(String(255), nullable=True)
    fet_data = Column(Text, nullable=False)
    
    status = Column(String(50), nullable=False, default=HorarioStatus.PENDING, index=True)
    current_step = Column(String(100), nullable=False, default=HorarioStep.ENFILEIRADO)
    
    activities_xml = Column(Text, nullable=True)
    output_fet = Column(Text, nullable=True)
    soft_conflicts = Column(JSON, nullable=True)
    solver_log = Column(Text, nullable=True)
    solver_version = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True, index=True)
    execution_time_seconds = Column(Float, nullable=True)
    
    created_at = Column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )
    updated_at = Column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    __table_args__ = (
        Index("idx_horarios_status", "status"),
        Index("idx_horarios_created_at", "created_at"),
        Index("idx_horarios_finished_at", "finished_at"),
    )
