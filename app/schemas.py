from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field


class HorarioCreate(BaseModel):
    nome: Optional[str] = Field(None, description="Nome identificador da grade de horário")
    fet_data: str = Field(..., description="Conteúdo em texto/XML do arquivo .fet de entrada")
    timeout_seconds: Optional[int] = Field(60, description="Timeout limite para execução do FET em segundos")


class HorarioResponse(BaseModel):
    id: str
    nome: Optional[str] = None
    status: str
    current_step: str
    has_activities_xml: bool
    has_output_fet: bool
    soft_conflicts_count: int = 0
    soft_conflicts: Optional[List[str]] = None
    solver_version: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    execution_time_seconds: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class HorarioListResponse(BaseModel):
    items: List[HorarioResponse]
    total: int
    page: int
    limit: int
    pages: int


class AllocationItem(BaseModel):
    id: str
    day: Optional[str] = None
    hour: Optional[str] = None
    room: Optional[str] = None
    teachers: List[str] = []
    students: List[str] = []
    subject: Optional[str] = None
    duration: int = 1


class TimetableResponse(BaseModel):
    horario_id: str
    status: str
    allocated_count: int
    total_count: int
    allocations: List[AllocationItem]
