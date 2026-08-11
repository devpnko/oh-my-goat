#!/usr/bin/env python3
"""Discover locally exposed model products without promoting any model.

The snapshot is a derived routing observation.  It is neither a model registry
nor Stack Authority.  Promotion remains evidence-based through Model League.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "stacker.provider_model_discovery.v1"


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def stable_inventory_payload(inventory: dict[str, Any]) -> dict[str, Any]:
    """Return only routing-semantic fields; omit observation freshness."""
    return {
        key: value
        for key, value in inventory.items()
        if key not in {"inventory_digest", "catalog_fetched_at", "observed_at", "harness"}
    }


def runtime_observations(previous: dict[str, Any] | None, paths: list[str]) -> list[dict[str, Any]]:
    observed = {
        (str(item.get("provider_id")), str(item.get("selector"))): dict(item)
        for item in (previous or {}).get("runtime_alias_observations", [])
        if item.get("provider_id") and item.get("selector")
    }
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        schema = str(payload.get("schema_version") or "")
        established_status = (
            payload.get("status") == "ESTABLISHED"
            or (schema == "stacker.claude_lane_watchdog.v1" and payload.get("status") == "PASS")
        )
        if not established_status:
            continue
        if schema == "claude.actual_model_attestation.v1":
            provider_id = "anthropic_claude"
            selector = str(payload.get("requested_selector") or "")
            actual_model = str(payload.get("final_actual_model") or "")
            versions = list(payload.get("observed_cli_versions") or [])
            harness_version = str(versions[0]) if len(versions) == 1 else ""
        elif schema == "codex.actual_model_attestation.v1":
            provider_id = "openai_codex"
            selector = str(payload.get("expected_model") or "")
            models = list(payload.get("actual_models") or [])
            actual_model = str(models[0]) if len(models) == 1 else ""
            versions = list(payload.get("actual_cli_versions") or [])
            harness_version = str(versions[0]) if len(versions) == 1 else ""
        elif schema == "stacker.claude_lane_watchdog.v1" and payload.get("status") == "PASS":
            provider_id = "anthropic_claude"
            policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
            selector = str(policy.get("requested_selector") or "")
            actual_model = str(payload.get("first_actual_model") or "")
            harness_version = str(policy.get("actual_cli_version") or "")
        else:
            continue
        if not selector or not actual_model:
            continue
        observed[(provider_id, selector)] = {
            "provider_id": provider_id,
            "selector": selector,
            "actual_model": actual_model,
            "harness_version": harness_version,
            "attestation_schema": schema,
            "attestation_status": "ESTABLISHED",
        }
    return [observed[key] for key in sorted(observed)]


def apply_runtime_observations(providers: list[dict[str, Any]], observations: list[dict[str, Any]]) -> None:
    lookup = {
        (str(item.get("provider_id")), str(item.get("selector"))): item
        for item in observations
    }
    for provider in providers:
        provider_id = str(provider.get("provider_id") or "")
        for model in provider.get("models", []):
            observation = lookup.get((provider_id, str(model.get("selector") or "")))
            if not observation:
                continue
            model["last_attested_actual_model"] = observation["actual_model"]
            model["last_attested_harness_version"] = observation["harness_version"]
            model["attestation_status"] = observation["attestation_status"]
        if provider.get("models"):
            provider["inventory_digest"] = digest(stable_inventory_payload(provider))


def run(argv: list[str], timeout: int = 10) -> str:
    process = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    if process.returncode != 0:
        raise ValueError(f"command failed ({process.returncode}): {' '.join(argv)}")
    return (process.stdout or process.stderr).strip()


def resolved_executable(command: str) -> str:
    discovered = shutil.which(command)
    return str(Path(discovered or command).expanduser().resolve())


def harness_identity(executable: str) -> str:
    path = Path(executable)
    if "cmux-cli-shims" in path.parts:
        return f"cmux-cli-shim:{path.name}"
    return str(path)


def version_token(output: str) -> str:
    fields = output.strip().split()
    if not fields:
        raise ValueError("empty harness version")
    return fields[0]


def claude_aliases_from_help(help_text: str) -> list[str]:
    """Extract moving aliases from the installed CLI's --model description."""
    lines = help_text.splitlines()
    block: list[str] = []
    collecting = False
    option_start = re.compile(r"^\s{2}(?:-[A-Za-z],\s+)?--[A-Za-z0-9-]+")
    for line in lines:
        if not collecting and re.search(r"(?:^|\s)--model(?:\s|<|$)", line):
            collecting = True
            block.append(line)
            continue
        if collecting:
            if option_start.match(line):
                break
            block.append(line)
    aliases: list[str] = []
    for token in re.findall(r"['`]([a-z][a-z0-9._-]*)['`]", "\n".join(block)):
        if token.startswith("claude-") or token in aliases:
            continue
        aliases.append(token)
    return aliases


