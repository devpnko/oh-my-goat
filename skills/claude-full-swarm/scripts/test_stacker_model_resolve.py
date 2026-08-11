#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("stacker_model_resolve.py")
SPEC = importlib.util.spec_from_file_location("stacker_model_resolve", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


POLICY = MODULE.load_policy(SCRIPT.parent.parent / "references" / "stacker-model-policy.json")


def entry(model: str, role: str, score: float, source: str = "project"):
    return MODULE.LeagueEntry(
        source=source,
        model=model,
        role=role,
        task_type="review",
        score=score,
        verdict="win",
        availability="available",
        timestamp="2026-08-03T00:00:00+00:00",
    )


class ResolveTests(unittest.TestCase):
    def test_uses_project_role_champion_and_moving_alias(self):
        result = MODULE.choose_resolution(
            role="semantic",
            policy=POLICY,
            project_entries=[entry("claude-opus-5", "semantic reviewer", 94)],
            global_entries=[entry("claude-sonnet-5", "semantic reviewer", 99, "global")],
            available_aliases={"opus", "sonnet", "fable"},
        )
        self.assertEqual(result["requested_selector"], "opus")
        self.assertEqual(result["expected_model"], "")
        self.assertEqual(result["allowed_model_pattern"], "claude-opus-.+")

    def test_role_score_can_promote_sonnet(self):
        result = MODULE.choose_resolution(
            role="verifier",
            policy=POLICY,
            project_entries=[
                entry("claude-opus-5", "writer", 98),
                entry("claude-sonnet-5", "verifier", 93),
            ],
            global_entries=[],
            available_aliases={"opus", "sonnet"},
        )
        self.assertEqual(result["requested_selector"], "sonnet")

    def test_no_champion_uses_highest_policy_family(self):
        result = MODULE.choose_resolution(
            role="atomicity",
            policy=POLICY,
            project_entries=[entry("claude-sonnet-5", "db reviewer", 70)],
            global_entries=[],
            available_aliases={"opus", "sonnet"},
        )
        self.assertEqual(result["requested_selector"], "opus")
        self.assertEqual(result["selection_basis"], "policy_preference_no_comparable_champion")

    def test_named_gate_is_exact_and_not_family_fallback(self):
        result = MODULE.choose_resolution(
            role="named_advisor",
            policy=POLICY,
            project_entries=[],
            global_entries=[],
            available_aliases={"fable", "opus"},
            allow_premium_advisor=True,
            exact_named_model="claude-fable-5",
        )
        self.assertEqual(result["requested_selector"], "fable")
        self.assertEqual(result["expected_model"], "claude-fable-5")
        self.assertTrue(result["named_model_gate"])

    def test_unavailable_family_is_not_selected(self):
        result = MODULE.choose_resolution(
            role="semantic",
            policy=POLICY,
            project_entries=[entry("claude-opus-5", "semantic reviewer", 99)],
            global_entries=[],
            available_aliases={"sonnet"},
        )
        self.assertEqual(result["requested_selector"], "sonnet")

    def test_quota_eligible_high_leverage_role_can_select_fable(self):
        result = MODULE.choose_resolution(
            role="intent_gap",
            policy=POLICY,
            project_entries=[
                entry("claude-fable-5", "intent gap", 97),
                entry("claude-opus-5", "intent gap", 94),
            ],
            global_entries=[],
            available_aliases={"fable", "opus", "sonnet"},
            premium_eligible_roles={"intent_gap"},
        )
        self.assertEqual(result["requested_selector"], "fable")

    def test_ineligible_high_leverage_role_uses_nonpremium_champion(self):
        result = MODULE.choose_resolution(
            role="intent_gap",
            policy=POLICY,
            project_entries=[
                entry("claude-fable-5", "intent gap", 99),
                entry("claude-opus-5", "intent gap", 94),
            ],
            global_entries=[],
            available_aliases={"fable", "opus", "sonnet"},
            premium_eligible_roles=set(),
        )
        self.assertEqual(result["requested_selector"], "opus")


if __name__ == "__main__":
    unittest.main()
