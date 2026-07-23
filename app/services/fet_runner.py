import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Optional


def get_fet_version(fet_cl_path: str) -> str:
    """Obtém a versão do binário fet-cl instalado."""
    try:
        proc = subprocess.run([fet_cl_path, "--version"], capture_output=True, text=True, timeout=5)
        output = (proc.stdout + proc.stderr).strip()
        if output:
            return output.splitlines()[0]
    except Exception:
        pass
    return "FET 7.8.5"


def run_fet_pipeline(
    fet_data: str, 
    timeout_seconds: int = 60, 
    fet_cl_path: str = "fet-cl"
) -> Dict[str, Any]:
    """
    Executa o fet-cl dentro de um TemporaryDirectory isolado.
    Coleta activities.xml, data_and_timetable.fet, soft_conflicts.txt e result.txt.
    """
    solver_version = get_fet_version(fet_cl_path)
    t0 = time.time()

    with tempfile.TemporaryDirectory(prefix="fet_job_") as tmp_dir:
        job_dir = Path(tmp_dir)
        input_fet_path = job_dir / "input.fet"
        input_fet_path.write_text(fet_data, encoding="utf-8")
        
        output_dir = job_dir / "out"
        output_dir.mkdir(exist_ok=True)

        cmd = [
            fet_cl_path,
            f"--inputfile={input_fet_path}",
            f"--outputdir={output_dir}",
            f"--timelimitseconds={timeout_seconds}",
            "--writetimetablesxml=true",
            "--writetimetablesdayshorizontal=false",
            "--writetimetablesdaysvertical=false",
            "--writetimetablestimehorizontal=false",
            "--writetimetablestimevertical=false",
            "--verbose=true",
        ]

        status = "FAILED"
        error_message = None
        stdout_log = ""
        stderr_log = ""

        try:
            # Timeout duplo: limite interno do FET + timeout externo no subprocess.run
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds + 15
            )
            stdout_log = proc.stdout
            stderr_log = proc.stderr
            elapsed = time.time() - t0

            if proc.returncode != 0 and "Generation successful" not in stdout_log:
                status = "FAILED"
                error_message = f"fet-cl retornou código de saída {proc.returncode}"
        except subprocess.TimeoutExpired:
            elapsed = time.time() - t0
            status = "TIMEOUT"
            error_message = f"Processo fet-cl excedeu o timeout externo de {timeout_seconds + 15}s"
            stdout_log = "TIMEOUT EXPIRED"
        except Exception as e:
            elapsed = time.time() - t0
            status = "FAILED"
            error_message = f"Erro ao executar subprocesso fet-cl: {str(e)}"

        # Leitura e Coleta de Artefatos no output_dir
        base_name = input_fet_path.stem  # "input"
        
        # 1. Result.txt e Logs
        result_txt_path = output_dir / "logs" / "result.txt"
        result_txt_content = ""
        if result_txt_path.exists():
            result_txt_content = result_txt_path.read_text(encoding="utf-8", errors="ignore")

        full_solver_log = (
            f"--- RESULT.TXT ---\n{result_txt_content}\n\n"
            f"--- STDOUT ---\n{stdout_log}\n\n"
            f"--- STDERR ---\n{stderr_log}"
        )

        # Determinar status com base no result.txt se não houver erro fatal prévio
        if status != "TIMEOUT":
            if "Generation successful" in result_txt_content or "Generation successful" in stdout_log:
                status = "SUCCESS"
            elif "impossible" in result_txt_content.lower() or "impossible" in stdout_log.lower():
                status = "IMPOSSIBLE"
            elif status != "SUCCESS" and not error_message:
                status = "FAILED"
                error_message = "Execução do FET concluída sem atingir 'Generation successful'"

        # 2. Activities XML
        activities_xml_content: Optional[str] = None
        act_matches = list(output_dir.rglob("*_activities.xml"))
        if act_matches:
            activities_xml_content = act_matches[0].read_text(encoding="utf-8-sig", errors="ignore")

        # 3. Data and Timetable FET
        output_fet_content: Optional[str] = None
        fet_matches = list(output_dir.rglob("*_data_and_timetable.fet"))
        if fet_matches:
            output_fet_content = fet_matches[0].read_text(encoding="utf-8-sig", errors="ignore")

        # 4. Soft Conflicts
        soft_conflicts: List[str] = []
        sc_matches = list(output_dir.rglob("*_soft_conflicts.txt"))
        if sc_matches:
            sc_raw = sc_matches[0].read_text(encoding="utf-8-sig", errors="ignore")
            ignore_prefixes = (
                "Soft conflicts", "Generated with", "Number of", "Total", "Soft conflicts list", "End of file"
            )
            soft_conflicts = [
                line.strip() for line in sc_raw.splitlines()
                if line.strip() and not line.strip().startswith(ignore_prefixes)
            ]

        return {
            "status": status,
            "activities_xml": activities_xml_content,
            "output_fet": output_fet_content,
            "soft_conflicts": soft_conflicts,
            "solver_log": full_solver_log,
            "solver_version": solver_version,
            "error_message": error_message,
            "execution_time_seconds": round(elapsed, 2)
        }
