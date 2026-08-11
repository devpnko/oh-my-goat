#!/usr/bin/env python3
"""Capture Claude Code quota fields and render a compact local status line."""

from __future__ import annotations

import fcntl
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from stacker_quota_pace import (  # noqa: E402
    merge_quota_observations,
    normalize_quota_observation,
)


DEFAULT_OUTPUT = Path(
    os.environ.get(
        "STACKER_PROVIDER_QUOTA_STATE",
        "~/.codex/swarm/provider-quota-state.json",
    )
).expanduser()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def merge_and_write(path: Path, incoming: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            previous = {}
        merged = merge_quota_observations(previous, incoming)
        atomic_write_json(path, merged)
        return merged


def compact_percentage(value: Any) -> str:
    try:
        return f"{float(value):.0f}%"
    except (TypeError, ValueError):
        return "--"


def render_status(observation: dict[str, Any]) -> str:
    by_id = {str(item.get("bucket_id")): item for item in observation.get("buckets", [])}
    segments: list[str] = []
    if "five_hour" in by_id:
        segments.append(f"5h {compact_percentage(by_id['five_hour'].get('used_percentage'))}")
    if "seven_day" in by_id:
        segments.append(f"7d {compact_percentage(by_id['seven_day'].get('used_percentage'))}")
    fable = next(
        (
            item for item in observation.get("buckets", [])
            if item.get("scope") == "model_family" and item.get("family") == "fable"
        ),
        None,
    )
    if fable:
        segments.append(f"Fable {compact_percentage(fable.get('used_percentage'))}")
    if not segments:
        return "Claude quota pending"
    return "Claude quota " + " · ".join(segments)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        print("Claude quota unavailable")
        return 0
    if not isinstance(payload, dict):
        print("Claude quota unavailable")
        return 0
    observation = normalize_quota_observation(payload)
    if observation.get("buckets"):
        try:
            observation = merge_and_write(DEFAULT_OUTPUT, observation)
        except OSError:
            # Status-line rendering must never interfere with the Claude session.
            pass
    print(render_status(observation))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
