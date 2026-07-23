import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from app.schemas import AllocationItem


def parse_fet_metadata(fet_xml: str) -> Dict[str, Any]:
    """Extrai atividades, professores, turmas e disciplinas do XML .fet."""
    root = ET.fromstring(fet_xml)
    
    activities = {}
    act_list = root.find("Activities_List")
    if act_list is not None:
        for act in act_list.findall("Activity"):
            act_id = act.findtext("Id")
            if not act_id:
                continue
            teachers = [t.text.strip() for t in act.findall("Teacher") if t.text]
            students = [s.text.strip() for s in act.findall("Students") if s.text]
            subject = (act.findtext("Subject") or "").strip()
            duration = int(act.findtext("Duration") or "1")
            activities[act_id] = {
                "teachers": teachers,
                "students": students,
                "subject": subject,
                "duration": duration,
            }
    return activities


def parse_allocations(fet_xml: str, activities_xml: Optional[str]) -> List[AllocationItem]:
    """Combina os metadados do .fet com as alocações do activities.xml."""
    act_metadata = parse_fet_metadata(fet_xml)
    allocations: List[AllocationItem] = []

    if not activities_xml:
        # Se não houver activities_xml gerado ainda, retorna apenas as atividades não alocadas
        for act_id, meta in act_metadata.items():
            allocations.append(AllocationItem(
                id=act_id,
                day=None,
                hour=None,
                room=None,
                teachers=meta["teachers"],
                students=meta["students"],
                subject=meta["subject"],
                duration=meta["duration"]
            ))
        return allocations

    root = ET.fromstring(activities_xml)
    for act in root.findall("Activity"):
        act_id = act.findtext("Id")
        day = act.findtext("Day")
        hour = act.findtext("Hour")
        room = act.findtext("Room") or None

        meta = act_metadata.get(act_id, {
            "teachers": [], "students": [], "subject": None, "duration": 1
        })

        allocations.append(AllocationItem(
            id=act_id,
            day=day,
            hour=hour,
            room=room,
            teachers=meta["teachers"],
            students=meta["students"],
            subject=meta["subject"],
            duration=meta["duration"]
        ))

    return allocations


def render_html_timetable(horario_nome: str, allocations: List[AllocationItem]) -> str:
    """Gera visualização HTML autocontida da grade horária."""
    rows_html = ""
    for alloc in allocations:
        teachers_str = ", ".join(alloc.teachers) or "-"
        students_str = ", ".join(alloc.students) or "-"
        rows_html += f"""
        <tr>
            <td>{alloc.id}</td>
            <td><strong>{alloc.subject or '-'}</strong></td>
            <td>{teachers_str}</td>
            <td>{students_str}</td>
            <td><span class="badge day">{alloc.day or 'Não alocado'}</span></td>
            <td><span class="badge hour">{alloc.hour or '-'}</span></td>
            <td>{alloc.room or '-'}</td>
        </tr>
        """

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Grade de Horários — {horario_nome or 'FET'}</title>
    <style>
        :root {{
            --bg: #0f172a;
            --card-bg: #1e293b;
            --text: #f8fafc;
            --accent: #38bdf8;
            --border: #334155;
        }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 2rem;
        }}
        h1 {{
            color: var(--accent);
            margin-bottom: 0.5rem;
        }}
        .table-container {{
            overflow-x: auto;
            background: var(--card-bg);
            border-radius: 8px;
            border: 1px solid var(--border);
            margin-top: 1rem;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}
        th, td {{
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
        }}
        th {{
            background-color: rgba(56, 189, 248, 0.1);
            color: var(--accent);
        }}
        tr:hover {{
            background-color: rgba(255, 255, 255, 0.03);
        }}
        .badge {{
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.85rem;
            font-weight: 600;
        }}
        .badge.day {{ background: #0284c7; color: #fff; }}
        .badge.hour {{ background: #475569; color: #fff; }}
    </style>
</head>
<body>
    <h1>Grade de Horários: {horario_nome or 'FET Job'}</h1>
    <p>Total de atividades: {len(allocations)}</p>

    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Disciplina</th>
                    <th>Professor(es)</th>
                    <th>Turma(s)</th>
                    <th>Dia</th>
                    <th>Hora</th>
                    <th>Sala</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </div>
</body>
</html>
"""
