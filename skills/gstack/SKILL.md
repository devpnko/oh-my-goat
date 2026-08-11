---
name: gstack
description: Propose, compare, explain, select, and bind a versioned Execution Stack under owner governance. Use when the user says gstack, aswarm, arvis swarm, asks which agents or models should work, or needs a Stack binding decision.
---

<!-- skill-contract
surface_owner: goat_governance
provenance_class: stack_binding_proposal
canonical_skill: gstack
accepted_aliases: aswarm,gstack
public_claim: false
-->

# Execution Stack Binding

## Portable Path Resolution

Resolve relative script paths from the directory containing this `SKILL.md`,
never from the user's project working directory. The `../full-swarm` and
`../claude-full-swarm` paths refer to sibling skills in this plugin.

1. Describe candidate roles, graph or opaque nodes, runtime, harness, provider/model versions, Skills, prompts, tools, permissions, configuration, and recovery ownership.
2. Distinguish a proposal from an owner-authorized binding.
3. Record constraints, provenance, unknowns, and the reason for the selected binding.
4. Pass the authorized binding to ARVIS execution supervision; do not execute domain work here.

For model-backed roles, prefer a capability/role selector plus a resolution
policy over a permanently hardcoded version. High-impact Stacker/reviewer roles
default to `highest_suitable_first`: project Model League role champion, current
provider/harness health, then the newest moving family alias when evidence is
tied or absent. A lower/older candidate requires a recorded constraint or
role-fit reason.

For Claude-backed Stacker candidates, materialize this projection with
`../claude-full-swarm/scripts/stacker_model_resolve.py`
and bind its selection basis plus the later actual-model attestation into the
Stack. Resolver output is a candidate projection, not Authority.

For provider-neutral Stacker selection, run the following before candidate
binding:

```bash
python3 ../full-swarm/scripts/provider_model_discover.py --write-state
python3 ../full-swarm/scripts/stacker_stack_resolve.py \
  --project <project> \
  --roles semantic,mechanical,atomicity
```

Discovery reads the current Claude moving aliases, Codex model cache, configured
providers, and any explicit local catalog adapters. The saved snapshot is a
derived observation only. A newly discovered model enters isolated intake; it
does not displace a role champion until attested role evidence earns promotion.
For a high/critical review, a champion is the comparison baseline rather than
an exclusive route: `FRONTIER_INTAKE_REQUIRED` means the returned newest
attested lane must actually run before the review policy is complete. Coalesce
the same candidate across compatible roles when one honest evaluation can
cover them. Use `max` as the stable default ceiling. Use `ultra` only with an
explicit run-level opt-in and healthy runtime evidence; on quota/rate-limit or
transport failure, record an effort-level exclusion with
`stacker_runtime_health.py`, fall back without blind retries, and do not score
the incident as model quality.
Fable eligibility is quota-paced rather than permanently opt-in or permanently
default. Read `~/.codex/swarm/provider-quota-state.json` through
`stacker_stack_resolve.py --fable-routing auto`: fresh provider-wide quota may
open only `intent_gap`, `strategy_planner`, and `correction_architect`; fresh
Fable-scoped surplus may additionally open `ux_product` and `orchestrator`.
`named_advisor` and downstream `fable_final` are exact roles even when quota is
unknown. Stale/invalid quota never expands roles, quota never promotes a model,
and no lane may be invented solely to consume allowance. Ordinary-role Fable
unavailability may produce a fresh Opus/other candidate; an exact Fable gate
must HOLD rather than inherit a fallback identity. This quota projection is
non-canonical and grants no Authority.
Run every Codex-backed Stacker lane through
`../full-swarm/scripts/stacker_codex_lane.py`. Its
watchdog must override ambient orchestration limits and enforce the selected
total-session, tree-depth, concurrent-agent, and wall-clock budgets. The
hard ultra envelope is 100 total sessions, depth 8, concurrency 32, and two
hours; the first violation terminates the exact process group with no automatic
retry. Do not launch Stacker ultra through an unbounded direct `codex exec`
wrapper.
At final lane acceptance, use the provider's metadata attestor. Providers with
no catalog or attestor remain configured-but-ineligible for binding.
Successful Claude/Codex attestation outputs are folded back into the derived
discovery state, so an alias resolving to a different actual model is detected
on the next refresh and re-enters intake instead of inheriting the old score.

Every resolved Stack projection must distinguish:

```text
requested_selector
selection_basis
expected_harness_version
resolved_actual_model
fallback_event
attestation_status
```

Requested alias, pane title, and model self-report are not binding evidence.
Attest the actual provider metadata before accepting a lane and again at its
final report. Exact named-model constraints do not degrade: a fallback creates
a different Stack candidate and requires the applicable Owner/review boundary.

For a large exact-digest review, also compile a derived evidence-aware review
graph with `stacker_review_graph.py build`. The graph must bind the exact
subject digest, Fact Packet producer, artifact index, role-specific evidence
slices, direct-recheck obligations, dependencies, and concurrency groups.
Share deterministic facts, not model verdicts. Mechanical slices require one
cross-invariant champion synthesis; Fable remains downstream of the completed
triad. ARVIS execution supervision runs dependency-free nodes in bounded
parallel waves. The Stacker graph grants no Authority and creates no canonical
state or parallel lifecycle.

Aggregate lane watchdogs with `stacker_review_graph.py metrics`. Treat the
receipt as cost telemetry only: zero findings never proves review quality or a
fast path without later escape evidence.

`aswarm` and `arvis swarm` are installed transports for route explanation. A route, provider, model, or mode descriptor alone is not Stack Authority, proof, or Done.
