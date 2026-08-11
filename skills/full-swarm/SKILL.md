---
name: full-swarm
description: Full Swarm execution protocol for highest-performance coding and planning work. Use when the user asks for "full swarm", "full swarm mode", "fsm", "best model swarm", "최신모델 최대 활용", dynamically selected Codex/GPT/Claude/Fable/Opus/Sonnet builders or judges, parallel subagents, independent evaluators, or rubric-based PM approval before integration. FSM is not equal model balancing; its goal is best possible output by routing each role to the best-performing available AI, while aggressively trying the newest usable models as challenger lanes according to the persistent model league and recent project feedback. Best for large, risky, multi-file, architecture, auth, billing, data, UI-flow, migration, or launch-critical work. For Codex/GPT-heavy swarms triggered by "cdfsm", use the cdfsm skill.
---

# Full Swarm

## Portable Path Resolution

Resolve every relative path in this skill from the directory containing this
`SKILL.md`, never from the user's project working directory. For example,
`../claude-full-swarm/scripts/stacker_claude_lane.py` is the sibling skill's
script inside the installed Oh My GOAT plugin.

## Operating Model

Use Full Swarm only when the user explicitly wants parallel agents or the task is large enough to justify it. The main agent is the PM, architect, integrator, and final judge. Builders produce work. Evaluators stress-test the work. Verifiers run tests and user-flow checks.

FSM does not mean "use every model equally." FSM means optimize for the best possible result using the available AI portfolio. Route each role by persistent model league, recent project feedback, task type, and current harness availability. Codex/GPT, Claude, Opus, Sonnet, and other runners may all be used, but each lane is assigned because it is expected to improve the result, not for symmetry.

FSM should also maximize useful latest-model exposure. When a new or newest available model/effort is callable, include it as a challenger lane in non-trivial FSM runs unless it is unavailable, recently failed, or unsafe for the task. The newest lane does not automatically win, but it should be tested often enough that the model league stays current.

For code-heavy work, the current default hypothesis is that Codex/GPT is often strongest for implementation review, verifier work, contract tests, migrations, API boundaries, and final semantic gates. Treat this as a hypothesis to confirm against the model league and current evidence, not as a permanent law. Use Claude/Opus/Sonnet where the scorecard shows they perform better: broad implementation, exhaustive option generation, UI alternatives, long-context critique, or second-opinion review.

Mode distinction:

- LTSM minimizes GPT tokens; Claude workers do most work and GPT reads compact summaries.
- CFSM maximizes Claude parallel work while GPT PM performs semantic hard verification and final commit.
- Full Swarm optimizes for the best possible output by routing each worker role to the best-performing available model/effort from the model league and by aggressively testing newest usable models as challenger lanes.
- CDFSM maximizes Codex/GPT model usage, including the strongest currently attested high-reasoning escalation lane when available; use the `cdfsm` skill for that profile.
- FCFSM, in which Fable visibly owns the high-level gate or swarm, remains an explicit mode. A bounded Fable advisory lane may also be selected automatically by Stacker's installed quota-paced Owner policy when fresh local quota evidence makes the requested high-leverage role eligible. This does not authorize implementation loops, invented extra work, or silent substitution for an exact Fable gate.

Default roles:

- Stacker-selected PM champion: define intent, scorecard, ownership, gates, final approval, and escalation; bind the actual model and effort at runtime.
- Primary builder: choose the model/effort with the best recent implementation score for this repo, file type, and task class. Add a newest-model challenger builder when scope can be isolated safely.
- Skeptic judge: choose the model that most reliably catches boundary, product, architecture, and long-horizon risk, even if it writes slower code.
- Verifier: choose the model/tooling lane with strongest evidence discipline for tests, type checks, browser checks, migrations, or smoke checks. Verifier is read-only unless PM explicitly asks for a fix.
- Summarizer: choose the cheapest/fastest model that preserves blockers, risks, changed files, and PM inspection targets without losing meaning.
- Cost-effective Codex worker: when the harness exposes a Codex Spark-class lane such as `GPT-5.3-Codex-Spark`, use it for proofable code-shaped work: small patches, tests, fixtures, grep/file_exists checks, CLI smoke, proof criteria generation, log triage, and receipt cleanup. Do not use it as final Done approver, architecture/product semantics owner, security/billing/secrets gate, public-claim judge, or high-impact verifier authority.
- Latest-model challenger: for important work, include at least one newest available model/effort as writer, reviewer, or skeptic in an isolated or read-only lane, then score it.

