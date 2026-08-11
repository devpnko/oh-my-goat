#!/usr/bin/env python3
"""Resolve a provider-neutral Stacker review graph from discovery + evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SKILLS_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
CLAUDE_SCRIPTS = SKILLS_ROOT / "claude-full-swarm" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(CLAUDE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CLAUDE_SCRIPTS))

import stacker_model_resolve as league  # noqa: E402
import stacker_quota_pace as quota  # noqa: E402


SCHEMA_VERSION = "stacker.provider_neutral_stack_resolution.v1"
DEFAULT_CLAUDE_POLICY = SKILLS_ROOT / "claude-full-swarm" / "references" / "stacker-model-policy.json"
DEFAULT_RUNTIME_HEALTH = Path("~/.codex/swarm/provider-runtime-health.json")
DEFAULT_QUOTA_STATE = Path("~/.codex/swarm/provider-quota-state.json")


@dataclass(frozen=True)
class Candidate:
    provider_id: str
    selector: str
    exact_model: str
    family: str
    priority: int
    effort: str
    supported_efforts: tuple[str, ...]
    effort_basis: str
    attestor: str
    allowed_model_pattern: str
    last_attested_actual_model: str
    attestation_status: str


def choose_effort(
    model: dict[str, Any],
    *,
    allow_ultra: bool,
    excluded_efforts: set[str],
) -> tuple[str, str]:
    efforts = [str(item) for item in model.get("efforts", [])]
    preference = ("ultra", "max", "xhigh", "high", "medium", "low") if allow_ultra else (
        "max", "xhigh", "high", "medium", "low"
    )
    for desired in preference:
        if desired in efforts and desired not in excluded_efforts:
            basis = "EXPLICIT_ULTRA_OPT_IN" if desired == "ultra" else "HIGHEST_STABLE_USEFUL_EFFORT"
            return desired, basis
    fallback = str(model.get("default_effort") or "")
    if fallback and fallback not in excluded_efforts:
        return fallback, "CATALOG_DEFAULT_FALLBACK"
    return "", "NO_HEALTHY_SUPPORTED_EFFORT"


def active_runtime_exclusions(payload: dict[str, Any]) -> dict[tuple[str, str], set[str]]:
    result: dict[tuple[str, str], set[str]] = {}
    for item in payload.get("exclusions", []):
        if str(item.get("status") or "") not in {"ACTIVE", "UNTIL_REVALIDATED"}:
            continue
        provider_id = str(item.get("provider_id") or "")
        selector = str(item.get("selector") or "")
        effort = str(item.get("effort") or "*")
        if provider_id and selector:
            result.setdefault((provider_id, selector), set()).add(effort)
    return result


def build_candidates(
    snapshot: dict[str, Any],
    claude_policy: dict[str, Any],
    allow_fable: bool,
    *,
    allow_ultra: bool,
    runtime_exclusions: dict[tuple[str, str], set[str]],
) -> list[Candidate]:
    result: list[Candidate] = []
    for provider in snapshot.get("providers", []):
        provider_id = str(provider.get("provider_id") or "")
        for model in provider.get("models", []):
            if str(model.get("visibility") or "list") == "hide":
                continue
            family = str(model.get("family") or provider_id)
            if provider_id == "anthropic_claude":
                spec = claude_policy["families"].get(family)
                if not spec or (spec.get("premium_opt_in") and not allow_fable):
                    continue
                allowed_pattern = str(spec.get("actual_model_pattern") or "")
            else:
                allowed_pattern = ""
            selector = str(model.get("selector") or "")
            excluded_efforts = runtime_exclusions.get((provider_id, selector), set())
            if "*" in excluded_efforts:
                continue
            effort, effort_basis = choose_effort(
                model,
                allow_ultra=allow_ultra,
                excluded_efforts=excluded_efforts,
            )
            if not effort:
                continue
            result.append(Candidate(
                provider_id=provider_id,
                selector=selector,
                exact_model=str(model.get("exact_model") or ""),
                family=family,
                priority=int(model.get("priority", 1_000_000)),
                effort=effort,
                supported_efforts=tuple(str(item) for item in model.get("efforts", [])),
                effort_basis=effort_basis,
                attestor=str(model.get("attestor") or "provider_adapter_required"),
                allowed_model_pattern=allowed_pattern,
                last_attested_actual_model=str(model.get("last_attested_actual_model") or ""),
                attestation_status=str(model.get("attestation_status") or "NOT_ESTABLISHED"),
            ))
    return [item for item in result if item.selector]


def candidate_allowed_for_role(
    candidate: Candidate,
    role: str,
    policy: dict[str, Any],
    fable_eligible_roles: set[str],
) -> bool:
    """Apply role-family policy after provider discovery.

    Non-Claude providers remain capability candidates and are ranked by league
    evidence.  Claude families are constrained by the role's declared family
    set, and premium Fable additionally requires quota/Owner eligibility.
    """

    profile = policy["roles"][role]
    if profile.get("exact_family_required"):
        return (
            candidate.provider_id == "anthropic_claude"
            and candidate.family in set(profile.get("family_preference", []))
            and (candidate.family != "fable" or role in fable_eligible_roles)
        )
    if candidate.provider_id != "anthropic_claude":
        return True
    declared = set(profile.get("family_preference", []))
    if candidate.family not in declared:
        return False
    if candidate.family == "fable" and role not in fable_eligible_roles:
        return False
    return True


def entry_matches_candidate(entry: league.LeagueEntry, candidate: Candidate, claude_policy: dict[str, Any]) -> bool:
    if entry.provider and entry.provider != candidate.provider_id:
        return False
    model = entry.model.lower().strip()
    if candidate.provider_id == "anthropic_claude":
        if league.infer_family(model, claude_policy) != candidate.family:
            return False
        actual = candidate.last_attested_actual_model.lower().strip()
        if not actual:
            return True
        if model == actual:
            return True
        actual_tail = actual.removeprefix(f"claude-{candidate.family}-")
        actual_versions = {
            value.replace("-", ".")
            for value in re.findall(r"\d+(?:[.-]\d+)*", actual_tail)
        }
        evidence_versions = {
            value.replace("-", ".")
            for value in re.findall(r"\d+(?:[.-]\d+)*", model)
        }
        return bool(actual_versions and actual_versions & evidence_versions)
    names = {candidate.selector.lower(), candidate.exact_model.lower()}
    return model in {name for name in names if name}


def eligible_evidence(
    entries: list[league.LeagueEntry],
    candidates: list[Candidate],
    terms: list[str],
    minimum: float,
    claude_policy: dict[str, Any],
    excluded_provider: str = "",
) -> list[tuple[tuple[float, ...], league.LeagueEntry, Candidate]]:
    result = []
    for entry in entries:
        if not league.entry_is_eligible(entry, minimum):
            continue
        fit = league.role_fit(entry, terms)
        if fit <= 0:
            continue
        for candidate in candidates:
            if excluded_provider and candidate.provider_id == excluded_provider:
                continue
            if not entry_matches_candidate(entry, candidate, claude_policy):
                continue
            key = (float(fit), entry.score, league.parse_time(entry.timestamp), float(-candidate.priority))
            result.append((key, entry, candidate))
    return result


def evidence_payload(entry: league.LeagueEntry, scope: str) -> dict[str, Any]:
    return {
        "scope": scope,
        "source": entry.source,
        "provider": entry.provider,
        "model_record": entry.model,
        "role_record": entry.role,
        "task_type_record": entry.task_type,
        "score_0_100": entry.score,
        "verdict": entry.verdict,
        "timestamp": entry.timestamp,
    }


def best_discovered_per_provider(candidates: list[Candidate], role: str, policy: dict[str, Any]) -> list[Candidate]:
    profile = policy["roles"][role]
    family_rank = {family: index for index, family in enumerate(profile.get("family_preference", []))}
    grouped: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.provider_id, []).append(candidate)
    result = []
    for provider_id, items in grouped.items():
        if provider_id == "anthropic_claude":
            items.sort(key=lambda item: (family_rank.get(item.family, 1_000_000), item.priority, item.selector))
        else:
            items.sort(key=lambda item: (item.priority, item.selector))
        result.append(items[0])
    return sorted(result, key=lambda item: item.provider_id)


def candidate_payload(candidate: Candidate, status: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = asdict(candidate)
    payload["status"] = status
    payload["league_evidence"] = evidence
    payload["expected_actual_model"] = (
        candidate.exact_model or candidate.last_attested_actual_model
    )
    payload["fresh_runtime_attestation_required"] = True
    return payload


def has_comparable_role_evidence(
    candidate: Candidate,
    entries: list[league.LeagueEntry],
    terms: list[str],
    policy: dict[str, Any],
) -> bool:
    return any(
        entry_matches_candidate(entry, candidate, policy) and league.role_fit(entry, terms) > 0
        for entry in entries
    )


def role_frontier_candidates(
    role: str,
    candidates: list[Candidate],
    entries: list[league.LeagueEntry],
    policy: dict[str, Any],
    primary: Candidate | None,
) -> list[Candidate]:
    terms = list(policy["roles"][role].get("league_terms", []))
    latest = best_discovered_per_provider(candidates, role, policy)
    result = [
        candidate
        for candidate in latest
        if candidate != primary and not has_comparable_role_evidence(candidate, entries, terms, policy)
    ]
    result.sort(key=lambda candidate: (
        0 if primary and candidate.provider_id == primary.provider_id else 1,
        candidate.priority,
        candidate.provider_id,
        candidate.selector,
    ))
    return result


def resolve_role(
    role: str,
    candidates: list[Candidate],
    project_entries: list[league.LeagueEntry],
    global_entries: list[league.LeagueEntry],
    policy: dict[str, Any],
    require_frontier_intake: bool,
) -> dict[str, Any]:
    if role not in policy["roles"]:
        raise ValueError(f"unknown role: {role}")
    terms = list(policy["roles"][role].get("league_terms", []))
    minimum = float(policy["champion_score_minimum"])
    pool = eligible_evidence(project_entries, candidates, terms, minimum, policy)
    scope = "project_model_league"
    if not pool:
        pool = eligible_evidence(global_entries, candidates, terms, minimum, policy)
        scope = "global_model_league"
    if not pool:
        provisional = [candidate_payload(item, "INTAKE_REQUIRED") for item in best_discovered_per_provider(candidates, role, policy)]
        return {
            "role": role,
            "status": "INTAKE_REQUIRED",
            "primary": None,
            "provisional_candidates": provisional,
            "provider_diverse_challenger": None,
            "frontier_intake_candidates": provisional,
            "frontier_intake_required": True,
        }

    _, entry, primary = max(pool, key=lambda item: item[0])
    primary_payload = candidate_payload(primary, "ROLE_CHAMPION", evidence_payload(entry, scope))

    diversity_pool = eligible_evidence(
        project_entries, candidates, terms, minimum, policy, excluded_provider=primary.provider_id
    )
    diversity_scope = "project_model_league"
    if not diversity_pool:
        diversity_pool = eligible_evidence(
            global_entries, candidates, terms, minimum, policy, excluded_provider=primary.provider_id
        )
        diversity_scope = "global_model_league"
    if diversity_pool:
        _, diversity_entry, diversity = max(diversity_pool, key=lambda item: item[0])
        challenger = candidate_payload(
            diversity, "PROVIDER_DIVERSE_ROLE_CHAMPION", evidence_payload(diversity_entry, diversity_scope)
        )
    else:
        alternatives = [
            item for item in best_discovered_per_provider(candidates, role, policy)
            if item.provider_id != primary.provider_id
        ]
        challenger = candidate_payload(alternatives[0], "PROVISIONAL_INTAKE_REQUIRED") if alternatives else None
    frontier = role_frontier_candidates(
        role,
        candidates,
        project_entries + global_entries,
        policy,
        primary,
    )
    frontier_payloads = []
    for index, candidate in enumerate(frontier):
        status = "REQUIRED_FRONTIER_INTAKE" if require_frontier_intake and index == 0 else "PENDING_FRONTIER_INTAKE"
        frontier_payloads.append(candidate_payload(candidate, status))
    return {
        "role": role,
        "status": "FRONTIER_INTAKE_REQUIRED" if require_frontier_intake and frontier_payloads else "RESOLVED",
        "primary": primary_payload,
        "provisional_candidates": [],
        "provider_diverse_challenger": challenger,
        "frontier_intake_candidates": frontier_payloads,
        "frontier_intake_required": bool(require_frontier_intake and frontier_payloads),
    }


def coalesce_required_frontier_lanes(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for assignment in assignments:
        role = str(assignment["role"])
        for candidate in assignment.get("frontier_intake_candidates", []):
            if candidate.get("status") != "REQUIRED_FRONTIER_INTAKE":
                continue
            key = (
                str(candidate.get("provider_id") or ""),
                str(candidate.get("selector") or ""),
                str(candidate.get("effort") or ""),
            )
            lane = grouped.setdefault(key, {
                "provider_id": key[0],
                "selector": key[1],
                "effort": key[2],
                "expected_actual_model": candidate.get("expected_actual_model", ""),
                "allowed_model_pattern": candidate.get("allowed_model_pattern", ""),
                "last_attested_actual_model": candidate.get(
                    "last_attested_actual_model", ""
                ),
                "attestor": candidate.get("attestor", ""),
                "roles": [],
                "status": "REQUIRED_FRONTIER_INTAKE",
                "fresh_runtime_attestation_required": True,
            })
            lane["roles"].append(role)
    return [grouped[key] for key in sorted(grouped)]


def frontier_candidates(
    candidates: list[Candidate],
    entries: list[league.LeagueEntry],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    referenced = []
    for candidate in candidates:
        if any(entry_matches_candidate(entry, candidate, policy) for entry in entries):
            referenced.append(candidate)
    referenced_set = {(item.provider_id, item.selector) for item in referenced}
    result = []
    for candidate in candidates:
        if (candidate.provider_id, candidate.selector) in referenced_set:
            continue
        if candidate.priority != min(
            item.priority for item in candidates if item.provider_id == candidate.provider_id
        ):
            continue
        result.append(candidate_payload(candidate, "DISCOVERED_UNSCORED_FRONTIER"))
    return result


def resolve_stack(
    *,
    roles: list[str],
    snapshot: dict[str, Any],
    policy: dict[str, Any],
    project_entries: list[league.LeagueEntry],
    global_entries: list[league.LeagueEntry],
    allow_fable: bool,
    risk_class: str = "auto",
    allow_ultra: bool = False,
    runtime_health: dict[str, Any] | None = None,
    quota_state: dict[str, Any] | None = None,
    fable_routing_mode: str = "auto",
    now: float | None = None,
) -> dict[str, Any]:
    unknown_roles = [role for role in roles if role not in policy["roles"]]
    if unknown_roles:
        raise ValueError(f"unknown roles: {','.join(unknown_roles)}")
    effective_risk = risk_class
    if risk_class == "auto":
        high_impact_roles = {
            "semantic", "mechanical", "atomicity", "architect_skeptic", "verifier",
            "named_advisor", "fable_final", "intent_gap", "strategy_planner",
            "correction_architect", "ux_product", "orchestrator",
        }
        effective_risk = "high" if any(role in high_impact_roles for role in roles) else "standard"
    require_frontier_intake = effective_risk in {"high", "critical"}
    exclusions = active_runtime_exclusions(runtime_health or {})
    effective_fable_mode = "force" if allow_fable else fable_routing_mode
    fable_routing = quota.fable_pace_decision(
        quota_state=quota_state,
        policy=policy,
        routing_mode=effective_fable_mode,
        now=now,
    )
    fable_eligible_roles = set(fable_routing["eligible_roles"])
    include_fable = bool(set(roles) & fable_eligible_roles)
    candidates = build_candidates(
        snapshot,
        policy,
        include_fable,
        allow_ultra=allow_ultra,
        runtime_exclusions=exclusions,
    )
    assignments = [
        resolve_role(
            role,
            [
                candidate for candidate in candidates
                if candidate_allowed_for_role(
                    candidate,
                    role,
                    policy,
                    fable_eligible_roles,
                )
            ],
            project_entries,
            global_entries,
            policy,
            require_frontier_intake,
        )
        for role in roles
    ]
    frontier = frontier_candidates(candidates, project_entries + global_entries, policy)
    unresolved = [item["role"] for item in assignments if item["primary"] is None]
    frontier_required_roles = [item["role"] for item in assignments if item.get("frontier_intake_required")]
    required_frontier_lanes = coalesce_required_frontier_lanes(assignments)
    if unresolved:
        status = "INTAKE_REQUIRED"
    elif frontier_required_roles:
        status = "FRONTIER_INTAKE_REQUIRED"
    else:
        status = "RESOLVED"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "canonical": False,
        "authority": "NONE",
        "selection_policy": "ROLE_CHAMPION_PLUS_FRONTIER_INTAKE_PLUS_QUOTA_PACED_PREMIUM_ELIGIBILITY",
        "risk_class": effective_risk,
        "discovery_observation_digest": snapshot.get("observation_digest", ""),
        "discovery_update_detected": bool(snapshot.get("update_detected")),
        "unresolved_roles": unresolved,
        "frontier_intake_required_roles": frontier_required_roles,
        "assignments": assignments,
        "frontier_intake_candidates": frontier,
        "required_frontier_intake_lanes": required_frontier_lanes,
        "promotion_rule": "DISCOVERY_NEVER_PROMOTES;_ROLE_SCORE_AND_ATTESTED_INTAKE_REQUIRED",
        "runtime_rule": "EVERY_SELECTED_LANE_REQUIRES_FRESH_FIRST_RESPONSE_AND_FINAL_ATTESTATION",
        "premium_routing": {
            **fable_routing,
            "requested_eligible_roles": [role for role in roles if role in fable_eligible_roles],
            "requested_ineligible_roles": [role for role in roles if role not in fable_eligible_roles],
            "launch_effect": "NONE;_ROUTING_HINT_ONLY",
        },
        "effort_policy": {
            "default_ceiling": "max",
            "ultra": "EXPLICIT_OPT_IN_AND_RUNTIME_HEALTH_REQUIRED",
            "allow_ultra": allow_ultra,
            "codex_lane_runner": str(Path(__file__).with_name("stacker_codex_lane.py")),
            "claude_lane_runner": str(
                SKILLS_ROOT / "claude-full-swarm" / "scripts" / "stacker_claude_lane.py"
            ),
            "ultra_watchdog_defaults": {
                "max_total_sessions": 100,
                "max_tree_depth": 8,
                "max_concurrent_agents": 32,
                "timeout_seconds": 7200,
            },
            "ambient_1000_slot_inheritance": "FORBIDDEN",
            "infrastructure_failure_scoring": "DO_NOT_SCORE_AS_MODEL_QUALITY",
        },
        "review_planning": {
            "schema_version": "stacker.evidence_aware_review_planning.v1",
            "compiler": str(Path(__file__).with_name("stacker_review_graph.py")),
            "planner_role": "DERIVED_REVIEW_GRAPH_COMPILER",
            "executor_role": "ARVIS_EXECUTION_SUPERVISION",
            "deterministic_fact_reuse": "ALLOWED_WITH_PRODUCER_AND_RAW_LOCATOR_BINDING",
            "model_verdict_cache": "FORBIDDEN",
            "mechanical_slices": "PARALLEL_WHEN_RESOURCE_AND_PROVIDER_CAPS_ALLOW",
            "mechanical_champion_synthesis": "REQUIRED_BEFORE_TRIAD_JOIN",
            "fable_dependency": "COMPLETED_TRIAD_REQUIRED",
            "authority": "NONE",
            "canonical_state_effect": "NONE",
            "cost_receipt": "REPORTING_ONLY_NOT_FAST_PATH_PROOF",
        },
        "runtime_health_exclusions_applied": sum(len(items) for items in exclusions.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roles", default="semantic,mechanical,atomicity")
    parser.add_argument("--project", default="")
    parser.add_argument("--discovery-state", default="~/.codex/swarm/model-discovery-state.json")
    parser.add_argument("--policy", default=str(DEFAULT_CLAUDE_POLICY))
    parser.add_argument("--project-league", default="")
    parser.add_argument("--global-league", default="~/.codex/swarm/model-league.md")
    parser.add_argument("--runtime-health", default=str(DEFAULT_RUNTIME_HEALTH))
    parser.add_argument("--quota-state", default=str(DEFAULT_QUOTA_STATE))
    parser.add_argument("--risk-class", choices=("auto", "standard", "high", "critical"), default="auto")
    parser.add_argument("--allow-ultra", action="store_true")
    parser.add_argument(
        "--fable-routing",
        choices=("auto", "off", "force"),
        default="auto",
        help="auto uses fresh model-scoped quota; force is an explicit Owner policy override",
    )
    parser.add_argument(
        "--allow-fable",
        action="store_true",
        help="backward-compatible alias for --fable-routing force",
    )
    args = parser.parse_args()
    try:
        snapshot = json.loads(Path(args.discovery_state).expanduser().read_text(encoding="utf-8"))
        policy = league.load_policy(Path(args.policy).expanduser())
        project_path = args.project_league
        if not project_path and args.project:
            project_path = f"~/.codex/swarm/projects/{args.project}-model-league.md"
        project_entries = league.read_league(Path(project_path).expanduser(), "project") if project_path else []
        global_entries = league.read_league(Path(args.global_league).expanduser(), "global")
        runtime_health_path = Path(args.runtime_health).expanduser()
        runtime_health = (
            json.loads(runtime_health_path.read_text(encoding="utf-8"))
            if runtime_health_path.is_file()
            else {}
        )
        quota_state_path = Path(args.quota_state).expanduser()
        quota_state = (
            json.loads(quota_state_path.read_text(encoding="utf-8"))
            if quota_state_path.is_file()
            else {}
        )
        result = resolve_stack(
            roles=[item.strip() for item in args.roles.split(",") if item.strip()],
            snapshot=snapshot,
            policy=policy,
            project_entries=project_entries,
            global_entries=global_entries,
            allow_fable=args.allow_fable,
            risk_class=args.risk_class,
            allow_ultra=args.allow_ultra,
            runtime_health=runtime_health,
            quota_state=quota_state,
            fable_routing_mode=args.fable_routing,
        )
        result["project"] = args.project
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "ERROR", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "RESOLVED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
