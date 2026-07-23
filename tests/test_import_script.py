from pathlib import Path
from unittest.mock import Namespace
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.models import Horario, HorarioStatus
from scripts.import_horario import import_horario

BRAZIL_FET_PATH = Path(__file__).parent.parent / "Brazil.fet"


def test_import_horario_script(monkeypatch):
    # Criar um banco SQLite em memória temporário para testar o script
    from app import database
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    
    Base.metadata.create_all(bind=engine)

    args = Namespace(
        input_fet=BRAZIL_FET_PATH,
        activities_xml=None,
        timetable_fet=None,
        soft_conflicts=None,
        nome="Teste Import CLI",
        status=HorarioStatus.SUCCESS
    )

    imported_id = import_horario(args)
    assert isinstance(imported_id, str)

    db = TestingSessionLocal()
    horario = db.query(Horario).filter(Horario.id == imported_id).first()
    assert horario is not None
    assert horario.nome == "Teste Import CLI"
    assert horario.status == HorarioStatus.SUCCESS
    assert "fet" in horario.fet_data.lower()
    db.close()
