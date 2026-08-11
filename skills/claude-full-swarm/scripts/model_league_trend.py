#!/usr/bin/env python3
"""Export CFSM model league entries to chart-ready CSV/JSON/digest/dashboard.

The parser is intentionally tolerant because historical model-league files are
human-written Markdown. It recognizes simple `key: value` blocks and computes a
rough score when `score_0_100` is absent.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path


FIELDS = [
    "timestamp",
    "date",
    "mode",
    "project",
    "session",
    "model",
    "effort",
    "availability",
    "command_used",
    "role",
    "task_type",
    "verdict",
    "pm_corrections_needed",
    "scope_drift",
    "evidence_quality",
    "intent_match",
    "architecture_fit",
    "score_0_100",
    "notes",
    "source_file",
]


KEY_RE = re.compile(r"^\s*-?\s*([A-Za-z0-9_ -]+):\s*(.*)\s*$")


def norm_key(key: str) -> str:
    return key.strip().lower().replace(" ", "_").replace("-", "_")


def component(value: str, full: int) -> int:
    v = (value or "").strip().lower()
    if "pass" in v or v in {"win", "available", "none"}:
        return full
    if "usable" in v:
        return round(full * 0.75)
    if "weak" in v or "partial" in v or "minor" in v or "low" in v:
        return round(full * 0.5)
    if "moderate" in v:
        return round(full * 0.35)
    if "fail" in v or "major" in v or "high" in v or "takeover" in v:
        return 0
    return round(full * 0.5)


def pm_correction_score(value: str) -> int:
    v = (value or "").strip().lower()
    if not v or v == "none":
        return 15
    if "low" in v:
        return 12
    if "moderate" in v or "medium" in v:
        return 8
    if "high" in v:
        return 3
    if "takeover" in v or "unsafe" in v:
        return 0
    return 8


def computed_score(row: dict[str, str]) -> int:
    if row.get("score_0_100"):
        try:
            return max(0, min(100, round(float(row["score_0_100"]))))
        except ValueError:
            pass
    score = 0
    score += component(row.get("availability", ""), 10)
    score += component(row.get("intent_match", ""), 15)
    score += component(row.get("evidence_quality", ""), 15)
    score += component(row.get("scope_drift", "none"), 15)
    score += component(row.get("architecture_fit", ""), 10)
    score += pm_correction_score(row.get("pm_corrections_needed", ""))
    score += component(row.get("verdict", ""), 15)
    score += 3  # latency/cost unknown: neutral partial credit
    return max(0, min(100, score))


def parse_file(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    current: dict[str, str] = {}
    last_key = ""
    current_heading_date = ""
    text = path.read_text(encoding="utf-8", errors="replace")
    for raw in text.splitlines():
        line = raw.rstrip()
        heading = re.match(r"^#{1,3}\s+(\d{4}-\d{2}-\d{2})(?:\b|T)(.*)", line)
        if heading:
            if current.get("model") or current.get("role") or current.get("verdict"):
                rows.append(finalize(current, path, current_heading_date))
                current = {}
                last_key = ""
            current_heading_date = heading.group(1)
            continue
        if line.strip().startswith("```"):
            last_key = ""
            continue
        match = KEY_RE.match(line)
        if match:
            key = norm_key(match.group(1))
            value = match.group(2).strip()
            if key != "notes" and len(value) >= 2 and value.startswith("`") and value.endswith("`"):
                value = value[1:-1]
            if key in {"timestamp", "date"} and (
                current.get("model") or current.get("role") or current.get("verdict")
            ):
                rows.append(finalize(current, path, current_heading_date))
                current = {}
            if key == "model" and current.get("model"):
                if "model" in current and ("role" in current or "verdict" in current):
                    rows.append(finalize(current, path, current_heading_date))
                current = {}
            current[key] = value
            last_key = key
            continue
        if line.startswith("- model:"):
            if current.get("model"):
                rows.append(finalize(current, path, current_heading_date))
                current = {}
        if last_key == "notes" and line.strip() and current:
            current["notes"] = (current.get("notes", "") + " " + line.strip()).strip()
    if current.get("model") or current.get("role") or current.get("verdict"):
        rows.append(finalize(current, path, current_heading_date))
    return rows


def finalize(row: dict[str, str], path: Path, heading_date: str) -> dict[str, str]:
    out = {k: str(row.get(k, "")).strip() for k in FIELDS}
    if not out["date"]:
        out["date"] = (out["timestamp"][:10] if out["timestamp"] else heading_date)
    if not out["project"]:
        name = path.name
        out["project"] = name.replace("-model-league.md", "").replace("model-league.md", "global") or "global"
    out["source_file"] = str(path)
    out["score_0_100"] = str(computed_score(out))
    return out


def selected_digest_rows(rows: list[dict[str, str]], target_date: str, top_n: int) -> list[dict[str, str]]:
    dated = [r for r in rows if r.get("date") == target_date]
    if not dated:
        return []

    def sort_key(row: dict[str, str]) -> tuple[int, str, str]:
        try:
            score = int(row.get("score_0_100") or 0)
        except ValueError:
            score = 0
        availability = row.get("availability", "").lower()
        unavailable_boost = 1 if "unavailable" in availability or "fail" in row.get("verdict", "").lower() else 0
        return (unavailable_boost, score, row.get("model", ""))

    return sorted(dated, key=sort_key, reverse=True)[:top_n]


def write_digest(path: Path, rows: list[dict[str, str]], target_date: str, top_n: int) -> None:
    selected = selected_digest_rows(rows, target_date, top_n)
    lines = [
        "---",
        "type: cfsm_model_league_digest",
        f"date: {target_date}",
        "target: cc101_snspilot",
        "status: read_only",
        "---",
        "",
        f"# CFSM Model League Digest - {target_date}",
        "",
        "Read-only model routing signal for cc101/SNSPilot. Do not auto-publish.",
        "",
        "## Highlights",
    ]
    if not selected:
        lines.append("- No model-league rows found for this date.")
    for row in selected:
        note = row.get("notes", "").strip()
        if len(note) > 240:
            note = note[:237].rstrip() + "..."
        lines.append(
            "- "
            f"`{row.get('model', '')}` "
            f"score {row.get('score_0_100', '')}/100, "
            f"{row.get('project', '')} / {row.get('role', '')}: "
            f"{row.get('verdict', '')}. "
            f"{note}"
        )
    lines.extend(
        [
            "",
            "## cc101 Use",
            "- Treat high-scoring new models as 실전 사용기 소재, not benchmark hype.",
            "- Include both availability and failure/unavailable rows so the post can explain what is usable today.",
            "- Keep the claim tied to the recorded CFSM run, project, role, and score.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_dashboard(path: Path, rows: list[dict[str, str]]) -> None:
    data_json = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    generated = datetime.now(timezone.utc).isoformat()
    template = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CFSM Model League Dashboard</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #101114;
      --panel: #181a20;
      --panel-2: #20232b;
      --line: #343946;
      --text: #f4f4f5;
      --muted: #a1a1aa;
      --soft: #71717a;
      --cyan: #67e8f9;
      --green: #86efac;
      --amber: #fcd34d;
      --rose: #fda4af;
      --violet: #c4b5fd;
      --orange: #fdba74;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }
    button, input, select {
      font: inherit;
      color: inherit;
    }
    .shell {
      width: min(1500px, calc(100% - 32px));
      margin: 0 auto;
      padding: 28px 0 44px;
    }
    header {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 20px;
      align-items: end;
      margin-bottom: 20px;
    }
    h1 {
      margin: 0;
      font-size: clamp(28px, 4vw, 56px);
      line-height: 0.96;
      letter-spacing: 0;
    }
    .eyebrow {
      margin-bottom: 10px;
      color: var(--cyan);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .subtitle {
      max-width: 760px;
      margin: 14px 0 0;
      color: var(--muted);
      font-size: 14px;
    }
    .generated {
      color: var(--soft);
      font: 12px ui-monospace, SFMono-Regular, Menlo, monospace;
      text-align: right;
      white-space: nowrap;
    }
    .panel {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      min-width: 0;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .metric {
      min-height: 88px;
      padding: 14px;
    }
    .metric-label {
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .metric-value {
      margin-top: 6px;
      font: 800 30px ui-monospace, SFMono-Regular, Menlo, monospace;
      letter-spacing: 0;
    }
    .metric-note {
      margin-top: 3px;
      color: var(--soft);
      font-size: 12px;
    }
    .controls {
      display: grid;
      grid-template-columns: repeat(6, minmax(120px, 1fr));
      gap: 10px;
      margin-bottom: 12px;
      padding: 12px;
    }
    label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    select, input {
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #111217;
      padding: 0 10px;
      outline: none;
    }
    select:focus, input:focus {
      border-color: var(--cyan);
    }
    .tabs {
      display: inline-flex;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow: hidden;
      background: #111217;
    }
    .tabs button {
      border: 0;
      border-right: 1px solid var(--line);
      background: transparent;
      padding: 0 12px;
      cursor: pointer;
      color: var(--muted);
    }
    .tabs button:last-child { border-right: 0; }
    .tabs button.active {
      background: var(--panel-2);
      color: var(--text);
    }
    .main-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.9fr) minmax(320px, 0.9fr);
      gap: 12px;
      align-items: start;
    }
    .main-grid > *, .side > * {
      min-width: 0;
    }
    .chart-panel {
      padding: 16px;
    }
    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    h2 {
      margin: 0;
      font-size: 15px;
      letter-spacing: 0;
    }
    .hint {
      color: var(--soft);
      font-size: 12px;
    }
    .chart-wrap {
      position: relative;
      width: 100%;
      aspect-ratio: 16 / 8.5;
      min-height: 360px;
    }
    svg {
      width: 100%;
      height: 100%;
      display: block;
      border: 1px solid #262a34;
      border-radius: 8px;
      background: #111217;
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }
    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 24px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 0 9px;
      color: var(--muted);
      font-size: 12px;
    }
    .swatch {
      width: 9px;
      height: 9px;
      border-radius: 999px;
      background: currentColor;
    }
    .side {
      display: grid;
      gap: 12px;
    }
    .rank-list {
      display: grid;
      gap: 8px;
      padding: 12px;
    }
    .rank-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: center;
      border: 1px solid #2b303b;
      border-radius: 7px;
      padding: 10px;
      background: #14161b;
      min-width: 0;
    }
    .rank-name {
      font-size: 13px;
      font-weight: 750;
      overflow-wrap: anywhere;
    }
    .rank-meta {
      margin-top: 3px;
      color: var(--soft);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .score {
      min-width: 52px;
      text-align: right;
      font: 800 22px ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    .table-panel {
      margin-top: 12px;
      overflow: hidden;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 12px;
    }
    th, td {
      border-bottom: 1px solid #262a34;
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      background: #14161b;
    }
    td {
      color: #d4d4d8;
      overflow-wrap: anywhere;
    }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    .pill {
      display: inline-flex;
      min-height: 22px;
      align-items: center;
      border-radius: 999px;
      border: 1px solid var(--line);
      padding: 0 8px;
      color: var(--muted);
      white-space: nowrap;
    }
    .empty {
      padding: 40px 16px;
      text-align: center;
      color: var(--muted);
    }
    @media (max-width: 980px) {
      header, .main-grid { grid-template-columns: 1fr; }
      .generated { text-align: left; }
      .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .controls { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .chart-wrap { min-height: 300px; }
    }
    @media (max-width: 640px) {
      .shell { width: min(100% - 20px, 1500px); padding-top: 18px; }
      .metrics, .controls { grid-template-columns: 1fr; }
      th:nth-child(2), td:nth-child(2), th:nth-child(5), td:nth-child(5), th:nth-child(6), td:nth-child(6), th:nth-child(7), td:nth-child(7) { display: none; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <div class="eyebrow">Model League</div>
        <h1>CFSM/FSM/LTSM Scoreboard</h1>
        <p class="subtitle">GPT PM-owned score memory for routing Claude, Codex, and other worker models. This is not a public benchmark; it tracks how useful each model was in real project roles.</p>
      </div>
      <div class="generated">generated<br />__GENERATED__</div>
    </header>

    <section class="metrics" id="metrics"></section>

    <section class="controls panel">
      <label>Project <select id="projectFilter"></select></label>
      <label>Mode <select id="modeFilter"></select></label>
      <label>Model <select id="modelFilter"></select></label>
      <label>Role <select id="roleFilter"></select></label>
      <label>Minimum Score <input id="scoreFilter" type="number" min="0" max="100" step="1" value="0" /></label>
      <label>Granularity
        <select id="granularityFilter">
          <option value="day">Day</option>
          <option value="hour">Hour</option>
          <option value="minute">Minute</option>
        </select>
      </label>
      <label>Search <input id="searchFilter" type="search" placeholder="notes, task, session" /></label>
    </section>

    <section class="main-grid">
      <div class="panel chart-panel">
        <div class="panel-head">
          <div>
            <h2>Score Trend</h2>
            <div class="hint">x-axis date/time, y-axis GPT PM score_0_100</div>
          </div>
          <div class="tabs" role="tablist" aria-label="Grouping">
            <button id="groupModel" class="active" type="button">Model</button>
            <button id="groupRole" type="button">Model + Role</button>
          </div>
        </div>
        <div class="chart-wrap">
          <svg id="chart" role="img" aria-label="Model score trend chart"></svg>
        </div>
        <div class="legend" id="legend"></div>
      </div>

      <aside class="side">
        <div class="panel">
          <div class="rank-list">
            <div class="panel-head">
              <h2>Latest Leaders</h2>
              <span class="hint">avg by model</span>
            </div>
            <div id="leaders"></div>
          </div>
        </div>
        <div class="panel">
          <div class="rank-list">
            <div class="panel-head">
              <h2>Role Winners</h2>
              <span class="hint">best recent role score</span>
            </div>
            <div id="roles"></div>
          </div>
        </div>
      </aside>
    </section>

    <section class="panel table-panel">
      <table>
        <thead>
          <tr>
            <th style="width: 132px">Time</th>
            <th style="width: 120px">Project</th>
            <th style="width: 160px">Model</th>
            <th style="width: 70px">Score</th>
            <th style="width: 100px">Mode</th>
            <th style="width: 180px">Role</th>
            <th>Notes</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
    </section>
  </div>

  <script type="application/json" id="modelData">__DATA__</script>
  <script>
    const rawData = JSON.parse(document.getElementById("modelData").textContent);
    const palette = ["#67e8f9", "#86efac", "#fcd34d", "#fda4af", "#c4b5fd", "#fdba74", "#a7f3d0", "#93c5fd", "#f0abfc", "#fca5a5"];
    let groupBy = "model";

    const controls = {
      project: document.getElementById("projectFilter"),
      mode: document.getElementById("modeFilter"),
      model: document.getElementById("modelFilter"),
      role: document.getElementById("roleFilter"),
      score: document.getElementById("scoreFilter"),
      granularity: document.getElementById("granularityFilter"),
      search: document.getElementById("searchFilter"),
    };

    const data = rawData
      .map((row) => ({
        ...row,
        score: Number(row.score_0_100 || 0),
        mode: inferMode(row),
        timestamp: row.timestamp || row.date || "",
        dateValue: Date.parse(row.timestamp || row.date || "1970-01-01"),
      }))
      .filter((row) => row.date && Number.isFinite(row.score));

    function inferMode(row) {
      if (row.mode) return row.mode;
      const text = `${row.session || ""} ${row.source_file || ""} ${row.task_type || ""}`.toLowerCase();
      if (/\bltsm\b/.test(text)) return "LTSM";
      if (/\bcfsm\b/.test(text)) return "CFSM";
      if (/\bfull\b|\bfsm\b/.test(text)) return "FSM";
      return "PM scored";
    }

    function unique(field) {
      return [...new Set(data.map((row) => row[field]).filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b)));
    }

    function fillSelect(select, values, allLabel) {
      select.innerHTML = "";
      select.append(new Option(allLabel, ""));
      values.forEach((value) => select.append(new Option(value, value)));
    }

    fillSelect(controls.project, unique("project"), "All projects");
    fillSelect(controls.mode, unique("mode"), "All modes");
    fillSelect(controls.model, unique("model"), "All models");
    fillSelect(controls.role, unique("role"), "All roles");

    Object.values(controls).forEach((el) => el.addEventListener("input", render));
    document.getElementById("groupModel").addEventListener("click", () => setGroup("model"));
    document.getElementById("groupRole").addEventListener("click", () => setGroup("modelRole"));

    function setGroup(next) {
      groupBy = next;
      document.getElementById("groupModel").classList.toggle("active", next === "model");
      document.getElementById("groupRole").classList.toggle("active", next === "modelRole");
      render();
    }

    function filteredRows() {
      const q = controls.search.value.trim().toLowerCase();
      const minScore = Number(controls.score.value || 0);
      return data.filter((row) => {
        if (controls.project.value && row.project !== controls.project.value) return false;
        if (controls.mode.value && row.mode !== controls.mode.value) return false;
        if (controls.model.value && row.model !== controls.model.value) return false;
        if (controls.role.value && row.role !== controls.role.value) return false;
        if (row.score < minScore) return false;
        if (!q) return true;
        return [row.model, row.role, row.project, row.session, row.task_type, row.notes, row.command_used]
          .join(" ")
          .toLowerCase()
          .includes(q);
      });
    }

    function average(rows) {
      if (!rows.length) return 0;
      return rows.reduce((sum, row) => sum + (typeof row === "number" ? row : row.score), 0) / rows.length;
    }

    function latestDate(rows) {
      if (!rows.length) return "-";
      const latest = rows.reduce((max, row) => row.dateValue > max.dateValue ? row : max, rows[0]);
      return displayTime(latest);
    }

    function renderMetrics(rows) {
      const models = new Set(rows.map((row) => row.model)).size;
      const projects = new Set(rows.map((row) => row.project)).size;
      const latestRows = rows.filter((row) => row.date === latestDate(rows));
      const best = rows.reduce((top, row) => row.score > (top?.score ?? -1) ? row : top, null);
      const metrics = [
        ["Rows", rows.length, "filtered score entries"],
        ["Models", models, "distinct model labels"],
        ["Projects", projects, "source ledgers"],
        ["Average", average(rows).toFixed(1), "GPT PM score"],
        ["Latest", latestRows.length ? latestRows.length : "-", latestDate(rows)],
      ];
      if (best) metrics[4] = ["Best", best.score, `${best.model} / ${best.project}`];
      document.getElementById("metrics").innerHTML = metrics.map(([label, value, note]) => `
        <div class="metric panel">
          <div class="metric-label">${escapeHtml(label)}</div>
          <div class="metric-value">${escapeHtml(String(value))}</div>
          <div class="metric-note">${escapeHtml(note)}</div>
        </div>
      `).join("");
    }

    function seriesKey(row) {
      if (groupBy === "modelRole") return `${row.model} / ${row.role || "role n/a"}`;
      return row.model || "unknown";
    }

    function bucketFor(row) {
      const raw = String(row.timestamp || row.date || "1970-01-01").replace("T", " ");
      const parsed = new Date(row.timestamp || row.date || "1970-01-01");
      if (!Number.isFinite(parsed.getTime())) {
        return { label: row.date || "unknown", value: row.dateValue };
      }
      const granularity = controls.granularity.value;
      if (granularity === "minute") {
        const label = raw.slice(0, 16);
        return { label, value: bucketValue(label) };
      }
      if (granularity === "hour") {
        const label = raw.slice(0, 13) + ":00";
        return { label, value: bucketValue(label) };
      }
      const label = raw.slice(0, 10);
      return { label, value: bucketValue(label) };
    }

    function displayTime(row) {
      if (!row.timestamp) return row.date || "";
      return row.timestamp.replace("T", " ").slice(0, 16);
    }

    function bucketValue(label) {
      if (label.length === 10) return Date.parse(label + "T00:00:00");
      if (label.length === 13) return Date.parse(label.replace(" ", "T") + ":00:00");
      if (label.length === 16) return Date.parse(label.replace(" ", "T") + ":00");
      return Date.parse(label);
    }

    function aggregateSeries(rows) {
      const map = new Map();
      rows.forEach((row) => {
        const key = seriesKey(row);
        const bucket = bucketFor(row);
        const bucketKey = `${key}@@${bucket.label}`;
        if (!map.has(bucketKey)) map.set(bucketKey, { key, date: bucket.label, dateValue: bucket.value, scores: [] });
        map.get(bucketKey).scores.push(row.score);
      });
      const byKey = new Map();
      [...map.values()].forEach((bucket) => {
        const point = { key: bucket.key, date: bucket.date, dateValue: bucket.dateValue, score: average(bucket.scores) };
        if (!byKey.has(bucket.key)) byKey.set(bucket.key, []);
        byKey.get(bucket.key).push(point);
      });
      return [...byKey.entries()]
        .map(([key, points]) => ({ key, points: points.sort((a, b) => a.dateValue - b.dateValue), avg: average(points) }))
        .sort((a, b) => b.avg - a.avg)
        .slice(0, groupBy === "modelRole" ? 10 : 8);
    }

    function renderChart(rows) {
      const svg = document.getElementById("chart");
      const legend = document.getElementById("legend");
      const width = 1000;
      const height = 520;
      const pad = { left: 56, right: 24, top: 24, bottom: 58 };
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.innerHTML = "";
      legend.innerHTML = "";
      if (!rows.length) {
        svg.innerHTML = `<text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="#a1a1aa">No rows match filters</text>`;
        return;
      }
      const series = aggregateSeries(rows);
      const bucketedRows = rows.map((row) => ({ ...row, bucket: bucketFor(row) }));
      const minDate = Math.min(...bucketedRows.map((row) => row.bucket.value));
      const maxDate = Math.max(...bucketedRows.map((row) => row.bucket.value));
      const xSpan = Math.max(1, maxDate - minDate);
      const yMin = 0;
      const yMax = 100;
      const x = (dateValue) => pad.left + ((dateValue - minDate) / xSpan) * (width - pad.left - pad.right);
      const y = (score) => pad.top + ((yMax - score) / (yMax - yMin)) * (height - pad.top - pad.bottom);

      for (let score = 0; score <= 100; score += 20) {
        const yy = y(score);
        line(svg, pad.left, yy, width - pad.right, yy, "#252a34", 1);
        text(svg, pad.left - 12, yy + 4, String(score), "#71717a", "end", 12);
      }
      const dateTicks = [...new Set(bucketedRows.map((row) => row.bucket.label))].sort();
      const tickStep = Math.max(1, Math.ceil(dateTicks.length / 6));
      dateTicks.filter((_, i) => i % tickStep === 0 || i === dateTicks.length - 1).forEach((date) => {
        const xx = x(bucketValue(date));
        line(svg, xx, pad.top, xx, height - pad.bottom, "#202530", 1);
        text(svg, xx, height - pad.bottom + 25, date.length > 10 ? date.slice(5) : date.slice(5), "#71717a", "middle", 12);
      });
      line(svg, pad.left, pad.top, pad.left, height - pad.bottom, "#4b5563", 1);
      line(svg, pad.left, height - pad.bottom, width - pad.right, height - pad.bottom, "#4b5563", 1);

      series.forEach((s, idx) => {
        const color = palette[idx % palette.length];
        const d = s.points.map((point, i) => `${i === 0 ? "M" : "L"} ${x(point.dateValue).toFixed(1)} ${y(point.score).toFixed(1)}`).join(" ");
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", d);
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", color);
        path.setAttribute("stroke-width", "3");
        path.setAttribute("stroke-linecap", "round");
        path.setAttribute("stroke-linejoin", "round");
        svg.append(path);
        s.points.forEach((point) => {
          circle(svg, x(point.dateValue), y(point.score), 4.2, color);
        });
        const last = s.points[s.points.length - 1];
        text(svg, Math.min(width - 110, x(last.dateValue) + 8), y(last.score) - 8, String(Math.round(last.score)), color, "start", 12);
      });
      legend.innerHTML = series.map((s, idx) => `
        <span class="legend-item" style="color:${palette[idx % palette.length]}">
          <span class="swatch"></span>${escapeHtml(s.key)}
        </span>
      `).join("");
    }

    function renderLeaders(rows) {
      const latest = latestDate(rows);
      const latestRows = rows.filter((row) => row.date === latest);
      const groups = groupAverage(latestRows, "model").slice(0, 6);
      document.getElementById("leaders").innerHTML = groups.length ? groups.map((g) => rankRow(g.key, `${g.count} rows on ${latest}`, g.avg)).join("") : `<div class="empty">No latest rows</div>`;
    }

    function renderRoleWinners(rows) {
      const bestByRole = new Map();
      rows.forEach((row) => {
        const role = row.role || "role n/a";
        const prev = bestByRole.get(role);
        if (!prev || row.score > prev.score || (row.score === prev.score && row.dateValue > prev.dateValue)) bestByRole.set(role, row);
      });
      const winners = [...bestByRole.values()].sort((a, b) => b.score - a.score).slice(0, 6);
      document.getElementById("roles").innerHTML = winners.length ? winners.map((row) => rankRow(row.role || "role n/a", `${row.model} / ${row.project}`, row.score)).join("") : `<div class="empty">No role rows</div>`;
    }

    function groupAverage(rows, field) {
      const map = new Map();
      rows.forEach((row) => {
        const key = row[field] || "unknown";
        if (!map.has(key)) map.set(key, []);
        map.get(key).push(row);
      });
      return [...map.entries()].map(([key, vals]) => ({ key, avg: average(vals), count: vals.length })).sort((a, b) => b.avg - a.avg);
    }

    function rankRow(name, meta, score) {
      return `
        <div class="rank-row">
          <div>
            <div class="rank-name">${escapeHtml(name)}</div>
            <div class="rank-meta">${escapeHtml(meta)}</div>
          </div>
          <div class="score">${Math.round(score)}</div>
        </div>
      `;
    }

    function renderTable(rows) {
      const sorted = [...rows].sort((a, b) => b.dateValue - a.dateValue || b.score - a.score).slice(0, 120);
      document.getElementById("rows").innerHTML = sorted.map((row) => `
        <tr>
          <td class="mono">${escapeHtml(displayTime(row))}</td>
          <td>${escapeHtml(row.project || "")}</td>
          <td><span class="pill">${escapeHtml(row.model || "")}</span></td>
          <td class="mono">${Math.round(row.score)}</td>
          <td>${escapeHtml(row.mode)}</td>
          <td>${escapeHtml(row.role || "")}</td>
          <td>${escapeHtml(row.notes || row.task_type || "")}</td>
        </tr>
      `).join("");
    }

    function render() {
      const rows = filteredRows();
      renderMetrics(rows);
      renderChart(rows);
      renderLeaders(rows);
      renderRoleWinners(rows);
      renderTable(rows);
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[ch]));
    }

    function line(svg, x1, y1, x2, y2, stroke, width) {
      const el = document.createElementNS("http://www.w3.org/2000/svg", "line");
      el.setAttribute("x1", x1);
      el.setAttribute("y1", y1);
      el.setAttribute("x2", x2);
      el.setAttribute("y2", y2);
      el.setAttribute("stroke", stroke);
      el.setAttribute("stroke-width", width);
      svg.append(el);
    }

    function circle(svg, cx, cy, r, fill) {
      const el = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      el.setAttribute("cx", cx);
      el.setAttribute("cy", cy);
      el.setAttribute("r", r);
      el.setAttribute("fill", fill);
      el.setAttribute("stroke", "#111217");
      el.setAttribute("stroke-width", "2");
      svg.append(el);
    }

    function text(svg, x, y, value, fill, anchor, size) {
      const el = document.createElementNS("http://www.w3.org/2000/svg", "text");
      el.setAttribute("x", x);
      el.setAttribute("y", y);
      el.setAttribute("fill", fill);
      el.setAttribute("text-anchor", anchor);
      el.setAttribute("font-size", size);
      el.setAttribute("font-family", "ui-monospace, SFMono-Regular, Menlo, monospace");
      el.textContent = value;
      svg.append(el);
    }

    render();
  </script>
</body>
</html>
"""
    html = template.replace("__DATA__", data_json).replace("__GENERATED__", generated)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default="~/.codex/swarm",
        help="model league root containing model-league.md and projects/*-model-league.md",
    )
    parser.add_argument("--csv-out", default="")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--digest-out", default="")
    parser.add_argument("--digest-date", default="", help="date to use for digest; defaults to latest row date")
    parser.add_argument("--digest-top-n", type=int, default=8)
    parser.add_argument("--html-out", default="", help="write a standalone dashboard HTML")
    args = parser.parse_args()

    root = Path(args.root).expanduser()
    files = []
    main_file = root / "model-league.md"
    if main_file.exists():
        files.append(main_file)
    projects = root / "projects"
    if projects.exists():
        files.extend(sorted(projects.glob("*model-league.md")))

    rows: list[dict[str, str]] = []
    for file in files:
        rows.extend(parse_file(file))
    rows.sort(key=lambda r: (r.get("date", ""), r.get("project", ""), r.get("model", ""), r.get("role", "")))

    if args.csv_out:
        out = Path(args.csv_out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    if args.json_out:
        out = Path(args.json_out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.digest_out:
        target_date = args.digest_date or max((r.get("date", "") for r in rows), default="")
        out = Path(args.digest_out).expanduser()
        write_digest(out, rows, target_date, args.digest_top_n)
    if args.html_out:
        out = Path(args.html_out).expanduser()
        write_dashboard(out, rows)
    if not args.csv_out and not args.json_out and not args.digest_out and not args.html_out:
        writer = csv.DictWriter(__import__("sys").stdout, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