Do not let a builder approve its own work. Do not merge or accept work until it passes PM hard gates.

## Swarm PM Contract

This PM/Advisor contract applies to every `*fsm` variant, not only Fable-gated modes.

The PM/Advisor does:

- requirement analysis, owner-intent restatement, scope and non-goal definition;
- worker brief writing with context, files/modules, known traps, acceptance criteria, and verification commands;
- architecture/proof-gate decisions and stop conditions;
- diff/evidence/test inspection after workers finish;
- final approval, rejection, or correction brief.

Workers do:

- implementation, tests, mechanical refactors, retries, and routine debugging;
- isolated/chunked exploration under assigned ownership;
- evidence reports for PM/verifier inspection.

Boundaries:

- Worker "done" is not approval.
- Model choice is not proof.
- PM/advisor/verifier must inspect evidence before Done.
- Fable-gated modes and quota-paced Fable advisory lanes are high-cost specializations of the same contract: spend Fable tokens on intent, strategy, architecture, UX judgment, and final synthesis, not deterministic checks or implementation loops.

## Workflow

1. Lock a mission packet before implementation:

```text
Objective:
User intent:
Non-goals:
Allowed files/modules:
Forbidden scope:
Acceptance criteria:
Hard gates:
Verification commands:
Rollback risk:
Session name:
Session lifecycle: HOT keep-alive / WARM handoff / COLD close conditions
Report format:
```

2. Start with `git status --short` and create a rollback tag unless the task is read-only. Use session names shaped like `<mode>-<project>-<area>-<job>-<MMDD-HHMM>`.

3. Choose the swarm size:

```text
Small: PM only, no swarm.
Medium: PM + 1 builder + 1 skeptic.
Full: PM + builder(s) + skeptic + verifier + optional summarizer.
Critical: Full + current role champion baseline + newest attested frontier
challenger at the resolver-selected effort before final approval.
```

4. Run model/provider preflight before dispatch. Check provider registry order, auth/login status, recent runtime attempt health, model league availability, and the local normalized quota snapshot when available. Treat hard quota, usage limit, rate limit, and provider unavailable states as current-run exclusions; route to the next best candidate instead of blind retrying. Quota data may broaden Fable eligibility only while fresh; it never proves model quality. Record compact selected/excluded labels and reasons, never raw usage logs, tokens, credentials, or private provider account details.

5. Choose model lanes from the model league. Route by recent evidence: intent match, scope control, tests, PM correction count, runtime/cost, and task class. A champion is the baseline, not a monopoly: for high/critical review, `FRONTIER_INTAKE_REQUIRED` means the newest attested unscored candidate must also run in a read-only or isolated lane before final synthesis. Coalesce one candidate across compatible roles when one prompt can evaluate them honestly. If the project league says Codex/GPT is winning code review, use it there. If Claude/Opus/Sonnet is winning UI exploration or long-horizon critique, use it there. Promote any model only after it beats the current role default.

6. Split ownership. Each builder must have a disjoint write set. If two agents need the same file, one owns the file and the other reviews only.

7. Launch agents with concrete prompts. For Codex-native agents, use worker/explorer/verifier/reviewer roles where available. For external Claude/Opus/Sonnet, use tmux/cmux/Claude Code or the user's available runner. Do not assume a named model is callable unless the harness exposes it.

8. Monitor without duplicating work. While agents run, PM prepares scorecards, reviews architecture, or handles non-overlapping integration tasks.

9. Recover transient worker failures before judging the lane. `API Error: Connection closed mid-response`, stream closed, network reset, timeout, provider 5xx, or partial output without the required report means: capture pane output, mark `interrupted_transient`, retry once in the same pane, then spawn a replacement pane with the same mission/report path, then switch model/effort/provider if available. Explicit hard quota/rate-limit errors require backoff or fallback instead of blind retry loops. Only after recovery attempts fail may the PM mark the lane weak/fail or take over, and the scorecard must record the attempts.

10. Evaluate before integration. Read worker self-reports as evidence, not proof. Judges must inspect the diff, tests, and requirements.

11. Integrate narrowly. PM resolves conflicts, applies final fixes, runs verification, and reports final status.

## Session Lifecycle

Use the same HOT/WARM/COLD lifecycle as CFSM for every FSM run. A live agent session is working memory, not durable memory.

