#!/usr/bin/env python3
"""Build digest-bound review packets, a review DAG, and cost receipts.

Outputs are derived review inputs, never Authority, reviewer verdicts, or
canonical GOAT state. Deterministic facts may be shared; model judgment may not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


FACT_PACKET_SCHEMA = "stacker.deterministic_fact_packet.v1"
ROLE_PACKET_SCHEMA = "stacker.role_review_packet.v1"
REVIEW_GRAPH_SCHEMA = "stacker.evidence_aware_review_graph.v1"
METRICS_SCHEMA = "stacker.review_cost_receipt.v1"
TRIAD_GATE_SCHEMA = "stacker.triad_dependency_join_receipt.v1"
VERIFIER_RECEIPT_SCHEMA = "stacker.compact_verifier_receipt.v3"
BOUND_LAUNCHER_RECEIPT_SCHEMA = "stacker.bound_launcher_execution_receipt.v3"
LAUNCHER_BINDING_CONTRACT_SCHEMA = "stacker.launcher_binding_contract.v1"
SPEC_SCHEMA = "stacker.review_graph_spec.v1"
SYSTEM_SHELL_ALIAS = Path("/bin/sh")

PROVIDER_TERMINAL_MARKERS = (
    (b"usage limit", "PROVIDER_USAGE_LIMIT"),
    (b"hard quota", "PROVIDER_USAGE_LIMIT"),
    (b"429 too many requests", "PROVIDER_RATE_LIMIT"),
    (b"exceeded retry limit", "PROVIDER_RETRY_LIMIT_EXCEEDED"),
    (b"401 unauthorized", "PROVIDER_AUTHENTICATION_FAILURE"),
    (b"403 forbidden", "PROVIDER_FORBIDDEN_TRANSPORT"),
)


def expected_verifier_result(required_digest: str) -> dict[str, Any]:
    return {
        "result": "PASS_AT_EXACT_AUDIT_EPOCH",
        "decision_subject_sha256": required_digest,
        "authority": "NONE",
        "repository_effect": "NONE_READ_ONLY",
        "database_effect": "NONE_READ_ONLY",
        "schema_version": "goat.subject_verifier_result.v2",
    }


def load_launcher_binding_contract(
    contract_path: Path,
    *,
    launcher_path: Path,
    label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    contract, _ = parse_json(contract_path, require_canonical=True)
    expected_fields = {
        "schema_version",
        "label",
        "launcher_path",
        "launcher_sha256",
        "launcher_bytes",
    }
    if set(contract) != expected_fields:
        raise ReviewGraphError("launcher_binding_contract_shape_invalid")
    if contract.get("schema_version") != LAUNCHER_BINDING_CONTRACT_SCHEMA:
        raise ReviewGraphError("launcher_binding_contract_schema_invalid")
    if contract.get("label") != label:
        raise ReviewGraphError("launcher_binding_contract_label_mismatch")
    if Path(str(contract.get("launcher_path"))).resolve() != launcher_path.resolve():
        raise ReviewGraphError("launcher_binding_contract_path_mismatch")
    expected_sha256 = str(contract.get("launcher_sha256") or "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_sha256):
        raise ReviewGraphError("launcher_binding_contract_digest_invalid")
    observed = exact_file_binding(launcher_path)
    if (
        observed["sha256"] != expected_sha256
        or observed["bytes"] != int(contract.get("launcher_bytes", -1))
    ):
        raise ReviewGraphError("launcher_binding_contract_prelaunch_mismatch")
    return contract, exact_file_binding(contract_path)

DEFAULT_COMMON_SECTIONS = (
    "schema_version",
    "decision_subject_ref",
    "decision_subject_version",
    "authority_status",
    "review_policy",
    "successor_lineage",
    "owner_decision_projection",
    "claim_ceiling",
)

DEFAULT_ROLE_SECTIONS = {
    "mechanical": (
        "authority",
        "authority_consumption",
        "write_set",
        "execution_transport",
        "publication_time_axis",
        "deterministic_evidence",
        "postimage_build_manifest",
        "successful_postconditions",
        "excluded_effects",
        "projection_time_currentness",
    ),
    "semantic": (
        "claim_ceiling",
        "observed_material_blocker",
        "progress_reporting",
        "successor_lineage",
        "owner_decision_projection",
        "exact_stack_v2",
        "excluded_effects",
        "deferred_not_established",
        "review_policy",
    ),
    "atomicity": (
        "authority",
        "authority_consumption",
        "publication_time_axis",
        "write_set",
        "execution_transport",
        "postimage_build_manifest",
        "successful_postconditions",
        "excluded_effects",
        "projection_time_currentness",
    ),
    "fable": (
        "claim_ceiling",
        "review_policy",
        "progress_reporting",
        "owner_decision_projection",
        "excluded_effects",
        "deferred_not_established",
        "successor_lineage",
    ),
}

DEFAULT_MECHANICAL_SLICES = {
    "authority-replay": (
        "authority",
        "authority_status",
        "authority_consumption",
        "owner_decision_projection",
        "excluded_effects",
    ),
    "filesystem-crash": (
        "write_set",
        "publication_time_axis",
        "postimage_build_manifest",
        "successful_postconditions",
    ),
    "sandbox-process": (
        "execution_transport",
        "projection_time_currentness",
        "successful_postconditions",
    ),
    "evidence-verifier": (
        "deterministic_evidence",
        "review_policy",
        "claim_ceiling",
        "projection_time_currentness",
    ),
}

ALLOWED_SPEC_FIELDS = {
    "schema_version",
    "common_sections",
    "role_sections",
    "mechanical_slices",
    "direct_recheck_sections",
    "sample_count",
}


class ReviewGraphError(RuntimeError):
    """The proposed review inputs cannot be bound safely."""


def system_shell_path() -> Path:
    """Return a resolved, root-owned, non-writable POSIX shell executable."""
    try:
        resolved = SYSTEM_SHELL_ALIAS.resolve(strict=True)
        observed = os.lstat(resolved)
    except OSError as exc:
        raise ReviewGraphError("system_shell_unavailable") from exc
    permissions = stat.S_IMODE(observed.st_mode)
    if (
        not resolved.is_absolute()
        or not stat.S_ISREG(observed.st_mode)
        or observed.st_uid != 0
        or permissions & 0o022
    ):
        raise ReviewGraphError(f"system_shell_not_trusted:{resolved}")
    return resolved


def provider_terminal_reason(raw: bytes) -> str | None:
    lowered = raw.lower()
    for marker, reason in PROVIDER_TERMINAL_MARKERS:
        if marker in lowered:
            return reason
    return None


def terminal_lane_without_final(
    *, review_dir: Path, stem: str, watchdog: dict[str, Any]
) -> tuple[bool, str | None, dict[str, Any] | None]:
    """Resolve a fail-closed lane, including legacy stdout-only provider stops."""
    fallback_events = watchdog.get("fallback_events", [])
    declared_reason = watchdog.get("stop_reason")
    events_binding: dict[str, Any] | None = None
    observed_reason: str | None = None
    events_path = review_dir / f"{stem}.events.jsonl"
    if declared_reason is None and events_path.is_file():
        events_raw = stable_read(events_path)
        observed_reason = provider_terminal_reason(events_raw)
        if observed_reason:
            events_binding = {
                "path": str(events_path),
                "bytes": len(events_raw),
                "sha256": digest(events_raw),
                "observed_stop_reason": observed_reason,
            }
    resolved_reason = (
        declared_reason if isinstance(declared_reason, str) else observed_reason
    )
    terminal = (
        watchdog.get("status") != "PASS"
        and isinstance(watchdog.get("returncode"), int)
        and watchdog.get("returncode") != 0
        and watchdog.get("automatic_retry") is False
        and isinstance(resolved_reason, str)
        and bool(resolved_reason)
        and isinstance(fallback_events, list)
        and not fallback_events
    )
    return terminal, resolved_reason, events_binding


def unavailable_mechanical_champion_from_slices(
    review_dir: Path,
) -> dict[str, Any] | None:
    """Derive champion unavailability only from a complete terminal slice set."""
    slices: list[dict[str, Any]] = []
    saw_nonpass = False
    for name in DEFAULT_MECHANICAL_SLICES:
        stem = f"mechanical-{name}"
        watchdog_path = review_dir / f"{stem}.watchdog.json"
        final_path = review_dir / f"{stem}.final.json"
        if not watchdog_path.is_file():
            return None
        watchdog, watchdog_raw = parse_json(watchdog_path)
        if not isinstance(watchdog, dict):
            return None
        if watchdog.get("status") == "PASS":
            if not final_path.is_file():
                return None
            slices.append(
                {
                    "stem": stem,
                    "outcome": "PASS",
                    "watchdog": {
                        "path": str(watchdog_path),
                        "bytes": len(watchdog_raw),
                        "sha256": digest(watchdog_raw),
                    },
                }
            )
            continue
        if final_path.exists() or os.path.lexists(final_path):
            return None
        terminal, resolved_reason, events_binding = terminal_lane_without_final(
            review_dir=review_dir,
            stem=stem,
            watchdog=watchdog,
        )
        if not terminal:
            return None
        saw_nonpass = True
        record: dict[str, Any] = {
            "stem": stem,
            "outcome": "NO_FINAL_VERDICT",
            "stop_reason": resolved_reason,
            "watchdog": {
                "path": str(watchdog_path),
                "bytes": len(watchdog_raw),
                "sha256": digest(watchdog_raw),
            },
        }
        if events_binding is not None:
            record["events"] = events_binding
        slices.append(record)
    if not saw_nonpass:
        return None
    return {
        "reason_class": "MECHANICAL_CHAMPION_NOT_STARTED_UPSTREAM_LANE_NONPASS",
        "upstream_slices": slices,
        "stop_reasons": sorted(
            {
                str(item["stop_reason"])
                for item in slices
                if item.get("outcome") == "NO_FINAL_VERDICT"
            }
        ),
    }


def canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def descriptor_identity(info: os.stat_result) -> dict[str, int]:
    return {
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "mode_type": int(stat.S_IFMT(info.st_mode)),
        "mode_permissions": int(stat.S_IMODE(info.st_mode)),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
        "bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "ctime_ns": int(info.st_ctime_ns),
    }


def same_capture_inode_transition(before: dict[str, int], after: dict[str, int]) -> bool:
    """Validate the expected link-count/ctime transition for one captured inode."""
    stable_keys = (
        "device",
        "inode",
        "mode_type",
        "mode_permissions",
        "uid",
        "gid",
        "bytes",
        "mtime_ns",
    )
    return (
        all(before.get(key) == after.get(key) for key in stable_keys)
        and before.get("nlink") == 1
        and after.get("nlink") == 0
        and isinstance(before.get("ctime_ns"), int)
        and isinstance(after.get("ctime_ns"), int)
        and int(after["ctime_ns"]) >= int(before["ctime_ns"])
    )


def stable_read_descriptor(descriptor: int) -> tuple[bytes, dict[str, int]]:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ReviewGraphError("descriptor_not_regular")
    chunks: list[bytes] = []
    offset = 0
    while True:
        chunk = os.pread(descriptor, 1024 * 1024, offset)
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
    after = os.fstat(descriptor)
    if descriptor_identity(before) != descriptor_identity(after):
        raise ReviewGraphError("descriptor_changed_during_read")
    raw = b"".join(chunks)
    if len(raw) != int(before.st_size):
        raise ReviewGraphError("descriptor_short_read")
    return raw, descriptor_identity(before)


def stable_read(path: Path) -> bytes:
    before = os.lstat(path)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ReviewGraphError(f"not_stable_regular_file:{path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        raw, observed_identity = stable_read_descriptor(descriptor)
        after_fd = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after_path = os.lstat(path)
    identities = {tuple(descriptor_identity(item).items()) for item in (before, opened, after_fd, after_path)}
    if len(identities) != 1:
        raise ReviewGraphError(f"unstable_file_during_read:{path}")
    if observed_identity != descriptor_identity(opened) or len(raw) != opened.st_size:
        raise ReviewGraphError(f"short_read:{path}")
    return raw


def captured_regular_source(path: Path) -> tuple[bytes, dict[str, Any], dict[str, int]]:
    before = os.lstat(path)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ReviewGraphError(f"captured_source_not_regular:{path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        raw, opened_identity = stable_read_descriptor(descriptor)
        after_fd = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after_path = os.lstat(path)
    identities = {
        tuple(descriptor_identity(item).items())
        for item in (before, opened, after_fd, after_path)
    }
    if len(identities) != 1 or opened_identity != descriptor_identity(opened):
        raise ReviewGraphError(f"captured_source_changed_during_read:{path}")
    binding = {
        "path": str(path),
        "bytes": len(raw),
        "mode_permissions": stat.S_IMODE(opened.st_mode),
        "sha256": digest(raw),
    }
    return raw, binding, opened_identity


def open_unlinked_private_capture(
    *, raw: bytes, output_dir: Path, label: str
) -> tuple[int, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    directory_info = os.lstat(output_dir)
    if stat.S_ISLNK(directory_info.st_mode) or not stat.S_ISDIR(directory_info.st_mode):
        raise ReviewGraphError("capture_output_directory_not_bound")
    directory_fd = os.open(
        output_dir,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    writer: int | None = None
    reader: int | None = None
    temporary_name: str | None = None
    try:
        if descriptor_identity(os.fstat(directory_fd)) != descriptor_identity(
            directory_info
        ):
            raise ReviewGraphError("capture_output_directory_rebound")
        for _attempt in range(16):
            candidate = f".{label}.launcher-capture-{os.urandom(16).hex()}"
            try:
                writer = os.open(
                    candidate,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
                temporary_name = candidate
                break
            except FileExistsError:
                continue
        if writer is None or temporary_name is None:
            raise ReviewGraphError("private_launcher_capture_name_exhausted")
        view = memoryview(raw)
        while view:
            written = os.write(writer, view)
            view = view[written:]
        os.fchmod(writer, 0o400)
        os.fsync(writer)
        reader = os.open(
            temporary_name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        captured_raw, before_unlink = stable_read_descriptor(reader)
        if captured_raw != raw:
            raise ReviewGraphError("private_launcher_capture_content_mismatch")
        writer_before_close = descriptor_identity(os.fstat(writer))
        if writer_before_close != before_unlink:
            raise ReviewGraphError("private_launcher_capture_writer_reader_identity_mismatch")
        os.close(writer)
        writer = None
        os.unlink(temporary_name, dir_fd=directory_fd)
        temporary_name = None
        os.fsync(directory_fd)
        after_unlink_raw, after_unlink = stable_read_descriptor(reader)
        if after_unlink_raw != raw or after_unlink.get("nlink") != 0:
            raise ReviewGraphError("private_launcher_capture_not_unlinked_exact")
        return reader, {
            "creation": (
                "PRIVATE_O_EXCL_WRITE_FSYNC_0400_REOPEN_READ_FD_"
                "EXACT_WRITER_READER_IDENTITY_THEN_UNLINK"
            ),
            "content_sha256": digest(raw),
            "bytes": len(raw),
            "o_excl_writer_identity_before_close": writer_before_close,
            "execution_reader_identity_before_unlink": before_unlink,
            "writer_reader_identity_equal": True,
            "before_unlink_identity": before_unlink,
            "unlinked_identity": after_unlink,
            "writable_descriptor_closed_before_execution": True,
            "pathname_absent_before_execution": True,
        }
    except BaseException:
        if reader is not None:
            os.close(reader)
            reader = None
        raise
    finally:
        if writer is not None:
            os.close(writer)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def capture_execution_transport(
    *, launcher_path: Path, output_dir: Path, label: str
) -> tuple[dict[str, Any], int, dict[str, Any]]:
    raw, launcher, source_identity = captured_regular_source(launcher_path)
    capture_fd, private_capture = open_unlinked_private_capture(
        raw=raw,
        output_dir=output_dir,
        label=label,
    )
    return launcher, capture_fd, {
        "kind": "CONTENT_BOUND_SOURCE_TO_UNLINKED_PRIVATE_CAPTURE_TO_ROOT_OWNED_SHELL",
        "launcher": launcher,
        "source_descriptor_identity": source_identity,
        "source_descriptor_content_sha256": digest(raw),
        "private_capture": private_capture,
        "parent_environment": "EMPTY",
    }


def parse_json(path: Path, *, require_canonical: bool = False) -> tuple[Any, bytes]:
    raw = stable_read(path)
    try:
        value = json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewGraphError(f"invalid_json:{path}:{exc}") from exc
    if require_canonical:
        canonical_raw = canonical(value)
        if raw not in (canonical_raw, canonical_raw + b"\n"):
            raise ReviewGraphError(f"json_not_canonical:{path}")
    return value, raw


def exact_file_binding(path: Path) -> dict[str, Any]:
    raw = stable_read(path)
    observed = os.lstat(path)
    return {
        "path": str(path),
        "bytes": len(raw),
        "mode_permissions": stat.S_IMODE(observed.st_mode),
        "sha256": digest(raw),
    }


def exact_review_schema_binding(path: Path, required_digest: str) -> dict[str, Any]:
    schema, raw = parse_json(path)
    if not isinstance(schema, dict):
        raise ReviewGraphError("review_schema_must_be_object")
    properties = schema.get("properties")
    subject_property = (
        properties.get("subject_sha256") if isinstance(properties, dict) else None
    )
    observed_const = (
        subject_property.get("const") if isinstance(subject_property, dict) else None
    )
    if observed_const != required_digest:
        raise ReviewGraphError(
            "review_schema_subject_digest_mismatch:"
            f"expected={required_digest}:observed={observed_const}"
        )
    binding = exact_file_binding(path)
    if binding["sha256"] != digest(raw):
        raise ReviewGraphError("review_schema_changed_during_validation")
    return {**binding, "subject_sha256_const": observed_const}


def json_pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def pointer_top_level(pointer: str) -> str:
    if not pointer.startswith("/"):
        return ""
    token = pointer[1:].split("/", 1)[0]
    return token.replace("~1", "/").replace("~0", "~")


def walk(value: Any, pointer: str = "") -> Iterable[tuple[str, Any]]:
    yield pointer or "/", value
    if isinstance(value, dict):
        for key in sorted(value):
            child = pointer + "/" + json_pointer_escape(str(key))
            yield from walk(value[key], child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, pointer + f"/{index}")


def _declared_sha(binding: dict[str, Any]) -> str:
    for key in ("sha256", "file_sha256", "content_sha256"):
        value = binding.get(key)
        if isinstance(value, str) and value.startswith("sha256:") and len(value) == 71:
            return value
    return ""


def binding_semantics(pointer: str) -> str:
    if pointer.startswith("/write_set/") and pointer.endswith("/postimage"):
        return "EXPECTED_POSTIMAGE_NOT_CURRENTNESS"
    if pointer.startswith("/postimage_build_manifest/"):
        return "EXPECTED_POSTIMAGE_RELATIVE_BINDING"
    if pointer.startswith("/projection_time_currentness/"):
        return "CURRENTNESS_CANDIDATE"
    if pointer.startswith("/execution_transport/"):
        return "EXECUTION_TRUST_BASE_CANDIDATE"
    return "UNCLASSIFIED_BINDING_OBSERVATION"


def collect_artifact_references(subject: Any) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for pointer, value in walk(subject):
        if not isinstance(value, dict):
            continue
        path = value.get("path")
        declared_sha = _declared_sha(value)
        if not isinstance(path, str) or not path or not declared_sha:
            continue
        declared_bytes = value.get("bytes")
        references.append(
            {
                "pointer": pointer,
                "top_level_section": pointer_top_level(pointer),
                "path": path,
                "declared_sha256": declared_sha,
                "declared_bytes": declared_bytes if isinstance(declared_bytes, int) else None,
                "binding_semantics": binding_semantics(pointer),
            }
        )
    return references


def path_is_within(path: Path, roots: tuple[Path, ...]) -> bool:
    absolute = path.expanduser().absolute()
    return any(absolute == root or root in absolute.parents for root in roots)


def build_artifact_index(
    subject: Any,
    *,
    allowed_roots: tuple[Path, ...],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    references = collect_artifact_references(subject)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in references:
        grouped[(item["path"], item["declared_sha256"])].append(item)

    records: list[dict[str, Any]] = []
    unique_bytes_read = 0
    duplicate_bytes_avoided = 0
    for (raw_path, declared_sha), items in sorted(grouped.items()):
        path = Path(raw_path).expanduser()
        pointers = sorted(item["pointer"] for item in items)
        observed_sha = ""
        observed_bytes: int | None = None
        status = "UNREAD"
        error = ""
        if pointers and all(
            re.fullmatch(r"/write_set/[0-9]+/postimage", pointer)
            for pointer in pointers
        ):
            status = "DECLARED_FUTURE_POSTIMAGE_NOT_CURRENT_ARTIFACT"
        elif not path.is_absolute() and pointers and all(
            pointer.startswith("/postimage_build_manifest/entries/")
            for pointer in pointers
        ):
            status = "RELATIVE_MANIFEST_ENTRY_NOT_DIRECT_ARTIFACT"
        elif not path.is_absolute():
            status = "NONABSOLUTE_PATH"
        elif not path_is_within(path, allowed_roots):
            status = "OUTSIDE_ALLOWED_ROOT"
        else:
            try:
                raw = stable_read(path)
                observed_sha = digest(raw)
                observed_bytes = len(raw)
                unique_bytes_read += len(raw)
                declared_sizes = {
                    item["declared_bytes"]
                    for item in items
                    if item["declared_bytes"] is not None
                }
                if observed_sha != declared_sha:
                    status = "DIGEST_MISMATCH"
                elif declared_sizes and declared_sizes != {len(raw)}:
                    status = "BYTES_MISMATCH"
                else:
                    status = "EXACT"
                duplicate_bytes_avoided += len(raw) * max(0, len(items) - 1)
            except (OSError, ReviewGraphError) as exc:
                status = "UNREADABLE"
                error = str(exc)
        records.append(
            {
                "path": raw_path,
                "declared_sha256": declared_sha,
                "declared_bytes": sorted(
                    {
                        item["declared_bytes"]
                        for item in items
                        if item["declared_bytes"] is not None
                    }
                ),
                "observed_sha256": observed_sha,
                "observed_bytes": observed_bytes,
                "status": status,
                "error": error or None,
                "reference_count": len(items),
                "pointers": pointers,
                "top_level_sections": sorted(
                    {item["top_level_section"] for item in items if item["top_level_section"]}
                ),
                "binding_semantics": sorted(
                    {item["binding_semantics"] for item in items}
                ),
            }
        )

    statuses = Counter(record["status"] for record in records)
    summary = {
        "reference_count": len(references),
        "unique_binding_count": len(records),
        "duplicate_reference_count": len(references) - len(records),
        "status_counts": dict(sorted(statuses.items())),
        "unique_artifact_bytes_read": unique_bytes_read,
        "duplicate_hash_bytes_avoided_within_packet_build": duplicate_bytes_avoided,
        "observed_exact_binding_count": int(statuses.get("EXACT", 0)),
        "nonexact_observation_count": len(records) - int(statuses.get("EXACT", 0)),
        "observation_is_admission_verdict": False,
        "interpretation_rule": (
            "CLASSIFY_BY_POINTER_SEMANTICS_AND_EXACT_SUBJECT_CONTRACT_BEFORE_GATING"
        ),
        "actual_reviewer_evidence_bytes_read": "NOT_INSTRUMENTED",
    }
    return records, summary


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def section_index(subject: dict[str, Any], inline_max_bytes: int) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key in sorted(subject):
        value = subject[key]
        raw = canonical(value)
        record: dict[str, Any] = {
            "pointer": "/" + json_pointer_escape(key),
            "type": type_name(value),
            "canonical_bytes": len(raw),
            "sha256": digest(raw),
        }
        if len(raw) <= inline_max_bytes:
            record["inline_value"] = value
        result[key] = record
    return result


def load_spec(path: Path | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": SPEC_SCHEMA,
        "common_sections": list(DEFAULT_COMMON_SECTIONS),
        "role_sections": {key: list(value) for key, value in DEFAULT_ROLE_SECTIONS.items()},
        "mechanical_slices": {
            key: list(value) for key, value in DEFAULT_MECHANICAL_SLICES.items()
        },
        "direct_recheck_sections": {},
        "sample_count": 3,
    }
    if path is None:
        return result
    supplied, _ = parse_json(path)
    if not isinstance(supplied, dict):
        raise ReviewGraphError("review_graph_spec_must_be_object")
    unknown = set(supplied) - ALLOWED_SPEC_FIELDS
    if unknown:
        raise ReviewGraphError("unknown_review_graph_spec_fields:" + ",".join(sorted(unknown)))
    if supplied.get("schema_version") != SPEC_SCHEMA:
        raise ReviewGraphError("review_graph_spec_version_mismatch")
    for key in ALLOWED_SPEC_FIELDS - {"schema_version"}:
        if key in supplied:
            result[key] = supplied[key]
    if not isinstance(result["sample_count"], int) or not 0 <= result["sample_count"] <= 50:
        raise ReviewGraphError("sample_count_must_be_0_to_50")
    return result


def normalized_sections(values: Any, subject: dict[str, Any]) -> list[str]:
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise ReviewGraphError("section_list_must_be_strings")
    return sorted({item for item in values if item in subject})


def select_samples(
    records: list[dict[str, Any]],
    *,
    role: str,
    sections: set[str],
    subject_sha256: str,
    count: int,
) -> list[dict[str, Any]]:
    eligible = [
        record
        for record in records
        if record["status"] == "EXACT"
        and sections.intersection(record["top_level_sections"])
    ]
    ranked = sorted(
        eligible,
        key=lambda record: hashlib.sha256(
            (subject_sha256 + "\0" + role + "\0" + record["path"]).encode("utf-8")
        ).hexdigest(),
    )
    return [
        {
            "path": record["path"],
            "declared_sha256": record["declared_sha256"],
            "observed_sha256": record["observed_sha256"],
            "source_pointers": record["pointers"],
            "selection_basis": "SUBJECT_DIGEST_AND_ROLE_SEEDED_SPOT_RECHECK",
        }
        for record in ranked[:count]
    ]


def wrapped(schema_version: str, content: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "content_sha256": digest(canonical(content)),
        "content": content,
    }


def publish_exact(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if stable_read(path) == payload:
            return "EXACT_EXISTING"
        raise ReviewGraphError(f"refuse_overwrite_nonmatching_output:{path}")
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        if stable_read(temporary) != payload:
            raise ReviewGraphError(f"nonmatching_temporary_output:{temporary}")
        os.replace(temporary, path)
        return "RECOVERED_EXACT_TEMPORARY"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    parent_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return "CREATED"


def packet_bytes(payload: dict[str, Any]) -> bytes:
    return canonical(payload) + b"\n"


def role_packet(
    *,
    role: str,
    sections: list[str],
    common_sections: list[str],
    section_records: dict[str, dict[str, Any]],
    subject_path: Path,
    subject_sha256: str,
    fact_packet: dict[str, Any],
    artifact_index_path: Path,
    artifact_index_sha256: str,
    samples: list[dict[str, Any]],
    required_rechecks: list[str],
    upstream_results: list[str] | None = None,
) -> dict[str, Any]:
    selected = sorted(set(common_sections + sections))
    compact_receipt = fact_packet.get("content", {}).get(
        "compact_verifier_receipt"
    )
    content = {
        "role": role,
        "subject": {"path": str(subject_path), "sha256": subject_sha256},
        "fact_packet": {"sha256": fact_packet["content_sha256"]},
        "section_refs": {
            key: section_records[key] for key in selected if key in section_records
        },
        "artifact_index": {
            "path": str(artifact_index_path),
            "sha256": artifact_index_sha256,
        },
        "direct_recheck_contract": {
            "required_section_pointers": [
                "/" + json_pointer_escape(item) for item in required_rechecks
            ],
            "seeded_artifact_samples": samples,
            "contradiction_rule": "OPEN_EXACT_RAW_LOCATOR_AND_RECOMPUTE",
            "shared_fact_rule": (
                "DETERMINISTIC_FACTS_MAY_BE_REUSED;_MODEL_JUDGMENT_MUST_NOT_BE_CACHED"
            ),
        },
        "scope_budget": {
            "initial_inputs": "ROLE_PACKET_PLUS_COMPACT_VERIFIER_RECEIPT",
            "whole_tree_enumeration": "FORBIDDEN_UNLESS_CONTRADICTION_REQUIRES_IT",
            "seeded_artifact_opens_before_escalation": len(samples),
            "additional_raw_open_requires_recorded_reason": True,
            "single_command_output_ceiling_bytes": 65536,
            "exact_verifier_execution": (
                "FORBIDDEN_REUSE_COMPACT_RECEIPT"
                if compact_receipt is not None
                else "NOT_BOUND_BY_FACT_PACKET"
            ),
        },
        "upstream_results_required_at_runtime": upstream_results or [],
        "authority": "NONE",
        "canonical_state_effect": "NONE_DERIVED_REVIEW_INPUT",
    }
    return wrapped(ROLE_PACKET_SCHEMA, content)


def build_review_bundle(
    *,
    subject_path: Path,
    required_digest: str,
    output_dir: Path,
    allowed_roots: tuple[Path, ...],
    spec_path: Path | None = None,
    verifier_receipt_path: Path | None = None,
    review_schema_path: Path | None = None,
    inline_max_bytes: int = 1024,
) -> dict[str, Any]:
    subject, subject_raw = parse_json(subject_path, require_canonical=True)
    if not isinstance(subject, dict):
        raise ReviewGraphError("subject_must_be_json_object")
    observed_digest = digest(subject_raw)
    if observed_digest != required_digest:
        raise ReviewGraphError(
            f"subject_digest_mismatch:expected={required_digest}:observed={observed_digest}"
        )
    if not required_digest.startswith("sha256:") or len(required_digest) != 71:
        raise ReviewGraphError("required_digest_must_be_sha256")
    review_schema = (
        exact_review_schema_binding(review_schema_path, required_digest)
        if review_schema_path is not None
        else None
    )
    spec = load_spec(spec_path)
    common_sections = normalized_sections(spec["common_sections"], subject)
    role_sections_raw = spec["role_sections"]
    if not isinstance(role_sections_raw, dict):
        raise ReviewGraphError("role_sections_must_be_object")
    role_sections = {
        str(role): normalized_sections(values, subject)
        for role, values in role_sections_raw.items()
    }
    mechanical_slices_raw = spec["mechanical_slices"]
    if not isinstance(mechanical_slices_raw, dict) or not mechanical_slices_raw:
        raise ReviewGraphError("mechanical_slices_must_be_nonempty_object")
    mechanical_slices = {
        str(name): normalized_sections(values, subject)
        for name, values in mechanical_slices_raw.items()
    }
    direct_raw = spec.get("direct_recheck_sections") or {}
    if not isinstance(direct_raw, dict):
        raise ReviewGraphError("direct_recheck_sections_must_be_object")

    section_records = section_index(subject, inline_max_bytes)
    artifact_records, artifact_summary = build_artifact_index(
        subject, allowed_roots=allowed_roots
    )
    artifact_lines = b"".join(canonical(record) + b"\n" for record in artifact_records)
    artifact_index_path = output_dir / "artifact-index.jsonl"
    artifact_index_sha256 = digest(artifact_lines)
    verifier_receipt: dict[str, Any] | None = None
    if verifier_receipt_path is not None:
        parsed_receipt, receipt_raw = parse_json(
            verifier_receipt_path, require_canonical=True
        )
        try:
            receipt_content = parsed_receipt["content"]
            receipt_subject = receipt_content["subject"]
            receipt_launcher = receipt_content["launcher"]
            stdout_binding = receipt_content["raw_stdout"]
            stderr_binding = receipt_content["raw_stderr"]
        except (KeyError, TypeError) as exc:
            raise ReviewGraphError("malformed_compact_verifier_receipt") from exc
        if (
            not isinstance(parsed_receipt, dict)
            or set(parsed_receipt) != {"schema_version", "content_sha256", "content"}
            or parsed_receipt.get("schema_version") != VERIFIER_RECEIPT_SCHEMA
            or not isinstance(receipt_content, dict)
            or parsed_receipt.get("content_sha256") != digest(canonical(receipt_content))
        ):
            raise ReviewGraphError("compact_verifier_receipt_wrapper_invalid")
        if not all(
            isinstance(item, dict)
            for item in (receipt_subject, receipt_launcher, stdout_binding, stderr_binding)
        ):
            raise ReviewGraphError("malformed_compact_verifier_receipt")
        if receipt_subject != exact_file_binding(subject_path):
            raise ReviewGraphError("compact_verifier_receipt_subject_mismatch")
        launcher_path = Path(str(receipt_launcher.get("path") or ""))
        if not launcher_path.is_absolute() or receipt_launcher != exact_file_binding(
            launcher_path
        ):
            raise ReviewGraphError("compact_verifier_receipt_launcher_mismatch")
        stdout_path = Path(str(stdout_binding.get("path") or ""))
        stderr_path = Path(str(stderr_binding.get("path") or ""))
        if not stdout_path.is_absolute() or not stderr_path.is_absolute():
            raise ReviewGraphError("compact_verifier_receipt_raw_path_invalid")
        stdout_raw = stable_read(stdout_path)
        stderr_raw = stable_read(stderr_path)
        if stdout_binding != {
            "path": str(stdout_path),
            "bytes": len(stdout_raw),
            "sha256": digest(stdout_raw),
        } or stderr_binding != {
            "path": str(stderr_path),
            "bytes": len(stderr_raw),
            "sha256": digest(stderr_raw),
        }:
            raise ReviewGraphError("compact_verifier_receipt_raw_binding_mismatch")
        try:
            stdout_result = json.loads(stdout_raw.decode("utf-8", "strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReviewGraphError("compact_verifier_receipt_stdout_invalid") from exc
        receipt_result = receipt_content.get("result")
        selected_stdout_result = (
            {key: stdout_result.get(key) for key in expected_verifier_result(required_digest)}
            if isinstance(stdout_result, dict)
            else None
        )
        if (
            receipt_content.get("returncode") != 0
            or receipt_result != expected_verifier_result(required_digest)
            or selected_stdout_result != receipt_result
            or stdout_raw
            not in (canonical(stdout_result), canonical(stdout_result) + b"\n")
            or stderr_raw != b""
            or receipt_content.get("logical_argv")
            != [str(launcher_path), str(subject_path), required_digest]
            or receipt_content.get("authority") != "NONE"
            or receipt_content.get("live_effect") != "NONE_READ_ONLY"
            or receipt_content.get("automatic_retry") is not False
            or receipt_content.get("claim_ceiling")
            != "COMPACT_TRANSPORT_RECEIPT_NOT_A_MODEL_VERDICT_OR_CONTINUOUS_CURRENTNESS"
        ):
            raise ReviewGraphError("compact_verifier_receipt_is_not_pass")
        execution_transport = receipt_content.get("execution_transport")
        actual_argv = receipt_content.get("argv")
        shell_path = system_shell_path()
        current_launcher_identity = descriptor_identity(os.lstat(launcher_path))
        private_capture = (
            execution_transport.get("private_capture")
            if isinstance(execution_transport, dict)
            else None
        )
        private_capture_after = (
            execution_transport.get("private_capture_post_execution")
            if isinstance(execution_transport, dict)
            else None
        )
        if (
            not isinstance(execution_transport, dict)
            or execution_transport.get("kind")
            != "CONTENT_BOUND_SOURCE_TO_UNLINKED_PRIVATE_CAPTURE_TO_ROOT_OWNED_SHELL"
            or execution_transport.get("producer")
            != exact_file_binding(Path(__file__).resolve())
            or execution_transport.get("shell") != exact_file_binding(shell_path)
            or execution_transport.get("launcher") != receipt_launcher
            or execution_transport.get("source_descriptor_identity")
            != current_launcher_identity
            or execution_transport.get("source_descriptor_content_sha256")
            != receipt_launcher.get("sha256")
            or execution_transport.get("parent_environment") != "EMPTY"
            or execution_transport.get("launcher_descriptor_closed_after_execution")
            is not True
            or not isinstance(private_capture, dict)
            or private_capture.get("creation")
            != (
                "PRIVATE_O_EXCL_WRITE_FSYNC_0400_REOPEN_READ_FD_"
                "EXACT_WRITER_READER_IDENTITY_THEN_UNLINK"
            )
            or private_capture.get("content_sha256") != receipt_launcher.get("sha256")
            or private_capture.get("bytes") != receipt_launcher.get("bytes")
            or private_capture.get("writer_reader_identity_equal") is not True
            or private_capture.get("o_excl_writer_identity_before_close")
            != private_capture.get("execution_reader_identity_before_unlink")
            or private_capture.get("before_unlink_identity")
            != private_capture.get("execution_reader_identity_before_unlink")
            or private_capture.get("writable_descriptor_closed_before_execution")
            is not True
            or private_capture.get("pathname_absent_before_execution") is not True
            or not isinstance(private_capture.get("before_unlink_identity"), dict)
            or private_capture["before_unlink_identity"].get("mode_type")
            != stat.S_IFREG
            or private_capture["before_unlink_identity"].get("mode_permissions")
            != 0o400
            or private_capture["before_unlink_identity"].get("nlink") != 1
            or private_capture["before_unlink_identity"].get("bytes")
            != receipt_launcher.get("bytes")
            or not isinstance(private_capture.get("unlinked_identity"), dict)
            or private_capture["unlinked_identity"].get("mode_type") != stat.S_IFREG
            or private_capture["unlinked_identity"].get("mode_permissions") != 0o400
            or private_capture["unlinked_identity"].get("nlink") != 0
            or private_capture["unlinked_identity"].get("bytes")
            != receipt_launcher.get("bytes")
            or not same_capture_inode_transition(
                private_capture["before_unlink_identity"],
                private_capture["unlinked_identity"],
            )
            or not isinstance(private_capture_after, dict)
            or private_capture_after.get("content_sha256")
            != receipt_launcher.get("sha256")
            or private_capture_after.get("identity")
            != private_capture.get("unlinked_identity")
            or not isinstance(actual_argv, list)
            or len(actual_argv) != 4
            or actual_argv[0] != str(shell_path)
            or not isinstance(actual_argv[1], str)
            or not actual_argv[1].startswith("/dev/fd/")
            or not actual_argv[1].removeprefix("/dev/fd/").isdigit()
            or actual_argv[2:] != [str(subject_path), required_digest]
        ):
            raise ReviewGraphError("compact_verifier_receipt_execution_transport_invalid")
        verifier_receipt = {
            "path": str(verifier_receipt_path),
            "bytes": len(receipt_raw),
            "sha256": digest(receipt_raw),
            "schema_version": parsed_receipt.get("schema_version"),
            "result": receipt_result,
        }
    fact_content = {
        "subject": {
            "path": str(subject_path),
            "schema_version": subject.get("schema_version"),
            "canonical_bytes": len(subject_raw),
            "sha256": observed_digest,
            "required_sha256": required_digest,
            "canonical_json": True,
        },
        "observation_epoch": {
            "kind": "EXACT_SUBJECT_CONTENT",
            "binding": observed_digest,
            "continuous_currentness": "NOT_CLAIMED",
        },
        "producer": {
            "path": str(Path(__file__).resolve()),
            "sha256": digest(stable_read(Path(__file__).resolve())),
            "python": sys.version.split()[0],
        },
        "section_index": section_records,
        "artifact_index": {
            "path": str(artifact_index_path),
            "sha256": artifact_index_sha256,
            "bytes": len(artifact_lines),
            "summary": artifact_summary,
        },
        "compact_verifier_receipt": verifier_receipt,
        "review_schema": review_schema,
        "claim_ceiling": {
            "deterministic_fact_reuse": (
                "ALLOWED_WITH_PRODUCER_AND_RAW_LOCATOR_BINDING"
            ),
            "reviewer_judgment_cache": "FORBIDDEN",
            "reviewer_independence": (
                "LOAD_BEARING_RECHECKS_AND_CONTRADICTION_ESCALATION_REQUIRED"
            ),
            "authority": "NONE",
            "canonical_state_effect": "NONE",
        },
    }
    fact_packet = wrapped(FACT_PACKET_SCHEMA, fact_content)

    output_status: dict[str, str] = {}
    output_status[str(artifact_index_path)] = publish_exact(
        artifact_index_path, artifact_lines
    )
    fact_path = output_dir / "fact-packet.json"
    output_status[str(fact_path)] = publish_exact(fact_path, packet_bytes(fact_packet))
    packet_paths: dict[str, str] = {}
    graph_nodes: list[dict[str, Any]] = [
        {
            "node_id": "deterministic-fact-packet",
            "kind": "DETERMINISTIC_DERIVATION",
            "depends_on": [],
            "concurrency_group": "preflight",
            "state": "MATERIALIZED",
            "output_sha256": fact_packet["content_sha256"],
        }
    ]

    for slice_name, sections in sorted(mechanical_slices.items()):
        role_id = "mechanical-" + slice_name
        direct_sections = normalized_sections(
            direct_raw.get(role_id, sections), subject
        )
        payload = role_packet(
            role=role_id,
            sections=sections,
            common_sections=common_sections,
            section_records=section_records,
            subject_path=subject_path,
            subject_sha256=observed_digest,
            fact_packet=fact_packet,
            artifact_index_path=artifact_index_path,
            artifact_index_sha256=artifact_index_sha256,
            samples=select_samples(
                artifact_records,
                role=role_id,
                sections=set(sections + common_sections),
                subject_sha256=observed_digest,
                count=spec["sample_count"],
            ),
            required_rechecks=direct_sections,
        )
        path = output_dir / f"{role_id}-packet.json"
        output_status[str(path)] = publish_exact(path, packet_bytes(payload))
        packet_paths[role_id] = str(path)
        graph_nodes.append(
            {
                "node_id": role_id,
                "kind": "MODEL_REVIEW_SLICE",
                "lens": "mechanical",
                "depends_on": ["deterministic-fact-packet"],
                "concurrency_group": "triad-and-mechanical-slices",
                "packet_path": str(path),
                "packet_sha256": payload["content_sha256"],
                "effort_policy": "SCOPED_HIGH_ESCALATE_MAX_ONLY_ON_AMBIGUITY",
                "verdict_cache": "FORBIDDEN",
            }
        )

    for role in ("semantic", "atomicity"):
        sections = role_sections.get(role, [])
        direct_sections = normalized_sections(direct_raw.get(role, sections), subject)
        payload = role_packet(
            role=role,
            sections=sections,
            common_sections=common_sections,
            section_records=section_records,
            subject_path=subject_path,
            subject_sha256=observed_digest,
            fact_packet=fact_packet,
            artifact_index_path=artifact_index_path,
            artifact_index_sha256=artifact_index_sha256,
            samples=select_samples(
                artifact_records,
                role=role,
                sections=set(sections + common_sections),
                subject_sha256=observed_digest,
                count=spec["sample_count"],
            ),
            required_rechecks=direct_sections,
        )
        path = output_dir / f"{role}-packet.json"
        output_status[str(path)] = publish_exact(path, packet_bytes(payload))
        packet_paths[role] = str(path)
        graph_nodes.append(
            {
                "node_id": role,
                "kind": "MODEL_REVIEW_LENS",
                "lens": role,
                "depends_on": ["deterministic-fact-packet"],
                "concurrency_group": "triad-and-mechanical-slices",
                "packet_path": str(path),
                "packet_sha256": payload["content_sha256"],
                "effort_policy": (
                    "MAX_FOR_CRITICAL_ATOMICITY"
                    if role == "atomicity"
                    else "SCOPED_HIGH_ESCALATE_MAX_ONLY_ON_AMBIGUITY"
                ),
                "verdict_cache": "FORBIDDEN",
            }
        )

    mechanical_ids = ["mechanical-" + name for name in sorted(mechanical_slices)]
    synthesis_sections = role_sections.get("mechanical", [])
    synthesis_payload = role_packet(
        role="mechanical-champion-synthesis",
        sections=synthesis_sections,
        common_sections=common_sections,
        section_records=section_records,
        subject_path=subject_path,
        subject_sha256=observed_digest,
        fact_packet=fact_packet,
        artifact_index_path=artifact_index_path,
        artifact_index_sha256=artifact_index_sha256,
        samples=select_samples(
            artifact_records,
            role="mechanical-champion-synthesis",
            sections=set(synthesis_sections + common_sections),
            subject_sha256=observed_digest,
            count=spec["sample_count"],
        ),
        required_rechecks=normalized_sections(
            direct_raw.get("mechanical-champion-synthesis", synthesis_sections),
            subject,
        ),
        upstream_results=mechanical_ids,
    )
    synthesis_path = output_dir / "mechanical-champion-synthesis-packet.json"
    output_status[str(synthesis_path)] = publish_exact(
        synthesis_path, packet_bytes(synthesis_payload)
    )
    packet_paths["mechanical-champion-synthesis"] = str(synthesis_path)
    graph_nodes.append(
        {
            "node_id": "mechanical-champion-synthesis",
            "kind": "CROSS_INVARIANT_SYNTHESIS",
            "lens": "mechanical",
            "depends_on": mechanical_ids,
            "concurrency_group": "mechanical-synthesis",
            "packet_path": str(synthesis_path),
            "packet_sha256": synthesis_payload["content_sha256"],
            "required_analysis": "SLICE_CONFLICTS_AND_CROSS_INVARIANT_INTERACTIONS",
            "effort_policy": "MAX",
            "verdict_cache": "FORBIDDEN",
        }
    )
    graph_nodes.extend(
        [
            {
                "node_id": "triad-join",
                "kind": "DEPENDENCY_JOIN",
                "depends_on": [
                    "mechanical-champion-synthesis",
                    "semantic",
                    "atomicity",
                ],
                "concurrency_group": "join",
            },
            {
                "node_id": "fable",
                "kind": "MODEL_REVIEW_LENS",
                "lens": "fable",
                "depends_on": ["triad-join"],
                "concurrency_group": "fable-after-triad",
                "runtime_inputs": [
                    "mechanical-champion-synthesis",
                    "semantic",
                    "atomicity",
                ],
                "verdict_cache": "FORBIDDEN",
            },
            {
                "node_id": "fresh-currentness",
                "kind": "DETERMINISTIC_RECHECK",
                "depends_on": ["fable"],
                "concurrency_group": "post-review-currentness",
            },
            {
                "node_id": "pm-projection",
                "kind": "ADVISORY_SYNTHESIS",
                "depends_on": ["fresh-currentness"],
                "concurrency_group": "pm",
            },
            {
                "node_id": "owner-boundary",
                "kind": "STOP_PENDING_OWNER_DECISION",
                "depends_on": ["pm-projection"],
                "concurrency_group": "owner",
            },
        ]
    )
    graph_content = {
        "subject_sha256": observed_digest,
        "fact_packet_sha256": fact_packet["content_sha256"],
        "review_schema": review_schema,
        "nodes": graph_nodes,
        "topological_levels": [
            ["deterministic-fact-packet"],
            sorted(mechanical_ids + ["semantic", "atomicity"]),
            ["mechanical-champion-synthesis"],
            ["triad-join"],
            ["fable"],
            ["fresh-currentness"],
            ["pm-projection"],
            ["owner-boundary"],
        ],
        "scheduler_contract": {
            "planner": "STACKER_DERIVED_REVIEW_GRAPH",
            "executor": "ARVIS_EXECUTION_SUPERVISION",
            "dependency_free_nodes_may_run_in_parallel": True,
            "dependency_ready_dispatch": "IMMEDIATE_AFTER_OWN_DEPENDENCIES",
            "global_level_barrier": "FORBIDDEN",
            "topological_levels_are": "DIAGNOSTIC_ONLY_NOT_EXECUTION_BARRIERS",
            "provider_and_resource_caps_still_apply": True,
            "authority": "NONE",
            "automatic_live_effect": "FORBIDDEN",
        },
        "independence_contract": {
            "shared_deterministic_facts": "ALLOWED",
            "load_bearing_direct_rechecks": "REQUIRED",
            "contradiction_raw_evidence_open": "REQUIRED",
            "model_verdict_reuse": "FORBIDDEN",
            "fable_before_triad": "FORBIDDEN",
            "exact_verifier_policy": (
                "COMPACT_RECEIPT_REUSE;_MODEL_REEXECUTION_FORBIDDEN"
                if verifier_receipt is not None
                else "NOT_BOUND_BY_GRAPH"
            ),
        },
        "packet_paths": packet_paths,
    }
    graph = wrapped(REVIEW_GRAPH_SCHEMA, graph_content)
    graph_path = output_dir / "review-graph.json"
    output_status[str(graph_path)] = publish_exact(graph_path, packet_bytes(graph))

    return {
        "status": "MATERIALIZED",
        "subject_sha256": observed_digest,
        "fact_packet_path": str(fact_path),
        "fact_packet_sha256": fact_packet["content_sha256"],
        "artifact_index_path": str(artifact_index_path),
        "artifact_index_sha256": artifact_index_sha256,
        "review_graph_path": str(graph_path),
        "review_graph_sha256": graph["content_sha256"],
        "artifact_summary": artifact_summary,
        "publication": output_status,
        "authority": "NONE",
        "live_effect": "NONE",
    }


def parse_wrapped_packet(path: Path, expected_schema: str) -> dict[str, Any]:
    value, raw = parse_json(path)
    if not isinstance(value, dict) or canonical(value) + b"\n" != raw:
        raise ReviewGraphError(f"packet_not_canonical_newline_json:{path}")
    if value.get("schema_version") != expected_schema:
        raise ReviewGraphError(f"packet_schema_mismatch:{path}")
    content = value.get("content")
    if not isinstance(content, dict):
        raise ReviewGraphError(f"packet_content_not_object:{path}")
    if value.get("content_sha256") != digest(canonical(content)):
        raise ReviewGraphError(f"packet_content_digest_mismatch:{path}")
    return value


def verify_review_bundle(
    *,
    bundle_dir: Path,
    subject_path: Path,
    required_digest: str,
) -> dict[str, Any]:
    subject, subject_raw = parse_json(subject_path, require_canonical=True)
    if not isinstance(subject, dict) or digest(subject_raw) != required_digest:
        raise ReviewGraphError("review_bundle_subject_binding_mismatch")
    fact_path = bundle_dir / "fact-packet.json"
    graph_path = bundle_dir / "review-graph.json"
    artifact_path = bundle_dir / "artifact-index.jsonl"
    fact = parse_wrapped_packet(fact_path, FACT_PACKET_SCHEMA)
    graph = parse_wrapped_packet(graph_path, REVIEW_GRAPH_SCHEMA)
    fact_content = fact["content"]
    graph_content = graph["content"]
    if fact_content.get("subject", {}).get("sha256") != required_digest:
        raise ReviewGraphError("fact_packet_subject_digest_mismatch")
    review_schema = fact_content.get("review_schema")
    if review_schema is not None:
        if not isinstance(review_schema, dict):
            raise ReviewGraphError("fact_packet_review_schema_binding_malformed")
        schema_path = Path(str(review_schema.get("path") or ""))
        if (
            not schema_path.is_absolute()
            or review_schema
            != exact_review_schema_binding(schema_path, required_digest)
        ):
            raise ReviewGraphError("fact_packet_review_schema_binding_mismatch")
    artifact_binding = fact_content.get("artifact_index")
    if not isinstance(artifact_binding, dict):
        raise ReviewGraphError("fact_packet_artifact_binding_missing")
    if artifact_binding.get("path") != str(artifact_path):
        raise ReviewGraphError("artifact_index_path_mismatch")
    artifact_raw = stable_read(artifact_path)
    if (
        artifact_binding.get("sha256") != digest(artifact_raw)
        or artifact_binding.get("bytes") != len(artifact_raw)
    ):
        raise ReviewGraphError("artifact_index_content_mismatch")
    if (
        graph_content.get("subject_sha256") != required_digest
        or graph_content.get("fact_packet_sha256") != fact["content_sha256"]
        or graph_content.get("review_schema") != review_schema
    ):
        raise ReviewGraphError("review_graph_subject_or_fact_binding_mismatch")
    scheduler = graph_content.get("scheduler_contract")
    if not isinstance(scheduler, dict) or (
        scheduler.get("authority") != "NONE"
        or scheduler.get("automatic_live_effect") != "FORBIDDEN"
        or scheduler.get("dependency_ready_dispatch")
        != "IMMEDIATE_AFTER_OWN_DEPENDENCIES"
        or scheduler.get("global_level_barrier") != "FORBIDDEN"
        or scheduler.get("topological_levels_are")
        != "DIAGNOSTIC_ONLY_NOT_EXECUTION_BARRIERS"
    ):
        raise ReviewGraphError("review_graph_authority_ceiling_mismatch")

    nodes = graph_content.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ReviewGraphError("review_graph_nodes_missing")
    node_map: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("node_id"), str):
            raise ReviewGraphError("review_graph_node_malformed")
        node_id = node["node_id"]
        if node_id in node_map:
            raise ReviewGraphError("review_graph_duplicate_node:" + node_id)
        node_map[node_id] = node
    for node_id, node in node_map.items():
        dependencies = node.get("depends_on")
        if not isinstance(dependencies, list) or not all(
            isinstance(item, str) for item in dependencies
        ):
            raise ReviewGraphError("review_graph_dependencies_malformed:" + node_id)
        missing = set(dependencies) - set(node_map)
        if missing:
            raise ReviewGraphError(
                "review_graph_missing_dependency:" + node_id + ":" + ",".join(sorted(missing))
            )

    levels = graph_content.get("topological_levels")
    if not isinstance(levels, list) or not all(
        isinstance(level, list) for level in levels
    ):
        raise ReviewGraphError("review_graph_topological_levels_malformed")
    flattened = [item for level in levels for item in level]
    if len(flattened) != len(set(flattened)) or set(flattened) != set(node_map):
        raise ReviewGraphError("review_graph_topological_level_coverage_mismatch")
    level_number = {
        node_id: index for index, level in enumerate(levels) for node_id in level
    }
    for node_id, node in node_map.items():
        if any(
            level_number[dependency] >= level_number[node_id]
            for dependency in node["depends_on"]
        ):
            raise ReviewGraphError("review_graph_dependency_order_mismatch:" + node_id)

    packet_paths = graph_content.get("packet_paths")
    if not isinstance(packet_paths, dict):
        raise ReviewGraphError("review_graph_packet_paths_missing")
    packet_digests: dict[str, str] = {}
    for role, raw_path in sorted(packet_paths.items()):
        if not isinstance(raw_path, str):
            raise ReviewGraphError("role_packet_path_malformed:" + str(role))
        path = Path(raw_path)
        if path.parent != bundle_dir:
            raise ReviewGraphError("role_packet_outside_bundle:" + str(role))
        packet = parse_wrapped_packet(path, ROLE_PACKET_SCHEMA)
        content = packet["content"]
        if (
            content.get("role") != role
            or content.get("subject", {}).get("sha256") != required_digest
            or content.get("fact_packet", {}).get("sha256") != fact["content_sha256"]
            or content.get("artifact_index", {}).get("sha256") != digest(artifact_raw)
        ):
            raise ReviewGraphError("role_packet_binding_mismatch:" + str(role))
        packet_digests[str(role)] = packet["content_sha256"]
    for node_id, node in node_map.items():
        if "packet_path" not in node:
            continue
        if (
            packet_paths.get(node_id) != node.get("packet_path")
            or packet_digests.get(node_id) != node.get("packet_sha256")
        ):
            raise ReviewGraphError("review_graph_node_packet_mismatch:" + node_id)
    return {
        "status": "MATERIALIZED_VERIFIED",
        "subject_sha256": required_digest,
        "fact_packet_sha256": fact["content_sha256"],
        "review_graph_sha256": graph["content_sha256"],
        "artifact_index_sha256": digest(artifact_raw),
        "node_count": len(node_map),
        "role_packet_count": len(packet_paths),
        "authority": "NONE",
        "live_effect": "NONE",
    }


def file_size(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def resolve_prompt_path(
    prompt_dir: Path | None, *, prefix: str, lens: str
) -> Path | None:
    if prompt_dir is None:
        return None
    normalized_lens = lens.lower()
    candidates = [
        prompt_dir / f"{prefix}.md",
        prompt_dir / f"{prefix}-prompt.md",
        prompt_dir / f"{prefix}-review-prompt.md",
    ]
    if prefix == "mechanical-champion":
        candidates.append(prompt_dir / "mechanical-review-prompt.md")
    candidates.extend(
        [
            prompt_dir / f"{normalized_lens}.md",
            prompt_dir / f"{normalized_lens}-review-prompt.md",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def event_reported_usage(path: Path) -> dict[str, Any]:
    """Return the last provider-reported usage record without normalizing semantics."""
    result: dict[str, Any] = {
        "source": "NOT_REPORTED",
        "input_tokens": None,
        "cached_input_tokens": None,
        "cache_creation_input_tokens": None,
        "cache_read_input_tokens": None,
        "output_tokens": None,
        "reasoning_output_tokens": None,
        "total_cost_usd": None,
    }
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return result
    with handle:
        for line in handle:
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(event, dict):
                continue
            usage = event.get("usage")
            if event.get("type") == "turn.completed" and isinstance(usage, dict):
                result.update(
                    {
                        "source": "CODEX_TURN_COMPLETED",
                        "input_tokens": usage.get("input_tokens"),
                        "cached_input_tokens": usage.get("cached_input_tokens"),
                        "cache_creation_input_tokens": None,
                        "cache_read_input_tokens": None,
                        "output_tokens": usage.get("output_tokens"),
                        "reasoning_output_tokens": usage.get(
                            "reasoning_output_tokens"
                        ),
                        "total_cost_usd": None,
                    }
                )
            elif event.get("type") == "result" and isinstance(usage, dict):
                result.update(
                    {
                        "source": "CLAUDE_RESULT",
                        "input_tokens": usage.get("input_tokens"),
                        "cached_input_tokens": None,
                        "cache_creation_input_tokens": usage.get(
                            "cache_creation_input_tokens"
                        ),
                        "cache_read_input_tokens": usage.get(
                            "cache_read_input_tokens"
                        ),
                        "output_tokens": usage.get("output_tokens"),
                        "reasoning_output_tokens": None,
                        "total_cost_usd": event.get("total_cost_usd"),
                    }
                )
    return result


def sum_reported_usage(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    fields = (
        "input_tokens",
        "cached_input_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_cost_usd",
    )
    totals: dict[str, Any] = {}
    for field in fields:
        values = [
            lane["reported_usage"].get(field)
            for lane in lanes
            if isinstance(lane.get("reported_usage"), dict)
            and isinstance(lane["reported_usage"].get(field), (int, float))
        ]
        totals[field] = round(sum(values), 6) if values else None
    totals["semantics"] = (
        "PROVIDER_REPORTED_RAW_FIELDS;_CACHE_FIELDS_DIFFER_BY_PROVIDER"
    )
    return totals


def review_graph_critical_path(
    graph_path: Path | None,
    lanes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Compute the observed model critical path from declared DAG dependencies.

    Missing deterministic/join nodes have zero duration.  Model nodes without an
    observed lane are excluded from the observed phase, so a pre-Fable receipt
    does not pretend that Fable or later nodes ran.
    """
    if graph_path is None or not graph_path.is_file():
        return None
    graph, _ = parse_json(graph_path)
    try:
        nodes = graph["content"]["nodes"]
    except (KeyError, TypeError):
        return {"status": "MALFORMED_REVIEW_GRAPH"}
    if not isinstance(nodes, list):
        return {"status": "MALFORMED_REVIEW_GRAPH"}

    lane_durations = {
        str(item["lane"]): float(item["elapsed_seconds"])
        for item in lanes
        if isinstance(item.get("lane"), str)
        and isinstance(item.get("elapsed_seconds"), (int, float))
    }
    aliases = {"mechanical-champion-synthesis": "mechanical-champion"}
    node_map: dict[str, dict[str, Any]] = {}
    observed_nodes: set[str] = set()
    durations: dict[str, float] = {}
    for item in nodes:
        if not isinstance(item, dict) or not isinstance(item.get("node_id"), str):
            return {"status": "MALFORMED_REVIEW_GRAPH"}
        node_id = str(item["node_id"])
        if node_id in node_map:
            return {"status": "MALFORMED_REVIEW_GRAPH_DUPLICATE_NODE"}
        node_map[node_id] = item
        lane_id = aliases.get(node_id, node_id)
        if lane_id in lane_durations:
            observed_nodes.add(node_id)
            durations[node_id] = lane_durations[lane_id]
        else:
            durations[node_id] = 0.0

    visiting: set[str] = set()
    finished: dict[str, float] = {}

    def finish(node_id: str) -> float:
        if node_id in finished:
            return finished[node_id]
        if node_id in visiting:
            raise ReviewGraphError("review_graph_dependency_cycle")
        visiting.add(node_id)
        node = node_map[node_id]
        dependencies = node.get("depends_on") or []
        if not isinstance(dependencies, list) or any(
            not isinstance(item, str) or item not in node_map for item in dependencies
        ):
            raise ReviewGraphError("review_graph_dependency_invalid:" + node_id)
        predecessor = max((finish(item) for item in dependencies), default=0.0)
        value = predecessor + durations[node_id]
        visiting.remove(node_id)
        finished[node_id] = value
        return value

    for node_id in node_map:
        finish(node_id)
    observed_seconds = max((finished[item] for item in observed_nodes), default=0.0)
    critical_end_nodes = sorted(
        item for item in observed_nodes if finished[item] == observed_seconds
    )
    return {
        "status": "COMPUTED",
        "method": "DECLARED_REVIEW_DAG_DEPENDENCIES_PLUS_OBSERVED_LANE_DURATIONS",
        "review_graph": exact_file_binding(graph_path),
        "observed_model_node_count": len(observed_nodes),
        "observed_model_critical_path_seconds": round(observed_seconds, 3),
        "critical_end_nodes": critical_end_nodes,
    }


