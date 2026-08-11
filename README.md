# Oh My GOAT

Oh My GOAT packages the portable, owner-governed Stacker layer used by GOAT and
ARVIS. It selects review and execution candidates by role, evidence novelty,
runtime health, and provider quota while keeping routing separate from
Authority, execution, and completion.

## What is included

- Provider-neutral model discovery and actual-model attestation
- Role-based champion and frontier-intake selection
- Quota-paced Fable routing without quota-driven busywork
- A bounded watchdog for expensive Codex lanes, including `ultra`
- Evidence-aware review DAGs, deterministic Fact Packets, and cost telemetry
- `gstack`, `full-swarm`, and `claude-full-swarm` skill surfaces

The initial release is deliberately narrower than the full GOAT system. It
does **not** issue execution Authority, declare Mission success, produce a
canonical Owner Trust Receipt, or establish Minimum Strong v0 closure.

## Safety semantics

```text
Discovery != promotion
Quota availability != model quality
Routing projection != Authority
Host PASS != canonical completion
Exact named-model gate != fallback-compatible lane
```

Newly discovered models enter isolated intake. They replace a role champion
only after actual-model attestation and role-relevant evidence. Fable quota may
expand eligible high-value roles, but it never invents work merely to consume
allowance. Exact Fable gates HOLD when Fable is unavailable; they do not silently
inherit an Opus identity.

## Repository layout

```text
.codex-plugin/plugin.json       Codex plugin manifest
skills/gstack/                  Owner-governed stack proposal surface
skills/full-swarm/              Provider-neutral resolver and review planner
skills/claude-full-swarm/       Claude/Fable lane and Model League support
```

Relative script paths inside a skill resolve from the directory containing that
skill's `SKILL.md`. Agents must not assume the user's project working directory.

## Local runtime state

Derived observations belong under `~/.codex/swarm/`, including Model League
ledgers and `provider-quota-state.json`. They are local inputs, not canonical
GOAT state, and are intentionally excluded from this repository.

## Validation

```bash
python3 -m pytest -q \
  skills/full-swarm/scripts/test_*.py \
  skills/claude-full-swarm/scripts/test_*.py

ruff check skills
```

The plugin manifest and each skill should also be validated with the current
Codex plugin/skill validators before release.

## Project status

This repository starts with the portable Stacker and routing boundary. The
current GOAT Minimum Strong mission remains a separate governed lineage; a
commit here must not be interpreted as automatically advancing that Mission.
