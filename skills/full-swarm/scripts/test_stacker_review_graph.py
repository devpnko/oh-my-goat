from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("stacker_review_graph.py")
SPEC = importlib.util.spec_from_file_location("stacker_review_graph", SCRIPT)
assert SPEC and SPEC.loader
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


def write_canonical(path: Path, value: object) -> str:
    raw = review.canonical(value)
    path.write_bytes(raw)
    return review.digest(raw)


class ReviewGraphTest(unittest.TestCase):
    def subject(self, artifact_a: Path, artifact_b: Path) -> dict:
        binding_a = {
            "path": str(artifact_a),
            "bytes": artifact_a.stat().st_size,
            "sha256": review.digest(artifact_a.read_bytes()),
        }
        binding_b = {
            "path": str(artifact_b),
            "bytes": artifact_b.stat().st_size,
            "sha256": review.digest(artifact_b.read_bytes()),
        }
        return {
            "schema_version": "goat.owner_decision_subject.v1",
            "decision_subject_ref": "test",
            "decision_subject_version": "v1",
            "authority": "candidate",
            "authority_status": "NONE",
            "authority_consumption": {"binding": binding_a},
            "claim_ceiling": "test only",
            "deferred_not_established": {},
            "deterministic_evidence": {"a": binding_a, "duplicate": binding_a},
            "exact_stack_v2": {},
            "excluded_effects": [],
            "execution_transport": {"b": binding_b},
            "observed_material_blocker": {},
            "owner_decision_projection": {"status": "STOP"},
            "postimage_build_manifest": {},
            "progress_reporting": {},
            "projection_time_currentness": {"state": "PASS"},
            "publication_time_axis": {},
            "review_policy": {"triad": True},
            "successful_postconditions": {},
            "successor_lineage": {},
            "write_set": [],
        }

    def test_artifact_index_classifies_future_and_relative_postimages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = root / "current.txt"
            current.write_bytes(b"current")
            future = root / "future.txt"
            future_sha = review.digest(b"future")
            subject = self.subject(current, current)
            subject["write_set"] = [
                {
                    "postimage": {
                        "path": str(future),
                        "bytes": 6,
                        "sha256": future_sha,
                    }
                }
            ]
            subject["postimage_build_manifest"] = {
                "entries": [
                    {"path": "future.txt", "bytes": 6, "sha256": future_sha}
                ]
            }
            records, _summary = review.build_artifact_index(
                subject,
                allowed_roots=(root,),
            )
            statuses = {record["path"]: record["status"] for record in records}
            self.assertEqual(
                statuses[str(future)],
                "DECLARED_FUTURE_POSTIMAGE_NOT_CURRENT_ARTIFACT",
            )
            self.assertEqual(
                statuses["future.txt"],
                "RELATIVE_MANIFEST_ENTRY_NOT_DIRECT_ARTIFACT",
            )

    def test_build_rejects_stale_review_schema_subject_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact.txt"
            artifact.write_bytes(b"artifact")
            subject_path = root / "subject.json"
            required = write_canonical(
                subject_path,
                self.subject(artifact, artifact),
            )
            schema_path = root / "review-schema.json"
            write_canonical(
                schema_path,
                {
                    "type": "object",
                    "properties": {
                        "subject_sha256": {
                            "type": "string",
                            "const": "sha256:" + "0" * 64,
                        }
                    },
                },
            )
            with self.assertRaisesRegex(
                review.ReviewGraphError,
                "review_schema_subject_digest_mismatch",
            ):
                review.build_review_bundle(
                    subject_path=subject_path,
                    required_digest=required,
                    output_dir=root / "bundle",
                    allowed_roots=(root,),
                    review_schema_path=schema_path,
                )

    def test_build_and_verify_bind_exact_review_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact.txt"
            artifact.write_bytes(b"artifact")
            subject_path = root / "subject.json"
            required = write_canonical(
                subject_path,
                self.subject(artifact, artifact),
            )
            schema_path = root / "review-schema.json"
            write_canonical(
                schema_path,
                {
                    "type": "object",
                    "properties": {
                        "subject_sha256": {
                            "type": "string",
                            "const": required,
                        }
                    },
                },
            )
            bundle = root / "bundle"
            review.build_review_bundle(
                subject_path=subject_path,
                required_digest=required,
                output_dir=bundle,
                allowed_roots=(root,),
                review_schema_path=schema_path,
            )
            fact = json.loads((bundle / "fact-packet.json").read_text())
            self.assertEqual(
                fact["content"]["review_schema"]["subject_sha256_const"],
                required,
            )
            verified = review.verify_review_bundle(
                bundle_dir=bundle,
                subject_path=subject_path,
                required_digest=required,
            )
            self.assertEqual(verified["status"], "MATERIALIZED_VERIFIED")

    def compact_receipt(
        self,
        root: Path,
        subject_path: Path,
        required: str,
        *,
        returncode: int = 0,
        result: dict | None = None,
        tool_published: bool = False,
    ) -> Path:
        launcher = root / "verifier.sh"
        launcher.write_bytes(b"#!/bin/sh\n")
        stdout_path = root / "verifier.stdout.json"
        stderr_path = root / "verifier.stderr"
        observed_result = result or review.expected_verifier_result(required)
        stdout_raw = review.canonical(observed_result) + b"\n"
        stdout_path.write_bytes(stdout_raw)
        stderr_path.write_bytes(b"")
        launcher_identity = review.descriptor_identity(os.lstat(launcher))
        capture_identity = {
            **launcher_identity,
            "inode": launcher_identity["inode"] + 1000,
            "mode_permissions": 0o400,
            "nlink": 0,
        }
        content = {
            "subject": review.exact_file_binding(subject_path),
            "launcher": review.exact_file_binding(launcher),
            "logical_argv": [str(launcher), str(subject_path), required],
            "argv": ["/bin/sh", "/dev/fd/9", str(subject_path), required],
            "execution_transport": {
                "kind": "CONTENT_BOUND_SOURCE_TO_UNLINKED_PRIVATE_CAPTURE_TO_ROOT_OWNED_SHELL",
                "producer": review.exact_file_binding(SCRIPT),
                "shell": review.exact_file_binding(Path("/bin/sh")),
                "launcher": review.exact_file_binding(launcher),
                "source_descriptor_identity": launcher_identity,
                "source_descriptor_content_sha256": review.digest(launcher.read_bytes()),
                "private_capture": {
                    "creation": (
                        "PRIVATE_O_EXCL_WRITE_FSYNC_0400_REOPEN_READ_FD_"
                        "EXACT_WRITER_READER_IDENTITY_THEN_UNLINK"
                    ),
                    "content_sha256": review.digest(launcher.read_bytes()),
                    "bytes": launcher.stat().st_size,
                    "o_excl_writer_identity_before_close": {
                        **capture_identity,
                        "nlink": 1,
                    },
                    "execution_reader_identity_before_unlink": {
                        **capture_identity,
                        "nlink": 1,
                    },
                    "writer_reader_identity_equal": True,
                    "before_unlink_identity": {**capture_identity, "nlink": 1},
                    "unlinked_identity": capture_identity,
                    "writable_descriptor_closed_before_execution": True,
                    "pathname_absent_before_execution": True,
                },
                "private_capture_post_execution": {
                    "identity": capture_identity,
                    "content_sha256": review.digest(launcher.read_bytes()),
                },
                "parent_environment": "EMPTY",
                "launcher_descriptor_closed_after_execution": True,
            },
            "returncode": returncode,
            "result": observed_result,
            "raw_stdout": {
                "path": str(stdout_path),
                "bytes": len(stdout_raw),
                "sha256": review.digest(stdout_raw),
            },
            "raw_stderr": {
                "path": str(stderr_path),
                "bytes": 0,
                "sha256": review.digest(b""),
            },
            "authority": "NONE",
            "live_effect": "NONE_READ_ONLY",
            "automatic_retry": False,
            "claim_ceiling": (
                "COMPACT_TRANSPORT_RECEIPT_NOT_A_MODEL_VERDICT_OR_CONTINUOUS_CURRENTNESS"
            ),
        }
        receipt = review.wrapped(review.VERIFIER_RECEIPT_SCHEMA, content)
        receipt_path = root / "compact.json"
        if tool_published:
            review.publish_exact(receipt_path, review.packet_bytes(receipt))
        else:
            write_canonical(receipt_path, receipt)
        return receipt_path

    def test_build_deduplicates_artifacts_and_emits_dependency_graph(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_a = root / "a.bin"
            artifact_b = root / "b.bin"
            artifact_a.write_bytes(b"alpha")
            artifact_b.write_bytes(b"beta")
            subject_path = root / "subject.json"
            required = write_canonical(subject_path, self.subject(artifact_a, artifact_b))
            output = root / "output"
            result = review.build_review_bundle(
                subject_path=subject_path,
                required_digest=required,
                output_dir=output,
                allowed_roots=(root,),
            )
            self.assertEqual(result["status"], "MATERIALIZED")
            summary = result["artifact_summary"]
            self.assertEqual(summary["reference_count"], 4)
            self.assertEqual(summary["unique_binding_count"], 2)
            self.assertEqual(summary["duplicate_reference_count"], 2)
            self.assertEqual(summary["status_counts"], {"EXACT": 2})
            graph = json.loads((output / "review-graph.json").read_text())
            nodes = {item["node_id"]: item for item in graph["content"]["nodes"]}
            self.assertEqual(nodes["fable"]["depends_on"], ["triad-join"])
            self.assertEqual(
                nodes["mechanical-champion-synthesis"]["kind"],
                "CROSS_INVARIANT_SYNTHESIS",
            )
            self.assertEqual(
                graph["content"]["scheduler_contract"]["authority"], "NONE"
            )
            self.assertEqual(
                graph["content"]["scheduler_contract"]["dependency_ready_dispatch"],
                "IMMEDIATE_AFTER_OWN_DEPENDENCIES",
            )
            self.assertEqual(
                graph["content"]["scheduler_contract"]["global_level_barrier"],
                "FORBIDDEN",
            )
            self.assertEqual(
                graph["content"]["scheduler_contract"]["topological_levels_are"],
                "DIAGNOSTIC_ONLY_NOT_EXECUTION_BARRIERS",
            )
            self.assertIn("topological_levels", graph["content"])
            self.assertNotIn("waves", graph["content"])
            verified = review.verify_review_bundle(
                bundle_dir=output,
                subject_path=subject_path,
                required_digest=required,
            )
            self.assertEqual(verified["status"], "MATERIALIZED_VERIFIED")
            self.assertEqual(verified["role_packet_count"], 7)

    def test_build_refuses_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "a.bin"
            artifact.write_bytes(b"a")
            subject_path = root / "subject.json"
            write_canonical(subject_path, self.subject(artifact, artifact))
            with self.assertRaises(review.ReviewGraphError):
                review.build_review_bundle(
                    subject_path=subject_path,
                    required_digest="sha256:" + "0" * 64,
                    output_dir=root / "output",
                    allowed_roots=(root,),
                )

    def test_build_binds_compact_verifier_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "a.bin"
            artifact.write_bytes(b"a")
            subject_path = root / "subject.json"
            required = write_canonical(subject_path, self.subject(artifact, artifact))
            receipt_path = self.compact_receipt(root, subject_path, required)
            output = root / "output"
            review.build_review_bundle(
                subject_path=subject_path,
                required_digest=required,
                output_dir=output,
                allowed_roots=(root,),
                verifier_receipt_path=receipt_path,
            )
            fact = json.loads((output / "fact-packet.json").read_text())
            self.assertEqual(
                fact["content"]["compact_verifier_receipt"]["path"],
                str(receipt_path),
            )
            graph = json.loads((output / "review-graph.json").read_text())
            self.assertIn(
                "COMPACT_RECEIPT_REUSE",
                graph["content"]["independence_contract"]["exact_verifier_policy"],
            )

    def test_build_binds_tool_published_compact_verifier_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "a.bin"
            artifact.write_bytes(b"a")
            subject_path = root / "subject.json"
            required = write_canonical(subject_path, self.subject(artifact, artifact))
            receipt_path = self.compact_receipt(
                root,
                subject_path,
                required,
                tool_published=True,
            )
            result = review.build_review_bundle(
                subject_path=subject_path,
                required_digest=required,
                output_dir=root / "output",
                allowed_roots=(root,),
                verifier_receipt_path=receipt_path,
            )
            self.assertEqual(result["status"], "MATERIALIZED")

    def test_parse_json_rejects_noncanonical_trailing_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "payload.json"
            path.write_bytes(review.canonical({"a": 1}) + b"\n\n")
            with self.assertRaisesRegex(review.ReviewGraphError, "json_not_canonical"):
                review.parse_json(path, require_canonical=True)

    def test_capture_then_build_compact_verifier_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "a.bin"
            artifact.write_bytes(b"a")
            subject_path = root / "subject.json"
            required = write_canonical(subject_path, self.subject(artifact, artifact))
            expected = review.expected_verifier_result(required)
            launcher = root / "verifier.sh"
            launcher.write_text(
                "#!/bin/sh\n"
                "test -z \"${STACKER_AMBIENT_LEAK+x}\"\n"
                "printf '%s\\n' "
                + json.dumps(review.canonical(expected).decode("utf-8"))
                + "\n"
            )
            launcher.chmod(0o700)
            launcher_binding = review.exact_file_binding(launcher)
            launcher_contract = root / "verifier-launcher-contract.json"
            write_canonical(
                launcher_contract,
                {
                    "schema_version": review.LAUNCHER_BINDING_CONTRACT_SCHEMA,
                    "label": "exact-verifier",
                    "launcher_path": str(launcher.resolve()),
                    "launcher_sha256": launcher_binding["sha256"],
                    "launcher_bytes": launcher_binding["bytes"],
                },
            )
            capture_dir = root / "capture"
            with mock.patch.dict(
                os.environ, {"STACKER_AMBIENT_LEAK": "forbidden"}, clear=False
            ):
                captured = review.capture_compact_verifier_receipt(
                    launcher_path=launcher,
                    launcher_contract_path=launcher_contract,
                    subject_path=subject_path,
                    required_digest=required,
                    output_dir=capture_dir,
                    timeout_seconds=10,
                )
            self.assertEqual(captured["status"], "CAPTURED_PASS")
            compact = json.loads(
                (capture_dir / "compact-verifier-receipt.json").read_text()
            )
            transport = compact["content"]["execution_transport"]
            self.assertEqual(transport["parent_environment"], "EMPTY")
            self.assertEqual(
                transport["private_capture"]["content_sha256"],
                review.digest(launcher.read_bytes()),
            )
            self.assertEqual(
                transport["private_capture"]["unlinked_identity"]["nlink"], 0
            )
            self.assertTrue(
                transport["private_capture"]["writer_reader_identity_equal"]
            )
            self.assertEqual(
                transport["private_capture"]["o_excl_writer_identity_before_close"],
                transport["private_capture"]["execution_reader_identity_before_unlink"],
            )
            self.assertTrue(
                review.same_capture_inode_transition(
                    transport["private_capture"]["before_unlink_identity"],
                    transport["private_capture"]["unlinked_identity"],
                )
            )
            built = review.build_review_bundle(
                subject_path=subject_path,
                required_digest=required,
                output_dir=root / "bundle",
                allowed_roots=(root,),
                verifier_receipt_path=capture_dir / "compact-verifier-receipt.json",
            )
            self.assertEqual(built["status"], "MATERIALIZED")

    def test_build_rejects_private_capture_writer_reader_inode_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "a.bin"
            artifact.write_bytes(b"a")
            subject_path = root / "subject.json"
            required = write_canonical(subject_path, self.subject(artifact, artifact))
            receipt_path = self.compact_receipt(root, subject_path, required)
            receipt = json.loads(receipt_path.read_text())
            capture = receipt["content"]["execution_transport"]["private_capture"]
            capture["o_excl_writer_identity_before_close"]["inode"] += 1
            receipt["content_sha256"] = review.digest(
                review.canonical(receipt["content"])
            )
            receipt_path.write_bytes(review.canonical(receipt))
            with self.assertRaisesRegex(
                review.ReviewGraphError,
                "compact_verifier_receipt_execution_transport_invalid",
            ):
                review.build_review_bundle(
                    subject_path=subject_path,
                    required_digest=required,
                    output_dir=root / "bundle",
                    allowed_roots=(root,),
                    verifier_receipt_path=receipt_path,
                )

    def test_build_refuses_nonpass_compact_verifier_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "a.bin"
            artifact.write_bytes(b"a")
            subject_path = root / "subject.json"
            required = write_canonical(subject_path, self.subject(artifact, artifact))
            receipt_path = self.compact_receipt(
                root,
                subject_path,
                required,
                returncode=1,
                result={"result": "FAIL"},
            )
            with self.assertRaisesRegex(
                review.ReviewGraphError, "compact_verifier_receipt_is_not_pass"
            ):
                review.build_review_bundle(
                    subject_path=subject_path,
                    required_digest=required,
                    output_dir=root / "output",
                    allowed_roots=(root,),
                    verifier_receipt_path=receipt_path,
                )

    def test_build_refuses_pass_prefix_compact_verifier_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "a.bin"
            artifact.write_bytes(b"a")
            subject_path = root / "subject.json"
            required = write_canonical(subject_path, self.subject(artifact, artifact))
            forged = review.expected_verifier_result(required)
            forged["result"] = "PASS_FORGED_PREFIX"
            receipt_path = self.compact_receipt(
                root,
                subject_path,
                required,
                result=forged,
            )
            with self.assertRaisesRegex(
                review.ReviewGraphError, "compact_verifier_receipt_is_not_pass"
            ):
                review.build_review_bundle(
                    subject_path=subject_path,
                    required_digest=required,
                    output_dir=root / "output",
                    allowed_roots=(root,),
                    verifier_receipt_path=receipt_path,
                )

    def test_build_refuses_compact_verifier_wrapper_digest_tamper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "a.bin"
            artifact.write_bytes(b"a")
            subject_path = root / "subject.json"
            required = write_canonical(subject_path, self.subject(artifact, artifact))
            receipt_path = self.compact_receipt(root, subject_path, required)
            receipt = json.loads(receipt_path.read_text())
            receipt["content_sha256"] = "sha256:" + "0" * 64
            write_canonical(receipt_path, receipt)
            with self.assertRaisesRegex(
                review.ReviewGraphError, "compact_verifier_receipt_wrapper_invalid"
            ):
                review.build_review_bundle(
                    subject_path=subject_path,
                    required_digest=required,
                    output_dir=root / "output",
                    allowed_roots=(root,),
                    verifier_receipt_path=receipt_path,
                )

    def test_exact_rebuild_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "a.bin"
            artifact.write_bytes(b"a")
            subject_path = root / "subject.json"
            required = write_canonical(subject_path, self.subject(artifact, artifact))
            output = root / "output"
            first = review.build_review_bundle(
                subject_path=subject_path,
                required_digest=required,
                output_dir=output,
                allowed_roots=(root,),
            )
            second = review.build_review_bundle(
                subject_path=subject_path,
                required_digest=required,
                output_dir=output,
                allowed_roots=(root,),
            )
            self.assertEqual(
                first["fact_packet_sha256"], second["fact_packet_sha256"]
            )
            self.assertTrue(
                all(
                    value == "EXACT_EXISTING"
                    for value in second["publication"].values()
                )
            )

    def test_verify_rejects_role_packet_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "a.bin"
            artifact.write_bytes(b"a")
            subject_path = root / "subject.json"
            required = write_canonical(subject_path, self.subject(artifact, artifact))
            output = root / "output"
            review.build_review_bundle(
                subject_path=subject_path,
                required_digest=required,
                output_dir=output,
                allowed_roots=(root,),
            )
            packet = output / "semantic-packet.json"
            packet.write_bytes(packet.read_bytes().replace(b'"semantic"', b'"tampered"', 1))
            with self.assertRaises(review.ReviewGraphError):
                review.verify_review_bundle(
                    bundle_dir=output,
                    subject_path=subject_path,
                    required_digest=required,
                )

    def test_metrics_separates_serial_and_parallel_cost(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            review_dir = root / "reviews"
            review_dir.mkdir()
            fixtures = [
                ("mechanical", 10.0, "MODIFY", [{"fingerprint": "A"}]),
                ("semantic", 6.0, "ADOPT", []),
            ]
            for index, (lens, elapsed, decision, findings) in enumerate(fixtures):
                prefix = f"{lens}-v1"
                watchdog = {
                    "status": "PASS",
                    "elapsed_seconds": elapsed,
                    "automatic_retry": False,
                    "policy": {"model": lens + "-model", "effort": "max"},
                }
                final = {
                    "lens": lens,
                    "decision": decision,
                    "subject_sha256": "sha256:" + "1" * 64,
                    "material_findings": findings,
                }
                (review_dir / f"{prefix}.watchdog.json").write_text(
                    json.dumps(watchdog)
                )
                (review_dir / f"{prefix}.final.json").write_text(json.dumps(final))
                os.utime(
                    review_dir / f"{prefix}.watchdog.json",
                    (100 + index, 100 + index),
                )
            result = review.build_metrics(
                review_dir=review_dir,
                output_path=root / "metrics.json",
            )
            self.assertEqual(
                result["aggregate"]["serial_elapsed_seconds"], 16.0
            )
            self.assertEqual(
                result["aggregate"]["distinct_reported_fingerprint_count"], 1
            )
            self.assertEqual(
                result["aggregate"]["deduplicated_material_mechanism_count"],
                "NOT_ESTABLISHED",
            )
            self.assertEqual(result["status"], "MATERIALIZED")

    def test_metrics_resolves_slice_prompt_and_collects_provider_usage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            review_dir = root / "reviews"
            prompt_dir = root / "prompts"
            review_dir.mkdir()
            prompt_dir.mkdir()
            prefix = "mechanical-authority-replay"
            (prompt_dir / f"{prefix}-prompt.md").write_text("bounded slice")
            (review_dir / f"{prefix}.watchdog.json").write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "elapsed_seconds": 2.0,
                        "automatic_retry": False,
                        "policy": {"model": "gpt", "effort": "max"},
                    }
                )
            )
            (review_dir / f"{prefix}.final.json").write_text(
                json.dumps(
                    {
                        "lens": "MECHANICAL",
                        "decision": "ADOPT",
                        "subject_sha256": "sha256:" + "2" * 64,
                        "material_findings": [],
                    }
                )
            )
            (review_dir / f"{prefix}.events.jsonl").write_text(
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 80,
                            "output_tokens": 20,
                            "reasoning_output_tokens": 10,
                        },
                    }
                )
                + "\n"
            )
            result = review.build_metrics(
                review_dir=review_dir,
                output_path=root / "metrics.json",
                prompt_dir=prompt_dir,
            )
            receipt = json.loads((root / "metrics.json").read_text())
            lane = receipt["content"]["lanes"][0]
            self.assertEqual(lane["prompt_bytes"], len("bounded slice"))
            self.assertEqual(lane["reported_usage"]["input_tokens"], 100)
            self.assertEqual(
                result["aggregate"]["reported_usage_totals"]["output_tokens"],
                20,
            )

    def test_metrics_resolves_direct_lane_prompt_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prompt_dir = root / "prompts"
            prompt_dir.mkdir()
            direct = prompt_dir / "semantic.md"
            direct.write_text("direct lane prompt")
            self.assertEqual(
                review.resolve_prompt_path(
                    prompt_dir, prefix="semantic", lens="SEMANTIC"
                ),
                direct,
            )

    def test_metrics_deduplicates_legacy_stdout_provider_failure_incidents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            review_dir = root / "reviews"
            review_dir.mkdir()
            for prefix in ("mechanical-a", "mechanical-b"):
                write_canonical(
                    review_dir / f"{prefix}.watchdog.json",
                    {
                        "status": "STOPPED",
                        "returncode": 1,
                        "automatic_retry": False,
                        "stop_reason": None,
                        "fallback_events": [],
                        "elapsed_seconds": 1.0,
                        "policy": {"model": "gpt", "effort": "high"},
                    },
                )
                (review_dir / f"{prefix}.events.jsonl").write_text(
                    json.dumps(
                        {
                            "type": "error",
                            "message": "You've hit your usage limit.",
                        }
                    )
                    + "\n"
                )
            result = review.build_metrics(
                review_dir=review_dir,
                output_path=root / "metrics.json",
            )
            self.assertEqual(result["status"], "MATERIALIZED")
            receipt = json.loads((root / "metrics.json").read_text())
            lanes = receipt["content"]["lanes"]
            self.assertEqual(
                {item["stop_reason"] for item in lanes},
                {"PROVIDER_USAGE_LIMIT"},
            )
            aggregate = receipt["content"]["aggregate"]
            self.assertEqual(aggregate["provider_failure_lane_count"], 2)
            self.assertEqual(aggregate["provider_failure_incident_count"], 1)
            self.assertEqual(
                aggregate["provider_failure_incident_keys"],
                ["PROVIDER_USAGE_LIMIT"],
            )

    def test_metrics_uses_declared_dag_for_sequential_champion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            review_dir = root / "reviews"
            review_dir.mkdir()
            for prefix, elapsed in (
                ("mechanical-authority-replay", 10.0),
                ("mechanical-filesystem-crash", 12.0),
                ("semantic", 8.0),
                ("atomicity", 9.0),
                ("mechanical-champion", 5.0),
            ):
                (review_dir / f"{prefix}.watchdog.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "elapsed_seconds": elapsed,
                            "automatic_retry": False,
                            "policy": {"model": "test", "effort": "high"},
                        }
                    )
                )
                (review_dir / f"{prefix}.final.json").write_text(
                    json.dumps(
                        {
                            "lens": prefix,
                            "decision": "ADOPT",
                            "subject_sha256": "sha256:" + "3" * 64,
                            "material_findings": [],
                        }
                    )
                )
            graph_path = root / "review-graph.json"
            write_canonical(
                graph_path,
                review.wrapped(
                    review.REVIEW_GRAPH_SCHEMA,
                    {
                        "nodes": [
                            {"node_id": "deterministic", "depends_on": []},
                            {
                                "node_id": "mechanical-authority-replay",
                                "depends_on": ["deterministic"],
                            },
                            {
                                "node_id": "mechanical-filesystem-crash",
                                "depends_on": ["deterministic"],
                            },
                            {"node_id": "semantic", "depends_on": ["deterministic"]},
                            {"node_id": "atomicity", "depends_on": ["deterministic"]},
                            {
                                "node_id": "mechanical-champion-synthesis",
                                "depends_on": [
                                    "mechanical-authority-replay",
                                    "mechanical-filesystem-crash",
                                ],
                            },
                        ]
                    },
                ),
            )
            result = review.build_metrics(
                review_dir=review_dir,
                output_path=root / "metrics.json",
                review_graph_path=graph_path,
            )
            timing = result["aggregate"]["declared_dag_timing"]
            self.assertEqual(timing["status"], "COMPUTED")
            self.assertEqual(timing["observed_model_critical_path_seconds"], 17.0)
            self.assertEqual(
                timing["critical_end_nodes"], ["mechanical-champion-synthesis"]
            )
            self.assertEqual(
                result["aggregate"]["declared_dag_parallel_gain_fraction"],
                0.6136,
            )

    def test_capture_bound_launcher_executes_retained_descriptor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher = root / "launcher.sh"
            launcher.write_text(
                "#!/bin/sh\nset -eu\n"
                "test -z \"${STACKER_AMBIENT_LEAK+x}\"\n"
                "printf 'OK:%s\\n' \"$1\"\n"
            )
            launcher.chmod(0o700)
            launcher_binding = review.exact_file_binding(launcher)
            launcher_contract = root / "bound-launcher-contract.json"
            write_canonical(
                launcher_contract,
                {
                    "schema_version": review.LAUNCHER_BINDING_CONTRACT_SCHEMA,
                    "label": "test-launcher",
                    "launcher_path": str(launcher.resolve()),
                    "launcher_sha256": launcher_binding["sha256"],
                    "launcher_bytes": launcher_binding["bytes"],
                },
            )
            with mock.patch.dict(
                os.environ, {"STACKER_AMBIENT_LEAK": "forbidden"}, clear=False
            ):
                result = review.capture_bound_launcher_receipt(
                    launcher_path=launcher,
                    launcher_contract_path=launcher_contract,
                    arguments=["bound"],
                    output_dir=root / "capture",
                    label="test-launcher",
                    timeout_seconds=5,
                )
            self.assertEqual(result["status"], "CAPTURED_PASS")
            receipt = json.loads(Path(result["receipt"]).read_text())
            content = receipt["content"]
            self.assertEqual(content["returncode"], 0)
            self.assertEqual(content["logical_argv"], [str(launcher), "bound"])
            self.assertEqual(
                content["execution_transport"]["kind"],
                "CONTENT_BOUND_SOURCE_TO_UNLINKED_PRIVATE_CAPTURE_TO_ROOT_OWNED_SHELL",
            )
            self.assertEqual(
                content["execution_transport"]["private_capture"][
                    "content_sha256"
                ],
                review.digest(launcher.read_bytes()),
            )
            self.assertEqual(
                content["execution_transport"]["private_capture"][
                    "unlinked_identity"
                ]["nlink"],
                0,
            )
            self.assertTrue(
                content["execution_transport"]["private_capture"][
                    "writer_reader_identity_equal"
                ]
            )
            self.assertEqual(
                (root / "capture/test-launcher.stdout").read_bytes(),
                b"OK:bound\n",
            )
            self.assertEqual(
                receipt["content_sha256"], review.digest(review.canonical(content))
            )

    def write_triad_lane(
        self,
        review_dir: Path,
        *,
        stem: str,
        lens: str,
        required: str,
        decision: str,
        fingerprints: tuple[str, ...] = (),
    ) -> None:
        write_canonical(
            review_dir / f"{stem}.final.json",
            {
                "lens": lens,
                "subject_sha256": required,
                "digest_verified": True,
                "decision": decision,
                "material_findings": [
                    {"fingerprint": fingerprint} for fingerprint in fingerprints
                ],
            },
        )
        write_canonical(
            review_dir / f"{stem}.watchdog.json",
            {
                "status": "PASS",
                "returncode": 0,
                "automatic_retry": False,
                "stop_reason": None,
                "fallback_events": [],
            },
        )

    def test_triad_gate_stops_before_fable_on_material_finding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            required = "sha256:" + "1" * 64
            self.write_triad_lane(
                root,
                stem="mechanical-champion",
                lens="mechanical",
                required=required,
                decision="MODIFY",
                fingerprints=("material-a",),
            )
            self.write_triad_lane(
                root,
                stem="semantic",
                lens="semantic",
                required=required,
                decision="ADOPT",
            )
            self.write_triad_lane(
                root,
                stem="atomicity",
                lens="atomicity",
                required=required,
                decision="ADOPT",
            )
            result = review.build_triad_gate(
                review_dir=root,
                required_digest=required,
                output_path=root / "triad-gate.json",
            )
            self.assertEqual(result["status"], "STOP_BEFORE_FABLE")
            self.assertEqual(result["blocking"][0]["lens"], "mechanical")

    def test_triad_gate_allows_fable_only_after_exact_adopt_join(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            required = "sha256:" + "2" * 64
            for stem, lens in (
                ("mechanical-champion", "mechanical"),
                ("semantic", "semantic"),
                ("atomicity", "atomicity"),
            ):
                self.write_triad_lane(
                    root,
                    stem=stem,
                    lens=lens,
                    required=required,
                    decision="ADOPT",
                )
            result = review.build_triad_gate(
                review_dir=root,
                required_digest=required,
                output_path=root / "triad-gate.json",
            )
            self.assertEqual(result["status"], "FABLE_ELIGIBLE")
            self.assertEqual(result["blocking"], [])

    def test_triad_gate_stops_on_terminal_lane_without_final_verdict(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            required = "sha256:" + "3" * 64
            self.write_triad_lane(
                root,
                stem="mechanical-champion",
                lens="mechanical",
                required=required,
                decision="ADOPT",
            )
            self.write_triad_lane(
                root,
                stem="semantic",
                lens="semantic",
                required=required,
                decision="ADOPT",
            )
            write_canonical(
                root / "atomicity.watchdog.json",
                {
                    "status": "STOPPED",
                    "returncode": 1,
                    "automatic_retry": False,
                    "stop_reason": "RESULT_ERROR",
                    "fallback_events": [],
                },
            )
            result = review.build_triad_gate(
                review_dir=root,
                required_digest=required,
                output_path=root / "triad-gate.json",
            )
            self.assertEqual(result["status"], "STOP_BEFORE_FABLE")
            atomicity = next(
                item for item in result["blocking"] if item["lens"] == "atomicity"
            )
            self.assertEqual(atomicity["decision"], "UNAVAILABLE")
            self.assertEqual(
                atomicity["reason_class"],
                "MODEL_LANE_NONPASS_NO_FINAL_VERDICT",
            )
            gate = json.loads((root / "triad-gate.json").read_text())
            self.assertFalse(gate["content"]["fable_started"])

    def test_triad_gate_stops_when_champion_was_not_started_after_slice_quota(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            required = "sha256:" + "4" * 64
            self.write_triad_lane(
                root,
                stem="semantic",
                lens="semantic",
                required=required,
                decision="ADOPT",
            )
            self.write_triad_lane(
                root,
                stem="atomicity",
                lens="atomicity",
                required=required,
                decision="ADOPT",
            )
            for name in review.DEFAULT_MECHANICAL_SLICES:
                stem = f"mechanical-{name}"
                write_canonical(
                    root / f"{stem}.watchdog.json",
                    {
                        "status": "STOPPED",
                        "returncode": 1,
                        "automatic_retry": False,
                        "stop_reason": None,
                        "fallback_events": [],
                    },
                )
                (root / f"{stem}.events.jsonl").write_text(
                    json.dumps(
                        {
                            "type": "error",
                            "message": "You've hit your usage limit.",
                        }
                    )
                    + "\n"
                )
            result = review.build_triad_gate(
                review_dir=root,
                required_digest=required,
                output_path=root / "triad-gate.json",
            )
            self.assertEqual(result["status"], "STOP_BEFORE_FABLE")
            mechanical = next(
                item for item in result["blocking"] if item["lens"] == "mechanical"
            )
            self.assertEqual(mechanical["decision"], "UNAVAILABLE")
            self.assertEqual(
                mechanical["reason_class"],
                "MECHANICAL_CHAMPION_NOT_STARTED_UPSTREAM_LANE_NONPASS",
            )
            self.assertEqual(
                mechanical["stop_reasons"],
                ["PROVIDER_USAGE_LIMIT"],
            )
            gate = json.loads((root / "triad-gate.json").read_text())
            self.assertFalse(gate["content"]["fable_started"])


if __name__ == "__main__":
    unittest.main()
