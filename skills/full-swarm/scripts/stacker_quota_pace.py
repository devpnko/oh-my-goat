#!/usr/bin/env python3
"""Normalize provider quota observations and derive bounded premium routing.

This module is deliberately read-only with respect to providers.  It consumes a
local observation (normally captured from Claude Code's status-line stdin) and
returns a non-canonical routing hint.  It never logs in, calls a provider, buys
usage, grants Authority, or launches a model lane.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


OBSERVATION_SCHEMA_VERSION = "stacker.provider_quota_observation.v1"
DECISION_SCHEMA_VERSION = "stacker.premium_quota_pace_decision.v1"


def canonical_digest(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def parse_epoch(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return float(text)
    except ValueError:
        pass
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def bounded_percentage(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or number > 100:
        return None
    return number


def infer_family(*values: Any) -> str:
    text = " ".join(str(value or "") for value in values).lower()
    for family in ("fable", "opus", "sonnet"):
        if family in text:
            return family
    return ""


def normalize_bucket(
    *,
    bucket_id: str,
    raw: dict[str, Any],
    scope: str,
    family: str = "",
    default_window_seconds: int,
) -> dict[str, Any] | None:
    used = bounded_percentage(
        raw.get("used_percentage", raw.get("utilization", raw.get("usage_percentage")))
    )
    resets_at = parse_epoch(raw.get("resets_at", raw.get("reset_at")))
    if used is None or resets_at is None:
        return None
    try:
        window_seconds = int(raw.get("window_seconds") or default_window_seconds)
    except (TypeError, ValueError):
        return None
    if window_seconds <= 0:
        return None
    return {
        "bucket_id": bucket_id,
        "scope": scope,
        "family": family,
        "used_percentage": round(used, 6),
        "resets_at": iso_utc(resets_at),
        "window_seconds": window_seconds,
    }


def iter_model_scoped(raw: Any) -> list[tuple[str, dict[str, Any]]]:
    result: list[tuple[str, dict[str, Any]]] = []
    if isinstance(raw, list):
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            label = str(
                item.get("family")
                or item.get("model")
                or item.get("model_id")
                or item.get("name")
                or index
            )
            result.append((label, item))
        return result
    if not isinstance(raw, dict):
        return result
    if any(key in raw for key in ("used_percentage", "utilization", "usage_percentage")):
        label = str(raw.get("family") or raw.get("model") or raw.get("name") or "model")
        return [(label, raw)]
    for label, item in raw.items():
        if isinstance(item, dict):
            result.append((str(label), item))
    return result


def normalize_quota_observation(
    payload: dict[str, Any],
    *,
    observed_at: float | None = None,
    provider_id: str = "anthropic_claude",
    source_kind: str = "claude_statusline_stdin",
) -> dict[str, Any]:
    """Convert Claude status-line or compatible usage JSON to a stable schema."""

    observed_epoch = observed_at if observed_at is not None else datetime.now(timezone.utc).timestamp()
    rate_limits = payload.get("rate_limits", payload)
    if not isinstance(rate_limits, dict):
        rate_limits = {}

    buckets: list[dict[str, Any]] = []
    global_specs = {
        "five_hour": 5 * 60 * 60,
        "seven_day": 7 * 24 * 60 * 60,
    }
    for bucket_id, window_seconds in global_specs.items():
        raw = rate_limits.get(bucket_id)
        if not isinstance(raw, dict):
            continue
        bucket = normalize_bucket(
            bucket_id=bucket_id,
            raw=raw,
            scope="provider",
            default_window_seconds=window_seconds,
        )
        if bucket:
            bucket["observed_at"] = iso_utc(observed_epoch)
            buckets.append(bucket)

    for label, raw in iter_model_scoped(rate_limits.get("model_scoped")):
        family = infer_family(label, raw.get("family"), raw.get("model"), raw.get("model_id"))
        if not family:
            continue
        bucket = normalize_bucket(
            bucket_id=f"model_scoped:{label}",
            raw=raw,
            scope="model_family",
            family=family,
            default_window_seconds=7 * 24 * 60 * 60,
        )
        if bucket:
            bucket["observed_at"] = iso_utc(observed_epoch)
            buckets.append(bucket)

    source_view = {"provider_id": provider_id, "rate_limits": rate_limits}
    observation = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "canonical": False,
        "authority": "NONE",
        "provider_id": provider_id,
        "observed_at": iso_utc(observed_epoch),
        "source_kind": source_kind,
        "source_digest": canonical_digest(source_view),
        "buckets": buckets,
        "model_scoped_observation": any(
            bucket["scope"] == "model_family" for bucket in buckets
        ),
    }
    observation["observation_digest"] = canonical_digest(observation)
    return observation


def bucket_key(bucket: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(bucket.get("bucket_id") or ""),
        str(bucket.get("scope") or ""),
        str(bucket.get("family") or ""),
    )


def choose_newer_bucket(
    previous: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
    *,
    now: float,
) -> dict[str, Any] | None:
    if previous is None:
        previous_valid = False
    else:
        previous_reset = parse_epoch(previous.get("resets_at"))
        previous_valid = previous_reset is not None and previous_reset > now
    if incoming is None:
        incoming_valid = False
    else:
        incoming_reset = parse_epoch(incoming.get("resets_at"))
        incoming_valid = incoming_reset is not None and incoming_reset > now
    if incoming_valid and not previous_valid:
        return incoming
    if previous_valid and not incoming_valid:
        return previous
    if not previous_valid and not incoming_valid:
        return None

    assert previous is not None and incoming is not None
    previous_reset = parse_epoch(previous.get("resets_at"))
    incoming_reset = parse_epoch(incoming.get("resets_at"))
    assert previous_reset is not None and incoming_reset is not None
    if incoming_reset > previous_reset:
        return incoming
    if incoming_reset < previous_reset:
        return previous

    previous_used = bounded_percentage(previous.get("used_percentage"))
    incoming_used = bounded_percentage(incoming.get("used_percentage"))
    if previous_used is None:
        return incoming
    if incoming_used is None:
        return previous
    if incoming_used > previous_used:
        return incoming
    if incoming_used < previous_used:
        # Concurrent Claude sessions can publish an older cached observation
        # after a newer one.  Within one reset epoch, usage never regains trust
        # merely because the later writer reports a lower number.
        return previous
    return incoming


def merge_quota_observations(
    previous: dict[str, Any] | None,
    incoming: dict[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Merge concurrent local observations without stale last-writer wins."""

    current = now if now is not None else datetime.now(timezone.utc).timestamp()
    prior = previous or {}
    previous_by_key = {
        bucket_key(item): item
        for item in prior.get("buckets", [])
        if isinstance(item, dict)
    }
    incoming_by_key = {
        bucket_key(item): item
        for item in incoming.get("buckets", [])
        if isinstance(item, dict)
    }
    selected: list[dict[str, Any]] = []
    for key in sorted(set(previous_by_key) | set(incoming_by_key)):
        winner = choose_newer_bucket(
            previous_by_key.get(key),
            incoming_by_key.get(key),
            now=current,
        )
        if winner:
            selected.append(dict(winner))

    bucket_observed_epochs = [
        parsed
        for parsed in (parse_epoch(item.get("observed_at")) for item in selected)
        if parsed is not None
    ]
    incoming_observed = parse_epoch(incoming.get("observed_at")) or current
    observed_epoch = max(bucket_observed_epochs, default=incoming_observed)
    merged = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "canonical": False,
        "authority": "NONE",
        "provider_id": str(incoming.get("provider_id") or prior.get("provider_id") or "anthropic_claude"),
        "observed_at": iso_utc(observed_epoch),
        "source_kind": "merged_local_statusline_observations",
        "source_digest": canonical_digest({
            "previous": prior.get("observation_digest", ""),
            "incoming": incoming.get("observation_digest", ""),
        }),
        "buckets": selected,
        "model_scoped_observation": any(
            item.get("scope") == "model_family" for item in selected
        ),
    }
    merged["observation_digest"] = canonical_digest(merged)
    return merged


