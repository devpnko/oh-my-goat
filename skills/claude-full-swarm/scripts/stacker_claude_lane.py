#!/usr/bin/env python3
"""Run one Claude-backed Stacker lane with early actual-model attestation.

The resolver chooses a role-appropriate selector and expected runtime identity.
This runner does not choose or hardcode a model version.  It observes Claude
Code's stream metadata and terminates the exact process group before a costly
review can continue when the first actual model, fallback state, harness, or
provider health does not match the resolved lane.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILLS_ROOT = Path(__file__).resolve().parents[2]
FULL_SWARM_SCRIPTS = SKILLS_ROOT / "full-swarm" / "scripts"
if str(FULL_SWARM_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(FULL_SWARM_SCRIPTS))

import stacker_runtime_health as runtime_health  # noqa: E402


SCHEMA_VERSION = "stacker.claude_lane_watchdog.v1"
DEFAULT_RUNTIME_HEALTH = Path("~/.codex/swarm/provider-runtime-health.json")
DEFAULT_TIMEOUT_SECONDS = 7200
HARD_MAX_TIMEOUT_SECONDS = 7200
PROVIDER_MARKERS = {
    b"401 unauthorized": ("PROVIDER_AUTH_STOP", "auth_unavailable"),
    b"403 forbidden": ("PROVIDER_FORBIDDEN_STOP", "transport_forbidden"),
    b"429 too many requests": ("PROVIDER_RATE_LIMIT_STOP", "rate_limited"),
    b"exceeded retry limit": ("PROVIDER_RETRY_LIMIT_STOP", "rate_limited"),
    b"hard quota": ("PROVIDER_QUOTA_STOP", "hard_quota"),
    b"usage limit": ("PROVIDER_QUOTA_STOP", "hard_quota"),
    b"not logged in": ("PROVIDER_AUTH_STOP", "auth_unavailable"),
    b"please login": ("PROVIDER_AUTH_STOP", "auth_unavailable"),
    b"please log in": ("PROVIDER_AUTH_STOP", "auth_unavailable"),
}


class PolicyError(ValueError):
    """Raised when a Claude lane violates the bounded Stacker policy."""


def current_cli_version(claude_bin: str) -> str:
    process = subprocess.run(
        [claude_bin, "--version"], capture_output=True, text=True, timeout=10, check=False
    )
    if process.returncode != 0:
        raise PolicyError(f"unable to read Claude Code version from {claude_bin}")
    fields = (process.stdout or process.stderr).strip().split()
    if not fields:
        raise PolicyError("Claude Code returned an empty version")
    return fields[0]


def auth_status(claude_bin: str) -> dict[str, Any]:
    process = subprocess.run(
        [claude_bin, "auth", "status", "--json"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if process.returncode != 0:
        raise PolicyError(
            "Claude auth preflight failed; interactive login is forbidden"
        )
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise PolicyError("Claude auth preflight was not JSON") from exc
    if payload.get("loggedIn") is not True:
        raise PolicyError(
            "Claude is not logged in; interactive login is forbidden"
        )
    return {
        "logged_in": True,
        "auth_method": payload.get("authMethod"),
        "api_provider": payload.get("apiProvider"),
        "subscription_type": payload.get("subscriptionType"),
    }


def exclusive_json_write(path: Path, payload: dict[str, Any]) -> None:
    raw = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def model_matches(model: str, expected_model: str, allowed_pattern: str) -> bool:
    if expected_model and model != expected_model:
        return False
    if allowed_pattern and re.fullmatch(allowed_pattern, model) is None:
        return False
    return bool(model)


def event_models(event: dict[str, Any]) -> list[str]:
    """Return primary response-model metadata from one stream event."""
    result: list[str] = []

    def add(value: Any) -> None:
        model = str(value or "").strip()
        if model and model not in result:
            result.append(model)

    if event.get("type") == "system" and event.get("subtype") == "init":
        add(event.get("model"))
    message = event.get("message")
    if isinstance(message, dict):
        add(message.get("model"))
    nested = event.get("event")
    if isinstance(nested, dict):
        nested_message = nested.get("message")
        if isinstance(nested_message, dict):
            add(nested_message.get("model"))
    return result


def fallback_event(event: dict[str, Any]) -> dict[str, str] | None:
    candidates = [event]
    nested = event.get("event")
    if isinstance(nested, dict):
        candidates.append(nested)
    for candidate in candidates:
        if candidate.get("type") == "system" and candidate.get("subtype") == "model_refusal_fallback":
            return {
                "original_model": str(candidate.get("originalModel") or ""),
                "fallback_model": str(candidate.get("fallbackModel") or ""),
                "trigger": str(candidate.get("trigger") or ""),
                "category": str(candidate.get("apiRefusalCategory") or ""),
            }
    return None


def structured_result(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get("type") != "result":
        return None
    value = event.get("structured_output")
    if isinstance(value, dict):
        return value
    value = event.get("result")
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def result_failure(event: dict[str, Any]) -> tuple[str, str] | None:
    if event.get("type") != "result" or not event.get("is_error"):
        return None
    subtype = str(event.get("subtype") or "")
    if subtype == "error_max_budget_usd":
        return "BUDGET_EXHAUSTED", ""
    rendered = json.dumps(event, ensure_ascii=False, sort_keys=True).lower().encode("utf-8")
    for marker, normalized in PROVIDER_MARKERS.items():
        if marker in rendered:
            return normalized
    return "RESULT_ERROR", ""


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


def build_command(
    *,
    claude: str,
    model: str,
    effort: str,
    schema: dict[str, Any],
    max_budget_usd: float,
) -> list[str]:
    command = [
        claude,
        "--print",
        "--model",
        model,
        "--effort",
        effort,
        "--safe-mode",
        "--permission-mode",
        "plan",
        "--tools",
        "Read,Glob,Grep,Bash",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--no-chrome",
        "--disable-slash-commands",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--no-session-persistence",
        "--json-schema",
        json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "--append-system-prompt",
        (
            "This is one bounded read-only Stacker lane. Do not edit files, invoke "
            "provider/model CLIs, create child agents, or retry provider failures. "
            "Return the requested structured review once."
        ),
    ]
    if max_budget_usd > 0:
        command.extend(["--max-budget-usd", str(max_budget_usd)])
    return command


def update_exclusion(
    path: Path,
    *,
    provider: str,
    selector: str,
    reason: str,
) -> None:
    payload = runtime_health.read_state(path)
    payload = runtime_health.exclude(
        payload,
        provider_id=provider,
        selector=selector,
        effort="*",
        reason=reason,
        observed_at=datetime.now(timezone.utc).isoformat(),
    )
    runtime_health.atomic_write(path, payload)


def execute(
    *,
    command: list[str],
    cwd: Path,
    prompt: bytes,
    expected_model: str,
    allowed_model_pattern: str,
    expected_cli_version: str,
    actual_cli_version: str,
    timeout_seconds: int,
    event_path: Path,
    stderr_path: Path,
    final_path: Path,
) -> dict[str, Any]:
    launched_at = time.time()
    if expected_cli_version and actual_cli_version != expected_cli_version:
        return {
            "status": "REFUSED",
            "stop_reason": "HARNESS_VERSION_MISMATCH",
            "returncode": None,
            "observed_models": [],
            "first_actual_model": None,
            "fallback_events": [],
            "elapsed_seconds": 0.0,
            "automatic_retry": False,
        }
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdin and process.stdout and process.stderr
    process.stdin.write(prompt)
    process.stdin.close()
    os.set_blocking(process.stdout.fileno(), False)
    os.set_blocking(process.stderr.fileno(), False)
    selected = selectors.DefaultSelector()
    selected.register(process.stdout, selectors.EVENT_READ, "stdout")
    selected.register(process.stderr, selectors.EVENT_READ, "stderr")
    stdout_buffer = b""
    stderr_tail = b""
    observed_models: list[str] = []
    fallback_events: list[dict[str, str]] = []
    final_payload: dict[str, Any] | None = None
    stop_reason = ""
    health_reason = ""
    with event_path.open("xb") as events, stderr_path.open("xb") as errors:
        while True:
            for key, _ in selected.select(timeout=0.2):
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    try:
                        selected.unregister(key.fileobj)
                    except KeyError:
                        pass
                    continue
                if key.data == "stderr":
                    errors.write(chunk)
                    errors.flush()
                    stderr_tail = (stderr_tail + chunk)[-8192:].lower()
                    for marker, (normalized, reason) in PROVIDER_MARKERS.items():
                        if marker in stderr_tail:
                            stop_reason, health_reason = normalized, reason
                            break
                    continue
                events.write(chunk)
                events.flush()
                stdout_buffer += chunk
                while b"\n" in stdout_buffer:
                    raw, stdout_buffer = stdout_buffer.split(b"\n", 1)
                    try:
                        event = json.loads(raw)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if not isinstance(event, dict):
                        continue
                    fallback = fallback_event(event)
                    if fallback is not None:
                        fallback_events.append(fallback)
                        stop_reason = "FALLBACK_OBSERVED"
                        health_reason = "fallback_observed"
                    failure = result_failure(event)
                    if failure is not None:
                        stop_reason, health_reason = failure
                    for model in event_models(event):
                        if model not in observed_models:
                            observed_models.append(model)
                        if not model_matches(model, expected_model, allowed_model_pattern):
                            stop_reason = "ACTUAL_MODEL_MISMATCH"
                            health_reason = "actual_model_mismatch"
                    candidate = structured_result(event)
                    if candidate is not None:
                        final_payload = candidate
            if time.time() - launched_at > timeout_seconds:
                stop_reason = "WALL_CLOCK_BUDGET_EXCEEDED"
            if stop_reason:
                terminate_process_group(process)
            if process.poll() is not None and not selected.get_map():
                break
        if stdout_buffer:
            events.write(stdout_buffer)
    process.stdout.close()
    process.stderr.close()
    completion = (
        process.returncode == 0
        and not stop_reason
        and bool(observed_models)
        and final_payload is not None
        and all(model_matches(model, expected_model, allowed_model_pattern) for model in observed_models)
    )
    if completion and final_payload is not None:
        exclusive_json_write(final_path, final_payload)
    elif not stop_reason:
        stop_reason = "INCOMPLETE_STREAM_RESULT"
    return {
        "status": "PASS" if completion else "STOPPED",
        "stop_reason": stop_reason or None,
        "runtime_health_reason": health_reason or None,
        "returncode": process.returncode,
        "observed_models": observed_models,
        "first_actual_model": observed_models[0] if observed_models else None,
        "fallback_events": fallback_events,
        "elapsed_seconds": round(time.time() - launched_at, 3),
        "automatic_retry": False,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output-prefix", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--expected-model", default="")
    parser.add_argument("--allowed-model-pattern", default="")
    parser.add_argument("--effort", default="max")
    parser.add_argument("--schema", required=True)
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--claude", default="/opt/homebrew/bin/claude")
    parser.add_argument("--provider", default="anthropic_claude")
    parser.add_argument("--expected-cli-version", default="current")
    parser.add_argument("--runtime-health", default=str(DEFAULT_RUNTIME_HEALTH))
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-budget-usd", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    prompt_path = Path(args.prompt).expanduser().resolve()
    output_prefix = Path(args.output_prefix).expanduser().resolve()
    schema_path = Path(args.schema).expanduser().resolve()
    cwd = Path(args.cwd).expanduser().resolve()
    health_path = Path(args.runtime_health).expanduser()
    try:
        if not args.expected_model and not args.allowed_model_pattern:
            raise PolicyError("expected model or allowed model pattern is required")
        if not 30 <= args.timeout_seconds <= HARD_MAX_TIMEOUT_SECONDS:
            raise PolicyError(f"timeout must be 30..{HARD_MAX_TIMEOUT_SECONDS} seconds")
        if args.max_budget_usd < 0:
            raise PolicyError("max budget must be non-negative")
        if not prompt_path.is_file() or not schema_path.is_file() or not cwd.is_dir():
            raise PolicyError("prompt, schema, and cwd must exist before launch")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if not isinstance(schema, dict):
            raise PolicyError("schema must be a JSON object")
        actual_cli = current_cli_version(args.claude)
        auth = auth_status(args.claude)
        expected_cli = actual_cli if args.expected_cli_version == "current" else args.expected_cli_version
        command = build_command(
            claude=args.claude,
            model=args.model,
            effort=args.effort,
            schema=schema,
            max_budget_usd=args.max_budget_usd,
        )
        policy = {
            "provider": args.provider,
            "requested_selector": args.model,
            "expected_model": args.expected_model,
            "allowed_model_pattern": args.allowed_model_pattern,
            "effort": args.effort,
            "expected_cli_version": expected_cli,
            "actual_cli_version": actual_cli,
            "timeout_seconds": args.timeout_seconds,
            "max_budget_usd": args.max_budget_usd or None,
            "fallback_allowed": False,
            "child_agent_tools_available": False,
            "auth_preflight": auth,
        }
        if args.dry_run:
            print(json.dumps({"status": "DRY_RUN", "command": command, "policy": policy}, indent=2))
            return 0
        output_prefix.parent.mkdir(parents=True, exist_ok=True)
        output_paths = [
            Path(str(output_prefix) + suffix)
            for suffix in (".events.jsonl", ".stderr", ".final.json", ".watchdog.json")
        ]
        if any(path.exists() for path in output_paths):
            raise PolicyError("Claude lane outputs are create-only")
        result = execute(
            command=command,
            cwd=cwd,
            prompt=prompt_path.read_bytes(),
            expected_model=args.expected_model,
            allowed_model_pattern=args.allowed_model_pattern,
            expected_cli_version=expected_cli,
            actual_cli_version=actual_cli,
            timeout_seconds=args.timeout_seconds,
            event_path=Path(str(output_prefix) + ".events.jsonl"),
            stderr_path=Path(str(output_prefix) + ".stderr"),
            final_path=Path(str(output_prefix) + ".final.json"),
        )
        health_reason = str(result.get("runtime_health_reason") or "")
        health_updated = False
        if health_reason:
            update_exclusion(
                health_path,
                provider=args.provider,
                selector=args.model,
                reason=health_reason,
            )
            health_updated = True
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "policy": policy,
            "runtime_health_updated": health_updated,
            **result,
        }
        exclusive_json_write(Path(str(output_prefix) + ".watchdog.json"), receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 75
    except (OSError, PolicyError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, ensure_ascii=False))
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
