#!/usr/bin/env python3
"""
Gera uma visualização HTML interativa da grade horária, cruzando:
  - o arquivo .fet de origem (metadados: professor, disciplina, turma, dias, horas,
    e as restrições ConstraintTeacherNotAvailableTimes de cada professor)
  - o {base}_activities.xml gerado pelo fet-cl (alocação: dia, hora, sala)

Na visão "Por professor", os horários sem aula são diferenciados entre
"Disponível" (sem restrição) e "Indisponível" (bloqueado por uma restrição
de disponibilidade do professor no .fet), com um padrão hachurado.

Uso:
    python3 visualize_timetable.py Brazil.fet Brazil_activities.xml -o grade.html

Se você só tem o .fet de origem (ainda não rodou o fet-cl), o script também
aceita o "*_data_and_timetable.fet" gerado na saída -- nesse caso passe-o
no lugar do --activities e ele extrai a alocação dele mesmo:

    python3 visualize_timetable.py Brazil.fet out/timetables/Brazil/Brazil_data_and_timetable.fet -o grade.html

Não depende de nenhuma biblioteca externa (só stdlib).
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def read_xml_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="ignore")


def parse_fet_source(path: Path) -> dict:
    """Extrai metadados de um .fet: instituição, dias, horas e atividades
    (id -> professor(es), disciplina, turma(s), duração)."""
    root = ET.fromstring(read_xml_text(path))

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
    # -> {professor: {(day, hour): weight_percentage}}
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
                    # se a mesma célula aparecer em mais de uma constraint,
                    # fica o maior peso (mais restritivo)
                    slots[(day, hour)] = max(weight, slots.get((day, hour), 0))

    return {
        "institution": institution, "days": days, "hours": hours,
        "activities": activities, "unavailability": unavailability,
    }


def parse_placements(path: Path) -> dict:
    """Aceita tanto um {base}_activities.xml (raiz <Activities_Timetable>)
    quanto um {base}_data_and_timetable.fet (contém <Timetable><Activities_Timetable>)."""
    root = ET.fromstring(read_xml_text(path))

    container = root if root.tag == "Activities_Timetable" else root.find(".//Activities_Timetable")
    if container is None:
        sys.exit(f"Não encontrei <Activities_Timetable> em {path} -- arquivo inesperado.")

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

    # Disponibilidade por professor: {professor: {"di_hi": weight_percentage}}
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


def render_html(dataset: dict) -> str:
    html = HTML_TEMPLATE.replace("__INSTITUTION__", dataset["institution"])
    html = html.replace("__DATA_JSON__", json.dumps(dataset, ensure_ascii=False))
    return html


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fet_source", type=Path, help="Arquivo .fet de origem (metadados)")
    parser.add_argument("placements", type=Path,
                         help="Arquivo *_activities.xml OU *_data_and_timetable.fet gerado pelo fet-cl")
    parser.add_argument("-o", "--output", type=Path, default=Path("grade.html"), help="Arquivo HTML de saída")
    args = parser.parse_args()

    for p in (args.fet_source, args.placements):
        if not p.exists():
            sys.exit(f"Arquivo não encontrado: {p}")

    source = parse_fet_source(args.fet_source)
    placements = parse_placements(args.placements)
    dataset = build_dataset(source, placements)

    args.output.write_text(render_html(dataset), encoding="utf-8")
    print(f"OK: {len(dataset['rows'])} aulas, {len(dataset['unallocated'])} não alocadas")
    print(f"Gerado: {args.output}")


if __name__ == "__main__":
    main()