def discover_claude(claude_bin: str) -> dict[str, Any]:
    executable = resolved_executable(claude_bin)
    version = version_token(run([executable, "--version"]))
    help_text = run([executable, "--help"])
    aliases = claude_aliases_from_help(help_text)
    models = [{
        "selector": alias,
        "exact_model": "",
        "family": alias,
        "priority": index + 1,
        "visibility": "list",
        "efforts": ["low", "medium", "high", "xhigh", "max"],
        "requires_runtime_attestation": True,
        "attestor": "claude_jsonl",
    } for index, alias in enumerate(aliases)]
    inventory = {
        "provider_id": "anthropic_claude",
        "harness": executable,
        "harness_identity": harness_identity(executable),
        "harness_version": version,
        "discovery_source": "claude_cli_help_moving_aliases",
        "models": models,
    }
    inventory["inventory_digest"] = digest(stable_inventory_payload(inventory))
    return inventory


def discover_codex(codex_bin: str, cache_path: Path) -> dict[str, Any]:
    executable = resolved_executable(codex_bin)
    version_output = run([executable, "--version"])
    version = version_output.strip().split()[-1]
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    models: list[dict[str, Any]] = []
    for raw in cache.get("models", []):
        if not isinstance(raw, dict) or not raw.get("slug"):
            continue
        efforts = [
            str(item.get("effort"))
            for item in raw.get("supported_reasoning_levels", [])
            if isinstance(item, dict) and item.get("effort")
        ]
        models.append({
            "selector": str(raw["slug"]),
            "exact_model": str(raw["slug"]),
            "family": "openai_codex",
            "display_name": str(raw.get("display_name") or raw["slug"]),
            "description": str(raw.get("description") or ""),
            "priority": int(raw.get("priority", 1_000_000)),
            "visibility": str(raw.get("visibility") or "unknown"),
            "efforts": efforts,
            "default_effort": str(raw.get("default_reasoning_level") or ""),
            "context_window": int(raw.get("context_window") or 0),
            "input_modalities": list(raw.get("input_modalities") or []),
            "supported_in_api": bool(raw.get("supported_in_api")),
            "requires_runtime_attestation": True,
            "attestor": "codex_jsonl",
        })
    models.sort(key=lambda item: (item["priority"], item["selector"]))
    inventory = {
        "provider_id": "openai_codex",
        "harness": executable,
        "harness_identity": harness_identity(executable),
        "harness_version": version,
        "discovery_source": "codex_models_cache",
        "catalog_path": str(cache_path.resolve()),
        "catalog_client_version": str(cache.get("client_version") or ""),
        "catalog_fetched_at": str(cache.get("fetched_at") or ""),
        "models": models,
    }
    inventory["inventory_digest"] = digest(stable_inventory_payload(inventory))
    return inventory


def configured_external_providers(config_path: Path) -> list[dict[str, Any]]:
    if not config_path.is_file():
        return []
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    result: list[dict[str, Any]] = []
    for provider_id, raw in sorted((config.get("model_providers") or {}).items()):
        if not isinstance(raw, dict):
            continue
        result.append({
            "provider_id": str(provider_id),
            "display_name": str(raw.get("name") or provider_id),
            "base_url": str(raw.get("base_url") or ""),
            "discovery_status": "CONFIGURED_NO_LOCAL_CATALOG",
            "models": [],
        })
    return result


def discover_generic_catalog(spec: str) -> dict[str, Any]:
    if ":" not in spec:
        raise ValueError("--catalog must be PROVIDER_ID:PATH")
    provider_id, raw_path = spec.split(":", 1)
    path = Path(raw_path).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_models = payload.get("models", []) if isinstance(payload, dict) else payload
    if not isinstance(raw_models, list):
        raise ValueError(f"generic catalog models must be a list: {path}")
    models = []
    for index, raw in enumerate(raw_models):
        if isinstance(raw, str):
            raw = {"id": raw}
        if not isinstance(raw, dict):
            continue
        identifier = str(raw.get("id") or raw.get("slug") or raw.get("name") or "").strip()
        if not identifier:
            continue
        selector = str(raw.get("alias") or raw.get("selector") or identifier).strip()
        models.append({
            "selector": selector,
            "exact_model": identifier,
            "family": str(raw.get("family") or provider_id),
            "display_name": str(raw.get("display_name") or raw.get("name") or identifier),
            "description": str(raw.get("description") or ""),
            "priority": int(raw.get("priority", index + 1)),
            "visibility": str(raw.get("visibility") or "list"),
            "efforts": list(raw.get("efforts") or []),
            "requires_runtime_attestation": True,
            "attestor": str(raw.get("attestor") or "provider_adapter_required"),
        })
    inventory = {
        "provider_id": provider_id.strip(),
        "harness": str(payload.get("harness") or "") if isinstance(payload, dict) else "",
        "harness_version": str(payload.get("harness_version") or "") if isinstance(payload, dict) else "",
        "discovery_source": "generic_local_catalog",
        "catalog_path": str(path),
        "models": sorted(models, key=lambda item: (item["priority"], item["selector"])),
    }
    inventory["inventory_digest"] = digest(stable_inventory_payload(inventory))
    return inventory


