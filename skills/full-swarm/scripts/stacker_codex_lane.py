#!/usr/bin/env python3
"""Run a Codex Stacker lane with bounded multi-agent orchestration.

The Codex ``ultra`` effort is a proactive multi-agent mode.  The CLI exposes a
concurrency limit, but it does not expose hard total-session or tree-depth
limits.  This wrapper supplies both an invocation-local concurrency cap and an
external watchdog over the persisted session tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import selectors
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_RUNTIME_HEALTH = Path("~/.codex/swarm/provider-runtime-health.json")
DEFAULT_SESSION_ROOT = Path("~/.codex/sessions")
DEFAULT_MODELS_CACHE = Path("~/.codex/models_cache.json")
DEFAULT_MAX_TOTAL_SESSIONS = 100
DEFAULT_MAX_TREE_DEPTH = 8
DEFAULT_MAX_CONCURRENT_AGENTS = 32
DEFAULT_TIMEOUT_SECONDS = 7200
HARD_MAX_TOTAL_SESSIONS = 100
HARD_MAX_TREE_DEPTH = 8
HARD_MAX_CONCURRENT_AGENTS = 32
HARD_MAX_TIMEOUT_SECONDS = 7200
PROVIDER_STOP_MARKERS = (
    (b"usage limit", "PROVIDER_USAGE_LIMIT"),
    (b"hard quota", "PROVIDER_USAGE_LIMIT"),
    (b"429 too many requests", "PROVIDER_RATE_LIMIT"),
    (b"exceeded retry limit", "PROVIDER_RETRY_LIMIT_EXCEEDED"),
    (b"401 unauthorized", "PROVIDER_AUTHENTICATION_FAILURE"),
    (b"403 forbidden", "PROVIDER_FORBIDDEN_TRANSPORT"),
)


class PolicyError(ValueError):
    """Raised when an invocation violates the local Stacker safety policy."""


def classify_provider_stop(raw: bytes) -> str | None:
    """Classify a terminal provider response found on either output stream."""
    lowered = raw.lower()
    for marker, reason in PROVIDER_STOP_MARKERS:
        if marker in lowered:
            return reason
    return None


def sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def normalized_model_catalog(path: Path) -> tuple[bytes, dict[str, Any]]:
    """Build a read-only compatible catalog snapshot without mutating the shared cache."""
    path = path.expanduser()
    if not path.is_file():
        raise PolicyError("models cache is absent; discovery must run before review")
    before_raw = path.read_bytes()
    payload = json.loads(before_raw.decode("utf-8", "strict"))
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list) or not all(isinstance(item, dict) for item in models):
        raise PolicyError("models cache is not a closed model catalog")
    changed: list[str] = []
    for model in models:
        if "supports_reasoning_summaries" not in model:
            model["supports_reasoning_summaries"] = True
            changed.append(str(model.get("slug") or "<missing-slug>"))
    after_raw = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n"
    )
    return after_raw, {
        "status": (
            "SNAPSHOT_NORMALIZED_REQUIRED_FIELDS"
            if changed
            else "SNAPSHOT_EXACT_COMPATIBLE"
        ),
        "source_path": str(path),
        "source_sha256": sha256(before_raw),
        "snapshot_sha256": sha256(after_raw),
        "changed_model_count": len(changed),
        "changed_models": changed,
        "inserted_defaults": (
            {"supports_reasoning_summaries": True} if changed else {}
        ),
        "model_selection_changed": False,
        "shared_cache_mutation": "NONE",
    }


def publish_model_catalog_snapshot(
    source_path: Path,
    snapshot_path: Path,
) -> dict[str, Any]:
    """Publish one invocation-local static catalog with exclusive custody."""
    raw, report = normalized_model_catalog(source_path)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        snapshot_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent_fd = os.open(
        snapshot_path.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return {
        **report,
        "snapshot_path": str(snapshot_path),
        "publication": "O_EXCL_FILE_FSYNC_PARENT_FSYNC",
    }


def read_runtime_health(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exclusions": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("exclusions", []), list):
        raise PolicyError("runtime health payload is not closed enough to evaluate")
    return payload


def is_excluded(
    payload: dict[str, Any], *, provider_id: str, selector: str, effort: str
) -> bool:
    return any(
        item.get("provider_id") == provider_id
        and item.get("selector") == selector
        and item.get("effort") == effort
        and item.get("status") == "UNTIL_REVALIDATED"
        for item in payload.get("exclusions", [])
        if isinstance(item, dict)
    )


def validate_limits(
    *,
    effort: str,
    allow_ultra: bool,
    revalidation_smoke: bool,
    max_total_sessions: int,
    max_tree_depth: int,
    max_concurrent_agents: int,
    timeout_seconds: int,
    runtime_excluded: bool,
) -> None:
    if effort == "ultra" and not allow_ultra:
        raise PolicyError("ultra requires explicit --allow-ultra")
    if effort == "ultra" and runtime_excluded and not revalidation_smoke:
        raise PolicyError("selector/ultra is excluded until a bounded revalidation smoke passes")
    if not 1 <= max_total_sessions <= HARD_MAX_TOTAL_SESSIONS:
        raise PolicyError(f"max total sessions must be 1..{HARD_MAX_TOTAL_SESSIONS}")
    if not 0 <= max_tree_depth <= HARD_MAX_TREE_DEPTH:
        raise PolicyError(f"max tree depth must be 0..{HARD_MAX_TREE_DEPTH}")
    if not 1 <= max_concurrent_agents <= HARD_MAX_CONCURRENT_AGENTS:
        raise PolicyError(
            f"max concurrent agents must be 1..{HARD_MAX_CONCURRENT_AGENTS}"
        )
    if max_concurrent_agents > max_total_sessions:
        raise PolicyError("concurrent-agent cap cannot exceed total-session cap")
    if not 60 <= timeout_seconds <= HARD_MAX_TIMEOUT_SECONDS:
        raise PolicyError(f"timeout must be 60..{HARD_MAX_TIMEOUT_SECONDS} seconds")
    if revalidation_smoke and (
        max_total_sessions > 12
        or max_tree_depth > 3
        or max_concurrent_agents > 6
        or timeout_seconds > 900
    ):
        raise PolicyError("revalidation smoke exceeds its stricter 12/3/6/900 budget")


def bounded_prompt(
    prompt: bytes,
    *,
    max_total_sessions: int,
    max_tree_depth: int,
    max_concurrent_agents: int,
) -> bytes:
    contract = (
        "\n\n<stacker_orchestration_budget>\n"
        f"Total sessions in this root tree, including root, must not exceed {max_total_sessions}.\n"
        f"Tree depth must not exceed {max_tree_depth}.\n"
        f"Concurrent active agents must not exceed {max_concurrent_agents}.\n"
        "Before every spawn, account for the existing tree and do not spawn if any bound would be exceeded.\n"
        "Do not retry quota, rate-limit, authentication, or forbidden-transport failures.\n"
        "Return the required final report once the bounded review is complete.\n"
        "</stacker_orchestration_budget>\n"
    ).encode("utf-8")
    return prompt + contract


def build_command(
    *,
    codex: str,
    cwd: Path,
    model: str,
    effort: str,
    max_concurrent_agents: int,
    output_schema: Path,
    final_path: Path,
    model_catalog_path: Path,
    isolated_review_scratch: Path | None = None,
) -> list[str]:
    command = [
        codex,
        "exec",
        "-C",
        str(isolated_review_scratch or cwd),
        "--model",
        model,
        "--config",
        f'model_reasoning_effort="{effort}"',
        "--config",
        "model_catalog_json=" + json.dumps(str(model_catalog_path)),
        "--config",
        f"agents.max_threads={max_concurrent_agents}",
        "--config",
        (
            "features.multi_agent_v2.max_concurrent_threads_per_session="
            f"{max_concurrent_agents}"
        ),
        "--sandbox",
        "workspace-write" if isolated_review_scratch else "read-only",
        "--output-schema",
        str(output_schema),
        "--output-last-message",
        str(final_path),
        "--json",
        "-",
    ]
    if isolated_review_scratch:
        command.insert(-1, "--skip-git-repo-check")
    return command


def session_directories(session_root: Path) -> set[Path]:
    now_local = datetime.now().astimezone()
    now_utc = datetime.now(timezone.utc)
    return {
        session_root / f"{value.year:04d}" / f"{value.month:02d}" / f"{value.day:02d}"
        for value in (now_local, now_utc)
    }


def ingest_session_tree(
    *,
    root_thread_id: str,
    session_root: Path,
    launched_at: float,
    known: dict[Path, int],
) -> tuple[int, int]:
    for directory in session_directories(session_root):
        if not directory.is_dir():
            continue
        for path in directory.glob("*.jsonl"):
            if path in known:
                continue
            try:
                if path.stat().st_mtime < launched_at - 5:
                    continue
                with path.open("r", encoding="utf-8") as handle:
                    first = json.loads(handle.readline())
                payload = first.get("payload", {}) if first.get("type") == "session_meta" else {}
                if payload.get("session_id") != root_thread_id:
                    continue
                source = payload.get("source")
                spawn = (
                    source.get("subagent", {}).get("thread_spawn", {})
                    if isinstance(source, dict)
                    else {}
                )
                depth = spawn.get("depth")
                if not isinstance(depth, int):
                    depth = 0 if payload.get("id") == root_thread_id else -1
                known[path] = depth
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    depths = [value for value in known.values() if value >= 0]
    return len(known), max(depths, default=0)


def terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


def execute(
    *,
    command: list[str],
    prompt: bytes,
    event_path: Path,
    stderr_path: Path,
    session_root: Path,
    max_total_sessions: int,
    max_tree_depth: int,
    timeout_seconds: int,
    isolated_review_scratch: Path | None,
) -> dict[str, Any]:
    launched_at = time.time()
    process_environment = os.environ.copy()
    if isolated_review_scratch:
        process_environment["TMPDIR"] = str(isolated_review_scratch)
    process = subprocess.Popen(
        command,
        cwd=command[command.index("-C") + 1],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=process_environment,
    )
    assert process.stdin and process.stdout and process.stderr
    process.stdin.write(prompt)
    process.stdin.close()
    os.set_blocking(process.stdout.fileno(), False)
    os.set_blocking(process.stderr.fileno(), False)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    stdout_buffer = b""
    stdout_tail = b""
    stderr_tail = b""
    root_thread_id = ""
    known_sessions: dict[Path, int] = {}
    observed_sessions = 0
    observed_depth = 0
    stop_reason = ""
    last_scan = 0.0
    with event_path.open("wb") as events, stderr_path.open("wb") as errors:
        while True:
            for key, _ in selector.select(timeout=0.25):
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    try:
                        selector.unregister(key.fileobj)
                    except KeyError:
                        pass
                    continue
                if key.data == "stdout":
                    events.write(chunk)
                    events.flush()
                    stdout_tail = (stdout_tail + chunk)[-4096:]
                    provider_stop = classify_provider_stop(stdout_tail)
                    if provider_stop:
                        stop_reason = provider_stop
                    stdout_buffer += chunk
                    while b"\n" in stdout_buffer:
                        line, stdout_buffer = stdout_buffer.split(b"\n", 1)
                        try:
                            event = json.loads(line)
                        except (ValueError, json.JSONDecodeError):
                            continue
                        if event.get("type") == "thread.started":
                            candidate = event.get("thread_id")
                            if isinstance(candidate, str):
                                root_thread_id = candidate
                else:
                    errors.write(chunk)
                    errors.flush()
                    stderr_tail = (stderr_tail + chunk)[-4096:]
                    provider_stop = classify_provider_stop(stderr_tail)
                    if provider_stop:
                        stop_reason = provider_stop
            now = time.time()
            if not stop_reason and root_thread_id and now - last_scan >= 1.0:
                observed_sessions, observed_depth = ingest_session_tree(
                    root_thread_id=root_thread_id,
                    session_root=session_root,
                    launched_at=launched_at,
                    known=known_sessions,
                )
                last_scan = now
                if observed_sessions > max_total_sessions:
                    stop_reason = "TOTAL_SESSION_BUDGET_EXCEEDED"
                elif observed_depth > max_tree_depth:
                    stop_reason = "TREE_DEPTH_BUDGET_EXCEEDED"
            if not stop_reason and now - launched_at > timeout_seconds:
                stop_reason = "WALL_CLOCK_BUDGET_EXCEEDED"
            if stop_reason:
                terminate_process_group(process)
            if process.poll() is not None and not selector.get_map():
                break
        if stdout_buffer:
            events.write(stdout_buffer)
    selector.close()
    process.stdout.close()
    process.stderr.close()
    return {
        "status": "PASS" if process.returncode == 0 and not stop_reason else "STOPPED",
        "stop_reason": stop_reason or None,
        "returncode": process.returncode,
        "root_thread_id": root_thread_id or None,
        "observed_total_sessions": observed_sessions,
        "observed_max_depth": observed_depth,
        "elapsed_seconds": round(time.time() - launched_at, 3),
        "automatic_retry": False,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output-prefix", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", default="max")
    parser.add_argument("--schema", required=True)
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--provider", default="openai_codex")
    parser.add_argument("--runtime-health", default=str(DEFAULT_RUNTIME_HEALTH))
    parser.add_argument("--session-root", default=str(DEFAULT_SESSION_ROOT))
    parser.add_argument("--models-cache", default=str(DEFAULT_MODELS_CACHE))
    parser.add_argument("--max-total-sessions", type=int, default=DEFAULT_MAX_TOTAL_SESSIONS)
    parser.add_argument("--max-tree-depth", type=int, default=DEFAULT_MAX_TREE_DEPTH)
    parser.add_argument(
        "--max-concurrent-agents", type=int, default=DEFAULT_MAX_CONCURRENT_AGENTS
    )
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--isolated-review-scratch",
        help=(
            "Existing disposable directory used as the sole workspace-write root "
            "and TMPDIR while the governed repository remains read-only"
        ),
    )
    parser.add_argument("--allow-ultra", action="store_true")
    parser.add_argument("--revalidation-smoke", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    prompt_path = Path(args.prompt).expanduser().resolve()
    output_prefix = Path(args.output_prefix).expanduser().resolve()
    schema_path = Path(args.schema).expanduser().resolve()
    cwd = Path(args.cwd).expanduser().resolve()
    health_path = Path(args.runtime_health).expanduser()
    session_root = Path(args.session_root).expanduser()
    models_cache = Path(args.models_cache).expanduser()
    isolated_review_scratch = (
        Path(args.isolated_review_scratch).expanduser().resolve()
        if args.isolated_review_scratch
        else None
    )
    try:
        health = read_runtime_health(health_path)
        excluded = is_excluded(
            health,
            provider_id=args.provider,
            selector=args.model,
            effort=args.effort,
        )
        validate_limits(
            effort=args.effort,
            allow_ultra=args.allow_ultra,
            revalidation_smoke=args.revalidation_smoke,
            max_total_sessions=args.max_total_sessions,
            max_tree_depth=args.max_tree_depth,
            max_concurrent_agents=args.max_concurrent_agents,
            timeout_seconds=args.timeout_seconds,
            runtime_excluded=excluded,
        )
        if not prompt_path.is_file() or not schema_path.is_file() or not cwd.is_dir():
            raise PolicyError("prompt, schema, and cwd must exist before launch")
        if isolated_review_scratch:
            allowed_roots = (Path("/private/tmp"), Path("/tmp"))
            if (
                not isolated_review_scratch.is_dir()
                or isolated_review_scratch.is_symlink()
                or not any(
                    isolated_review_scratch == root
                    or root in isolated_review_scratch.parents
                    for root in allowed_roots
                )
            ):
                raise PolicyError(
                    "isolated review scratch must be an existing non-symlink directory under /private/tmp or /tmp"
                )
        final_path = Path(str(output_prefix) + ".final.json")
        event_path = Path(str(output_prefix) + ".events.jsonl")
        stderr_path = Path(str(output_prefix) + ".stderr")
        receipt_path = Path(str(output_prefix) + ".watchdog.json")
        model_catalog_path = Path(str(output_prefix) + ".model-catalog.json")
        if isolated_review_scratch and not all(
            path == isolated_review_scratch
            or isolated_review_scratch in path.parents
            for path in (final_path, event_path, stderr_path, receipt_path)
        ):
            raise PolicyError(
                "all lane outputs must remain inside isolated review scratch"
            )
        if args.dry_run:
            _catalog_raw, model_cache_compatibility = normalized_model_catalog(
                models_cache
            )
            model_cache_compatibility = {
                **model_cache_compatibility,
                "snapshot_path": str(model_catalog_path),
                "publication": "PLANNED_NO_WRITE_DRY_RUN",
            }
        else:
            output_prefix.parent.mkdir(parents=True, exist_ok=True)
            model_cache_compatibility = publish_model_catalog_snapshot(
                models_cache,
                model_catalog_path,
            )
        command = build_command(
            codex=args.codex,
            cwd=cwd,
            model=args.model,
            effort=args.effort,
            max_concurrent_agents=args.max_concurrent_agents,
            output_schema=schema_path,
            final_path=final_path,
            model_catalog_path=model_catalog_path,
            isolated_review_scratch=isolated_review_scratch,
        )
        policy = {
            "model": args.model,
            "effort": args.effort,
            "max_total_sessions": args.max_total_sessions,
            "max_tree_depth": args.max_tree_depth,
            "max_concurrent_agents": args.max_concurrent_agents,
            "timeout_seconds": args.timeout_seconds,
            "runtime_exclusion_active": excluded,
            "revalidation_smoke": args.revalidation_smoke,
            "sandbox_mode": (
                "isolated_review_scratch" if isolated_review_scratch else "read_only"
            ),
            "isolated_review_scratch": (
                str(isolated_review_scratch) if isolated_review_scratch else None
            ),
            "model_cache_compatibility": model_cache_compatibility,
        }
        if args.dry_run:
            print(json.dumps({"status": "DRY_RUN", "command": command, "policy": policy}, indent=2))
            return 0
        result = execute(
            command=command,
            prompt=bounded_prompt(
                prompt_path.read_bytes(),
                max_total_sessions=args.max_total_sessions,
                max_tree_depth=args.max_tree_depth,
                max_concurrent_agents=args.max_concurrent_agents,
            ),
            event_path=event_path,
            stderr_path=stderr_path,
            session_root=session_root,
            max_total_sessions=args.max_total_sessions,
            max_tree_depth=args.max_tree_depth,
            timeout_seconds=args.timeout_seconds,
            isolated_review_scratch=isolated_review_scratch,
        )
        receipt = {"schema_version": "stacker.codex_lane_watchdog.v1", "policy": policy, **result}
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 75
    except (OSError, PolicyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, ensure_ascii=False))
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
