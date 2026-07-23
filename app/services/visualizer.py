import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Dict, Any, List, Optional
from app.schemas import AllocationItem


# ---------------------------------------------------------------------------
# 1. PARSER E VISUALIZADOR DA GRADE DE HORÁRIOS GERADA (TIMETABLE)
# ---------------------------------------------------------------------------

def parse_fet_source_from_str(fet_xml: str) -> dict:
    """Extrai metadados de um .fet: instituição, dias, horas, atividades e indisponibilidade de professores."""
    root = ET.fromstring(fet_xml)

    institution = (root.findtext("Institution_Name") or "").strip() or "Instituição"

    days = []
    days_list = root.find("Days_List")
    if days_list is not None:
        for day in days_list.findall("Day"):
            code = day.findtext("Name") or day.findtext("n") or ""
            long_name = day.findtext("Long_Name") or ""
            days.append({"code": code, "label": long_name or code})

    hours = []
    hours_list = root.find("Hours_List")
    if hours_list is not None:
        for hour in hours_list.findall("Hour"):
            code = hour.findtext("Name") or hour.findtext("n") or ""
            long_name = hour.findtext("Long_Name") or ""
            hours.append({"code": code, "label": long_name or code})

    activities = {}
    activities_list = root.find("Activities_List")
    if activities_list is not None:
        for act in activities_list.findall("Activity"):
            act_id = act.findtext("Id")
            if act_id is None:
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

    # Indisponibilidade de professores: ConstraintTeacherNotAvailableTimes
    unavailability = {}
    tc_list = root.find("Time_Constraints_List")
    if tc_list is not None:
        for c in tc_list.findall("ConstraintTeacherNotAvailableTimes"):
            active = (c.findtext("Active") or "true").strip().lower()
            if active != "true":
                continue
            teacher = (c.findtext("Teacher") or "").strip()
            if not teacher:
                continue
            weight = c.findtext("Weight_Percentage") or "100"
            try:
                weight = float(weight)
            except ValueError:
                weight = 100.0
            slots = unavailability.setdefault(teacher, {})
            for nat in c.findall("Not_Available_Time"):
                day = (nat.findtext("Day") or "").strip()
                hour = (nat.findtext("Hour") or "").strip()
                if day and hour:
                    slots[(day, hour)] = max(weight, slots.get((day, hour), 0))

    return {
        "institution": institution,
        "days": days,
        "hours": hours,
        "activities": activities,
        "unavailability": unavailability,
    }


def parse_placements_from_str(xml_str: Optional[str]) -> dict:
    """Extrai as alocações de um activities.xml ou data_and_timetable.fet."""
    if not xml_str:
        return {}

    root = ET.fromstring(xml_str)
    container = root if root.tag == "Activities_Timetable" else root.find(".//Activities_Timetable")
    if container is None:
        return {}

    placements = {}
    for act in container.findall("Activity"):
        act_id = act.findtext("Id")
        if act_id is None:
            continue
        placements[act_id] = {
            "day": (act.findtext("Day") or "").strip(),
            "hour": (act.findtext("Hour") or "").strip(),
            "room": (act.findtext("Room") or "").strip(),
        }
    return placements


