#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


def load(name: str):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DISCOVERY = load("provider_model_discover")
ATTEST = load("codex_lane_attest")


class DiscoveryTests(unittest.TestCase):
    def test_successful_claude_watchdog_receipt_updates_alias_observation(self):
        with tempfile.TemporaryDirectory() as raw:
            receipt = Path(raw) / "receipt.json"
            receipt.write_text(json.dumps({
                "schema_version": "stacker.claude_lane_watchdog.v1",
                "status": "PASS",
                "first_actual_model": "claude-opus-5",
                "policy": {
                    "requested_selector": "opus",
                    "actual_cli_version": "2.1.220",
                },
            }), encoding="utf-8")
            observed = DISCOVERY.runtime_observations(None, [str(receipt)])
            self.assertEqual(observed[0]["selector"], "opus")
            self.assertEqual(observed[0]["actual_model"], "claude-opus-5")

    def test_claude_alias_discovery_is_not_name_hardcoded(self):
        help_text = """\
Options:
  --model <model>  Provide an alias for the latest model (e.g. 'frontier',
                   'opus', or 'sonnet') or a model's full name
                   (e.g. 'claude-frontier-6').
  --name <name>    Session name.
"""
        self.assertEqual(
            DISCOVERY.claude_aliases_from_help(help_text),
            ["frontier", "opus", "sonnet"],
        )

    def test_claude_alias_discovery_is_scoped_to_model_option(self):
        help_text = """\
Options:
  --effort <level>  Effort (e.g. 'max').
  --model <model>   Alias (e.g. 'fable') or full name
                    (e.g. 'claude-fable-5').
  --output <kind>   Output (e.g. 'json').
"""
        self.assertEqual(
            DISCOVERY.claude_aliases_from_help(help_text),
            ["fable"],
        )

    def test_compare_finds_model_and_harness_changes(self):
        old = {"providers": [{
            "provider_id": "openai_codex",
            "harness_version": "1",
            "inventory_digest": "old",
            "models": [{"selector": "gpt-old", "exact_model": "gpt-old", "priority": 1, "visibility": "list", "efforts": ["high"]}],
        }]}
        new = [{
            "provider_id": "openai_codex",
            "harness_version": "2",
            "inventory_digest": "new",
            "models": [
                {"selector": "gpt-old", "exact_model": "gpt-old", "priority": 2, "visibility": "list", "efforts": ["high"]},
                {"selector": "gpt-new", "exact_model": "gpt-new", "priority": 1, "visibility": "list", "efforts": ["max"]},
            ],
        }]
        kinds = [item["kind"] for item in DISCOVERY.compare(old, new)]
        self.assertEqual(kinds, ["harness_version_changed", "model_or_alias_added", "model_metadata_changed"])

    def test_generic_catalog_is_adapter_driven(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models.json"
            path.write_text(json.dumps({"models": [{"id": "vendor-best", "alias": "best", "priority": 1}]}))
            found = DISCOVERY.discover_generic_catalog(f"vendor:{path}")
        self.assertEqual(found["provider_id"], "vendor")
        self.assertEqual(found["models"][0]["selector"], "best")
        self.assertEqual(found["models"][0]["attestor"], "provider_adapter_required")

    def test_first_observation_is_baseline_not_update(self):
        self.assertEqual(DISCOVERY.compare(None, []), [])

    def test_catalog_fetch_time_does_not_change_inventory_identity(self):
        first = {"provider_id": "openai_codex", "catalog_fetched_at": "one", "models": []}
        second = {"provider_id": "openai_codex", "catalog_fetched_at": "two", "models": []}
        self.assertEqual(
            DISCOVERY.digest(DISCOVERY.stable_inventory_payload(first)),
            DISCOVERY.digest(DISCOVERY.stable_inventory_payload(second)),
        )

    def test_compare_detects_model_capability_metadata_change(self):
        old = {"providers": [{
            "provider_id": "openai_codex",
            "harness_version": "1",
            "models": [{
                "selector": "gpt-new",
                "exact_model": "gpt-new",
                "priority": 1,
                "visibility": "list",
                "efforts": ["max"],
                "description": "old",
            }],
        }]}
        new = [{
            "provider_id": "openai_codex",
            "harness_version": "1",
            "models": [{
                "selector": "gpt-new",
                "exact_model": "gpt-new",
                "priority": 1,
                "visibility": "list",
                "efforts": ["max"],
                "description": "new",
            }],
        }]
        self.assertEqual(
            [item["kind"] for item in DISCOVERY.compare(old, new)],
            ["model_metadata_changed"],
        )

    def test_executable_identity_is_absolute(self):
        resolved = Path(DISCOVERY.resolved_executable(sys.executable))
        self.assertTrue(resolved.is_absolute())
        self.assertEqual(resolved, Path(sys.executable).resolve())

    def test_cmux_shim_identity_omits_ephemeral_directory(self):
        first = "/private/tmp/cmux-cli-shims/session-a/codex"
        second = "/private/tmp/cmux-cli-shims/session-b/codex"
        self.assertEqual(DISCOVERY.harness_identity(first), "cmux-cli-shim:codex")
        self.assertEqual(DISCOVERY.harness_identity(first), DISCOVERY.harness_identity(second))

    def test_attested_alias_resolution_is_persisted_and_applied(self):
        previous = {"runtime_alias_observations": [{
            "provider_id": "anthropic_claude", "selector": "opus",
            "actual_model": "claude-opus-5", "harness_version": "2.1.220",
            "attestation_schema": "claude.actual_model_attestation.v1",
            "attestation_status": "ESTABLISHED",
        }]}
        observations = DISCOVERY.runtime_observations(previous, [])
        providers = [{"provider_id": "anthropic_claude", "models": [{"selector": "opus"}]}]
        DISCOVERY.apply_runtime_observations(providers, observations)
        self.assertEqual(providers[0]["models"][0]["last_attested_actual_model"], "claude-opus-5")
        self.assertEqual(providers[0]["models"][0]["attestation_status"], "ESTABLISHED")


class CodexAttestationTests(unittest.TestCase):
    def transcript(self, model: str = "gpt-current") -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        rows = [
            {"timestamp": "2026-08-03T00:00:00Z", "type": "session_meta", "payload": {
                "session_id": "session-1", "cli_version": "9.9.9", "model_provider": "openai"
            }},
            {"timestamp": "2026-08-03T00:00:01Z", "type": "turn_context", "payload": {"model": model}},
        ]
        for row in rows:
            handle.write(json.dumps(row) + "\n")
        handle.close()
        return Path(handle.name)

    def test_exact_codex_metadata_passes(self):
        path = self.transcript()
        try:
            result = ATTEST.attest(path, "gpt-current", "openai", "9.9.9", datetime(2026, 8, 3, tzinfo=timezone.utc))
        finally:
            path.unlink()
        self.assertTrue(result["completion_established"])

    def test_model_switch_fails(self):
        path = self.transcript("gpt-fallback")
        try:
            result = ATTEST.attest(path, "gpt-current", "openai", "9.9.9", None)
        finally:
            path.unlink()
        self.assertFalse(result["completion_established"])
        self.assertIn("actual_model_mismatch_or_switch", result["reasons"])


if __name__ == "__main__":
    unittest.main()
