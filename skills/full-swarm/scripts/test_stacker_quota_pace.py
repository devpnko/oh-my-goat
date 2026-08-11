#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from copy import deepcopy
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import stacker_quota_pace as QUOTA  # noqa: E402


RESOLVER_PATH = SCRIPT_DIR / "stacker_stack_resolve.py"
SPEC = importlib.util.spec_from_file_location("stacker_stack_resolve_quota_tests", RESOLVER_PATH)
assert SPEC and SPEC.loader
RESOLVER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RESOLVER
SPEC.loader.exec_module(RESOLVER)

POLICY = RESOLVER.league.load_policy(RESOLVER.DEFAULT_CLAUDE_POLICY)
NOW = 1_800_000_000.0


def bucket(
    bucket_id: str,
    used: float,
    seconds_to_reset: float,
    window_seconds: int,
    *,
    scope: str = "provider",
    family: str = "",
) -> dict:
    return {
        "bucket_id": bucket_id,
        "scope": scope,
        "family": family,
        "used_percentage": used,
        "resets_at": QUOTA.iso_utc(NOW + seconds_to_reset),
        "window_seconds": window_seconds,
    }


def state(*buckets: dict, observed_at: float = NOW) -> dict:
    return {
        "schema_version": QUOTA.OBSERVATION_SCHEMA_VERSION,
        "observation_digest": "sha256:quota-test",
        "observed_at": QUOTA.iso_utc(observed_at),
        "buckets": list(buckets),
    }


def league_entry(model: str, role: str, score: float):
    return RESOLVER.league.LeagueEntry(
        source="project",
        model=model,
        role=role,
        task_type="",
        score=score,
        verdict="win",
        availability="available",
        timestamp="2026-08-11T00:00:00Z",
    )


SNAPSHOT = {
    "observation_digest": "sha256:discovery",
    "update_detected": False,
    "providers": [
        {
            "provider_id": "anthropic_claude",
            "models": [
                {
                    "selector": "fable",
                    "exact_model": "",
                    "family": "fable",
                    "priority": 1,
                    "visibility": "list",
                    "efforts": ["max"],
                    "attestor": "claude_jsonl",
                },
                {
                    "selector": "opus",
                    "exact_model": "",
                    "family": "opus",
                    "priority": 2,
                    "visibility": "list",
                    "efforts": ["max"],
                    "attestor": "claude_jsonl",
                },
                {
                    "selector": "sonnet",
                    "exact_model": "",
                    "family": "sonnet",
                    "priority": 3,
                    "visibility": "list",
                    "efforts": ["max"],
                    "attestor": "claude_jsonl",
                },
            ],
        },
        {
            "provider_id": "openai_codex",
            "models": [
                {
                    "selector": "gpt-current",
                    "exact_model": "gpt-current",
                    "family": "openai_codex",
                    "priority": 1,
                    "visibility": "list",
                    "efforts": ["max"],
                    "attestor": "codex_jsonl",
                }
            ],
        },
    ],
}