- HOT / keep alive: same mission continues soon, workers are active, a checkpoint has not arrived, expensive context is loaded for immediate follow-up, or reports are not durable yet.
- WARM / park with handoff: the same mission is likely to resume within about 24 hours, all panes/agents are idle or safely read-only, durable artifacts are written, the next prompt is ready, and `held_until` is recorded.
- COLD / close/archive: the mission is done, the user's goal changes, high-cost lanes are no longer needed, panes are stale, there is safety/cost risk, or no near-term continuation is expected.

PM-designated sessions are pinned project control planes. Any session or pane named/titled/role-mapped as `*-pm`, `fsm-<project>-pm`, `cfsm-<project>-pm`, `cdfsm-<project>-pm`, `fcfsm-<project>-pm`, or `fcdfsm-<project>-pm` stays WARM/HOT by default. Do not kill, cleanup, or COLD-close it unless the owner explicitly approves or a concrete safety/cost reason is written.

Before WARM or COLD, write `.swarm/<run>/mission.md`, `pane-map.md` or agent map, compact worker reports, `model-scorecard.md` for meaningful lanes, `final-summary.md`, `next-goal.md`, and `session-lifecycle.md`. On resume, rebuild context from those files first; treat held pane memory as stale unless the mission is unchanged.

## Model League Routing

Before a non-trivial FSM run, read the persistent model league when available:

```text
~/.codex/swarm/model-league.md
~/.codex/swarm/projects/<project>-model-league.md
```

Use the project-specific file first, then the global file. If no scorecard exists for the exact task type, run one newest usable challenger lane plus one known-good baseline lane and record the result.

For Stacker/reviewer graphs, use `highest_suitable_first`, not a static model
version list. Bind each lens to a role/capability and risk class, rank current
candidates by the project Model League plus provider/harness health, and default
high-impact review to the strongest suitable role champion. When comparable
evidence is tied or absent, prefer the current runtime's newest moving alias at
the highest useful effort. Selecting an older or cheaper lane requires a
recorded role-fit, availability, latency, cost, or explicit Owner-policy reason.

Requested model is not actual model. Launch Claude-backed Stacker reviews with
`../claude-full-swarm/scripts/stacker_claude_lane.py`.
The runner checks stream metadata at the first model-bearing event and again at
completion. It terminates an actual-model mismatch or fallback before accepting
or continuing the review, records a runtime-health exclusion, and never retries
automatically. It must also perform a non-interactive auth preflight, disable
child-agent/MCP/browser routes, and publish create-only lane evidence. Never
open an interactive login browser from an autonomous lane; classify auth
failure and stop. Use `claude_lane_attest.py` for persisted interactive sessions.
If a moving alias mismatches a previously attested exact model, do not retry the
full review. The next resolver step may run one small exact-model revalidation
using that dynamically derived full model ID. If it passes, launch the costly
lane by that exact ID; otherwise choose the next healthy role candidate. This is
runtime-derived routing, not a version hardcode.
Pane titles and worker prose are not provenance. A named-model requirement is a
hard predicate: a fallback may be separately useful advisory evidence, but it
cannot inherit the named lane's identity or close that review gate.

Before launching a Claude-backed Stacker lane, run
`../claude-full-swarm/scripts/stacker_model_resolve.py`
with the project and lens role. Pass its returned selector, expected actual
model when present, family pattern, effort, and selection basis to the runner.
Never launch a costly raw `claude --print` review or copy a prior run's resolved
version into the next route.

At the start of any high-impact provider-neutral Stacker graph, refresh the
derived discovery state with `provider_model_discover.py --write-state`, then
run `stacker_stack_resolve.py` for the required lenses. Discovery triggers are
catalog/model additions or removals, alias changes, metadata changes, and
harness-version changes. Treat `FRONTIER_INTAKE_REQUIRED` as a hard completion
predicate for that high-impact graph: keep the proven champion as baseline and
actually run the returned `required_frontier_intake_lanes`. Newly seen frontier
models receive bounded read-only or isolated intake lanes; discovery alone
never promotes them. Promotion requires actual-model attestation plus a
comparable Model League score. Keep a provider-diverse challenger for
high-impact review when one is eligible.
Fold successful provider attestation outputs back into discovery state. If a
moving alias resolves to a new actual model, treat it as a new frontier intake
candidate; do not transfer the predecessor's role score automatically.

### Quota-paced Fable routing

Claude Code's local status-line hook writes a non-canonical normalized snapshot
to `~/.codex/swarm/provider-quota-state.json`. The hook reads only the JSON that
Claude Code sends to status-line stdin; it performs no login, browser action,
provider call, token-spending probe, or Authority effect. Stacker reads that
snapshot with `stacker_stack_resolve.py --fable-routing auto` (the default).