def build_metrics(
    *,
    review_dir: Path,
    output_path: Path,
    prompt_dir: Path | None = None,
    fact_packet_path: Path | None = None,
    review_graph_path: Path | None = None,
) -> dict[str, Any]:
    lanes: list[dict[str, Any]] = []
    unique_findings: set[str] = set()
    subject_digests: set[str] = set()
    starts: list[float] = []
    ends: list[float] = []
    for watchdog_path in sorted(review_dir.glob("*.watchdog.json")):
        prefix = watchdog_path.name.removesuffix(".watchdog.json")
        watchdog, _ = parse_json(watchdog_path)
        if not isinstance(watchdog, dict):
            continue
        final_path = review_dir / f"{prefix}.final.json"
        event_path = review_dir / f"{prefix}.events.jsonl"
        stderr_path = review_dir / f"{prefix}.stderr"
        final: dict[str, Any] = {}
        if final_path.is_file():
            parsed, _ = parse_json(final_path)
            if isinstance(parsed, dict):
                final = parsed
        findings = final.get("material_findings")
        if not isinstance(findings, list):
            findings = []
        for finding in findings:
            if isinstance(finding, dict):
                fingerprint = finding.get("fingerprint")
                if isinstance(fingerprint, str) and fingerprint:
                    unique_findings.add(fingerprint)
        subject_sha = final.get("subject_sha256")
        if isinstance(subject_sha, str) and subject_sha:
            subject_digests.add(subject_sha)
        elapsed = watchdog.get("elapsed_seconds")
        elapsed_value = float(elapsed) if isinstance(elapsed, (int, float)) else 0.0
        try:
            end = watchdog_path.stat().st_mtime
        except OSError:
            end = 0.0
        if end and elapsed_value:
            starts.append(end - elapsed_value)
            ends.append(end)
        lens = str(final.get("lens") or prefix.split("-", 1)[0])
        prompt_path = resolve_prompt_path(prompt_dir, prefix=prefix, lens=lens)
        reported_usage = event_reported_usage(event_path)
        policy = watchdog.get("policy") if isinstance(watchdog.get("policy"), dict) else {}
        resolved_stop_reason = watchdog.get("stop_reason")
        if watchdog.get("status") != "PASS" and not isinstance(
            resolved_stop_reason, str
        ):
            _, resolved_stop_reason, _ = terminal_lane_without_final(
                review_dir=review_dir,
                stem=prefix,
                watchdog=watchdog,
            )
        lanes.append(
            {
                "lane": prefix,
                "lens": lens,
                "status": watchdog.get("status"),
                "decision": final.get("decision"),
                "model": policy.get("model") or watchdog.get("first_actual_model"),
                "effort": policy.get("effort"),
                "elapsed_seconds": elapsed_value,
                "prompt_bytes": file_size(prompt_path),
                "event_bytes": file_size(event_path),
                "final_bytes": file_size(final_path),
                "stderr_bytes": file_size(stderr_path),
                "reported_usage": reported_usage,
                "material_finding_count": len(findings),
                "automatic_retry": bool(watchdog.get("automatic_retry")),
                "fallback_event_count": len(watchdog.get("fallback_events") or []),
                "stop_reason": resolved_stop_reason,
                "observed_total_sessions": watchdog.get("observed_total_sessions"),
                "observed_max_depth": watchdog.get("observed_max_depth"),
            }
        )
    serial_seconds = round(sum(item["elapsed_seconds"] for item in lanes), 3)
    wall_seconds = round(max(ends) - min(starts), 3) if starts and ends else None
    parallel_gain = (
        round(1.0 - (wall_seconds / serial_seconds), 4)
        if wall_seconds is not None and serial_seconds > 0
        else None
    )
    dag_timing = review_graph_critical_path(review_graph_path, lanes)
    dag_seconds = (
        dag_timing.get("observed_model_critical_path_seconds")
        if isinstance(dag_timing, dict) and dag_timing.get("status") == "COMPUTED"
        else None
    )
    dag_parallel_gain = (
        round(1.0 - (float(dag_seconds) / serial_seconds), 4)
        if isinstance(dag_seconds, (int, float)) and serial_seconds > 0
        else None
    )
    fact_summary: dict[str, Any] | None = None
    if fact_packet_path and fact_packet_path.is_file():
        packet, _ = parse_json(fact_packet_path)
        try:
            fact_summary = packet["content"]["artifact_index"]["summary"]
        except (KeyError, TypeError):
            fact_summary = {"status": "MALFORMED_FACT_PACKET"}
    content = {
        "review_dir": str(review_dir),
        "subject_digests": sorted(subject_digests),
        "lanes": lanes,
        "aggregate": {
            "lane_count": len(lanes),
            "serial_elapsed_seconds": serial_seconds,
            "estimated_parallel_wall_seconds": wall_seconds,
            "parallel_gain_fraction": parallel_gain,
            "wall_estimation_method": "WATCHDOG_MTIME_MINUS_RECORDED_ELAPSED",
            "declared_dag_timing": dag_timing,
            "declared_dag_parallel_gain_fraction": dag_parallel_gain,
            "reported_material_finding_count_total": sum(
                item["material_finding_count"] for item in lanes
            ),
            "distinct_reported_fingerprint_count": len(unique_findings),
            "reported_material_fingerprints": sorted(unique_findings),
            "provider_failure_lane_count": sum(
                1
                for item in lanes
                if str(item.get("stop_reason") or "").startswith("PROVIDER_")
            ),
            "provider_failure_incident_count": len(
                {
                    str(item["stop_reason"])
                    for item in lanes
                    if str(item.get("stop_reason") or "").startswith("PROVIDER_")
                }
            ),
            "provider_failure_incident_keys": sorted(
                {
                    str(item["stop_reason"])
                    for item in lanes
                    if str(item.get("stop_reason") or "").startswith("PROVIDER_")
                }
            ),
            "deduplicated_material_mechanism_count": "NOT_ESTABLISHED",
            "discovery_vs_closure_cost_class": "UNCLASSIFIED_REQUIRES_RUN_CONTEXT",
            "reported_usage_totals": sum_reported_usage(lanes),
        },
        "evidence_io": {
            "fact_packet_artifact_summary": fact_summary,
            "actual_reviewer_evidence_bytes_read": "NOT_INSTRUMENTED",
            "required_future_metric": (
                "SUM_LANE_BYTES_READ_DIVIDED_BY_UNIQUE_EVIDENCE_BYTES"
            ),
        },
        "claim_ceiling": {
            "cost_receipt_is_quality_proof": False,
            "zero_reported_material_findings_implies_fast_path": False,
            "later_escape_measurement_required": True,
        },
    }
    receipt = wrapped(METRICS_SCHEMA, content)
    publication = publish_exact(output_path, packet_bytes(receipt))
    return {
        "status": "MATERIALIZED",
        "output": str(output_path),
        "sha256": receipt["content_sha256"],
        "publication": publication,
        "aggregate": content["aggregate"],
    }