class QuotaNormalizationTests(unittest.TestCase):
    def test_normalizes_official_and_optional_model_scoped_fields(self):
        observation = QUOTA.normalize_quota_observation(
            {
                "rate_limits": {
                    "five_hour": {"used_percentage": 12, "resets_at": NOW + 9_000},
                    "seven_day": {"used_percentage": 30, "resets_at": NOW + 302_400},
                    "model_scoped": {
                        "claude-fable-5": {
                            "used_percentage": 10,
                            "resets_at": NOW + 302_400,
                        }
                    },
                }
            },
            observed_at=NOW,
        )
        self.assertEqual(observation["schema_version"], QUOTA.OBSERVATION_SCHEMA_VERSION)
        self.assertFalse(observation["canonical"])
        self.assertEqual(observation["authority"], "NONE")
        self.assertTrue(observation["model_scoped_observation"])
        self.assertEqual(len(observation["buckets"]), 3)
        fable = [item for item in observation["buckets"] if item["family"] == "fable"]
        self.assertEqual(fable[0]["scope"], "model_family")

    def test_merge_rejects_past_reset_and_lower_cached_same_epoch_usage(self):
        previous = QUOTA.normalize_quota_observation(
            {"rate_limits": {
                "five_hour": {"used_percentage": 22, "resets_at": NOW + 2_400},
                "seven_day": {"used_percentage": 47, "resets_at": NOW + 302_400},
            }},
            observed_at=NOW - 10,
        )
        incoming = QUOTA.normalize_quota_observation(
            {"rate_limits": {
                "five_hour": {"used_percentage": 1, "resets_at": NOW - 86_400},
                "seven_day": {"used_percentage": 20, "resets_at": NOW + 302_400},
            }},
            observed_at=NOW,
        )
        merged = QUOTA.merge_quota_observations(previous, incoming, now=NOW)
        by_id = {item["bucket_id"]: item for item in merged["buckets"]}
        self.assertEqual(by_id["five_hour"]["used_percentage"], 22)
        self.assertEqual(by_id["seven_day"]["used_percentage"], 47)
        self.assertEqual(merged["observed_at"], QUOTA.iso_utc(NOW - 10))

    def test_merge_refreshes_equal_same_epoch_observation(self):
        previous = QUOTA.normalize_quota_observation(
            {"rate_limits": {
                "seven_day": {"used_percentage": 47, "resets_at": NOW + 302_400},
            }},
            observed_at=NOW - 10,
        )
        incoming = QUOTA.normalize_quota_observation(
            {"rate_limits": {
                "seven_day": {"used_percentage": 47, "resets_at": NOW + 302_400},
            }},
            observed_at=NOW,
        )
        merged = QUOTA.merge_quota_observations(previous, incoming, now=NOW)
        self.assertEqual(merged["observed_at"], QUOTA.iso_utc(NOW))

    def test_stale_observation_never_auto_expands(self):
        decision = QUOTA.fable_pace_decision(
            quota_state=state(observed_at=NOW - 901),
            policy=POLICY,
            now=NOW,
        )
        self.assertEqual(decision["pace_mode"], "UNKNOWN")
        self.assertEqual(decision["eligible_roles"], ["named_advisor", "fable_final"])
        self.assertFalse(decision["automatic_expansion"])

    def test_fresh_model_scoped_surplus_unlocks_expanded_roles(self):
        decision = QUOTA.fable_pace_decision(
            quota_state=state(
                bucket("five_hour", 10, 9_000, 18_000),
                bucket("seven_day", 10, 302_400, 604_800),
                bucket(
                    "model_scoped:claude-fable-5",
                    10,
                    302_400,
                    604_800,
                    scope="model_family",
                    family="fable",
                ),
            ),
            policy=POLICY,
            now=NOW,
        )
        self.assertEqual(decision["pace_mode"], "SURPLUS")
        self.assertIn("intent_gap", decision["eligible_roles"])
        self.assertIn("ux_product", decision["eligible_roles"])
        self.assertIn("orchestrator", decision["eligible_roles"])

    def test_over_pace_or_near_exhaustion_preserves_exact_roles_only(self):
        decision = QUOTA.fable_pace_decision(
            quota_state=state(
                bucket("five_hour", 50, 9_000, 18_000),
                bucket("seven_day", 50, 302_400, 604_800),
                bucket(
                    "model_scoped:claude-fable-5",
                    96,
                    302_400,
                    604_800,
                    scope="model_family",
                    family="fable",
                ),
            ),
            policy=POLICY,
            now=NOW,
        )
        self.assertEqual(decision["pace_mode"], "RESERVE")
        self.assertEqual(decision["eligible_roles"], ["named_advisor", "fable_final"])

    def test_provider_wide_quota_is_a_core_only_proxy(self):
        decision = QUOTA.fable_pace_decision(
            quota_state=state(
                bucket("five_hour", 10, 9_000, 18_000),
                bucket("seven_day", 10, 302_400, 604_800),
            ),
            policy=POLICY,
            now=NOW,
        )
        self.assertEqual(decision["pace_mode"], "PROVIDER_PROXY_CORE")
        self.assertIn("strategy_planner", decision["eligible_roles"])
        self.assertNotIn("ux_product", decision["eligible_roles"])

    def test_model_scoped_quota_cannot_expand_without_provider_guard(self):
        decision = QUOTA.fable_pace_decision(
            quota_state=state(
                bucket(
                    "model_scoped:claude-fable-5",
                    10,
                    302_400,
                    604_800,
                    scope="model_family",
                    family="fable",
                )
            ),
            policy=POLICY,
            now=NOW,
        )
        self.assertEqual(decision["pace_mode"], "UNKNOWN")
        self.assertEqual(decision["eligible_roles"], ["named_advisor", "fable_final"])