Route Fable by judgment value, not by a blanket model default:

```text
exact even when quota is unknown: named_advisor, fable_final
core when fresh quota is on pace: intent_gap, strategy_planner, correction_architect
expanded only with fresh Fable-scoped surplus: ux_product, orchestrator
never quota-driven: mechanical, atomicity, deterministic checks, bulk retrieval,
                    transcript compaction, implementation loops, duplicate lanes
```

Official provider-wide 5h/7d quota fields can justify only the core tier. The
expanded tier requires a fresh model-scoped Fable observation. A missing or
stale snapshot permits exact Fable roles only; it must not trigger automatic
expansion. A provider-wide quota guard at conserve/reserve suppresses automatic
core/expanded use even when a Fable-specific bucket looks abundant.

`--fable-routing force` is an explicit Owner-policy override for the configured
high-leverage role set; it is not permission to create meaningless work. The
legacy `--allow-fable` flag is an alias for `force`. `--fable-routing off`
disables all Fable candidates. In every mode, the Model League still chooses the
role champion, discovery never promotes a model, and actual-model attestation is
required. An exact `fable_final` lane remains downstream of a completed triad;
Opus or another fallback may create separate advisory evidence but cannot close
that exact gate.

Use `max` as the default ceiling for frontier intake and high-impact review.
Use `ultra` only with explicit run-level opt-in, a healthy runtime observation,
and a recorded reason that extra latency/token use is justified. On 401/403,
429, quota, or repeated transport fallback, stop blind retries, record a
normalized runtime exclusion for that selector/effort, fall back to `max` or
the next healthy lane, and do not score the incident as model-quality evidence.
Record and clear those non-canonical exclusions with
`scripts/stacker_runtime_health.py exclude|clear`; a successful bounded smoke
and actual-model attestation are required before clearing an exclusion.

Launch Codex-backed Stacker lanes through
`scripts/stacker_codex_lane.py`, not an ad hoc blocking subprocess wrapper.
The runner overrides ambient agent limits per invocation and enforces a
watchdog over the persisted root session tree. The hard ultra envelope is 100
total sessions, maximum depth 8, 32 concurrent agents, and a two-hour
wall-clock backstop. These bounds preserve the observed useful ultra range
while separating it from recursive runaway. The runner must terminate the
exact process group on the first session-count, depth, time, authentication,
quota, or rate-limit violation, preserve its receipt, and never retry
automatically. Bounds are configurable only within the runner's hard ceiling;
do not inherit an ambient 1000-slot setting.

The runner also performs a schema-compatibility preflight on the local Codex
model catalog. It may fill a newly required catalog field whose omission would
otherwise cause repeated cache parse/refresh errors, but it must preserve every
model slug, priority, capability list, and routing score. Record before/after
digests, changed fields, and a recoverable content-addressed backup in the
watchdog policy. This is transport compatibility, never model promotion or a
static preferred-model hardcode.

When a read-only review must replay disposable rehearsals, create a fresh
non-symlink directory under `/private/tmp` or `/tmp` and pass it through
`--isolated-review-scratch`. The runner then makes only that directory the
workspace-write root and `TMPDIR`; keep the governed repository outside it and
read-only. Store every lane output inside the same scratch directory. Do not
use `danger-full-access` to solve reviewer scratch requirements.

Before a large exact-digest review, run the exact read-only verifier once with
`scripts/stacker_review_graph.py capture-verifier`. Its compact receipt binds
the subject, source-descriptor bytes, an unlinked private O_EXCL launcher
capture, empty parent environment, argv, return code, selected result fields,
and the full raw stdout/stderr by content address. Generic
`capture-launcher` receipts use the same executed-byte transport. A NONPASS
receipt stops the model graph; do not spend review lanes on a subject that is
already stale. A PASS receipt is a shared deterministic fact, not a model
verdict or continuous-currentness claim.

Then compile an evidence-aware review graph with
`scripts/stacker_review_graph.py build --verifier-receipt ...`. Bind the exact
subject digest and all allowed evidence roots. Reuse its deterministic Fact
Packet for hashes, schemas, custody, counts, compact verifier status, and raw
locators; never reuse a model verdict. Give each lens only its role packet plus
direct access to the exact raw subject and artifact index. Require seeded spot
rechecks for shared facts and exact raw recomputation whenever a contradiction
appears. Slices must not rerun the verifier or enumerate/read the whole tree by
default. Opening evidence beyond the seeded samples requires a recorded
contradiction or escalation reason. Cap individual command output so a compact
review is not defeated by dumping a large subject or runtime projection.