def build_triad_gate(
    *, review_dir: Path, required_digest: str, output_path: Path
) -> dict[str, Any]:
    lane_specs = (
        ("mechanical", "mechanical-champion"),
        ("semantic", "semantic"),
        ("atomicity", "atomicity"),
    )
    lanes: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []
    for expected_lens, stem in lane_specs:
        final_path = review_dir / f"{stem}.final.json"
        watchdog_path = review_dir / f"{stem}.watchdog.json"
        if (
            stem == "mechanical-champion"
            and not final_path.exists()
            and not os.path.lexists(final_path)
            and not watchdog_path.exists()
            and not os.path.lexists(watchdog_path)
        ):
            derived = unavailable_mechanical_champion_from_slices(review_dir)
            if derived is not None:
                lane = {
                    "lens": expected_lens,
                    "stem": stem,
                    "decision": "UNAVAILABLE",
                    "lane_outcome": "CHAMPION_NOT_STARTED",
                    "material_finding_count": 0,
                    "material_fingerprints": [],
                    "final": {"path": str(final_path), "kind": "ABSENT"},
                    "watchdog": {"path": str(watchdog_path), "kind": "ABSENT"},
                    "upstream_slices": derived["upstream_slices"],
                }
                lanes.append(lane)
                blocking.append(
                    {
                        "lens": expected_lens,
                        "decision": "UNAVAILABLE",
                        "material_fingerprints": [],
                        "reason_class": derived["reason_class"],
                        "stop_reasons": derived["stop_reasons"],
                    }
                )
                continue
        watchdog, watchdog_raw = parse_json(watchdog_path)
        if not isinstance(watchdog, dict):
            raise ReviewGraphError(f"triad_lane_not_object:{stem}")
        fallback_events = watchdog.get("fallback_events", [])
        if not final_path.exists():
            if os.path.lexists(final_path):
                raise ReviewGraphError(f"triad_lane_final_not_regular:{stem}")
            terminal_without_verdict, resolved_reason, events_binding = (
                terminal_lane_without_final(
                    review_dir=review_dir,
                    stem=stem,
                    watchdog=watchdog,
                )
            )
            if not terminal_without_verdict:
                raise ReviewGraphError(f"triad_lane_final_missing:{stem}")
            lane: dict[str, Any] = {
                "lens": expected_lens,
                "stem": stem,
                "decision": "UNAVAILABLE",
                "lane_outcome": "NO_FINAL_VERDICT",
                "material_finding_count": 0,
                "material_fingerprints": [],
                "final": {"path": str(final_path), "kind": "ABSENT"},
                "watchdog": {
                    "path": str(watchdog_path),
                    "bytes": len(watchdog_raw),
                    "sha256": digest(watchdog_raw),
                    "status": watchdog.get("status"),
                    "returncode": watchdog.get("returncode"),
                    "stop_reason": resolved_reason,
                },
            }
            if events_binding is not None:
                lane["events"] = events_binding
            lanes.append(lane)
            blocking.append(
                {
                    "lens": expected_lens,
                    "decision": "UNAVAILABLE",
                    "material_fingerprints": [],
                    "reason_class": "MODEL_LANE_NONPASS_NO_FINAL_VERDICT",
                    "stop_reason": resolved_reason,
                }
            )
            continue
        final, final_raw = parse_json(final_path)
        if not isinstance(final, dict):
            raise ReviewGraphError(f"triad_lane_not_object:{stem}")
        findings = final.get("material_findings")
        if not isinstance(findings, list):
            raise ReviewGraphError(f"triad_lane_findings_not_list:{stem}")
        if (
            str(final.get("lens") or "").lower() != expected_lens
            or final.get("subject_sha256") != required_digest
            or final.get("digest_verified") is not True
            or final.get("decision") not in {"ADOPT", "MODIFY", "HOLD"}
        ):
            raise ReviewGraphError(f"triad_lane_provenance_invalid:{stem}")
        watchdog_pass = (
            watchdog.get("status") == "PASS"
            and watchdog.get("returncode") == 0
            and watchdog.get("automatic_retry") is False
            and watchdog.get("stop_reason") is None
            and isinstance(fallback_events, list)
            and not fallback_events
        )
        if not watchdog_pass:
            raise ReviewGraphError(f"triad_lane_watchdog_invalid:{stem}")
        lane = {
            "lens": expected_lens,
            "stem": stem,
            "decision": final["decision"],
            "material_finding_count": len(findings),
            "material_fingerprints": sorted(
                str(item.get("fingerprint") or "")
                for item in findings
                if isinstance(item, dict)
            ),
            "final": {
                "path": str(final_path),
                "bytes": len(final_raw),
                "sha256": digest(final_raw),
            },
            "watchdog": {
                "path": str(watchdog_path),
                "bytes": len(watchdog_raw),
                "sha256": digest(watchdog_raw),
            },
        }
        lanes.append(lane)
        if final["decision"] != "ADOPT" or findings:
            blocking.append(
                {
                    "lens": expected_lens,
                    "decision": final["decision"],
                    "material_fingerprints": lane["material_fingerprints"],
                }
            )
    eligible = not blocking
    content = {
        "required_subject_sha256": required_digest,
        "review_dir": str(review_dir),
        "lanes": lanes,
        "result": "FABLE_ELIGIBLE" if eligible else "STOP_BEFORE_FABLE",
        "blocking": blocking,
        "fable_started": False,
        "authority": "NONE",
        "live_effect": "NONE_DERIVED_REPORT_ONLY",
        "claim_ceiling": (
            "DEPENDENCY_JOIN_ONLY_NOT_REVIEW_POLICY_COMPLETION_OR_OWNER_READINESS"
        ),
    }
    receipt = wrapped(TRIAD_GATE_SCHEMA, content)
    publication = publish_exact(output_path, packet_bytes(receipt))
    return {
        "status": content["result"],
        "output": str(output_path),
        "sha256": receipt["content_sha256"],
        "publication": publication,
        "blocking": blocking,
    }


