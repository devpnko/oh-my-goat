#!/usr/bin/env python3
"""Append a GPT PM model score and refresh the model-league dashboard."""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import model_league_trend


ROOT = Path("~/.codex/swarm").expanduser()
TREND_SCRIPT = Path(__file__).with_name("model_league_trend.py")


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="minutes")


def normalize_mode(value: str) -> str:
    mode = value.strip().upper()
    aliases = {
        "FULL": "FSM",
        "FULL-SWARM": "FSM",
        "FULL_SWARM": "FSM",
        "CLAUDE-FULL-SWARM": "CFSM",
        "LOW-TOKEN": "LTSM",
        "LOW_TOKEN": "LTSM",
    }
    return aliases.get(mode, mode)


def ledger_path(root: Path, project: str, global_ledger: bool) -> Path:
    if global_ledger:
        return root / "model-league.md"
    safe_project = project.strip().replace("/", "-") or "global"
    return root / "projects" / f"{safe_project}-model-league.md"


def entry_text(row: dict[str, str]) -> str:
    ordered = [
        "timestamp",
        "date",
        "mode",
        "project",
        "session",
        "provider",
        "model",
        "requested_model",
        "actual_model",
        "effort",
        "availability",
        "harness_version",
        "attestation_status",
        "fallback_event",
        "selection_basis",
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
        "score_components",
        "notes",
    ]
    heading = f"## {row['timestamp']} · {row['session']}"
    lines = ["", heading, ""]
    for key in ordered:
        value = row.get(key, "")
        if value:
            lines.append(f"{key}: {value}")
    lines.append("")
    return "\n".join(lines)


def refresh_outputs(root: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(TREND_SCRIPT),
            "--root",
            str(root),
            "--csv-out",
            str(root / "model-league-trend.csv"),
            "--json-out",
            str(root / "model-league-trend.json"),
            "--html-out",
            str(root / "model-league-dashboard.html"),
        ],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--global-ledger", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-refresh", action="store_true")
    parser.add_argument("--timestamp", default="")
    parser.add_argument("--mode", required=True, help="CFSM, FSM, LTSM, CDFSM, or PM")
    parser.add_argument("--project", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--provider", default="")
    parser.add_argument("--model", required=True)
    parser.add_argument("--requested-model", default="")
    parser.add_argument("--actual-model", default="")
    parser.add_argument("--role", required=True)
    parser.add_argument("--task-type", required=True)
    parser.add_argument("--effort", default="")
    parser.add_argument("--availability", default="available")
    parser.add_argument("--harness-version", default="")
    parser.add_argument("--attestation-status", default="")
    parser.add_argument("--fallback-event", default="")
    parser.add_argument("--selection-basis", default="")
    parser.add_argument("--command-used", default="")
    parser.add_argument("--verdict", default="usable")
    parser.add_argument("--pm-corrections-needed", default="none")
    parser.add_argument("--scope-drift", default="none")
    parser.add_argument("--evidence-quality", default="PASS")
    parser.add_argument("--intent-match", default="PASS")
    parser.add_argument("--architecture-fit", default="PASS")
    parser.add_argument("--score", default="")
    parser.add_argument("--score-components", default="")
    parser.add_argument("--notes", required=True)
    args = parser.parse_args()

    root = Path(args.root).expanduser()
    timestamp = args.timestamp or iso_now()
    row = {
        "timestamp": timestamp,
        "date": timestamp[:10],
        "mode": normalize_mode(args.mode),
        "project": args.project,
        "session": args.session,
        "provider": args.provider,
        "model": args.model,
        "requested_model": args.requested_model,
        "actual_model": args.actual_model,
        "effort": args.effort,
        "availability": args.availability,
        "harness_version": args.harness_version,
        "attestation_status": args.attestation_status,
        "fallback_event": args.fallback_event,
        "selection_basis": args.selection_basis,
        "command_used": args.command_used,
        "role": args.role,
        "task_type": args.task_type,
        "verdict": args.verdict,
        "pm_corrections_needed": args.pm_corrections_needed,
        "scope_drift": args.scope_drift,
        "evidence_quality": args.evidence_quality,
        "intent_match": args.intent_match,
        "architecture_fit": args.architecture_fit,
        "score_0_100": args.score,
        "score_components": args.score_components,
        "notes": args.notes,
        "source_file": "",
    }
    if not row["score_0_100"]:
        row["score_0_100"] = str(model_league_trend.computed_score(row))

    target = ledger_path(root, row["project"], args.global_ledger)
    text = entry_text(row)
    if args.dry_run:
        print(f"target: {target}")
        print(text)
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(f"# {row['project']} Model League\n", encoding="utf-8")
    with target.open("a", encoding="utf-8") as f:
        f.write(text)
    if not args.no_refresh:
        refresh_outputs(root)
    print(f"recorded: {target}")
    print(f"score_0_100: {row['score_0_100']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
