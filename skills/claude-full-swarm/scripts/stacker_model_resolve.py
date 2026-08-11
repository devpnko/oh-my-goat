#!/usr/bin/env python3
"""Resolve a Stacker role to the strongest suitable moving model selector.

The resolver deliberately chooses a model *family alias* (for example, the
current ``opus`` alias), never a frozen version such as ``opus-4.8``.  Exact
model identity is established after launch by ``claude_lane_attest.py``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "stacker.model_resolution.v1"
DEFAULT_POLICY = Path(__file__).resolve().parent.parent / "references" / "stacker-model-policy.json"
FULL_SWARM_SCRIPTS = Path(__file__).resolve().parents[2] / "full-swarm" / "scripts"
if str(FULL_SWARM_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(FULL_SWARM_SCRIPTS))

import stacker_quota_pace as quota  # noqa: E402

DEFAULT_QUOTA_STATE = Path("~/.codex/swarm/provider-quota-state.json")


@dataclass(frozen=True)
class LeagueEntry:
    source: str
    model: str
    role: str
    task_type: str
    score: float
    verdict: str
    availability: str
    timestamp: str
    provider: str = ""


def load_policy(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        policy = json.load(handle)
    if policy.get("schema_version") != "stacker.model_selection_policy.v1":
        raise ValueError(f"unsupported policy schema: {policy.get('schema_version')!r}")
    return policy


def parse_blocks(text: str, source: str) -> list[LeagueEntry]:
    entries: list[LeagueEntry] = []
    current: dict[str, str] = {}

    def flush() -> None:
        nonlocal current
        if "model" not in current or "score_0_100" not in current:
            current = {}
            return
        try:
            score = float(current["score_0_100"])
        except ValueError:
            current = {}
            return
        entries.append(LeagueEntry(
            source=source,
            model=current.get("model", "").strip(),
            role=current.get("role", "").strip(),
            task_type=current.get("task_type", "").strip(),
            score=score,
            verdict=current.get("verdict", "").strip().lower(),
            availability=current.get("availability", "").strip().lower(),
            timestamp=(current.get("timestamp") or current.get("date") or "").strip(),
            provider=current.get("provider", "").strip(),
        ))
        current = {}

    for raw in text.splitlines() + [""]:
        line = raw.strip()
        if not line:
            flush()
            continue
        match = re.match(r"^-?\s*([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.*?)\s*$", line)
        if not match:
            continue
        key, value = match.groups()
        key = key.lower()
        if key in {"timestamp", "date"} and current and ("model" in current or key in current):
            flush()
        current[key] = value
    return entries


def read_league(path: Path, source: str) -> list[LeagueEntry]:
    if not path.is_file():
        return []
    return parse_blocks(path.read_text(encoding="utf-8"), source)


def infer_family(model: str, policy: dict[str, Any]) -> str:
    normalized = model.lower().strip()
    for family, spec in policy["families"].items():
        for pattern in spec.get("model_patterns", []):
            if re.search(pattern, normalized):
                return family
    return ""


def normalized_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.lower()) if token}


def role_fit(entry: LeagueEntry, terms: list[str]) -> int:
    haystack = normalized_tokens(f"{entry.role} {entry.task_type}")
    requested = [normalized_tokens(term) for term in terms]
    return max((len(tokens & haystack) for tokens in requested), default=0)


def parse_time(value: str) -> float:
    if not value:
        return 0.0
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return 0.0


def entry_is_eligible(entry: LeagueEntry, minimum: float) -> bool:
    if entry.score < minimum:
        return False
    if entry.availability in {"unavailable", "disabled", "blocked"}:
        return False
    if entry.verdict in {"fail", "failed", "weak"}:
        return False
    return True


def choose_resolution(
    *,
    role: str,
    policy: dict[str, Any],
    project_entries: list[LeagueEntry],
    global_entries: list[LeagueEntry],
    available_aliases: set[str],
    allow_premium_advisor: bool = False,
    premium_eligible_roles: set[str] | None = None,
    exact_named_model: str = "",
) -> dict[str, Any]:
    if role not in policy["roles"]:
        raise ValueError(f"unknown role: {role}")
    profile = policy["roles"][role]
    families = policy["families"]

    if exact_named_model:
        family = infer_family(exact_named_model, policy)
        if not family:
            raise ValueError(f"exact named model is outside policy families: {exact_named_model}")
        selector = families[family]["selector"]
        if selector not in available_aliases:
            raise ValueError(f"required named-model selector is unavailable: {selector}")
        return {
            "selected_family": family,
            "requested_selector": selector,
            "expected_model": exact_named_model,
            "allowed_model_pattern": "",
            "named_model_gate": True,
            "selection_basis": "exact_named_model_gate",
            "league_evidence": None,
        }

    minimum = float(policy["champion_score_minimum"])
    terms = list(profile.get("league_terms", []))
    preferences = list(profile.get("family_preference", []))
    preference_rank = {family: len(preferences) - index for index, family in enumerate(preferences)}
    premium_allowed = allow_premium_advisor or role in (premium_eligible_roles or set())

    def candidates(entries: list[LeagueEntry]) -> list[tuple[tuple[float, ...], LeagueEntry, str]]:
        result: list[tuple[tuple[float, ...], LeagueEntry, str]] = []
        for entry in entries:
            family = infer_family(entry.model, policy)
            if not family or family not in preferences:
                continue
            spec = families[family]
            if spec.get("premium_opt_in") and not premium_allowed:
                continue
            selector = spec["selector"]
            if selector not in available_aliases or not entry_is_eligible(entry, minimum):
                continue
            fit = role_fit(entry, terms)
            if fit <= 0:
                continue
            key = (float(fit), entry.score, float(preference_rank.get(family, 0)), parse_time(entry.timestamp))
            result.append((key, entry, family))
        return result

    # Project evidence owns routing when it contains a suitable champion;
    # global evidence is consulted only if the project has none.
    pool = candidates(project_entries)
    evidence_scope = "project_model_league"
    if not pool:
        pool = candidates(global_entries)
        evidence_scope = "global_model_league"

    if pool:
        _, entry, family = max(pool, key=lambda item: item[0])
        basis = f"highest_suitable_role_champion:{evidence_scope}"
        evidence: dict[str, Any] | None = {
            "source": entry.source,
            "model_record": entry.model,
            "role_record": entry.role,
            "task_type_record": entry.task_type,
            "score_0_100": entry.score,
            "verdict": entry.verdict,
            "timestamp": entry.timestamp,
        }
    else:
        family = next((
            candidate for candidate in preferences
            if candidate in families
            and families[candidate]["selector"] in available_aliases
            and (premium_allowed or not families[candidate].get("premium_opt_in"))
        ), "")
        if not family:
            raise ValueError(f"no available suitable model family for role {role}")
        basis = "policy_preference_no_comparable_champion"
        evidence = None

    spec = families[family]
    return {
        "selected_family": family,
        "requested_selector": spec["selector"],
        "expected_model": "",
        "allowed_model_pattern": spec["actual_model_pattern"],
        "named_model_gate": False,
        "selection_basis": basis,
        "league_evidence": evidence,
    }


def cli_preflight(claude_bin: str) -> tuple[str, set[str]]:
    version_run = subprocess.run(
        [claude_bin, "--version"], capture_output=True, text=True, timeout=10, check=False
    )
    if version_run.returncode != 0:
        raise ValueError(f"unable to read Claude Code version from {claude_bin}")
    version_fields = (version_run.stdout or version_run.stderr).strip().split()
    if not version_fields:
        raise ValueError("Claude Code returned an empty version")
    help_run = subprocess.run(
        [claude_bin, "--help"], capture_output=True, text=True, timeout=10, check=False
    )
    if help_run.returncode != 0:
        raise ValueError(f"unable to read Claude Code help from {claude_bin}")
    help_text = help_run.stdout or help_run.stderr
    aliases = {alias for alias in ("fable", "opus", "sonnet") if re.search(rf"['`] {alias} ['`]", help_text)}
    if not aliases:
        # Current CLI renders aliases inside a prose example without stable
        # whitespace. Parse quoted alias tokens as the compatible fallback.
        aliases = set(re.findall(r"['`](fable|opus|sonnet)['`]", help_text))
    return version_fields[0], aliases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True)
    parser.add_argument("--project", default="")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--project-league", default="")
    parser.add_argument("--global-league", default="~/.codex/swarm/model-league.md")
    parser.add_argument("--claude-bin", default="/opt/homebrew/bin/claude")
    parser.add_argument("--quota-state", default=str(DEFAULT_QUOTA_STATE))
    parser.add_argument("--fable-routing", choices=("auto", "off", "force"), default="auto")
    parser.add_argument("--allow-premium-advisor", action="store_true")
    parser.add_argument("--exact-named-model", default="")
    args = parser.parse_args()

    try:
        policy = load_policy(Path(args.policy).expanduser())
        project_path = args.project_league
        if not project_path and args.project:
            project_path = f"~/.codex/swarm/projects/{args.project}-model-league.md"
        project_entries = read_league(Path(project_path).expanduser(), "project") if project_path else []
        global_entries = read_league(Path(args.global_league).expanduser(), "global")
        quota_path = Path(args.quota_state).expanduser()
        quota_state = (
            json.loads(quota_path.read_text(encoding="utf-8"))
            if quota_path.is_file()
            else {}
        )
        fable_routing = quota.fable_pace_decision(
            quota_state=quota_state,
            policy=policy,
            routing_mode=("force" if args.allow_premium_advisor else args.fable_routing),
        )
        cli_version, aliases = cli_preflight(args.claude_bin)
        resolution = choose_resolution(
            role=args.role,
            policy=policy,
            project_entries=project_entries,
            global_entries=global_entries,
            available_aliases=aliases,
            allow_premium_advisor=args.allow_premium_advisor,
            premium_eligible_roles=set(fable_routing["eligible_roles"]),
            exact_named_model=args.exact_named_model,
        )
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "RESOLVED",
            "strategy": policy["strategy"],
            "role": args.role,
            "project": args.project,
            "claude_cli_version": cli_version,
            "available_moving_aliases": sorted(aliases),
            "effort": policy["default_effort"],
            "premium_routing": fable_routing,
            **resolution,
        }
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "schema_version": SCHEMA_VERSION,
            "status": "NOT_RESOLVED",
            "reason": str(exc),
        }, ensure_ascii=False, sort_keys=True))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
