#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import timezone
from pathlib import Path


SCRIPT = Path(__file__).with_name("claude_lane_attest.py")
SPEC = importlib.util.spec_from_file_location("claude_lane_attest", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_jsonl(rows: list[dict]) -> Path:
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
    with handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return Path(handle.name)


def assistant(model: str, *, version: str = "2.1.220", timestamp: str = "2026-08-03T12:00:00Z") -> dict:
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "version": version,
        "sessionId": "session-1",
        "message": {"role": "assistant", "model": model, "content": []},
    }


class AttestationTest(unittest.TestCase):
    def test_exact_named_model_without_fallback_passes(self):
        path = write_jsonl([assistant("claude-fable-5")])
        result = MODULE.attest(
            path,
            requested_selector="fable",
            expected_model="claude-fable-5",
            expected_cli_version="2.1.220",
            named_model_gate=True,
        )
        self.assertTrue(result["completion_established"])
        self.assertEqual(result["final_actual_model"], "claude-fable-5")

    def test_named_model_fallback_is_not_established(self):
        fallback = {
            "type": "system",
            "subtype": "model_refusal_fallback",
            "timestamp": "2026-08-03T12:00:01Z",
            "version": "2.1.220",
            "sessionId": "session-1",
            "originalModel": "claude-fable-5",
            "fallbackModel": "claude-opus-4-8",
            "trigger": "refusal",
        }
        path = write_jsonl([fallback, assistant("claude-opus-4-8", timestamp="2026-08-03T12:00:02Z")])
        result = MODULE.attest(
            path,
            requested_selector="fable",
            expected_model="claude-fable-5",
            expected_cli_version="2.1.220",
            named_model_gate=True,
        )
        self.assertFalse(result["completion_established"])
        self.assertIn("fallback_event_observed", result["reasons"])
        self.assertIn("actual_model_outside_bound_selection", result["reasons"])

    def test_moving_family_alias_accepts_current_actual_model(self):
        path = write_jsonl([assistant("claude-opus-5")])
        result = MODULE.attest(
            path,
            requested_selector="opus",
            allowed_model_pattern=r"claude-opus-.+",
            expected_cli_version="2.1.220",
            selection_basis="quality_first_model_league_then_latest_alias",
        )
        self.assertTrue(result["completion_established"])

    def test_stale_harness_is_not_established(self):
        path = write_jsonl([assistant("claude-opus-5", version="2.1.207")])
        result = MODULE.attest(
            path,
            requested_selector="opus",
            allowed_model_pattern=r"claude-opus-.+",
            expected_cli_version="2.1.220",
        )
        self.assertFalse(result["completion_established"])
        self.assertIn("stale_or_unbound_harness_version", result["reasons"])

    def test_epoch_filter_excludes_historical_fallback(self):
        fallback = {
            "type": "system",
            "subtype": "model_refusal_fallback",
            "timestamp": "2026-08-02T12:00:00Z",
            "version": "2.1.207",
            "sessionId": "session-1",
            "originalModel": "claude-fable-5",
            "fallbackModel": "claude-opus-4-8",
        }
        path = write_jsonl([
            fallback,
            assistant("claude-fable-5", timestamp="2026-08-03T12:00:00Z"),
        ])
        since = MODULE.parse_timestamp("2026-08-03T00:00:00Z")
        self.assertEqual(since.tzinfo, timezone.utc)
        result = MODULE.attest(
            path,
            requested_selector="fable",
            expected_model="claude-fable-5",
            expected_cli_version="2.1.220",
            since=since,
            named_model_gate=True,
        )
        self.assertTrue(result["completion_established"])


if __name__ == "__main__":
    unittest.main()
