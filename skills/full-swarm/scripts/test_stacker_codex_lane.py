#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("stacker_codex_lane.py")
SPEC = importlib.util.spec_from_file_location("stacker_codex_lane", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class StackerCodexLaneTests(unittest.TestCase):
    def test_provider_usage_limit_is_classified_from_stdout_event_bytes(self):
        raw = (
            b'{"type":"error","message":"You have hit your usage limit. '
            b'Try again later."}\n'
        )
        self.assertEqual(
            MODULE.classify_provider_stop(raw),
            "PROVIDER_USAGE_LIMIT",
        )

    def test_provider_stop_classifier_is_case_insensitive_and_specific(self):
        self.assertEqual(
            MODULE.classify_provider_stop(b"429 Too Many Requests"),
            "PROVIDER_RATE_LIMIT",
        )
        self.assertEqual(
            MODULE.classify_provider_stop(b"403 FORBIDDEN"),
            "PROVIDER_FORBIDDEN_TRANSPORT",
        )
        self.assertIsNone(MODULE.classify_provider_stop(b"ordinary model output"))

    def test_execute_detects_usage_limit_from_stdout_json_stream(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root / "fake_codex.py"
            fake.write_text(
                "import sys\n"
                "sys.stdin.buffer.read()\n"
                "print('{\"type\":\"thread.started\",\"thread_id\":\"fake\"}')\n"
                "print('{\"type\":\"error\",\"message\":\"usage limit\"}')\n"
                "raise SystemExit(1)\n",
                encoding="utf-8",
            )
            result = MODULE.execute(
                command=[sys.executable, str(fake), "-C", str(root)],
                prompt=b"bounded review",
                event_path=root / "events.jsonl",
                stderr_path=root / "stderr",
                session_root=root / "sessions",
                max_total_sessions=100,
                max_tree_depth=8,
                timeout_seconds=60,
                isolated_review_scratch=None,
            )
            self.assertEqual(result["status"], "STOPPED")
            self.assertEqual(result["stop_reason"], "PROVIDER_USAGE_LIMIT")
            self.assertFalse(result["automatic_retry"])

    def test_default_limits_preserve_wide_ultra_but_bound_runaway(self):
        self.assertEqual(MODULE.DEFAULT_MAX_TOTAL_SESSIONS, 100)
        self.assertEqual(MODULE.DEFAULT_MAX_TREE_DEPTH, 8)
        self.assertEqual(MODULE.DEFAULT_MAX_CONCURRENT_AGENTS, 32)

    def test_ultra_requires_explicit_opt_in(self):
        with self.assertRaises(MODULE.PolicyError):
            MODULE.validate_limits(
                effort="ultra",
                allow_ultra=False,
                revalidation_smoke=False,
                max_total_sessions=100,
                max_tree_depth=8,
                max_concurrent_agents=32,
                timeout_seconds=7200,
                runtime_excluded=False,
            )

    def test_hard_limits_reject_old_thousand_slot_shape(self):
        with self.assertRaises(MODULE.PolicyError):
            MODULE.validate_limits(
                effort="ultra",
                allow_ultra=True,
                revalidation_smoke=False,
                max_total_sessions=1000,
                max_tree_depth=28,
                max_concurrent_agents=1000,
                timeout_seconds=7200,
                runtime_excluded=False,
            )

    def test_hard_limit_rejects_session_count_above_selected_ceiling(self):
        with self.assertRaises(MODULE.PolicyError):
            MODULE.validate_limits(
                effort="ultra",
                allow_ultra=True,
                revalidation_smoke=False,
                max_total_sessions=101,
                max_tree_depth=8,
                max_concurrent_agents=32,
                timeout_seconds=7200,
                runtime_excluded=False,
            )

    def test_runtime_exclusion_requires_strict_revalidation(self):
        with self.assertRaises(MODULE.PolicyError):
            MODULE.validate_limits(
                effort="ultra",
                allow_ultra=True,
                revalidation_smoke=False,
                max_total_sessions=100,
                max_tree_depth=8,
                max_concurrent_agents=32,
                timeout_seconds=7200,
                runtime_excluded=True,
            )
        MODULE.validate_limits(
            effort="ultra",
            allow_ultra=True,
            revalidation_smoke=True,
            max_total_sessions=12,
            max_tree_depth=3,
            max_concurrent_agents=6,
            timeout_seconds=900,
            runtime_excluded=True,
        )

    def test_command_overrides_ambient_thousand_slot_config(self):
        command = MODULE.build_command(
            codex="codex",
            cwd=Path("/tmp"),
            model="future-model",
            effort="ultra",
            max_concurrent_agents=32,
            output_schema=Path("/tmp/schema.json"),
            final_path=Path("/tmp/final.json"),
            model_catalog_path=Path("/tmp/model-catalog.json"),
        )
        self.assertIn("agents.max_threads=32", command)
        self.assertIn(
            "features.multi_agent_v2.max_concurrent_threads_per_session=32",
            command,
        )
        self.assertNotIn("1000", command)
        self.assertIn(
            'model_catalog_json="/tmp/model-catalog.json"',
            command,
        )

    def test_models_cache_schema_normalization_does_not_change_routing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "models_cache.json"
            cache.write_text(
                json.dumps(
                    {
                        "fetched_at": "2026-08-09T00:00:00Z",
                        "models": [
                            {
                                "slug": "future-model",
                                "priority": 1,
                                "supported_reasoning_levels": [
                                    {"effort": "max", "description": "maximum"}
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            snapshot = root / "lane.model-catalog.json"
            result = MODULE.publish_model_catalog_snapshot(cache, snapshot)
            self.assertEqual(
                result["status"], "SNAPSHOT_NORMALIZED_REQUIRED_FIELDS"
            )
            self.assertFalse(result["model_selection_changed"])
            normalized = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertEqual(normalized["models"][0]["slug"], "future-model")
            self.assertEqual(normalized["models"][0]["priority"], 1)
            self.assertIs(
                normalized["models"][0]["supports_reasoning_summaries"], True
            )
            self.assertEqual(result["shared_cache_mutation"], "NONE")
            original = json.loads(cache.read_text(encoding="utf-8"))
            self.assertNotIn(
                "supports_reasoning_summaries", original["models"][0]
            )

    def test_models_cache_schema_normalization_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "models_cache.json"
            cache.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "slug": "current-model",
                                "supports_reasoning_summaries": True,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            before = cache.read_bytes()
            snapshot = Path(temporary) / "lane.model-catalog.json"
            result = MODULE.publish_model_catalog_snapshot(cache, snapshot)
            self.assertEqual(result["status"], "SNAPSHOT_EXACT_COMPATIBLE")
            self.assertEqual(cache.read_bytes(), before)
            self.assertTrue(snapshot.is_file())

    def test_parallel_catalog_snapshots_do_not_share_a_writer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "models_cache.json"
            cache.write_text(
                json.dumps({"models": [{"slug": "future-model"}]}),
                encoding="utf-8",
            )
            before = cache.read_bytes()
            first = root / "first.model-catalog.json"
            second = root / "second.model-catalog.json"
            first_report = MODULE.publish_model_catalog_snapshot(cache, first)
            second_report = MODULE.publish_model_catalog_snapshot(cache, second)
            self.assertEqual(cache.read_bytes(), before)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(
                first_report["snapshot_sha256"],
                second_report["snapshot_sha256"],
            )

    def test_session_tree_counts_total_and_depth(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            now = __import__("datetime").datetime.now().astimezone()
            directory = root / f"{now.year:04d}" / f"{now.month:02d}" / f"{now.day:02d}"
            directory.mkdir(parents=True)
            root_id = "root-id"
            payloads = [
                {"type": "session_meta", "payload": {"session_id": root_id, "id": root_id, "source": "exec"}},
                {"type": "session_meta", "payload": {"session_id": root_id, "id": "child", "source": {"subagent": {"thread_spawn": {"depth": 7}}}}},
            ]
            for index, payload in enumerate(payloads):
                (directory / f"{index}.jsonl").write_text(json.dumps(payload) + "\n", encoding="utf-8")
            known = {}
            count, depth = MODULE.ingest_session_tree(
                root_thread_id=root_id,
                session_root=root,
                launched_at=0,
                known=known,
            )
            self.assertEqual((count, depth), (2, 7))


if __name__ == "__main__":
    unittest.main()
