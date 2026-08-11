#!/usr/bin/env python3
"""Attest the actual Codex model/provider/harness from session JSONL."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "codex.actual_model_attestation.v1"


def parse_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_records(path: Path) -> list[dict[str, Any]]:
    result = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {number}: {exc}") from exc
        if isinstance(row, dict):
            result.append(row)
    return result


def attest(path: Path, expected_model: str, expected_provider: str, expected_cli: str, since: datetime | None) -> dict[str, Any]:
    records = read_records(path)
    session_ids: list[str] = []
    cli_versions: list[str] = []
    providers: list[str] = []
    models: list[str] = []
    for row in records:
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        if row.get("type") == "session_meta":
            session_id = str(payload.get("session_id") or payload.get("id") or "")
            if session_id and session_id not in session_ids:
                session_ids.append(session_id)
            cli = str(payload.get("cli_version") or "")
            if cli and cli not in cli_versions:
                cli_versions.append(cli)
            provider = str(payload.get("model_provider") or "")
            if provider and provider not in providers:
                providers.append(provider)
        if row.get("type") != "turn_context":
            continue
        timestamp = str(row.get("timestamp") or "")
        if since:
            try:
                if parse_time(timestamp) < since:
                    continue
            except ValueError:
                continue
        model = str(payload.get("model") or "")
        if model and model not in models:
            models.append(model)
    reasons = []
    if len(session_ids) != 1:
        reasons.append("session_identity_not_exact")
    if models != [expected_model]:
        reasons.append("actual_model_mismatch_or_switch")
    if providers != [expected_provider]:
        reasons.append("provider_mismatch")
    if cli_versions != [expected_cli]:
        reasons.append("harness_version_mismatch")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ESTABLISHED" if not reasons else "NOT_ESTABLISHED",
        "completion_established": not reasons,
        "transcript": str(path.resolve()),
        "since": since.isoformat() if since else "",
        "session_ids": session_ids,
        "expected_model": expected_model,
        "actual_models": models,
        "expected_provider": expected_provider,
        "actual_providers": providers,
        "expected_cli_version": expected_cli,
        "actual_cli_versions": cli_versions,
        "reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--expected-model", required=True)
    parser.add_argument("--expected-provider", default="openai")
    parser.add_argument("--expected-cli-version", required=True)
    parser.add_argument("--since", default="")
    args = parser.parse_args()
    try:
        result = attest(
            Path(args.transcript).expanduser(),
            args.expected_model,
            args.expected_provider,
            args.expected_cli_version,
            parse_time(args.since) if args.since else None,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "ERROR", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["completion_established"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
