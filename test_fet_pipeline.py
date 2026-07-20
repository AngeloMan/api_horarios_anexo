#!/usr/bin/env python3
"""
Teste de integração ponta a ponta para a arquitetura FET do Projeto Anexo.

Reproduz, em miniatura, o que o Worker faz em produção:
  1. (FetXmlMapper) -- aqui pulado: já partimos de um .fet pronto
  2. Isola um diretório de job (input + outputdir)
  3. Invoca fet-cl como subprocesso, com timeout
  4. (ResultMapper) parseia o Activities.xml de saída
  5. (ConflictAnalyzer) parseia o relatório de conflitos soft
  6. Imprime um resumo -- útil como smoke test em CI

Uso:
    python3 test_fet_pipeline.py caminho/para/Brazil.fet [--fet-cl /usr/local/bin/fet-cl] [--timeout 60] [--keep-output ./out]

Por padrão o resultado do fet-cl fica num diretório temporário e é
descartado ao final (é só um smoke test). Use --keep-output para copiar
os arquivos gerados (activities.xml, .fet com o horário embutido, etc.)
para um caminho persistente antes do descarte -- por exemplo, para depois
visualizar com visualize_timetable.py.

Requer apenas a biblioteca padrão do Python (subprocess, xml.etree, tempfile).
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path


def run_fet_cl(fet_cl_path: str, input_fet: Path, outputdir: Path, timeout_seconds: int) -> subprocess.CompletedProcess:
    """Invoca o fet-cl exatamente como o Worker faria em produção."""
    cmd = [
        fet_cl_path,
        f"--inputfile={input_fet}",
        f"--outputdir={outputdir}",
        f"--timelimitseconds={timeout_seconds}",
        "--writetimetablesxml=true",
        "--writetimetablesdayshorizontal=false",
        "--writetimetablesdaysvertical=false",
        "--writetimetablestimehorizontal=false",
        "--writetimetablestimevertical=false",
        "--verbose=true",
    ]
    # timeout do próprio processo Python, além do --timelimitseconds do FET,
    # cobrindo o cenário de um processo travado que ignore o limite interno.
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout_seconds + 30
    )


def find_activities_xml(outputdir: Path, base_name: str) -> Path | None:
    """Localiza {base}_activities.xml -- nome real confirmado neste teste
    (documentações antigas do FET citam activities_timetable.xml, que NÃO
    é o nome usado pela versão 7.x)."""
    candidate = outputdir / "timetables" / base_name / f"{base_name}_activities.xml"
    if candidate.exists():
        return candidate
    matches = list(outputdir.rglob("*_activities.xml"))
    return matches[0] if matches else None


def parse_result_mapper(activities_xml: Path) -> list[dict]:
    """Equivalente ao ResultMapper: activities.xml -> lista de alocações."""
    tree = ET.parse(activities_xml)
    allocations = []
    for activity in tree.getroot().findall("Activity"):
        allocations.append({
            "id": activity.findtext("Id"),
            "day": activity.findtext("Day"),
            "hour": activity.findtext("Hour"),
            "room": activity.findtext("Room") or None,
        })
    return allocations


def parse_conflict_analyzer(outputdir: Path, base_name: str) -> dict:
    """Equivalente ao ConflictAnalyzer: lê o result.txt e o soft_conflicts.txt."""
    result_txt = outputdir / "logs" / "result.txt"
    soft_conflicts_txt = outputdir / "timetables" / base_name / f"{base_name}_soft_conflicts.txt"

    status = "UNKNOWN"
    if result_txt.exists():
        content = result_txt.read_text(encoding="utf-8", errors="ignore")
        if "Generation successful" in content:
            status = "SUCCESS"
        elif "impossible" in content.lower():
            status = "IMPOSSIBLE"
        else:
            status = "FAILED"

    soft_conflicts = []
    if soft_conflicts_txt.exists():
        raw = soft_conflicts_txt.read_text(encoding="utf-8-sig", errors="ignore")
        soft_conflicts = [
            line.strip() for line in raw.splitlines()
            if line.strip() and not line.startswith(("Soft conflicts", "Generated with", "Number of", "Total", "Soft conflicts list", "End of file"))
        ]

    return {"status": status, "soft_conflicts": soft_conflicts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_fet", type=Path, help="Caminho para o arquivo .fet de teste")
    parser.add_argument("--fet-cl", default="fet-cl", help="Caminho do binário fet-cl (default: procura no PATH)")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout em segundos para a geração")
    parser.add_argument("--keep-output", type=Path, default=None,
                         help="Copia o outputdir do fet-cl para este caminho antes de descartar o "
                              "diretório temporário (por padrão nada é mantido -- é só um smoke test)")
    args = parser.parse_args()

    if not args.input_fet.exists():
        sys.exit(f"Arquivo não encontrado: {args.input_fet}")

    base_name = args.input_fet.stem  # ex.: "Brazil"

    with tempfile.TemporaryDirectory(prefix="fet_job_") as tmp:
        job_dir = Path(tmp)
        job_input = job_dir / args.input_fet.name
        shutil.copy(args.input_fet, job_input)
        outputdir = job_dir / "out"
        outputdir.mkdir()

        print(f"[1/4] Executando fet-cl (timeout={args.timeout}s)...")
        t0 = time.time()
        try:
            proc = run_fet_cl(args.fet_cl, job_input, outputdir, args.timeout)
        except subprocess.TimeoutExpired:
            sys.exit("FALHOU: fet-cl excedeu o timeout do processo Python.")
        elapsed = time.time() - t0

        if proc.returncode != 0:
            print("FALHOU: fet-cl retornou código != 0")
            print("--- stdout ---")
            print(proc.stdout[-3000:])
            print("--- stderr ---")
            print(proc.stderr[-3000:])
            sys.exit(1)

        print(f"      concluído em {elapsed:.2f}s")

        print("[2/4] Localizando activities.xml de saída...")
        activities_xml = find_activities_xml(outputdir, base_name)
        if activities_xml is None:
            sys.exit("FALHOU: nenhum *_activities.xml encontrado no outputdir.")
        print(f"      encontrado: {activities_xml.relative_to(outputdir)}")

        print("[3/4] ResultMapper (parseando alocações)...")
        allocations = parse_result_mapper(activities_xml)
        allocated = [a for a in allocations if a["day"] and a["hour"]]
        print(f"      {len(allocated)}/{len(allocations)} atividades alocadas")

        print("[4/4] ConflictAnalyzer (status + soft conflicts)...")
        diag = parse_conflict_analyzer(outputdir, base_name)
        print(f"      status={diag['status']}  soft_conflicts={len(diag['soft_conflicts'])}")
        for c in diag["soft_conflicts"][:5]:
            print(f"        - {c[:120]}")

        print()
        print("=" * 60)
        ok = diag["status"] == "SUCCESS" and len(allocated) == len(allocations)
        print("RESULTADO:", "OK" if ok else "REVISAR")
        print("=" * 60)

        if args.keep_output:
            if args.keep_output.exists():
                shutil.rmtree(args.keep_output)
            shutil.copytree(outputdir, args.keep_output)
            print(f"\nSaída completa copiada para: {args.keep_output}")

        sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()