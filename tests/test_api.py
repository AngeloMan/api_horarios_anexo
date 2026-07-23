from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base, get_db
from app.models import Horario, HorarioStatus

# Banco de dados SQLite em memória para os testes da API
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

BRAZIL_FET_PATH = Path(__file__).parent.parent / "Brazil.fet"
SAMPLE_FET = """<?xml version="1.0" encoding="UTF-8"?><fet version="7.8.5"><Institution_Name>Teste</Institution_Name></fet>"""


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"


def test_create_horario_json():
    payload = {
        "nome": "Grade Teste API",
        "fet_data": SAMPLE_FET,
        "timeout_seconds": 30
    }
    response = client.post("/api/v1/horarios", json=payload)
    assert response.status_code == 202
    data = response.json()
    assert "id" in data
    assert data["nome"] == "Grade Teste API"
    assert data["status"] == HorarioStatus.PENDING
    assert data["current_step"] == "ENFILEIRADO"


def test_list_horarios_with_pagination_and_filter():
    # Inserir alguns registros de teste diretamente no banco
    db = TestingSessionLocal()
    h1 = Horario(nome="Job 1", fet_data=SAMPLE_FET, status=HorarioStatus.SUCCESS)
    h2 = Horario(nome="Job 2", fet_data=SAMPLE_FET, status=HorarioStatus.PENDING)
    h3 = Horario(nome="Job 3", fet_data=SAMPLE_FET, status=HorarioStatus.CANCELLED)
    db.add_all([h1, h2, h3])
    db.commit()

    # Listagem geral
    res = client.get("/api/v1/horarios?page=1&limit=2")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2

    # Filtro por status
    res_filter = client.get("/api/v1/horarios?status=SUCCESS")
    assert res_filter.status_code == 200
    data_filter = res_filter.json()
    assert data_filter["total"] == 1
    assert data_filter["items"][0]["status"] == HorarioStatus.SUCCESS


def test_cancel_horario():
    # Criar um job PENDING
    payload = {"nome": "Job para Cancelar", "fet_data": SAMPLE_FET}
    res_create = client.post("/api/v1/horarios", json=payload)
    job_id = res_create.json()["id"]

    # Cancelar job
    res_cancel = client.post(f"/api/v1/horarios/{job_id}/cancel")
    assert res_cancel.status_code == 200
    data_cancel = res_cancel.json()
    assert data_cancel["status"] == HorarioStatus.CANCELLED
    assert data_cancel["current_step"] == "CANCELADO"


def test_download_endpoint_not_found():
    payload = {"nome": "Job sem XML", "fet_data": SAMPLE_FET}
    res_create = client.post("/api/v1/horarios", json=payload)
    job_id = res_create.json()["id"]

    # Tentar baixar sem ter o XML gravado deve retornar 404
    res_dl = client.get(f"/api/v1/horarios/{job_id}/download?format=xml")
    assert res_dl.status_code == 404


def test_download_endpoint_success():
    db = TestingSessionLocal()
    h = Horario(
        nome="Job Concluído", 
        fet_data=SAMPLE_FET, 
        status=HorarioStatus.SUCCESS,
        activities_xml="<activities><Activity><Id>1</Id></Activity></activities>",
        output_fet="<fet_out></fet_out>"
    )
    db.add(h)
    db.commit()
    db.refresh(h)

    # Download XML
    res_xml = client.get(f"/api/v1/horarios/{h.id}/download?format=xml")
    assert res_xml.status_code == 200
    assert res_xml.headers["content-type"] == "application/xml"
    assert "<activities>" in res_xml.text

    # Download FET
    res_fet = client.get(f"/api/v1/horarios/{h.id}/download?format=fet")
    assert res_fet.status_code == 200
    assert res_fet.headers["content-type"] == "application/xml"
    assert "<fet_out>" in res_fet.text