Pass the structured-output review schema to `build` with `--review-schema`.
Before any model starts, Stacker must prove that
`properties.subject_sha256.const` equals the graph's exact subject digest and
bind the schema identity into both the Fact Packet and review graph. A stale or
malformed schema is a hard preflight rejection. Stop all not-yet-completed
lanes, preserve any partial outputs as invalid provenance, and never count
their verdicts. Patch the schema, rebuild the graph, and start fresh lanes; an
Owner decision or review result for the predecessor digest never transfers.

Dispatch every node immediately when its own declared dependencies are
satisfied, under provider and resource caps. Topological levels are diagnostic
only; a global level/wave barrier is forbidden. In particular, launch the
Mechanical champion as soon as all Mechanical slices finish even if Semantic
or Atomicity is still running. Mechanical risk slices may run in parallel, but
the Mechanical champion must synthesize cross-invariant interactions before
triad completion. Semantic and Atomicity remain independent lenses. Fable must
wait for the completed triad; fresh currentness, PM projection, Owner decision,
LIVE Host, and poststate audit retain their causal order. Stacker compiles this
derived graph; ARVIS execution supervision runs it. The graph is not Authority
or canonical state.
Use the same highest-suitable model across scoped slices when appropriate, but
do not default every slice to maximum effort. Prefer scoped `high` and escalate
to `max` on ambiguity or a MATERIAL candidate; keep critical Atomicity and the
cross-invariant Mechanical champion at `max`. This is adaptive effort, not a
hardcoded model identity.

After the champion, Semantic, and Atomicity lanes finish, run
`scripts/stacker_review_graph.py triad-gate`. It verifies the exact digest and
watchdog provenance of all three results. Any `MODIFY`, `HOLD`, MATERIAL
finding, retry, fallback, or non-PASS watchdog produces `STOP_BEFORE_FABLE`;
do not spend a Fable lane on that digest. `FABLE_ELIGIBLE` is only a dependency
join receipt, not review-policy completion or Owner readiness.

After review, run `scripts/stacker_review_graph.py metrics` over the lane
receipts. Record serial cost, estimated parallel wall time, model/effort,
retry/fallback, prompt/event sizes, provider-reported token/cache/cost fields,
and MATERIAL fingerprints. Compare wall-time reduction against total compute;
a faster graph that spends more aggregate reasoning is only partially
optimized. Do not infer a fast path from zero findings. Later escaped blockers
and actual per-lane evidence bytes read are required before automatic cost
routing is justified.

Role routing policy:

```text
writer: best recent implementation score for repo + file type + task class.
reviewer: best recent bug-finding and semantic correctness score.
verifier: best evidence discipline and command accuracy.
architect/skeptic: best boundary, product, data, and long-horizon risk detection.
ui/product reviewer: best match to user workflow and visual/product intent.
intent_gap: preserve Owner intent, Success Contract meaning, and decision-relevant Gap.
strategy_planner: choose and critique the bounded plan or roadmap.
correction_architect: reason about root cause, recovery, and minimal successor design.
fable_final: exact downstream Fable synthesis after the completed triad.
ux_product: premium product/workflow judgment only when quota policy makes it eligible.
orchestrator: premium cross-lane orchestration judgment only under Fable-scoped surplus.
summarizer: fastest/cheapest model that preserves blockers and PM inspection targets.
codex_spark_worker: cheapest reliable Codex Spark-class lane for deterministic coding/proof chores; escalate to stronger Codex/GPT or Advisor when semantics/risk rise.
```

Aggressive champion utilization:

- Do not keep splitting work evenly once the model league identifies a role champion.
- A role champion is a model/effort with score >= 88 and `win`/strong `usable` in the latest comparable run, two wins in the latest three comparable runs, or clearly lower PM correction count than the baseline.
- For matching tasks, assign the champion the main lane and spend more of the swarm budget there. Give challengers smaller read-only or isolated lanes until they beat the champion.
- Promote a newest challenger to champion immediately for a role after two strong comparable wins, or one decisive win on a task class where the baseline was weak.
- Keep independent review for risky changes; a champion writer should not be its own final verifier.
- Do not demote a champion for transient connection/provider failures. Demote for semantic evidence: drift, unsafe commands, invented evidence, repeated PM correction, or two weak comparable runs.

