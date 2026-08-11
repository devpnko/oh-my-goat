#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("stacker_stack_resolve.py")
SPEC = importlib.util.spec_from_file_location("stacker_stack_resolve", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

POLICY = MODULE.league.load_policy(MODULE.DEFAULT_CLAUDE_POLICY)


def entry(model: str, role: str, score: float, source: str = "project"):
    return MODULE.league.LeagueEntry(
        source=source,
        model=model,
        role=role,
        task_type="",
        score=score,
        verdict="win",
        availability="available",
        timestamp="2026-08-03T00:00:00Z",
    )


SNAPSHOT = {
    "observation_digest": "sha256:test",
    "update_detected": True,
    "providers": [
        {"provider_id": "anthropic_claude", "models": [
            {"selector": "opus", "exact_model": "", "family": "opus", "priority": 2, "visibility": "list", "efforts": ["max"], "attestor": "claude_jsonl"},
            {"selector": "sonnet", "exact_model": "", "family": "sonnet", "priority": 3, "visibility": "list", "efforts": ["max"], "attestor": "claude_jsonl"},
        ]},
        {"provider_id": "openai_codex", "models": [
            {"selector": "gpt-new", "exact_model": "gpt-new", "family": "openai_codex", "priority": 1, "visibility": "list", "efforts": ["max", "ultra"], "attestor": "codex_jsonl"},
            {"selector": "gpt-old", "exact_model": "gpt-old", "family": "openai_codex", "priority": 2, "visibility": "list", "efforts": ["max"], "attestor": "codex_jsonl"},
        ]},
    ],
}


class StackResolutionTests(unittest.TestCase):
    def test_attested_claude_version_does_not_inherit_older_family_score(self):
        candidate = MODULE.Candidate(
            provider_id="anthropic_claude",
            selector="opus",
            exact_model="",
            family="opus",
            priority=1,
            effort="max",
            supported_efforts=("max",),
            effort_basis="HIGHEST_STABLE_USEFUL_EFFORT",
            attestor="claude_jsonl",
            allowed_model_pattern="claude-opus-.+",
            last_attested_actual_model="claude-opus-5",
            attestation_status="ESTABLISHED",
        )
        self.assertFalse(
            MODULE.entry_matches_candidate(
                entry("Opus 4.8 max", "semantic", 94), candidate, POLICY
            )
        )
        self.assertFalse(
            MODULE.entry_matches_candidate(
                entry("opus", "semantic", 94), candidate, POLICY
            )
        )
        self.assertTrue(
            MODULE.entry_matches_candidate(
                entry("Opus 5 max", "semantic", 94), candidate, POLICY
            )
        )
        payload = MODULE.candidate_payload(candidate, "REQUIRED_FRONTIER_INTAKE")
        self.assertEqual(payload["expected_actual_model"], "claude-opus-5")

    def test_role_champion_wins_without_version_hardcode(self):
        result = MODULE.resolve_stack(
            roles=["semantic"], snapshot=SNAPSHOT, policy=POLICY,
            project_entries=[entry("claude-opus-5", "semantic", 94)],
            global_entries=[], allow_fable=False,
        )
        primary = result["assignments"][0]["primary"]
        self.assertEqual(primary["selector"], "opus")
        self.assertEqual(primary["exact_model"], "")
        self.assertEqual(primary["allowed_model_pattern"], "claude-opus-.+")

    def test_exact_discovered_gpt_can_be_champion(self):
        result = MODULE.resolve_stack(
            roles=["mechanical"], snapshot=SNAPSHOT, policy=POLICY,
            project_entries=[entry("gpt-old", "verifier", 96)],
            global_entries=[], allow_fable=False,
        )
        self.assertEqual(result["assignments"][0]["primary"]["selector"], "gpt-old")

    def test_unscored_new_model_is_intake_not_auto_promoted(self):
        result = MODULE.resolve_stack(
            roles=["semantic"], snapshot=SNAPSHOT, policy=POLICY,
            project_entries=[entry("claude-opus-5", "semantic", 94)],
            global_entries=[], allow_fable=False,
        )
        frontier = {(item["provider_id"], item["selector"]) for item in result["frontier_intake_candidates"]}
        self.assertIn(("openai_codex", "gpt-new"), frontier)
        self.assertEqual(result["assignments"][0]["primary"]["selector"], "opus")
        self.assertEqual(result["status"], "FRONTIER_INTAKE_REQUIRED")
        self.assertEqual(result["required_frontier_intake_lanes"][0]["selector"], "gpt-new")
        self.assertEqual(result["required_frontier_intake_lanes"][0]["effort"], "max")

    def test_no_evidence_requires_intake(self):
        result = MODULE.resolve_stack(
            roles=["atomicity"], snapshot=SNAPSHOT, policy=POLICY,
            project_entries=[], global_entries=[], allow_fable=False,
        )
        self.assertEqual(result["status"], "INTAKE_REQUIRED")
        self.assertIsNone(result["assignments"][0]["primary"])
        self.assertGreaterEqual(len(result["assignments"][0]["provisional_candidates"]), 2)

    def test_diverse_challenger_uses_other_provider(self):
        result = MODULE.resolve_stack(
            roles=["semantic"], snapshot=SNAPSHOT, policy=POLICY,
            project_entries=[
                entry("claude-opus-5", "semantic", 94),
                entry("gpt-old", "semantic", 91),
            ],
            global_entries=[], allow_fable=False,
        )
        challenger = result["assignments"][0]["provider_diverse_challenger"]
        self.assertEqual(challenger["provider_id"], "openai_codex")
        self.assertEqual(challenger["status"], "PROVIDER_DIVERSE_ROLE_CHAMPION")

    def test_standard_risk_reports_frontier_without_blocking_champion(self):
        result = MODULE.resolve_stack(
            roles=["semantic"], snapshot=SNAPSHOT, policy=POLICY,
            project_entries=[entry("claude-opus-5", "semantic", 94)],
            global_entries=[], allow_fable=False, risk_class="standard",
        )
        self.assertEqual(result["status"], "RESOLVED")
        frontier = result["assignments"][0]["frontier_intake_candidates"]
        self.assertEqual(frontier[0]["status"], "PENDING_FRONTIER_INTAKE")

    def test_one_frontier_lane_can_cover_multiple_roles(self):
        result = MODULE.resolve_stack(
            roles=["semantic", "atomicity"], snapshot=SNAPSHOT, policy=POLICY,
            project_entries=[
                entry("claude-opus-5", "semantic", 94),
                entry("claude-opus-5", "atomicity", 94),
            ],
            global_entries=[], allow_fable=False,
        )
        lanes = result["required_frontier_intake_lanes"]
        self.assertEqual(len(lanes), 1)
        self.assertEqual(lanes[0]["selector"], "gpt-new")
        self.assertEqual(lanes[0]["roles"], ["semantic", "atomicity"])

    def test_ultra_requires_opt_in_and_healthy_runtime(self):
        baseline = MODULE.resolve_stack(
            roles=["mechanical"], snapshot=SNAPSHOT, policy=POLICY,
            project_entries=[entry("gpt-old", "mechanical", 94)],
            global_entries=[], allow_fable=False,
        )
        self.assertEqual(baseline["required_frontier_intake_lanes"][0]["effort"], "max")

        opted_in = MODULE.resolve_stack(
            roles=["mechanical"], snapshot=SNAPSHOT, policy=POLICY,
            project_entries=[entry("gpt-old", "mechanical", 94)],
            global_entries=[], allow_fable=False, allow_ultra=True,
        )
        self.assertEqual(opted_in["required_frontier_intake_lanes"][0]["effort"], "ultra")

        unhealthy = MODULE.resolve_stack(
            roles=["mechanical"], snapshot=SNAPSHOT, policy=POLICY,
            project_entries=[entry("gpt-old", "mechanical", 94)],
            global_entries=[], allow_fable=False, allow_ultra=True,
            runtime_health={"exclusions": [{
                "provider_id": "openai_codex",
                "selector": "gpt-new",
                "effort": "ultra",
                "status": "UNTIL_REVALIDATED",
            }]},
        )
        self.assertEqual(unhealthy["required_frontier_intake_lanes"][0]["effort"], "max")
        self.assertEqual(unhealthy["runtime_health_exclusions_applied"], 1)

    def test_resolver_emits_bounded_ultra_watchdog_contract(self):
        result = MODULE.resolve_stack(
            roles=["mechanical"], snapshot=SNAPSHOT, policy=POLICY,
            project_entries=[entry("gpt-old", "mechanical", 94)],
            global_entries=[], allow_fable=False, allow_ultra=True,
        )
        effort = result["effort_policy"]
        self.assertTrue(effort["codex_lane_runner"].endswith("stacker_codex_lane.py"))
        self.assertEqual(effort["ultra_watchdog_defaults"]["max_total_sessions"], 100)
        self.assertEqual(effort["ultra_watchdog_defaults"]["max_tree_depth"], 8)
        self.assertEqual(effort["ambient_1000_slot_inheritance"], "FORBIDDEN")
        planning = result["review_planning"]
        self.assertTrue(planning["compiler"].endswith("stacker_review_graph.py"))
        self.assertEqual(planning["model_verdict_cache"], "FORBIDDEN")
        self.assertEqual(planning["mechanical_champion_synthesis"], "REQUIRED_BEFORE_TRIAD_JOIN")
        self.assertEqual(planning["authority"], "NONE")


if __name__ == "__main__":
    unittest.main()