def provider_projection(provider: dict[str, Any]) -> dict[str, Any]:
    return {
        "harness_version": provider.get("harness_version", ""),
        "harness_identity": provider.get("harness_identity", ""),
        "inventory_digest": provider.get("inventory_digest", ""),
        "models": {
            str(item.get("selector")): {
                "family": item.get("family", ""),
                "display_name": item.get("display_name", ""),
                "description": item.get("description", ""),
                "exact_model": item.get("exact_model", ""),
                "last_attested_actual_model": item.get("last_attested_actual_model", ""),
                "last_attested_harness_version": item.get("last_attested_harness_version", ""),
                "attestation_status": item.get("attestation_status", ""),
                "priority": item.get("priority"),
                "visibility": item.get("visibility", ""),
                "efforts": item.get("efforts", []),
                "default_effort": item.get("default_effort", ""),
                "context_window": item.get("context_window", 0),
                "input_modalities": item.get("input_modalities", []),
                "supported_in_api": item.get("supported_in_api", False),
                "requires_runtime_attestation": item.get("requires_runtime_attestation", False),
                "attestor": item.get("attestor", ""),
            }
            for item in provider.get("models", [])
        },
    }


def compare(previous: dict[str, Any] | None, providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if previous is None:
        return []
    old = {item["provider_id"]: provider_projection(item) for item in previous.get("providers", [])}
    new = {item["provider_id"]: provider_projection(item) for item in providers}
    changes: list[dict[str, Any]] = []
    for provider_id in sorted(old.keys() | new.keys()):
        if provider_id not in old:
            changes.append({"kind": "provider_added", "provider_id": provider_id})
            continue
        if provider_id not in new:
            changes.append({"kind": "provider_removed", "provider_id": provider_id})
            continue
        if old[provider_id]["harness_version"] != new[provider_id]["harness_version"]:
            changes.append({
                "kind": "harness_version_changed",
                "provider_id": provider_id,
                "before": old[provider_id]["harness_version"],
                "after": new[provider_id]["harness_version"],
            })
        if old[provider_id]["harness_identity"] != new[provider_id]["harness_identity"]:
            changes.append({
                "kind": "harness_route_changed",
                "provider_id": provider_id,
                "before": old[provider_id]["harness_identity"],
                "after": new[provider_id]["harness_identity"],
            })
        old_models = old[provider_id]["models"]
        new_models = new[provider_id]["models"]
        for selector in sorted(old_models.keys() | new_models.keys()):
            if selector not in old_models:
                changes.append({"kind": "model_or_alias_added", "provider_id": provider_id, "selector": selector})
            elif selector not in new_models:
                changes.append({"kind": "model_or_alias_removed", "provider_id": provider_id, "selector": selector})
            elif old_models[selector] != new_models[selector]:
                actual_changed = (
                    old_models[selector].get("last_attested_actual_model")
                    != new_models[selector].get("last_attested_actual_model")
                )
                old_actual = str(old_models[selector].get("last_attested_actual_model") or "")
                new_actual = str(new_models[selector].get("last_attested_actual_model") or "")
                if actual_changed and not old_actual and new_actual:
                    kind = "alias_resolution_established"
                elif actual_changed:
                    kind = "alias_resolution_changed"
                else:
                    kind = "model_metadata_changed"
                changes.append({
                    "kind": kind,
                    "provider_id": provider_id,
                    "selector": selector,
                })
    return changes


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claude-bin", default="/opt/homebrew/bin/claude")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--codex-cache", default="~/.codex/models_cache.json")
    parser.add_argument("--codex-config", default="~/.codex/config.toml")
    parser.add_argument("--catalog", action="append", default=[])
    parser.add_argument("--attestation", action="append", default=[])
    parser.add_argument("--state", default="~/.codex/swarm/model-discovery-state.json")
    parser.add_argument("--write-state", action="store_true")
    args = parser.parse_args()

    state_path = Path(args.state).expanduser()
    try:
        previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else None
        providers = [
            discover_claude(args.claude_bin),
            discover_codex(args.codex_bin, Path(args.codex_cache).expanduser()),
        ]
        discovered_ids = {item["provider_id"] for item in providers}
        for provider in configured_external_providers(Path(args.codex_config).expanduser()):
            if provider["provider_id"] not in discovered_ids:
                providers.append(provider)
        for spec in args.catalog:
            provider = discover_generic_catalog(spec)
            providers = [item for item in providers if item["provider_id"] != provider["provider_id"]]
            providers.append(provider)
        providers.sort(key=lambda item: item["provider_id"])
        observations = runtime_observations(previous, args.attestation)
        apply_runtime_observations(providers, observations)
        changes = compare(previous, providers)
        intake_changes = [
            item for item in changes
            if item.get("kind") != "alias_resolution_established"
        ]
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "canonical": False,
            "authority": "NONE",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "baseline_created": previous is None,
            "update_detected": bool(changes),
            "changes": changes,
            "intake_required": bool(intake_changes),
            "runtime_alias_observations": observations,
            "providers": providers,
        }
        snapshot["observation_digest"] = digest({
            "schema_version": SCHEMA_VERSION,
            "providers": {
                item["provider_id"]: provider_projection(item)
                for item in providers
            },
        })
        if args.write_state:
            atomic_write(state_path, canonical(snapshot))
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError, tomllib.TOMLDecodeError) as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "ERROR", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