At shutdown, update `.swarm/<run>/model-scorecard.md` and append compact useful results to the persistent project league. Prefer `../claude-full-swarm/scripts/model_league_record.py` so timestamp, mode, score, CSV/JSON, and the local dashboard refresh stay consistent. Record exact model/effort when known, command used, role, task type, elapsed time, PM corrections, scope drift, evidence quality, and final verdict.

## Latest-Model Maximization

FSM should keep the model league fresh. For substantial runs:

- Try the newest available GPT/Codex/Claude/Opus/Sonnet candidate when the harness exposes it.
- Put unproven latest models in read-only review, isolated worktree, or disjoint file ownership lanes first.
- Promote the latest model quickly if it beats the baseline on user-intent match, correctness, scope control, test evidence, PM correction count, and elapsed time.
- Demote or mark unavailable models that fail to start, drift scope, invent evidence, or require repeated PM correction.
- Do not waste lanes on a newest model that has recently failed in the same environment unless the CLI/version changed or the user explicitly asks to retest.
- Do not demote a model for one transient connection failure. Score semantic/model quality only after the recovery protocol has had a fair attempt to get a complete report.
- Once a newest model becomes the role champion, use it heavily for that role in the next matching run instead of keeping it as a token-light challenger.

## Hard Gates

Reject the result if any gate fails:

- User intent and acceptance criteria are not satisfied.
- Existing tests, type checks, or required smoke checks fail.
- The diff exceeds the assigned ownership without PM approval.
- The implementation invents a new architecture where a local pattern exists.
- Security, auth, billing, data loss, permissions, or migration risk is unresolved.
- The output "works" but does not match the user's intended workflow.

## Scorecard

Create the scorecard before implementation. Keep PASS items terse. Require evidence for WEAK or FAIL.

```text
Hard gates: PASS / FAIL

Quality score, after hard gates pass:
- Correctness: 30
- Edge cases: 20
- Architecture fit: 20
- Scope control/minimal diff: 10
- Test coverage: 10
- Maintainability: 10

Verdict:
- APPROVE
- REVISE with blocking issues
- REJECT and escalate
```

For detailed evaluator prompts, read `references/evaluation-rubric.md`.

## Prompt Patterns

Builder prompt:

```text
You are a worker in a parallel swarm. You are not alone in the codebase.
Do not revert edits made by others. Own only: <files/modules>.
Implement: <objective>.
Respect non-goals: <non-goals>.
Before finishing, run: <verification>.
Final report must include changed files, tests run, failures, risks, and open questions.
```

Evaluator prompt:

```text
You are an evaluator, not the implementer.
Use this scorecard: <scorecard>.
Find blocking issues first. Do not praise the implementation.
For every WEAK or FAIL, include file/line when possible, reproduction, impact, and required fix.
Return PASS / WEAK / FAIL per gate plus a final APPROVE / REVISE / REJECT verdict.
```

Verifier prompt:

```text
Verify the implementation against the acceptance criteria.
Run the specified checks. Add no feature work unless the PM asks.
Report command output summaries, failures, and whether the user workflow is actually satisfied.
```

Worker final report format:

```text
verdict: win / usable / weak / fail / blocked_success
role:
model_effort:
edit_permission:
owned_files:
changed_files:
tests_run:
pass_fail:
blockers:
risks:
off_scope_changes:
pm_must_inspect:
non_goals_confirmed:
next:
```

PM final gate:

```text
git status --short
git diff --stat
git diff --check
inspect key diffs directly
run required tests/checks
check staged files
PM-only commit or explicit no-commit decision
record HOT/WARM/COLD in session-lifecycle.md and kill, park, or keep alive accordingly
```

## Escalation

Escalate to the strongest currently attested high-reasoning champion for direct review or implementation when:

- Opus/Claude misses intent after one or two correction loops.
- The same test or blocker fails twice.
- A worker keeps widening scope.
- The change touches auth, billing, secrets, permissions, migrations, or destructive writes.
- The PM cannot determine correctness from summaries and diffs alone.

Escalation means the PM reads the relevant code and either writes the final patch or gives a precise revision order. It does not mean starting the whole swarm again.

Recommend explicit FCFSM escalation when Fable should own the visible PM/gate or when the installed quota-paced advisory policy cannot resolve a high-value judgment problem with acceptable confidence. The PM must state the blocker, proposed Fable role, expected output or verdict, and stop condition. Bounded quota-paced advisory use does not remove this explicit boundary for FCFSM ownership.