def classify_bucket(
    bucket: dict[str, Any],
    *,
    now: float,
    target_utilization_percentage: float,
    tolerance_percentage: float,
    reserve_percentage: float,
) -> dict[str, Any]:
    used = bounded_percentage(bucket.get("used_percentage"))
    resets_at = parse_epoch(bucket.get("resets_at"))
    try:
        window_seconds = float(bucket.get("window_seconds"))
    except (TypeError, ValueError):
        window_seconds = 0
    if used is None or resets_at is None or window_seconds <= 0:
        return {"bucket_id": bucket.get("bucket_id", ""), "mode": "UNKNOWN"}

    seconds_to_reset = resets_at - now
    if seconds_to_reset <= 0 or seconds_to_reset > window_seconds * 1.25:
        return {"bucket_id": bucket.get("bucket_id", ""), "mode": "UNKNOWN"}

    elapsed_percentage = max(
        0.0,
        min(100.0, (1.0 - (seconds_to_reset / window_seconds)) * 100.0),
    )
    desired_used = target_utilization_percentage * elapsed_percentage / 100.0
    pace_delta = desired_used - used
    remaining = 100.0 - used
    if remaining <= reserve_percentage:
        mode = "RESERVE"
    elif pace_delta >= tolerance_percentage:
        mode = "SURPLUS"
    elif pace_delta <= -tolerance_percentage:
        mode = "CONSERVE"
    else:
        mode = "BALANCED"
    return {
        "bucket_id": bucket.get("bucket_id", ""),
        "scope": bucket.get("scope", ""),
        "family": bucket.get("family", ""),
        "mode": mode,
        "used_percentage": round(used, 3),
        "remaining_percentage": round(remaining, 3),
        "elapsed_percentage": round(elapsed_percentage, 3),
        "desired_used_percentage": round(desired_used, 3),
        "underuse_pressure_percentage": round(pace_delta, 3),
        "resets_at": bucket.get("resets_at", ""),
    }