def build_dataset(source: dict, placements: dict) -> dict:
    """Junta metadados + alocação em uma estrutura pronta para a UI."""
    day_index = {d["code"]: i for i, d in enumerate(source["days"])}
    hour_index = {h["code"]: i for i, h in enumerate(source["hours"])}

    rows = []
    unallocated = []
    for act_id, meta in source["activities"].items():
        placement = placements.get(act_id)
        if not placement or not placement["day"] or not placement["hour"]:
            unallocated.append({"id": act_id, **meta})
            continue
        rows.append({
            "id": act_id,
            "subject": meta["subject"],
            "teachers": meta["teachers"],
            "students": meta["students"],
            "duration": meta["duration"],
            "day": placement["day"],
            "hour": placement["hour"],
            "room": placement["room"],
            "dayIdx": day_index.get(placement["day"], -1),
            "hourIdx": hour_index.get(placement["hour"], -1),
        })

    turmas = sorted({s for r in rows for s in r["students"]})
    professores = sorted({t for r in rows for t in r["teachers"]} | set(source["unavailability"].keys()))
    disciplinas = sorted({r["subject"] for r in rows if r["subject"]})

    unavailability = {}
    for teacher, slots in source["unavailability"].items():
        converted = {}
        for (day, hour), weight in slots.items():
            di = day_index.get(day, -1)
            hi = hour_index.get(hour, -1)
            if di >= 0 and hi >= 0:
                converted[f"{di}_{hi}"] = weight
        if converted:
            unavailability[teacher] = converted

    return {
        "institution": source["institution"],
        "days": source["days"],
        "hours": source["hours"],
        "rows": rows,
        "unallocated": unallocated,
        "turmas": turmas,
        "professores": professores,
        "disciplinas": disciplinas,
        "unavailability": unavailability,
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Grade Horária — __INSTITUTION__</title>
<style>
  :root {
    --ink: #1c2333;
    --ink-soft: #5b6478;
    --paper: #fbfaf7;
    --panel: #ffffff;
    --line: #e4e1d8;
    --accent: #2f5d50;
    --accent-soft: #e7efe9;
    --warn: #a8461f;
    --radius: 10px;
    font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--paper);
    color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
  }
  header {
    padding: 28px 32px 20px;
    border-bottom: 1px solid var(--line);
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
  }
  header h1 {
    font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
    font-weight: 600;
    font-size: 26px;
    margin: 0;
    letter-spacing: 0.2px;
  }
  header .meta {
    font-size: 13px;
    color: var(--ink-soft);
  }
  .controls {
    display: flex;
    gap: 10px;
    align-items: center;
    padding: 18px 32px;
    flex-wrap: wrap;
    border-bottom: 1px solid var(--line);
    background: var(--panel);
    position: sticky;
    top: 0;
    z-index: 5;
  }
  .seg {
    display: inline-flex;
    border: 1px solid var(--line);
    border-radius: 999px;
    overflow: hidden;
  }
  .seg button {
    border: none;
    background: transparent;
    padding: 8px 18px;
    font-size: 13px;
    cursor: pointer;
    color: var(--ink-soft);
    font-family: inherit;
  }
  .seg button.active {
    background: var(--accent);
    color: white;
  }
  select {
    padding: 8px 14px;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: white;
    font-size: 13px;
    color: var(--ink);
    font-family: inherit;
    min-width: 220px;
  }
  .stat {
    font-size: 12px;
    color: var(--ink-soft);
    margin-left: auto;
  }
  main { padding: 24px 32px 60px; }
  .grid-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel); }
  table.grid { border-collapse: collapse; width: 100%; min-width: 640px; }
  table.grid th, table.grid td {
    border: 1px solid var(--line);
    padding: 0;
    text-align: left;
    vertical-align: top;
  }
  table.grid th {
    background: #f4f2ec;
    font-size: 12px;
    font-weight: 600;
    color: var(--ink-soft);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 10px 12px;
  }
  table.grid th.hourcol { width: 92px; }
  table.grid td.hourcell {
    background: #f4f2ec;
    font-size: 12px;
    color: var(--ink-soft);
    padding: 10px 12px;
    white-space: nowrap;
    font-weight: 600;
  }
  .cell-inner {
    min-height: 58px;
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 2px;
  }
  .cell-inner .subj { font-size: 13px; font-weight: 600; line-height: 1.25; }
  .cell-inner .sub { font-size: 11.5px; color: var(--ink-soft); }
  .cell-empty { min-height: 58px; }
  td.unavailable {
    background: repeating-linear-gradient(
      135deg, rgba(168,70,31,0.10), rgba(168,70,31,0.10) 5px,
      transparent 5px, transparent 10px
    );
  }
  td.unavailable .cell-inner {
    justify-content: center;
    align-items: flex-start;
  }
  .avail-label {
    font-size: 11px;
    font-weight: 600;
  }
  .avail-label.un { color: var(--warn); }
  .avail-label.ok { color: #8f9a86; }
  td.available .cell-inner .avail-label { opacity: 0; transition: opacity .1s; }
  td.available:hover .cell-inner .avail-label { opacity: 1; }
  .badge {
    display: inline-block;
    font-size: 10px;
    padding: 1px 7px;
    border-radius: 999px;
    background: rgba(0,0,0,0.06);
    color: var(--ink-soft);
    margin-top: 2px;
    width: fit-content;
  }
  footer.panel {
    margin-top: 28px;
    padding: 16px 20px;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: var(--panel);
    font-size: 13px;
    color: var(--ink-soft);
  }
  footer.panel strong { color: var(--ink); }
  .empty-state {
    padding: 60px 20px;
    text-align: center;
    color: var(--ink-soft);
    font-size: 14px;
  }
  .legend { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
  .legend span.chip {
    display:inline-flex; align-items:center; gap:6px;
    font-size: 11.5px; color: var(--ink-soft);
    padding: 3px 9px; border-radius: 999px; border: 1px solid var(--line);
  }
  .legend .dot { width:9px; height:9px; border-radius:50%; display:inline-block; }
  @media (max-width: 720px) {
    header, .controls, main { padding-left: 16px; padding-right: 16px; }
  }
</style>
</head>
<body>

<header>
  <div>
    <h1>Grade Horária</h1>
    <div class="meta">__INSTITUTION__</div>
  </div>
  <div class="meta" id="summary"></div>
</header>

<div class="controls">
  <div class="seg" id="viewSeg">
    <button data-view="turma" class="active">Por turma</button>
    <button data-view="professor">Por professor</button>
  </div>
  <select id="entitySelect"></select>
  <div class="stat" id="stat"></div>
</div>

<main>
  <div class="grid-wrap">
    <table class="grid" id="gridTable"></table>
  </div>
  <div class="legend" id="legend"></div>
  <footer class="panel" id="unallocatedPanel" style="display:none;"></footer>
</main>

<script>
const DATA = __DATA_JSON__;

const PALETTE = [
  "#2f5d50", "#a8461f", "#3d5a80", "#8a5a44", "#6b5b95",
  "#4f772d", "#c46210", "#3c6e71", "#9a4f50", "#556b2f",
  "#7a5c61", "#2e6f95", "#8c6d1f", "#4d5b6a", "#a15843"
];
function colorFor(subject) {
  let h = 0;
  for (let i = 0; i < subject.length; i++) h = (h * 31 + subject.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

let state = { view: "turma", entity: null };

function populateSelect() {
  const sel = document.getElementById("entitySelect");
  const list = state.view === "turma" ? DATA.turmas : DATA.professores;
  sel.innerHTML = list.map(x => `<option value="${x}">${x}</option>`).join("");
  if (!list.includes(state.entity)) state.entity = list[0] || null;
  sel.value = state.entity || "";
}

function rowsFor(entity) {
  if (state.view === "turma") {
    return DATA.rows.filter(r => r.students.includes(entity));
  }
  return DATA.rows.filter(r => r.teachers.includes(entity));
}

function renderGrid() {
  const table = document.getElementById("gridTable");
  if (!state.entity) {
    table.innerHTML = "";
    document.getElementById("stat").textContent = "";
    return;
  }
  const rows = rowsFor(state.entity);
  const byCell = {};
  rows.forEach(r => { byCell[`${r.dayIdx}_${r.hourIdx}`] = r; });

  let thead = "<thead><tr><th class='hourcol'>Horário</th>" +
    DATA.days.map(d => `<th>${d.label}</th>`).join("") + "</tr></thead>";

  let tbody = "<tbody>";
  DATA.hours.forEach((h, hi) => {
    tbody += `<tr><td class="hourcell">${h.label}</td>`;
    DATA.days.forEach((d, di) => {
      const r = byCell[`${di}_${hi}`];
      if (r) {
        const color = colorFor(r.subject);
        const secondary = state.view === "turma"
          ? (r.teachers.join(", ") || "—")
          : (r.students.join(", ") || "—");
        const room = r.room ? `<span class="badge">${r.room}</span>` : "";
        tbody += `<td style="border-left:3px solid ${color};">
          <div class="cell-inner">
            <div class="subj">${r.subject}</div>
            <div class="sub">${secondary}</div>
            ${room}
          </div>
        </td>`;
      } else if (state.view === "professor") {
        const slots = DATA.unavailability[state.entity] || {};
        const weight = slots[`${di}_${hi}`];
        if (weight !== undefined) {
          const label = weight >= 100
            ? "Indisponível"
            : `Indisponível (${Math.round(weight)}%)`;
          tbody += `<td class="unavailable" title="${label}">
            <div class="cell-inner"><span class="avail-label un">${label}</span></div>
          </td>`;
        } else {
          tbody += `<td class="available" title="Disponível">
            <div class="cell-inner"><span class="avail-label ok">Disponível</span></div>
          </td>`;
        }
      } else {
        tbody += `<td><div class="cell-empty"></div></td>`;
      }
    });
    tbody += "</tr>";
  });
  tbody += "</tbody>";

  table.innerHTML = thead + tbody;

  const subjectsHere = [...new Set(rows.map(r => r.subject))];
  let legendHtml = subjectsHere.map(s =>
    `<span class="chip"><span class="dot" style="background:${colorFor(s)}"></span>${s}</span>`
  ).join("");

  let statText = `${rows.length} aula${rows.length === 1 ? "" : "s"} na semana`;

  if (state.view === "professor") {
    const slots = DATA.unavailability[state.entity] || {};
    const totalSlots = DATA.days.length * DATA.hours.length;
    const unavailableCount = Object.keys(slots).length;
    const freeCount = totalSlots - rows.length - unavailableCount;
    legendHtml += `
      <span class="chip"><span class="dot" style="background:#8f9a86"></span>Disponível (sem aula)</span>
      <span class="chip"><span class="dot" style="background:#a8461f"></span>Indisponível (restrição do professor)</span>
    `;
    const freeLabel = freeCount === 1 ? "horário livre" : "horários livres";
    const unavailLabel = unavailableCount === 1 ? "horário indisponível" : "horários indisponíveis";
    statText += ` · ${freeCount} ${freeLabel} · ${unavailableCount} ${unavailLabel}`;
  }

  document.getElementById("legend").innerHTML = legendHtml;
  document.getElementById("stat").textContent = statText;
}

function renderUnallocated() {
  const panel = document.getElementById("unallocatedPanel");
  if (!DATA.unallocated.length) { panel.style.display = "none"; return; }
  panel.style.display = "block";
  panel.innerHTML = `<strong>${DATA.unallocated.length} atividade(s) não alocada(s)</strong> — ` +
    DATA.unallocated.map(u => `${u.subject} (${(u.teachers||[]).join(", ")} · ${(u.students||[]).join(", ")})`).join("; ");
}

function renderSummary() {
  document.getElementById("summary").textContent =
    `${DATA.rows.length} aulas alocadas · ${DATA.turmas.length} turmas · ${DATA.professores.length} professores · ${DATA.disciplinas.length} disciplinas`;
}

document.getElementById("viewSeg").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-view]");
  if (!btn) return;
  state.view = btn.dataset.view;
  state.entity = null;
  document.querySelectorAll("#viewSeg button").forEach(b => b.classList.toggle("active", b === btn));
  populateSelect();
  renderGrid();
});

document.getElementById("entitySelect").addEventListener("change", (e) => {
  state.entity = e.target.value;
  renderGrid();
});

populateSelect();
renderSummary();
renderUnallocated();
renderGrid();
</script>
</body>
</html>
"""


def parse_allocations(fet_xml: str, activities_xml: Optional[str]) -> List[AllocationItem]:
    """Combina os metadados do .fet com as alocações para retornar lista de AllocationItem."""
    source = parse_fet_source_from_str(fet_xml)
    placements = parse_placements_from_str(activities_xml)
    dataset = build_dataset(source, placements)

    allocations: List[AllocationItem] = []
    for r in dataset["rows"]:
        allocations.append(AllocationItem(
            id=r["id"],
            day=r["day"],
            hour=r["hour"],
            room=r["room"],
            teachers=r["teachers"],
            students=r["students"],
            subject=r["subject"],
            duration=r["duration"]
        ))
    for u in dataset["unallocated"]:
        allocations.append(AllocationItem(
            id=u["id"],
            day=None,
            hour=None,
            room=None,
            teachers=u["teachers"],
            students=u["students"],
            subject=u["subject"],
            duration=u["duration"]
        ))
    return allocations


def render_html_timetable(horario_nome: str, fet_xml: str, activities_xml: Optional[str] = None, output_fet: Optional[str] = None) -> str:
    """Gera visualização HTML interativa da grade horária gerada."""
    source = parse_fet_source_from_str(fet_xml)
    placements = parse_placements_from_str(activities_xml or output_fet)
    dataset = build_dataset(source, placements)
    
    if horario_nome:
        dataset["institution"] = horario_nome

    html = HTML_TEMPLATE.replace("__INSTITUTION__", dataset["institution"])
    html = html.replace("__DATA_JSON__", json.dumps(dataset, ensure_ascii=False))
    return html


# ---------------------------------------------------------------------------
# 2. PARSER E VISUALIZADOR DOS DADOS DE ENTRADA DO .FET (INPUT DATA / VIEWDATA)
# ---------------------------------------------------------------------------

def parse_input_from_str(fet_xml: str) -> dict:
    root = ET.fromstring(fet_xml)
    institution = (root.findtext("Institution_Name") or "").strip() or "Instituição"

    def code_label_list(list_tag, item_tag):
        out = []
        node = root.find(list_tag)
        if node is not None:
            for item in node.findall(item_tag):
                code = item.findtext("Name") or item.findtext("n") or ""
                long_name = item.findtext("Long_Name") or ""
                out.append({"code": code, "label": long_name or code})
        return out

    days = code_label_list("Days_List", "Day")
    hours = code_label_list("Hours_List", "Hour")

    subjects = []
    subj_list = root.find("Subjects_List")
    if subj_list is not None:
        for s in subj_list.findall("Subject"):
            name = (s.findtext("Name") or s.findtext("n") or "").strip()
            if name:
                subjects.append(name)

    teachers_target_hours = {}
    teach_list = root.find("Teachers_List")
    if teach_list is not None:
        for t in teach_list.findall("Teacher"):
            name = (t.findtext("Name") or t.findtext("n") or "").strip()
            target = t.findtext("Target_Number_of_Hours")
            if name:
                try:
                    teachers_target_hours[name] = int(target) if target else 0
                except ValueError:
                    teachers_target_hours[name] = 0

    turma_names = []
    stu_list = root.find("Students_List")
    if stu_list is not None:
        for y in stu_list.findall("Year"):
            name = (y.findtext("Name") or y.findtext("n") or "").strip()
            if name:
                turma_names.append(name)

    groups = {}
    order = []
    activities_list = root.find("Activities_List")
    if activities_list is not None:
        for act in activities_list.findall("Activity"):
            act_id = act.findtext("Id")
            gid_raw = (act.findtext("Activity_Group_Id") or "").strip()
            gid = gid_raw if gid_raw and gid_raw != "0" else f"single_{act_id}"
            teachers = [t.text.strip() for t in act.findall("Teacher") if t.text]
            students = [s.text.strip() for s in act.findall("Students") if s.text]
            subject = (act.findtext("Subject") or "").strip()
            duration = int(act.findtext("Duration") or "1")
            total_duration = act.findtext("Total_Duration")
            total_duration = int(total_duration) if total_duration else duration
            if gid not in groups:
                groups[gid] = {
                    "subject": subject, "teachers": teachers, "students": students,
                    "weekly_hours": total_duration, "parts": 0,
                }
                order.append(gid)
            groups[gid]["parts"] += 1

    unavailability = {}
    max_days_per_week = {}
    min_days_constraints = 0
    max_gaps_per_week = None

    tc_list = root.find("Time_Constraints_List")
    if tc_list is not None:
        for c in tc_list.findall("ConstraintTeacherNotAvailableTimes"):
            if (c.findtext("Active") or "true").strip().lower() != "true":
                continue
            teacher = (c.findtext("Teacher") or "").strip()
            if not teacher:
                continue
            weight = float(c.findtext("Weight_Percentage") or "100")
            slots = unavailability.setdefault(teacher, {})
            for nat in c.findall("Not_Available_Time"):
                day = (nat.findtext("Day") or "").strip()
                hour = (nat.findtext("Hour") or "").strip()
                if day and hour:
                    slots[(day, hour)] = max(weight, slots.get((day, hour), 0))

        for c in tc_list.findall("ConstraintTeacherMaxDaysPerWeek"):
            if (c.findtext("Active") or "true").strip().lower() != "true":
                continue
            teacher = (c.findtext("Teacher") or "").strip()
            max_days = c.findtext("Max_Days_Per_Week")
            if teacher and max_days:
                max_days_per_week[teacher] = int(max_days)

        min_days_constraints = len(tc_list.findall("ConstraintMinDaysBetweenActivities"))

        gaps_node = tc_list.find("ConstraintTeachersMaxGapsPerWeek")
        if gaps_node is not None and (gaps_node.findtext("Active") or "true").strip().lower() == "true":
            max_gaps_per_week = gaps_node.findtext("Max_Gaps")

    rooms = []
    rooms_list = root.find("Rooms_List")
    if rooms_list is not None:
        rooms = [r.findtext("Name") or r.findtext("n") or "" for r in rooms_list.findall("Room")]

    return {
        "institution": institution, "days": days, "hours": hours,
        "subjects": subjects, "teachers_target_hours": teachers_target_hours,
        "turma_names": turma_names, "groups": [groups[g] for g in order],
        "unavailability": unavailability, "max_days_per_week": max_days_per_week,
        "min_days_constraints": min_days_constraints, "max_gaps_per_week": max_gaps_per_week,
        "rooms": rooms,
    }


def build_input_dataset(src: dict) -> dict:
    day_index = {d["code"]: i for i, d in enumerate(src["days"])}
    hour_index = {h["code"]: i for i, h in enumerate(src["hours"])}

    turma_curriculo = defaultdict(list)
    professor_carga = defaultdict(list)

    for g in src["groups"]:
        for turma in g["students"]:
            turma_curriculo[turma].append({
                "subject": g["subject"], "teachers": g["teachers"], "hours": g["weekly_hours"],
            })
        for prof in g["teachers"]:
            professor_carga[prof].append({
                "subject": g["subject"], "turmas": g["students"], "hours": g["weekly_hours"],
            })

    turmas = []
    for name in src["turma_names"]:
        items = sorted(turma_curriculo.get(name, []), key=lambda x: x["subject"])
        turmas.append({
            "name": name, "items": items,
            "totalHours": sum(i["hours"] for i in items),
            "numSubjects": len({i["subject"] for i in items}),
        })

    all_teacher_names = sorted(set(professor_carga.keys()) | set(src["unavailability"].keys()))
    professores = []
    for name in all_teacher_names:
        items = sorted(professor_carga.get(name, []), key=lambda x: x["subject"])
        slots = src["unavailability"].get(name, {})
        converted = {}
        for (day, hour), weight in slots.items():
            di, hi = day_index.get(day, -1), hour_index.get(hour, -1)
            if di >= 0 and hi >= 0:
                converted[f"{di}_{hi}"] = weight
        professores.append({
            "name": name, "items": items,
            "totalHours": sum(i["hours"] for i in items),
            "numTurmas": len({t for i in items for t in i["turmas"]}),
            "maxDaysPerWeek": src["max_days_per_week"].get(name),
            "unavailableCount": len(converted),
            "targetHours": src["teachers_target_hours"].get(name),
        })
        professores[-1]["_slots"] = converted

    unavailability_out = {p["name"]: p.pop("_slots") for p in professores}

    return {
        "institution": src["institution"], "days": src["days"], "hours": src["hours"],
        "turmas": turmas, "professores": professores, "unavailability": unavailability_out,
        "subjects": src["subjects"], "rooms": src["rooms"],
        "minDaysConstraints": src["min_days_constraints"],
        "maxGapsPerWeek": src["max_gaps_per_week"],
        "totals": {
            "turmas": len(turmas), "professores": len(professores),
            "disciplinas": len(src["subjects"]), "grupos": len(src["groups"]),
            "aulasSemana": sum(g["weekly_hours"] for g in src["groups"]),
            "salas": len(src["rooms"]),
        },
    }


INPUT_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dados de Entrada — __INSTITUTION__</title>
<style>
  :root {
    --ink: #1c2333; --ink-soft: #5b6478;
    --paper: #fbfaf7; --panel: #ffffff; --line: #e4e1d8;
    --accent: #2f5d50; --warn: #a8461f; --radius: 10px;
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--paper); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif; }
  header { padding:28px 32px 20px; border-bottom:1px solid var(--line);
    display:flex; align-items:baseline; justify-content:space-between; flex-wrap:wrap; gap:12px; }
  header h1 { font-family:"Iowan Old Style","Palatino Linotype",Georgia,serif;
    font-weight:600; font-size:26px; margin:0; }
  header .meta { font-size:13px; color:var(--ink-soft); }
  .cards { display:flex; gap:10px; flex-wrap:wrap; padding:18px 32px; border-bottom:1px solid var(--line); }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:var(--radius);
    padding:10px 16px; min-width:110px; }
  .card .n { font-size:22px; font-weight:700; color:var(--accent); }
  .card .l { font-size:11px; color:var(--ink-soft); text-transform:uppercase; letter-spacing:.05em; }
  .controls { display:flex; gap:10px; align-items:center; padding:18px 32px; flex-wrap:wrap;
    border-bottom:1px solid var(--line); background:var(--panel); position:sticky; top:0; z-index:5; }
  .seg { display:inline-flex; border:1px solid var(--line); border-radius:999px; overflow:hidden; }
  .seg button { border:none; background:transparent; padding:8px 18px; font-size:13px; cursor:pointer;
    color:var(--ink-soft); font-family:inherit; }
  .seg button.active { background:var(--accent); color:white; }
  select { padding:8px 14px; border-radius:999px; border:1px solid var(--line); background:white;
    font-size:13px; color:var(--ink); font-family:inherit; min-width:220px; }
  main { padding:24px 32px 60px; }
  table.data { border-collapse:collapse; width:100%; background:var(--panel);
    border:1px solid var(--line); border-radius:var(--radius); overflow:hidden; }
  table.data th, table.data td { border-bottom:1px solid var(--line); padding:9px 14px; text-align:left; font-size:13.5px; }
  table.data th { background:#f4f2ec; font-size:11.5px; font-weight:600; color:var(--ink-soft);
    text-transform:uppercase; letter-spacing:.05em; }
  table.data tr:last-child td { border-bottom:none; }
  table.data td.num { text-align:right; font-variant-numeric:tabular-nums; }
  .section-title { font-size:13px; font-weight:600; color:var(--ink-soft); text-transform:uppercase;
    letter-spacing:.05em; margin:22px 0 8px; }
  .grid-wrap { overflow-x:auto; border:1px solid var(--line); border-radius:var(--radius); background:var(--panel); margin-top:8px;}
  table.grid { border-collapse:collapse; width:100%; min-width:560px; }
  table.grid th, table.grid td { border:1px solid var(--line); padding:0; text-align:left; vertical-align:top; }
  table.grid th { background:#f4f2ec; font-size:12px; font-weight:600; color:var(--ink-soft);
    text-transform:uppercase; letter-spacing:.05em; padding:9px 12px; }
  table.grid th.hourcol { width:92px; }
  table.grid td.hourcell { background:#f4f2ec; font-size:12px; color:var(--ink-soft); padding:9px 12px;
    white-space:nowrap; font-weight:600; }
  td.unavailable { background:repeating-linear-gradient(135deg, rgba(168,70,31,0.10), rgba(168,70,31,0.10) 5px, transparent 5px, transparent 10px); }
  .cell-inner { min-height:40px; padding:7px 10px; display:flex; align-items:center; }
  .avail-label { font-size:11px; font-weight:600; }
  .avail-label.un { color:var(--warn); }
  .avail-label.ok { color:#8f9a86; }
  .badge { display:inline-block; font-size:11px; padding:2px 9px; border-radius:999px;
    background:rgba(0,0,0,0.06); color:var(--ink-soft); }
  .badge.warn { background:rgba(168,70,31,0.12); color:var(--warn); }
  .footnote { font-size:12px; color:var(--ink-soft); margin-top:10px; }
  @media (max-width:720px){ header,.controls,main{padding-left:16px;padding-right:16px;} }
</style>
</head>
<body>

<header>
  <div>
    <h1>Dados de Entrada</h1>
    <div class="meta">__INSTITUTION__ — revisão pré-geração</div>
  </div>
</header>

<div class="cards" id="cards"></div>

<div class="controls">
  <div class="seg" id="viewSeg">
    <button data-view="turma" class="active">Por turma</button>
    <button data-view="professor">Por professor</button>
  </div>
  <select id="entitySelect"></select>
</div>

<main id="main"></main>

<script>
const DATA = __DATA_JSON__;
let state = { view: "turma", entity: null };

function renderCards() {
  const t = DATA.totals;
  const items = [
    [t.turmas, "Turmas"], [t.professores, "Professores"], [t.disciplinas, "Disciplinas"],
    [t.grupos, "Blocos de currículo"], [t.aulasSemana, "Aulas/semana (total)"], [t.salas, "Salas cadastradas"],
  ];
  document.getElementById("cards").innerHTML = items.map(([n, l]) =>
    `<div class="card"><div class="n">${n}</div><div class="l">${l}</div></div>`
  ).join("");
}

function populateSelect() {
  const sel = document.getElementById("entitySelect");
  const list = state.view === "turma" ? DATA.turmas.map(x => x.name) : DATA.professores.map(x => x.name);
  sel.innerHTML = list.map(x => `<option value="${x}">${x}</option>`).join("");
  if (!list.includes(state.entity)) state.entity = list[0] || null;
  sel.value = state.entity || "";
}

function renderTurma(name) {
  const t = DATA.turmas.find(x => x.name === name);
  const main = document.getElementById("main");
  if (!t) { main.innerHTML = "<p>Nenhuma turma encontrada.</p>"; return; }

  let rows = t.items.map(i => `
    <tr>
      <td>${i.subject}</td>
      <td>${(i.teachers||[]).join(", ") || "—"}</td>
      <td class="num">${i.hours}h/semana</td>
    </tr>`).join("");

  main.innerHTML = `
    <div class="section-title">Currículo — ${t.name}</div>
    <table class="data">
      <thead><tr><th>Disciplina</th><th>Professor</th><th style="text-align:right">Carga</th></tr></thead>
      <tbody>${rows || "<tr><td colspan=3>Nenhuma atividade cadastrada.</td></tr>"}</tbody>
    </table>
    <p class="footnote">${t.numSubjects} disciplina${t.numSubjects===1?"":"s"} · ${t.totalHours} aula${t.totalHours===1?"":"s"} por semana no total</p>

    <div class="section-title">Todas as turmas</div>
    <table class="data">
      <thead><tr><th>Turma</th><th style="text-align:right">Disciplinas</th><th style="text-align:right">Aulas/semana</th></tr></thead>
      <tbody>${DATA.turmas.map(x => `
        <tr${x.name===name?' style="background:#f4f2ec"':''}>
          <td>${x.name}</td><td class="num">${x.numSubjects}</td><td class="num">${x.totalHours}</td>
        </tr>`).join("")}</tbody>
    </table>
  `;
}

function renderProfessor(name) {
  const p = DATA.professores.find(x => x.name === name);
  const main = document.getElementById("main");
  if (!p) { main.innerHTML = "<p>Nenhum professor encontrado.</p>"; return; }

  let rows = p.items.map(i => `
    <tr>
      <td>${i.subject}</td>
      <td>${(i.turmas||[]).join(", ") || "—"}</td>
      <td class="num">${i.hours}h/semana</td>
    </tr>`).join("");

  const badges = [];
  if (p.maxDaysPerWeek) badges.push(`<span class="badge">máx. ${p.maxDaysPerWeek} dia${p.maxDaysPerWeek===1?"":"s"}/semana</span>`);
  if (p.unavailableCount) badges.push(`<span class="badge warn">${p.unavailableCount} horário${p.unavailableCount===1?"":"s"} indisponíve${p.unavailableCount===1?"l":"is"}</span>`);
  if (p.targetHours) badges.push(`<span class="badge">meta: ${p.targetHours}h/semana</span>`);

  main.innerHTML = `
    <div class="section-title">Carga horária — ${p.name}</div>
    <div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px;">${badges.join("")}</div>
    <table class="data">
      <thead><tr><th>Disciplina</th><th>Turma(s)</th><th style="text-align:right">Carga</th></tr></thead>
      <tbody>${rows || "<tr><td colspan=3>Nenhuma atividade cadastrada.</td></tr>"}</tbody>
    </table>
    <p class="footnote">${p.numTurmas} turma${p.numTurmas===1?"":"s"} · ${p.totalHours} aula${p.totalHours===1?"":"s"} por semana no total</p>

    <div class="section-title">Disponibilidade declarada</div>
    <div class="grid-wrap"><table class="grid" id="availGrid"></table></div>

    <div class="section-title">Todos os professores</div>
    <table class="data">
      <thead><tr><th>Professor</th><th style="text-align:right">Turmas</th><th style="text-align:right">Aulas/semana</th><th style="text-align:right">Indisponibilidades</th></tr></thead>
      <tbody>${DATA.professores.map(x => `
        <tr${x.name===name?' style="background:#f4f2ec"':''}>
          <td>${x.name}</td><td class="num">${x.numTurmas}</td><td class="num">${x.totalHours}</td><td class="num">${x.unavailableCount||0}</td>
        </tr>`).join("")}</tbody>
    </table>
  `;

  const slots = DATA.unavailability[name] || {};
  const grid = document.getElementById("availGrid");
  let thead = "<thead><tr><th class='hourcol'>Horário</th>" + DATA.days.map(d => `<th>${d.label}</th>`).join("") + "</tr></thead>";
  let tbody = "<tbody>";
  DATA.hours.forEach((h, hi) => {
    tbody += `<tr><td class="hourcell">${h.label}</td>`;
    DATA.days.forEach((d, di) => {
      const weight = slots[`${di}_${hi}`];
      if (weight !== undefined) {
        const label = weight >= 100 ? "Indisponível" : `Indisponível (${Math.round(weight)}%)`;
        tbody += `<td class="unavailable"><div class="cell-inner"><span class="avail-label un">${label}</span></div></td>`;
      } else {
        tbody += `<td><div class="cell-inner"><span class="avail-label ok">Disponível</span></div></td>`;
      }
    });
    tbody += "</tr>";
  });
  tbody += "</tbody>";
  grid.innerHTML = thead + tbody;
}

function render() {
  if (!state.entity) { document.getElementById("main").innerHTML = ""; return; }
  if (state.view === "turma") renderTurma(state.entity);
  else renderProfessor(state.entity);
}

document.getElementById("viewSeg").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-view]");
  if (!btn) return;
  state.view = btn.dataset.view;
  state.entity = null;
  document.querySelectorAll("#viewSeg button").forEach(b => b.classList.toggle("active", b === btn));
  populateSelect();
  render();
});
document.getElementById("entitySelect").addEventListener("change", (e) => {
  state.entity = e.target.value;
  render();
});

renderCards();
populateSelect();
render();
</script>
</body>
</html>
"""


def render_html_input_data(horario_nome: str, fet_xml: str) -> str:
    """Gera visualização HTML dos dados de entrada do .fet (antes do cálculo do FET)."""
    src = parse_input_from_str(fet_xml)
    dataset = build_input_dataset(src)
    
    if horario_nome:
        dataset["institution"] = horario_nome

    html = INPUT_HTML_TEMPLATE.replace("__INSTITUTION__", dataset["institution"])
    html = html.replace("__DATA_JSON__", json.dumps(dataset, ensure_ascii=False))
    return html