class QuotaAwareResolverTests(unittest.TestCase):
    def surplus_state(self) -> dict:
        return state(
            bucket("five_hour", 10, 9_000, 18_000),
            bucket("seven_day", 10, 302_400, 604_800),
            bucket(
                "model_scoped:claude-fable-5",
                10,
                302_400,
                604_800,
                scope="model_family",
                family="fable",
            ),
        )

    def test_surplus_quota_makes_fable_compete_for_high_leverage_role(self):
        result = RESOLVER.resolve_stack(
            roles=["intent_gap"],
            snapshot=SNAPSHOT,
            policy=POLICY,
            project_entries=[
                league_entry("claude-fable-5", "intent gap", 97),
                league_entry("claude-opus-5", "intent gap", 94),
            ],
            global_entries=[],
            allow_fable=False,
            risk_class="standard",
            quota_state=self.surplus_state(),
            now=NOW,
        )
        self.assertEqual(result["assignments"][0]["primary"]["selector"], "fable")
        self.assertEqual(result["premium_routing"]["pace_mode"], "SURPLUS")

    def test_stale_quota_keeps_fable_out_of_ordinary_role(self):
        result = RESOLVER.resolve_stack(
            roles=["intent_gap"],
            snapshot=SNAPSHOT,
            policy=POLICY,
            project_entries=[
                league_entry("claude-fable-5", "intent gap", 99),
                league_entry("claude-opus-5", "intent gap", 94),
            ],
            global_entries=[],
            allow_fable=False,
            risk_class="standard",
            quota_state=state(observed_at=NOW - 901),
            now=NOW,
        )
        self.assertEqual(result["assignments"][0]["primary"]["selector"], "opus")

    def test_exact_fable_final_never_silently_falls_back(self):
        snapshot = deepcopy(SNAPSHOT)
        snapshot["providers"][0]["models"] = [
            item for item in snapshot["providers"][0]["models"] if item["family"] != "fable"
        ]
        result = RESOLVER.resolve_stack(
            roles=["fable_final"],
            snapshot=snapshot,
            policy=POLICY,
            project_entries=[league_entry("claude-opus-5", "final review", 99)],
            global_entries=[],
            allow_fable=False,
            risk_class="standard",
            quota_state={},
            now=NOW,
        )
        self.assertEqual(result["status"], "INTAKE_REQUIRED")
        self.assertIsNone(result["assignments"][0]["primary"])
        self.assertEqual(result["assignments"][0]["provisional_candidates"], [])

    def test_force_does_not_put_fable_into_pre_fable_triad_roles(self):
        result = RESOLVER.resolve_stack(
            roles=["semantic"],
            snapshot=SNAPSHOT,
            policy=POLICY,
            project_entries=[
                league_entry("claude-fable-5", "semantic", 99),
                league_entry("claude-opus-5", "semantic", 94),
            ],
            global_entries=[],
            allow_fable=True,
            risk_class="standard",
            quota_state={},
            now=NOW,
        )
        self.assertEqual(result["assignments"][0]["primary"]["selector"], "opus")

    def test_runtime_quota_exclusion_moves_ordinary_role_to_fresh_opus_candidate(self):
        result = RESOLVER.resolve_stack(
            roles=["intent_gap"],
            snapshot=SNAPSHOT,
            policy=POLICY,
            project_entries=[
                league_entry("claude-fable-5", "intent gap", 99),
                league_entry("claude-opus-5", "intent gap", 94),
            ],
            global_entries=[],
            allow_fable=False,
            risk_class="standard",
            quota_state=self.surplus_state(),
            runtime_health={"exclusions": [{
                "provider_id": "anthropic_claude",
                "selector": "fable",
                "effort": "*",
                "status": "ACTIVE",
                "reason": "quota_exhausted",
            }]},
            now=NOW,
        )
        self.assertEqual(result["assignments"][0]["primary"]["selector"], "opus")
        self.assertEqual(result["runtime_health_exclusions_applied"], 1)


if __name__ == "__main__":
    unittest.main()