def unique_roles(*groups: list[str]) -> list[str]:
    result: list[str] = []
    for group in groups:
        for role in group:
            if role not in result:
                result.append(role)
    return result


def fable_pace_decision(
    *,
    quota_state: dict[str, Any] | None,
    policy: dict[str, Any],
    routing_mode: str = "auto",
    now: float | None = None,
) -> dict[str, Any]:
    """Return role eligibility; never launch work or grant authority."""

    if routing_mode not in {"auto", "off", "force"}:
        raise ValueError(f"unsupported Fable routing mode: {routing_mode}")
    config = policy.get("premium_routing", {}).get("fable", {})
    tiers = config.get("role_tiers", {})
    exact_roles = [str(item) for item in tiers.get("exact", ["named_advisor", "fable_final"])]
    core_roles = [str(item) for item in tiers.get("core", [])]
    expanded_roles = [str(item) for item in tiers.get("expanded", [])]
    all_roles = unique_roles(exact_roles, core_roles, expanded_roles)
    base = {
        "schema_version": DECISION_SCHEMA_VERSION,
        "canonical": False,
        "authority": "NONE",
        "family": "fable",
        "routing_mode": routing_mode,
        "exact_roles": exact_roles,
        "core_roles": core_roles,
        "expanded_roles": expanded_roles,
        "quota_observation_digest": "",
        "target_bucket_decisions": [],
        "guard_bucket_decisions": [],
    }
    if routing_mode == "off":
        return {
            **base,
            "pace_mode": "OFF",
            "freshness": "NOT_APPLICABLE",
            "eligible_roles": [],
            "automatic_expansion": False,
            "selection_basis": "FABLE_ROUTING_DISABLED",
        }
    if routing_mode == "force":
        return {
            **base,
            "pace_mode": "FORCE",
            "freshness": "OWNER_POLICY_OVERRIDE",
            "eligible_roles": all_roles,
            "automatic_expansion": bool(core_roles or expanded_roles),
            "selection_basis": "EXPLICIT_FABLE_ROUTING_OVERRIDE",
        }

    state = quota_state or {}
    observed_at = parse_epoch(state.get("observed_at"))
    current = now if now is not None else datetime.now(timezone.utc).timestamp()
    max_age = float(config.get("max_snapshot_age_seconds", 900))
    if observed_at is None or current - observed_at < -60 or current - observed_at > max_age:
        return {
            **base,
            "pace_mode": "UNKNOWN",
            "freshness": "MISSING_OR_STALE",
            "eligible_roles": exact_roles,
            "automatic_expansion": False,
            "selection_basis": "NO_FRESH_QUOTA_EVIDENCE;_EXACT_FABLE_ROLES_ONLY",
        }

    target_utilization = float(config.get("target_utilization_percentage", 95))
    tolerance = float(config.get("pace_tolerance_percentage", 5))
    reserve = float(config.get("reserve_percentage", 5))
    buckets = []
    for item in state.get("buckets", []):
        if not isinstance(item, dict):
            continue
        bucket_observed = parse_epoch(item.get("observed_at"))
        if bucket_observed is None:
            bucket_observed = observed_at
        if bucket_observed is None or current - bucket_observed < -60 or current - bucket_observed > max_age:
            continue
        buckets.append(item)
    target_buckets = [
        item for item in buckets
        if item.get("scope") == "model_family" and item.get("family") == "fable"
    ]
    guard_buckets = [item for item in buckets if item.get("scope") == "provider"]
    target_decisions = [
        classify_bucket(
            item,
            now=current,
            target_utilization_percentage=target_utilization,
            tolerance_percentage=tolerance,
            reserve_percentage=reserve,
        )
        for item in target_buckets
    ]
    guard_decisions = [
        classify_bucket(
            item,
            now=current,
            target_utilization_percentage=target_utilization,
            tolerance_percentage=tolerance,
            reserve_percentage=reserve,
        )
        for item in guard_buckets
    ]
    base.update({
        "quota_observation_digest": str(state.get("observation_digest") or ""),
        "target_bucket_decisions": target_decisions,
        "guard_bucket_decisions": guard_decisions,
    })
    if not target_decisions:
        guard_modes = {item["mode"] for item in guard_decisions}
        if not guard_decisions or "UNKNOWN" in guard_modes:
            return {
                **base,
                "pace_mode": "UNKNOWN",
                "freshness": "FRESH_WITHOUT_USABLE_FABLE_OR_PROVIDER_QUOTA",
                "eligible_roles": exact_roles,
                "automatic_expansion": False,
                "selection_basis": "NO_USABLE_QUOTA_PACING_EVIDENCE;_EXACT_FABLE_ROLES_ONLY",
            }
        if "RESERVE" in guard_modes:
            proxy_mode = "PROVIDER_PROXY_RESERVE"
            eligible = exact_roles
        elif "CONSERVE" in guard_modes:
            proxy_mode = "PROVIDER_PROXY_CONSERVE"
            eligible = exact_roles
        else:
            # Official Claude status-line data currently guarantees provider-wide
            # 5h/7d buckets, not a Fable-only bucket.  It can justify core
            # high-leverage use, but never the broader surplus-only role tier.
            proxy_mode = "PROVIDER_PROXY_CORE"
            eligible = unique_roles(exact_roles, core_roles)
        return {
            **base,
            "pace_mode": proxy_mode,
            "freshness": "FRESH_PROVIDER_WIDE_PROXY",
            "eligible_roles": eligible,
            "automatic_expansion": len(eligible) > len(exact_roles),
            "selection_basis": "PROVIDER_WIDE_QUOTA_PROXY;_EXPANDED_TIER_REQUIRES_MODEL_SCOPED_FABLE_QUOTA",
        }
    if any(item["mode"] == "UNKNOWN" for item in target_decisions):
        return {
            **base,
            "pace_mode": "UNKNOWN",
            "freshness": "FRESH_WITH_UNUSABLE_MODEL_SCOPED_FABLE_QUOTA",
            "eligible_roles": exact_roles,
            "automatic_expansion": False,
            "selection_basis": "INVALID_FABLE_QUOTA_BUCKET;_EXACT_FABLE_ROLES_ONLY",
        }
    if not guard_decisions or any(item["mode"] == "UNKNOWN" for item in guard_decisions):
        return {
            **base,
            "pace_mode": "UNKNOWN",
            "freshness": "FRESH_FABLE_BUCKET_WITHOUT_USABLE_PROVIDER_GUARD",
            "eligible_roles": exact_roles,
            "automatic_expansion": False,
            "selection_basis": "FABLE_QUOTA_CANNOT_OVERRIDE_MISSING_PROVIDER_GUARD",
        }

    target_modes = {item["mode"] for item in target_decisions}
    if "RESERVE" in target_modes:
        pace_mode = "RESERVE"
    elif "CONSERVE" in target_modes:
        pace_mode = "CONSERVE"
    elif target_modes == {"SURPLUS"}:
        pace_mode = "SURPLUS"
    else:
        pace_mode = "BALANCED"

    guard_modes = {item["mode"] for item in guard_decisions}
    if "RESERVE" in guard_modes:
        pace_mode = "RESERVE"
    elif "CONSERVE" in guard_modes and pace_mode in {"SURPLUS", "BALANCED"}:
        pace_mode = "CONSERVE"

    if pace_mode == "SURPLUS":
        eligible = all_roles
    elif pace_mode == "BALANCED":
        eligible = unique_roles(exact_roles, core_roles)
    else:
        eligible = exact_roles
    return {
        **base,
        "pace_mode": pace_mode,
        "freshness": "FRESH",
        "eligible_roles": eligible,
        "automatic_expansion": len(eligible) > len(exact_roles),
        "selection_basis": f"FRESH_MODEL_SCOPED_FABLE_QUOTA_{pace_mode}",
    }
