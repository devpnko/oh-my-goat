#!/usr/bin/env python3
"""Maintain non-canonical provider/model/effort runtime exclusions for Stacker."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "stacker.provider_runtime_health.v1"
DEFAULT_PATH = Path("~/.codex/swarm/provider-runtime-health.json")
REASONS = {
    "actual_model_mismatch",
    "auth_unavailable",
    "fallback_observed",
    "hard_quota",
    "provider_unavailable",
    "rate_limited",
    "transport_forbidden",
    "transport_unstable",
}


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "canonical": False,
        "authority": "NONE",
        "exclusions": [],
    }


def read_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return empty_state()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("runtime health schema mismatch")
    return payload


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def exclude(
    payload: dict[str, Any],
    *,
    provider_id: str,
    selector: str,
    effort: str,
    reason: str,
    observed_at: str,
) -> dict[str, Any]:
    if reason not in REASONS:
        raise ValueError(f"unsupported runtime exclusion reason: {reason}")
    exclusions = [
        item for item in payload.get("exclusions", [])
        if (item.get("provider_id"), item.get("selector"), item.get("effort"))
        != (provider_id, selector, effort)
    ]
    exclusions.append({
        "provider_id": provider_id,
        "selector": selector,
        "effort": effort,
        "reason": reason,
        "status": "UNTIL_REVALIDATED",
        "observed_at": observed_at,
    })
    result = empty_state()
    result["exclusions"] = sorted(
        exclusions,
        key=lambda item: (item["provider_id"], item["selector"], item["effort"]),
    )
    return result


def clear(payload: dict[str, Any], *, provider_id: str, selector: str, effort: str) -> dict[str, Any]:
    result = empty_state()
    result["exclusions"] = [
        item for item in payload.get("exclusions", [])
        if (item.get("provider_id"), item.get("selector"), item.get("effort"))
        != (provider_id, selector, effort)
    ]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default=str(DEFAULT_PATH))
    subparsers = parser.add_subparsers(dest="command", required=True)

    exclude_parser = subparsers.add_parser("exclude")
    exclude_parser.add_argument("--provider", required=True)
    exclude_parser.add_argument("--selector", required=True)
    exclude_parser.add_argument("--effort", required=True)
    exclude_parser.add_argument("--reason", choices=sorted(REASONS), required=True)

    clear_parser = subparsers.add_parser("clear")
    clear_parser.add_argument("--provider", required=True)
    clear_parser.add_argument("--selector", required=True)
    clear_parser.add_argument("--effort", required=True)

    subparsers.add_parser("show")
    args = parser.parse_args()
    path = Path(args.state).expanduser()
    try:
        payload = read_state(path)
        if args.command == "exclude":
            payload = exclude(
                payload,
                provider_id=args.provider,
                selector=args.selector,
                effort=args.effort,
                reason=args.reason,
                observed_at=datetime.now(timezone.utc).isoformat(),
            )
            atomic_write(path, payload)
        elif args.command == "clear":
            payload = clear(
                payload,
                provider_id=args.provider,
                selector=args.selector,
                effort=args.effort,
            )
            atomic_write(path, payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
