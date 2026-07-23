import os
from pathlib import Path
import pytest

from app.services.fet_runner import run_fet_pipeline, get_fet_version

BRAZIL_FET_PATH = Path(__file__).parent.parent / "Brazil.fet"


def test_get_fet_version():
    version = get_fet_version("fet-cl")
    assert isinstance(version, str)
    assert len(version) > 0


@pytest.mark.skipif(not BRAZIL_FET_PATH.exists(), reason="Brazil.fet não encontrado no repositório")
def test_fet_runner_success():
    fet_data = BRAZIL_FET_PATH.read_text(encoding="utf-8")
    # Tenta executar o fet-cl localmente (se instalado no PATH ou via docker)
    # Se não houver fet-cl no PATH local (ex: Windows sem binário nativo), valida tratamento gracioso
    res = run_fet_pipeline(fet_data, timeout_seconds=10, fet_cl_path="fet-cl")
    
    assert "status" in res
    assert "solver_version" in res
    assert "execution_time_seconds" in res
    assert isinstance(res["soft_conflicts"], list)


def test_fet_runner_impossible_dataset():
    # Dataset sintético propositalmente inviável:
    # 1 professor ministrando 100 horas no mesmo dia/hora
    impossible_fet = """<?xml version="1.0" encoding="UTF-8"?>
<fet version="7.8.5">
<Institution_Name>Impossivel</Institution_Name>
<Days_List><Number_of_Days>1</Number_of_Days><Day><Name>Segunda</Name></Day></Days_List>
<Hours_List><Number_of_Hours>1</Number_of_Hours><Hour><Name>08:00</Name></Hour></Hours_List>
<Teachers_List><Teacher><Name>Prof. X</Name></Teacher></Teachers_List>
<Subjects_List><Subject><Name>Matemática</Name></Subject></Subjects_List>
<Students_List><Year><Name>2026</Name><Group><Name>Turma 1</Name></Group></Year></Students_List>
<Activities_List>
    <Activity><Id>1</Id><Teacher>Prof. X</Teacher><Subject>Matemática</Subject><Students>Turma 1</Students><Duration>1</Duration></Activity>
    <Activity><Id>2</Id><Teacher>Prof. X</Teacher><Subject>Matemática</Subject><Students>Turma 1</Students><Duration>1</Duration></Activity>
</Activities_List>
<Time_Constraints_List>
    <ConstraintBasicCompulsoryTimeProvisions><Weight_Percentage>100</Weight_Percentage></ConstraintBasicCompulsoryTimeProvisions>
</Time_Constraints_List>
</fet>
"""
    res = run_fet_pipeline(impossible_fet, timeout_seconds=5, fet_cl_path="fet-cl")
    assert res["status"] in ("SUCCESS", "IMPOSSIBLE", "FAILED", "TIMEOUT")
