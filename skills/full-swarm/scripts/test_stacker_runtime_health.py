#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("stacker_runtime_health.py")
SPEC = importlib.util.spec_from_file_location("stacker_runtime_health", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RuntimeHealthTests(unittest.TestCase):
    def test_exclusion_round_trip_and_clear(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "health.json"
            payload = MODULE.exclude(
                MODULE.empty_state(),
                provider_id="openai_codex",
                selector="gpt-new",
                effort="ultra",
                reason="rate_limited",
                observed_at="2026-08-04T00:00:00+00:00",
            )
            MODULE.atomic_write(path, payload)
            loaded = MODULE.read_state(path)
            self.assertEqual(loaded["exclusions"][0]["status"], "UNTIL_REVALIDATED")
            cleared = MODULE.clear(
                loaded,
                provider_id="openai_codex",
                selector="gpt-new",
                effort="ultra",
            )
            self.assertEqual(cleared["exclusions"], [])

    def test_rejects_unknown_reason(self):
        with self.assertRaises(ValueError):
            MODULE.exclude(
                MODULE.empty_state(),
                provider_id="openai_codex",
                selector="gpt-new",
                effort="ultra",
                reason="model_bad",
                observed_at="2026-08-04T00:00:00+00:00",
            )

    def test_model_mismatch_can_exclude_selector_across_efforts(self):
        payload = MODULE.exclude(
            MODULE.empty_state(),
            provider_id="anthropic_claude",
            selector="opus",
            effort="*",
            reason="actual_model_mismatch",
            observed_at="2026-08-04T00:00:00+00:00",
        )
        self.assertEqual(payload["exclusions"][0]["effort"], "*")
        self.assertEqual(payload["exclusions"][0]["reason"], "actual_model_mismatch")


if __name__ == "__main__":
    unittest.main()
