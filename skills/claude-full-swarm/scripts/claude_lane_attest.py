#!/usr/bin/env python3
"""Attest the actual model and harness used by a Claude Code lane.

This is a read-only transport check.  It intentionally trusts neither a pane
title nor the model's prose self-report.  The source of truth is Claude Code's
session JSONL metadata for the bounded consultation epoch.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "claude.actual_model_attestation.v1"


def parse_timestamp(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("timestamp is empty")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def record_in_epoch(record: dict[str, Any], since: datetime | None) -> bool:
    if since is None:
        return True
    try:
        return parse_timestamp(str(record.get("timestamp") or "")) >= since
    except (TypeError, ValueError):
        return False


def read_records(path: Path, since: datetime | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            text = raw.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at line {line_number}: {exc}") from exc
            if isinstance(row, dict) and record_in_epoch(row, since):
                records.append(row)
    return records


def current_cli_version(claude_bin: str) -> str:
    process = subprocess.run(
        [claude_bin, "--version"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if process.returncode != 0:
        raise ValueError(f"unable to read Claude Code version from {claude_bin}")
    version = (process.stdout or process.stderr).strip().split()
    if not version:
        raise ValueError(f"empty Claude Code version from {claude_bin}")
    return version[0]


def ordered_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def model_matches(model: str, expected_model: str, allowed_pattern: str) -> bool:
    if expected_model and model != expected_model:
        return False
    if allowed_pattern and re.fullmatch(allowed_pattern, model) is None:
        return False
    return True


def attest(
    transcript: Path,
    *,
    requested_selector: str,
    expected_model: str = "",
    allowed_model_pattern: str = "",
    expected_cli_version: str = "",
    since: datetime | None = None,
    forbid_fallback: bool = True,
    named_model_gate: bool = False,
    selection_basis: str = "",
) -> dict[str, Any]:
    records = read_records(transcript, since=since)
    assistant_models: list[str] = []
    observed_versions: list[str] = []
    session_ids: list[str] = []
    fallback_events: list[dict[str, str]] = []

    for row in records:
        version = str(row.get("version") or "").strip()
        if version:
            observed_versions.append(version)
        session_id = str(row.get("sessionId") or "").strip()
        if session_id:
            session_ids.append(session_id)
        message = row.get("message")
        if row.get("type") == "assistant" and isinstance(message, dict):
            model = str(message.get("model") or "").strip()
            if model:
                assistant_models.append(model)
        if row.get("type") == "system" and row.get("subtype") == "model_refusal_fallback":
            fallback_events.append({
                "timestamp": str(row.get("timestamp") or ""),
                "original_model": str(row.get("originalModel") or ""),
                "fallback_model": str(row.get("fallbackModel") or ""),
                "trigger": str(row.get("trigger") or ""),
                "category": str(row.get("apiRefusalCategory") or ""),
            })

    actual_models = ordered_unique(assistant_models)
    versions = ordered_unique(observed_versions)
    sessions = ordered_unique(session_ids)
    final_model = assistant_models[-1] if assistant_models else ""
    unexpected_models = [
        model for model in actual_models
        if not model_matches(model, expected_model, allowed_model_pattern)
    ]
    harness_current = bool(expected_cli_version) and versions == [expected_cli_version]

    reasons: list[str] = []
    if not assistant_models:
        reasons.append("no_assistant_model_metadata_in_epoch")
    if len(sessions) != 1:
        reasons.append("session_identity_not_exact")
    if expected_cli_version and not harness_current:
        reasons.append("stale_or_unbound_harness_version")
    if unexpected_models:
        reasons.append("actual_model_outside_bound_selection")
    if fallback_events and forbid_fallback:
        reasons.append("fallback_event_observed")
    if named_model_gate and not expected_model:
        reasons.append("named_model_gate_requires_exact_expected_model")
    if named_model_gate and fallback_events:
        reasons.append("named_model_gate_cannot_be_satisfied_by_fallback")

    established = not reasons
    status = "ESTABLISHED" if established else "NOT_ESTABLISHED"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "completion_established": established,
        "requested_selector": requested_selector,
        "selection_basis": selection_basis,
        "expected_model": expected_model,
        "allowed_model_pattern": allowed_model_pattern,
        "named_model_gate": named_model_gate,
        "fallback_forbidden": forbid_fallback,
        "transcript": str(transcript.resolve()),
        "since": since.isoformat() if since else "",
        "session_ids": sessions,
        "expected_cli_version": expected_cli_version,
        "observed_cli_versions": versions,
        "actual_models": actual_models,
        "final_actual_model": final_model,
        "fallback_events": fallback_events,
        "reasons": reasons,
    }


def resolve_transcript(transcript: str, session_id: str, projects_root: str) -> Path:
    if transcript:
        path = Path(transcript).expanduser()
        if not path.is_file():
            raise ValueError(f"transcript not found: {path}")
        return path
    if not session_id:
        raise ValueError("--transcript or --session-id is required")
    root = Path(projects_root).expanduser()
    matches = sorted(root.rglob(f"{session_id}.jsonl"))
    if len(matches) != 1:
        raise ValueError(f"expected one transcript for session {session_id}, found {len(matches)}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", default="")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--projects-root", default="~/.claude/projects")
    parser.add_argument("--requested-selector", required=True)
    parser.add_argument("--expected-model", default="")
    parser.add_argument("--allowed-model-pattern", default="")
    parser.add_argument("--expected-cli-version", default="current")
    parser.add_argument("--claude-bin", default="/opt/homebrew/bin/claude")
    parser.add_argument("--since", default="")
    parser.add_argument("--allow-fallback", action="store_true")
    parser.add_argument("--named-model-gate", action="store_true")
    parser.add_argument("--selection-basis", default="")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    try:
        transcript = resolve_transcript(args.transcript, args.session_id, args.projects_root)
        since = parse_timestamp(args.since) if args.since else None
        expected_cli = args.expected_cli_version
        if expected_cli == "current":
            expected_cli = current_cli_version(args.claude_bin)
        result = attest(
            transcript,
            requested_selector=args.requested_selector,
            expected_model=args.expected_model,
            allowed_model_pattern=args.allowed_model_pattern,
            expected_cli_version=expected_cli,
            since=since,
            forbid_fallback=not args.allow_fallback,
            named_model_gate=args.named_model_gate,
            selection_basis=args.selection_basis,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({
            "schema_version": SCHEMA_VERSION,
            "status": "ERROR",
            "error": str(exc),
        }, ensure_ascii=False, sort_keys=True))
        return 2

    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        Path(args.json_out).expanduser().write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0 if result["completion_established"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
