#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("stacker_claude_lane.py")
SPEC = importlib.util.spec_from_file_location("stacker_claude_lane", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class StackerClaudeLaneTests(unittest.TestCase):
    def test_command_disables_fallback_agents_mcp_and_chrome(self):
        command = MODULE.build_command(
            claude="claude",
            model="opus",
            effort="max",
            schema={"type": "object"},
            max_budget_usd=15,
        )
        self.assertNotIn("--fallback-model", command)
        self.assertNotIn("Agent", command[command.index("--tools") + 1])
        self.assertIn("--strict-mcp-config", command)
        self.assertIn("--no-chrome", command)
        self.assertIn("--no-session-persistence", command)

    def test_exclusive_json_write_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "receipt.json"
            MODULE.exclusive_json_write(path, {"value": 1})
            with self.assertRaises(FileExistsError):
                MODULE.exclusive_json_write(path, {"value": 2})

    def test_extracts_models_from_init_assistant_and_partial_events(self):
        fixtures = [
            {"type": "system", "subtype": "init", "model": "claude-opus-5"},
            {"type": "assistant", "message": {"model": "claude-opus-5"}},
            {"type": "stream_event", "event": {"type": "message_start", "message": {"model": "claude-opus-5"}}},
        ]
        self.assertEqual([MODULE.event_models(item) for item in fixtures], [["claude-opus-5"]] * 3)

    def test_exact_expected_model_rejects_family_compatible_downgrade(self):
        self.assertFalse(
            MODULE.model_matches("claude-opus-4-8", "claude-opus-5", r"claude-opus-.+")
        )
        self.assertTrue(
            MODULE.model_matches("claude-opus-5", "claude-opus-5", r"claude-opus-.+")
        )

    def test_fallback_event_is_detected(self):
        observed = MODULE.fallback_event({
            "type": "system",
            "subtype": "model_refusal_fallback",
            "originalModel": "claude-opus-5",
            "fallbackModel": "claude-opus-4-8",
        })
        self.assertEqual(observed["fallback_model"], "claude-opus-4-8")

    def test_budget_exhaustion_is_not_a_model_health_failure(self):
        observed = MODULE.result_failure({
            "type": "result",
            "is_error": True,
            "subtype": "error_max_budget_usd",
        })
        self.assertEqual(observed, ("BUDGET_EXHAUSTED", ""))

    def test_mismatch_stops_before_final_result(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fake = root / "fake.py"
            fake.write_text(
                "import json,time\n"
                "print(json.dumps({'type':'system','subtype':'init','model':'claude-opus-4-8'}),flush=True)\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            result = MODULE.execute(
                command=[sys.executable, str(fake)],
                cwd=root,
                prompt=b"review",
                expected_model="claude-opus-5",
                allowed_model_pattern=r"claude-opus-.+",
                expected_cli_version="2.1.220",
                actual_cli_version="2.1.220",
                timeout_seconds=30,
                event_path=root / "events.jsonl",
                stderr_path=root / "stderr",
                final_path=root / "final.json",
            )
            self.assertEqual(result["status"], "STOPPED")
            self.assertEqual(result["stop_reason"], "ACTUAL_MODEL_MISMATCH")
            self.assertEqual(result["first_actual_model"], "claude-opus-4-8")
            self.assertLess(result["elapsed_seconds"], 5)
            self.assertFalse((root / "final.json").exists())

    def test_matching_stream_writes_structured_final(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fake = root / "fake.py"
            fake.write_text(
                "import json\n"
                "print(json.dumps({'type':'system','subtype':'init','model':'claude-opus-5'}),flush=True)\n"
                "print(json.dumps({'type':'result','structured_output':{'decision':'ADOPT'}}),flush=True)\n",
                encoding="utf-8",
            )
            final = root / "final.json"
            result = MODULE.execute(
                command=[sys.executable, str(fake)],
                cwd=root,
                prompt=b"review",
                expected_model="claude-opus-5",
                allowed_model_pattern=r"claude-opus-.+",
                expected_cli_version="2.1.220",
                actual_cli_version="2.1.220",
                timeout_seconds=30,
                event_path=root / "events.jsonl",
                stderr_path=root / "stderr",
                final_path=final,
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(json.loads(final.read_text())["decision"], "ADOPT")


if __name__ == "__main__":
    unittest.main()
