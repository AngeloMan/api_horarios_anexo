#!/usr/bin/env python3
"""
Script CLI para importar arquivos .fet e artefatos de saída (activities.xml, data_and_timetable.fet)
diretamente para o banco de dados PostgreSQL do projeto API de Horários FET.

Uso:
    python scripts/import_horario.py --input-fet Brazil.fet [--activities-xml out/Brazil_activities.xml] [--nome "Grade Brazil"]
"""
import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Garantir que a raiz do projeto esteja no sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from app.database import SessionLocal, Base, engine
from app.models import Horario, HorarioStatus, HorarioStep


def parse_args():
    parser = argparse.ArgumentParser(
        description="Importa um arquivo .fet e artefatos de saída diretamente para a tabela 'horarios' do PostgreSQL."
    )
    parser.add_argument(
        "--input-fet",
        type=Path,
        required=True,
        help="Caminho para o arquivo .fet de entrada (ex: Brazil.fet)"
    )
    parser.add_argument(
        "--activities-xml",
        type=Path,
        default=None,
        help="Caminho opcional para o arquivo {base}_activities.xml"
    )
    parser.add_argument(
        "--timetable-fet",
        type=Path,
        default=None,
        help="Caminho opcional para o arquivo {base}_data_and_timetable.fet"
    )
    parser.add_argument(
        "--soft-conflicts",
        type=Path,
        default=None,
        help="Caminho opcional para o arquivo {base}_soft_conflicts.txt"
    )
    parser.add_argument(
        "--nome",
        type=str,
        default=None,
        help="Nome descritivo opcional da grade (default: nome do arquivo .fet)"
    )
    parser.add_argument(
        "--status",
        type=str,
        default=HorarioStatus.SUCCESS,
        choices=[
            HorarioStatus.PENDING,
            HorarioStatus.RUNNING,
            HorarioStatus.SUCCESS,
            HorarioStatus.IMPOSSIBLE,
            HorarioStatus.FAILED,
            HorarioStatus.TIMEOUT,
            HorarioStatus.CANCELLED,
        ],
        help="Estado a ser gravado no banco de dados (default: SUCCESS)"
    )
    return parser.parse_args()


def import_horario(args) -> str:
    if not args.input_fet.exists():
        sys.exit(f"Erro: Arquivo .fet não encontrado: {args.input_fet}")

    # Ler conteúdo do .fet
    fet_data = args.input_fet.read_text(encoding="utf-8-sig", errors="ignore")

    # Ler activities_xml se fornecido
    activities_xml = None
    if args.activities_xml:
        if not args.activities_xml.exists():
            print(f"Aviso: Arquivo {args.activities_xml} não existe. Ignorando.")
        else:
            activities_xml = args.activities_xml.read_text(encoding="utf-8-sig", errors="ignore")

    # Ler data_and_timetable.fet se fornecido
    output_fet = None
    if args.timetable_fet:
        if not args.timetable_fet.exists():
            print(f"Aviso: Arquivo {args.timetable_fet} não existe. Ignorando.")
        else:
            output_fet = args.timetable_fet.read_text(encoding="utf-8-sig", errors="ignore")

    # Ler soft_conflicts.txt se fornecido
    soft_conflicts = []
    if args.soft_conflicts and args.soft_conflicts.exists():
        raw_sc = args.soft_conflicts.read_text(encoding="utf-8-sig", errors="ignore")
        ignore_prefixes = (
            "Soft conflicts", "Generated with", "Number of", "Total", "Soft conflicts list", "End of file"
        )
        soft_conflicts = [
            line.strip() for line in raw_sc.splitlines()
            if line.strip() and not line.strip().startswith(ignore_prefixes)
        ]

    # Determinar nome
    nome_job = args.nome or args.input_fet.stem

    # Criar tabelas se não existirem
    Base.metadata.create_all(bind=engine)

    # Iniciar sessão
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        step = HorarioStep.CONCLUIDO if args.status == HorarioStatus.SUCCESS else HorarioStep.ENFILEIRADO

        horario = Horario(
            id=str(uuid.uuid4()),
            nome=nome_job,
            fet_data=fet_data,
            status=args.status.upper(),
            current_step=step,
            activities_xml=activities_xml,
            output_fet=output_fet,
            soft_conflicts=soft_conflicts if soft_conflicts else None,
            solver_version="Importado via CLI",
            solver_log="Registro importado manualmente via script CLI import_horario.py",
            started_at=now if args.status != HorarioStatus.PENDING else None,
            finished_at=now if args.status != HorarioStatus.PENDING else None,
            created_at=now,
            updated_at=now,
        )

        db.add(horario)
        db.commit()
        db.refresh(horario)

        print("\n" + "=" * 60)
        print(f"  HORÁRIO IMPORTADO COM SUCESSO NO BANCO DE DADOS!")
        print("=" * 60)
        print(f"  ID do Registro: {horario.id}")
        print(f"  Nome:          {horario.nome}")
        print(f"  Status:        {horario.status}")
        print(f"  Activities XML:{' SIM' if horario.activities_xml else ' NÃO'}")
        print(f"  Output FET:    {' SIM' if horario.output_fet else ' NÃO'}")
        print("-" * 60)
        print("  Endpoints de Acesso:")
        print(f"  - Detalhes (JSON):   http://localhost:8000/api/v1/horarios/{horario.id}")
        print(f"  - Grade HTML:        http://localhost:8000/api/v1/horarios/{horario.id}/view")
        print(f"  - Dados de Entrada:  http://localhost:8000/api/v1/horarios/{horario.id}/viewdata")
        print(f"  - Alocações (JSON):  http://localhost:8000/api/v1/horarios/{horario.id}/timetable")
        if horario.activities_xml:
            print(f"  - Download XML:      http://localhost:8000/api/v1/horarios/{horario.id}/download?format=xml")
        print("=" * 60 + "\n")

        return horario.id

    except Exception as e:
        db.rollback()
        print(f"Erro ao importar horário para o banco: {str(e)}")
        sys.exit(1)
    finally:
        db.close()


def main():
    args = parse_args()
    import_horario(args)


if __name__ == "__main__":
    main()