def capture_compact_verifier_receipt(
    *,
    launcher_path: Path,
    launcher_contract_path: Path,
    subject_path: Path,
    required_digest: str,
    output_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    _, subject_raw = parse_json(subject_path, require_canonical=True)
    if digest(subject_raw) != required_digest:
        raise ReviewGraphError("verifier_capture_subject_digest_mismatch")
    launcher_contract, launcher_contract_binding = load_launcher_binding_contract(
        launcher_contract_path,
        launcher_path=launcher_path,
        label="exact-verifier",
    )
    subject_before = exact_file_binding(subject_path)
    launcher_before, launcher_fd, transport = capture_execution_transport(
        launcher_path=launcher_path,
        output_dir=output_dir,
        label="exact-verifier",
    )
    shell_path = system_shell_path()
    actual_argv = [
        str(shell_path),
        f"/dev/fd/{launcher_fd}",
        str(subject_path),
        required_digest,
    ]
    try:
        process = subprocess.run(
            actual_argv,
            cwd=subject_path.parent,
            env={},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            close_fds=True,
            pass_fds=(launcher_fd,),
            timeout=timeout_seconds,
        )
        capture_after_raw, capture_after_identity = stable_read_descriptor(launcher_fd)
    except subprocess.TimeoutExpired as exc:
        raise ReviewGraphError("compact_verifier_capture_timeout") from exc
    finally:
        os.close(launcher_fd)
    if (
        launcher_before != exact_file_binding(launcher_path)
        or launcher_contract_binding != exact_file_binding(launcher_contract_path)
        or transport["source_descriptor_identity"]
        != descriptor_identity(os.lstat(launcher_path))
        or digest(capture_after_raw) != launcher_before["sha256"]
        or capture_after_identity != transport["private_capture"]["unlinked_identity"]
        or subject_before != exact_file_binding(subject_path)
    ):
        raise ReviewGraphError("verifier_inputs_changed_during_capture")

    stdout_path = output_dir / "exact-verifier.stdout.json"
    stderr_path = output_dir / "exact-verifier.stderr"
    stdout_publication = publish_exact(stdout_path, process.stdout)
    stderr_publication = publish_exact(stderr_path, process.stderr)
    parsed: dict[str, Any] | None = None
    try:
        candidate = json.loads(process.stdout.decode("utf-8", "strict"))
        if isinstance(candidate, dict):
            parsed = candidate
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = None
    selected_keys = (
        "result",
        "decision_subject_sha256",
        "authority",
        "repository_effect",
        "database_effect",
        "schema_version",
    )
    compact_result = (
        {key: parsed.get(key) for key in selected_keys} if parsed is not None else None
    )
    content = {
        "subject": subject_before,
        "launcher_binding_contract": {
            "binding": launcher_contract_binding,
            "expected": launcher_contract,
            "observed_launcher": launcher_before,
            "verdict": "PASS",
        },
        "launcher": launcher_before,
        "logical_argv": [str(launcher_path), str(subject_path), required_digest],
        "argv": actual_argv,
        "execution_transport": {
            **transport,
            "producer": exact_file_binding(Path(__file__).resolve()),
            "shell": exact_file_binding(shell_path),
            "private_capture_post_execution": {
                "identity": capture_after_identity,
                "content_sha256": digest(capture_after_raw),
            },
            "launcher_descriptor_closed_after_execution": True,
        },
        "returncode": process.returncode,
        "result": compact_result,
        "raw_stdout": {
            "path": str(stdout_path),
            "bytes": len(process.stdout),
            "sha256": digest(process.stdout),
        },
        "raw_stderr": {
            "path": str(stderr_path),
            "bytes": len(process.stderr),
            "sha256": digest(process.stderr),
        },
        "authority": "NONE",
        "live_effect": "NONE_READ_ONLY",
        "automatic_retry": False,
        "claim_ceiling": (
            "COMPACT_TRANSPORT_RECEIPT_NOT_A_MODEL_VERDICT_OR_CONTINUOUS_CURRENTNESS"
        ),
    }
    receipt = wrapped(VERIFIER_RECEIPT_SCHEMA, content)
    receipt_path = output_dir / "compact-verifier-receipt.json"
    receipt_publication = publish_exact(receipt_path, packet_bytes(receipt))
    captured_pass = (
        process.returncode == 0
        and compact_result == expected_verifier_result(required_digest)
        and parsed is not None
        and process.stdout in (canonical(parsed), canonical(parsed) + b"\n")
        and process.stderr == b""
    )
    return {
        "status": "CAPTURED_PASS" if captured_pass else "CAPTURED_NONPASS",
        "subject_sha256": required_digest,
        "returncode": process.returncode,
        "result": compact_result,
        "receipt": str(receipt_path),
        "receipt_sha256": receipt["content_sha256"],
        "publication": {
            "stdout": stdout_publication,
            "stderr": stderr_publication,
            "receipt": receipt_publication,
        },
        "authority": "NONE",
        "live_effect": "NONE_READ_ONLY",
    }


def capture_bound_launcher_receipt(
    *,
    launcher_path: Path,
    launcher_contract_path: Path,
    arguments: list[str],
    output_dir: Path,
    label: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Execute an exact shell launcher from a retained O_NOFOLLOW descriptor."""
    if not label or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in label):
        raise ReviewGraphError("bound_launcher_label_invalid")
    launcher_contract, launcher_contract_binding = load_launcher_binding_contract(
        launcher_contract_path,
        launcher_path=launcher_path,
        label=label,
    )
    launcher_before, launcher_fd, transport = capture_execution_transport(
        launcher_path=launcher_path,
        output_dir=output_dir,
        label=label,
    )
    shell_path = system_shell_path()
    actual_argv = [
        str(shell_path),
        f"/dev/fd/{launcher_fd}",
        *arguments,
    ]
    started = time.monotonic()
    try:
        process = subprocess.run(
            actual_argv,
            cwd=launcher_path.parent,
            env={},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            close_fds=True,
            pass_fds=(launcher_fd,),
            timeout=timeout_seconds,
        )
        capture_after_raw, capture_after_identity = stable_read_descriptor(launcher_fd)
    except subprocess.TimeoutExpired as exc:
        raise ReviewGraphError("bound_launcher_capture_timeout") from exc
    finally:
        os.close(launcher_fd)
    elapsed_seconds = time.monotonic() - started
    if (
        launcher_before != exact_file_binding(launcher_path)
        or launcher_contract_binding != exact_file_binding(launcher_contract_path)
        or transport["source_descriptor_identity"]
        != descriptor_identity(os.lstat(launcher_path))
        or digest(capture_after_raw) != launcher_before["sha256"]
        or capture_after_identity != transport["private_capture"]["unlinked_identity"]
    ):
        raise ReviewGraphError("bound_launcher_changed_during_descriptor_exec")
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / f"{label}.stdout"
    stderr_path = output_dir / f"{label}.stderr"
    stdout_publication = publish_exact(stdout_path, process.stdout)
    stderr_publication = publish_exact(stderr_path, process.stderr)
    content = {
        "label": label,
        "producer": exact_file_binding(Path(__file__).resolve()),
        "launcher_binding_contract": {
            "binding": launcher_contract_binding,
            "expected": launcher_contract,
            "observed_launcher": launcher_before,
            "verdict": "PASS",
        },
        "launcher": launcher_before,
        "logical_argv": [str(launcher_path), *arguments],
        "actual_argv": actual_argv,
        "execution_transport": {
            **transport,
            "shell": exact_file_binding(shell_path),
            "private_capture_post_execution": {
                "identity": capture_after_identity,
                "content_sha256": digest(capture_after_raw),
            },
            "launcher_descriptor_closed_after_execution": True,
        },
        "returncode": int(process.returncode),
        "raw_stdout": {
            "path": str(stdout_path),
            "bytes": len(process.stdout),
            "sha256": digest(process.stdout),
        },
        "raw_stderr": {
            "path": str(stderr_path),
            "bytes": len(process.stderr),
            "sha256": digest(process.stderr),
        },
        "elapsed_seconds": elapsed_seconds,
        "automatic_retry": False,
        "authority": "NONE",
        "canonical_state_effect": "ONLY_EFFECTS_DECLARED_BY_BOUND_LAUNCHER",
    }
    receipt = wrapped(BOUND_LAUNCHER_RECEIPT_SCHEMA, content)
    receipt_path = output_dir / f"{label}.receipt.json"
    receipt_publication = publish_exact(receipt_path, packet_bytes(receipt))
    return {
        "status": "CAPTURED_PASS" if process.returncode == 0 else "CAPTURED_NONPASS",
        "returncode": int(process.returncode),
        "receipt": str(receipt_path),
        "receipt_sha256": receipt["content_sha256"],
        "publication": {
            "stdout": stdout_publication,
            "stderr": stderr_publication,
            "receipt": receipt_publication,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--subject", required=True)
    build.add_argument("--required-digest", required=True)
    build.add_argument("--output-dir", required=True)
    build.add_argument("--evidence-root", action="append", default=[])
    build.add_argument("--spec")
    build.add_argument("--verifier-receipt")
    build.add_argument("--review-schema")
    build.add_argument("--inline-max-bytes", type=int, default=1024)
    metrics = subparsers.add_parser("metrics")
    metrics.add_argument("--review-dir", required=True)
    metrics.add_argument("--output", required=True)
    metrics.add_argument("--prompt-dir")
    metrics.add_argument("--fact-packet")
    metrics.add_argument("--review-graph")
    triad = subparsers.add_parser("triad-gate")
    triad.add_argument("--review-dir", required=True)
    triad.add_argument("--required-digest", required=True)
    triad.add_argument("--output", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--bundle-dir", required=True)
    verify.add_argument("--subject", required=True)
    verify.add_argument("--required-digest", required=True)
    capture = subparsers.add_parser("capture-verifier")
    capture.add_argument("--launcher", required=True)
    capture.add_argument("--launcher-contract", required=True)
    capture.add_argument("--subject", required=True)
    capture.add_argument("--required-digest", required=True)
    capture.add_argument("--output-dir", required=True)
    capture.add_argument("--timeout-seconds", type=int, default=300)
    bound = subparsers.add_parser("capture-launcher")
    bound.add_argument("--launcher", required=True)
    bound.add_argument("--launcher-contract", required=True)
    bound.add_argument("--arg", action="append", default=[])
    bound.add_argument("--output-dir", required=True)
    bound.add_argument("--label", required=True)
    bound.add_argument("--timeout-seconds", type=int, default=3600)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "build":
            subject_path = Path(args.subject).expanduser().resolve()
            roots = [subject_path.parent]
            roots.extend(Path(item).expanduser().resolve() for item in args.evidence_root)
            result = build_review_bundle(
                subject_path=subject_path,
                required_digest=args.required_digest,
                output_dir=Path(args.output_dir).expanduser().resolve(),
                allowed_roots=tuple(dict.fromkeys(roots)),
                spec_path=Path(args.spec).expanduser().resolve() if args.spec else None,
                verifier_receipt_path=Path(args.verifier_receipt).expanduser().resolve()
                if args.verifier_receipt
                else None,
                review_schema_path=Path(args.review_schema).expanduser().resolve()
                if args.review_schema
                else None,
                inline_max_bytes=args.inline_max_bytes,
            )
        elif args.command == "metrics":
            result = build_metrics(
                review_dir=Path(args.review_dir).expanduser().resolve(),
                output_path=Path(args.output).expanduser().resolve(),
                prompt_dir=Path(args.prompt_dir).expanduser().resolve()
                if args.prompt_dir
                else None,
                fact_packet_path=Path(args.fact_packet).expanduser().resolve()
                if args.fact_packet
                else None,
                review_graph_path=Path(args.review_graph).expanduser().resolve()
                if args.review_graph
                else None,
            )
        elif args.command == "verify":
            result = verify_review_bundle(
                bundle_dir=Path(args.bundle_dir).expanduser().resolve(),
                subject_path=Path(args.subject).expanduser().resolve(),
                required_digest=args.required_digest,
            )
        elif args.command == "triad-gate":
            result = build_triad_gate(
                review_dir=Path(args.review_dir).expanduser().resolve(),
                required_digest=args.required_digest,
                output_path=Path(args.output).expanduser().resolve(),
            )
        elif args.command == "capture-verifier":
            result = capture_compact_verifier_receipt(
                launcher_path=Path(args.launcher).expanduser().resolve(),
                launcher_contract_path=Path(args.launcher_contract)
                .expanduser()
                .resolve(),
                subject_path=Path(args.subject).expanduser().resolve(),
                required_digest=args.required_digest,
                output_dir=Path(args.output_dir).expanduser().resolve(),
                timeout_seconds=args.timeout_seconds,
            )
        else:
            result = capture_bound_launcher_receipt(
                launcher_path=Path(args.launcher).expanduser().resolve(),
                launcher_contract_path=Path(args.launcher_contract)
                .expanduser()
                .resolve(),
                arguments=list(args.arg),
                output_dir=Path(args.output_dir).expanduser().resolve(),
                label=args.label,
                timeout_seconds=args.timeout_seconds,
            )
    except (OSError, ReviewGraphError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
