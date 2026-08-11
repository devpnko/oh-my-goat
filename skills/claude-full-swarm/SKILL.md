---
name: claude-full-swarm
description: Claude Full Swarm Mode execution protocol, currently the preferred/default swarm mode. Use when the user asks for "cfsm", "/cfsm", "CFSM", "cfsm으로 진행", "claude full swarm mode", "cfs", "/cfs", "claude full swarm", "Claude Full Swarm", "claude swarm", "use Claude as much as possible", "Claude workers", "parallel Claude", "Claude Code agent teams", or parallel Claude workers supervised by GPT PM. For direct "ltsm", "/ltsm", "low-token swarm mode", "ccc", or "cmux panes" requests, use the ltsm alias skill first.
---

# Claude Full Swarm Mode

## Portable Path Resolution

Resolve every relative path in this skill from the directory containing this
`SKILL.md`, never from the user's project working directory. Scripts referenced
as `scripts/...` live inside this installed skill directory.

## Operating Model

Claude Full Swarm Mode, abbreviated CFSM, is the default Claude-heavy full swarm mode. It is a cost-heavy, time-saving execution mode: use Claude accounts, Claude Code, cmux/tmux panes, and Claude agent teams aggressively; reserve the Stacker-selected cross-provider PM champion for judgment, routing, acceptance criteria, and final approval.

Default roles:

- Stacker-selected PM champion: mission packet, scorecard, ownership split, high-level review, and final judgment, with actual-model attestation required.
- Claude implementation candidate: choose from the model league scorecard for the current repo/task type; use a newest-available coding candidate only as a trial lane until it earns the writer role.
- Claude reasoning candidate: choose from the model league scorecard for architecture, long-horizon fixes, high-risk review, and product-direction skepticism; use newest-available reasoning models as trial lanes until proven.
- Claude Sonnet max: still a strong default for implementation, refactor, test writing, UI/user-flow verification, and fast diff repair when it has the best local score.
- Claude Opus max: still a strong default for architecture, long-horizon reasoning, high-risk review, and difficult blocker analysis when it has the best local score.
- Claude Fable/Fable 5: never a blanket CFSM default or mechanical worker. Use it for explicit FCFSM ownership, exact named gates, or bounded high-value intent/strategy/architecture/UX/final-synthesis roles made eligible by the installed fresh quota-paced Stacker policy.
- Codex Spark/Codex worker: cost-effective coding support for proofable patches, tests, fixtures, grep/file_exists checks, CLI smoke, proof criteria generation, log triage, receipt cleanup, counter-review, and diff attack. Use `GPT-5.3-Codex-Spark` only when the current harness exposes that provider/model; otherwise use the available Codex Spark-class lane recorded by model league.
- Claude summarizer: compress long pane outputs before GPT reads them.

The PM should not deep-read every worker transcript. Ask Claude workers to write short reports, then inspect only diffs, test output, blockers, and disputed files.

### Cost-Effective Codex Worker Policy

This policy applies to CFSM, LTSM, Full Swarm, CDFSM, FCFSM, FCDFSM, and ARVIS `*fsm` routes.

- Codex Spark-class workers are first-class cheap/default coding lanes for deterministic, code-shaped, proofable work.
- Use them for small patches, test/fixture generation, command-backed verifier prep, grep/file_exists checks, CLI smoke, log triage, proof criteria generation, and receipt cleanup.
- Do not use them as final Done approver, architecture/product semantics owner, security/billing/secrets/production-write gate, public-claim judge, or high-impact verifier authority.
- In CDFSM/FCDFSM they are primary cheap/default worker candidates before escalating to stronger Codex/GPT high/xhigh lanes.
- In CFSM/LTSM/FCFSM they are auxiliary proof/code-support lanes while Claude/Opus/Sonnet remains the main worker pool.
- In Full Swarm they are routed by model league and should start isolated or read-only unless already a role champion.
- Model choice is routing context, not proof. Proof still comes from tests, artifacts, observed hooks, verifier evidence, or owner override.

### Swarm PM Contract

This contract applies to CFSM, LTSM, FSM, CDFSM, FCFSM, FCDFSM, and any ARVIS `*fsm` route:

- PM/Advisor analyzes owner intent, scope, non-goals, and risk.
- PM/Advisor writes the worker brief with context, owned files, traps, acceptance criteria, and verification commands.
- Workers do implementation, tests, retries, routine debugging, and evidence reports.
- Worker "done" is not approval.
- PM/Advisor/verifier inspects diff, evidence, tests, and receipts before Done.
- Fable-gated modes are the high-cost specialization of this same contract; Fable should spend tokens on judgment, not implementation loops.

### Model Preflight Re-routing State Machine

This state machine applies to every FSM-like route before launch and whenever a
planned worker/advisor lane becomes unavailable.

- A failed preflight is a routing event, not a task failure by itself.
- Record `lane_unavailable` with the planned model/provider, role, surface
  requirement, and reason: `quota_exhausted`, `rate_limited`, `auth_unavailable`,
  `usage_credit_required`, `visible_pane_missing`, `cost_limit`, `speed_limit`,
  or `provider_unavailable`.
- Immediately re-rank substitutes by role fit, model-league evidence,
  availability, cost, risk, required visibility, and owner route contract.
- Use bounded cascade only. Do not loop forever: declare `fallback_exhausted`
  after the run's `max_hops` or after no candidate can preserve the role
  contract.
- A substitute must rerun the relevant proof gates. Never inherit proof from
  the unavailable lane.
- Mark `fallback_success` only when the substitute preserves the role contract,
  reruns and passes the proof gates, and `confidence_delta` is below the
  material-change threshold.
- Mark `override_fallback` when the substitute can proceed only with material
  confidence/cost/risk degradation or an owner-approved route-contract change.
- Mark `owner_hold` when a named visible Advisor route is unavailable and the
  route contract forbids silent substitution. FCFSM/FCDFSM visible Fable Advisor
  lanes are the hard-stop example: request owner override or stop.

Required routing states:

```text
lane_planned
lane_unavailable
substitute_selected
gates_revalidated
fallback_success
override_fallback
fallback_exhausted
owner_hold
```

Every fallback record must include:

```text
original_model:
unavailable_reason:
substitute_model:
substitution_scope:
confidence_delta:
proof_gates:
state:
model_league_note:
```

Worker count and token policy:

- PM/control-plane sessions are persistent by default; worker panes are ephemeral by default. Keep `*-pm`, `cfsm-<project>-pm`, `fcfsm-<project>-pm`, and equivalent PM panes WARM/HOT, but classify worker panes COLD after they write their report/evidence and the PM has captured the result.
- Do not pre-spawn workers just because a mode is named `full swarm`. Start the smallest useful wave for the current packet, then add lanes only when the PM has a distinct role, ownership boundary, report path, and proof gate for each lane.
- Medium CFSM default is 2-4 active worker panes, not a standing 5-pane team. Scale to 5-8 only when machine pressure is green, panes are tmux-headless or lightly observed, and ownership is independent. Treat 8-16 as an explicit stress/overnight/deep-run target, not the normal default.
- Normal CFSM is not Fable-owned. FCFSM remains the explicit mode for giving Fable visible PM/gate ownership. The installed Stacker Owner policy may nevertheless assign a bounded Fable advisory lane to an eligible high-leverage role when its local quota snapshot is fresh and on pace; this does not convert the run into FCFSM or authorize Fable implementation loops.
- If quota-aware Stacker does not make a Fable lane eligible but a non-Fable run is blocked, looping, disputed, or touching high-stakes architecture/safety/capital/trust decisions, surface an explicit FCFSM escalation with its reason and stop condition. Do not silently convert ordinary CFSM into FCFSM.
- When the user asks to maximize CFSM or says to spend Claude tokens heavily, switch to the **Claude-exhaustive profile**: assume Claude token spend is the intended resource, wait long enough for workers to produce deeper artifacts, and keep GPT PM work to mission design, boundary enforcement, report triage, and final hard gates. Do not prematurely replace this with PM manual implementation unless a worker hits a concrete stop condition after the declared checkpoint.
- Long silent work is normal for max-effort Claude lanes, especially Opus/Sonnet model-intake, architecture, codebase reading, UI review, and verifier lanes. For Fable, use the FCFSM patience/cost rules instead of normal CFSM defaults.
- When the PM invokes session-level parallel processing in CFSM, this means tmux-visible pane fan-out by default: create or reuse one named tmux session, split panes, launch interactive Claude workers, inject mission packets, and keep the pane map current. `cmux` is allowed as a wrapper/helper only when it preserves visible panes. Do not satisfy CFSM parallelism with hidden API proxy calls, background-only runners, or one-shot `claude --print` workers unless the user explicitly asks for that. Keep cmux as a control-room view; do not keep every worker live-tailed in cmux after its checkpoint.
- Do not spawn extra workers just to create noise. Each worker needs a distinct role, file/surface boundary, report path, and acceptance gate.
- GPT PM should read compact worker reports, model scorecards, key diffs, and hard gate outputs rather than full transcripts.

### Claude-Exhaustive Profile

Use this profile when the user explicitly wants CFSM to spend Claude effort generously, wait longer, or have GPT do less hands-on building.

Goal:

- Burn Claude thinking/building/verification capacity to make the target artifact better.
- GPT PM should not be the first implementer or first reviewer unless a worker has actually stalled, violated scope, or hit a hard blocker.
- Claude workers should create the graphs, UI alternatives, contracts, tests, screenshots, and critique packets the user asked for; GPT PM should judge, route, and final-check.

Default worker split:

- `writer`: owns the allowed implementation files only.
- `alt-designer` or `variant-builder`: creates alternatives or graph/layout variants in an isolated file/worktree when useful.
- `workflow-skeptic`: checks real user workflow and catches business logic errors.
- `visual-reviewer`: compares screenshots/reference images and UI density.
- `domain-math` or `ledger-reviewer`: checks calculations, source/settlement/stock/customer boundaries.
- `mechanical-verifier`: runs browser/tests/lint/diff-check and saves screenshots.
- `summarizer`: compresses all results into PM-ready blockers and inspect points.

Patience rules:

- Do not expect final output before T+10. T+10 is only a start/non-idle check.
- For artifact work, prefer T+20 to T+30 before asking for blockers unless all reports are already done.
- For UI/mockup/graph-heavy work, allow T+30 to T+45 for first useful drafts and visual critiques.
- For code plus tests, allow T+60 to T+90 when workers are active and within scope.
- If a worker is quiet but still reading/searching/testing/thinking inside Claude, wait until the checkpoint. Quiet is not failure.

### Active Worker Patience Contract

This contract applies to CFSM, LTSM, Full Swarm, CDFSM, and any FSM-like mode that uses visible Claude/Codex worker panes.

Classify a pane as `active` when it is doing any of these:

- reading files or tool output
- searching the repo
- running tests, builds, browsers, screenshots, or diagnostics
- composing a report or patch
- showing Claude thinking/spinner/status text
- waiting on a long command that is still running

For an `active` pane:

- Do not interrupt, checkpoint-force, replace, or demand a final report before the declared checkpoint.
- Do not treat "no report yet" as failure while the pane is visibly active.
- Do not let GPT PM implement the worker's task just because the worker is taking time.
- Use passive polling only: capture tails, update the pane map, and wait.
- At T+30, ask only for blockers if needed; do not require final artifacts from active workers.
- At T+60 to T+90, collect reports or ask for status, unless the mission declared a longer overnight checkpoint.

Stop or interrupt only for concrete stop conditions:

- idle prompt after prompt delivery or after a transient failure
- explicit blocker that needs PM/user decision
- off-scope work
- forbidden commands or unowned edits
- repeated failed loop
- unsafe production write, destructive command, credential request, or raw secret request
- explicit user instruction to stop or take over

If the PM interrupts an active worker too early:

- record it as `pm_orchestration_error` in the run summary and model scorecard
- resume or restart the worker if its lane still matters
- do not mark the model weak/fail because of the PM interruption
- do not use the interrupted partial output as approval until another worker or PM hard gate verifies it

### Transient Worker Failure Recovery

This rule applies to CFSM, LTSM, and any FSM-like swarm that uses visible Claude/Codex worker panes. A transient worker failure is not the same as model failure or task failure.

Treat these as recoverable transient failures first:

- `API Error: Connection closed mid-response`
- "response may be incomplete"
- stream closed / network reset / timeout / 5xx provider errors
- a pane returning to the prompt after partial output without writing its required report

Recovery protocol:

1. Capture the pane output into the run scratch area or pane map. Mark the worker `interrupted_transient`, not `fail`.
2. Retry once in the same pane with a compact continuation prompt: continue from the mission, do not redo completed reading, write the required report path first.
3. If the same pane fails again, spawn a fresh replacement pane with the same role, same ownership boundary, and same report path. Record it as retry attempt 2.
4. If replacement fails, switch model/effort/provider when available, or fall back to a different runner lane. Explicit hard quota/rate-limit errors should use backoff, model/provider fallback, or user-visible blocked status instead of blind retry loops.
5. Only after the recovery attempts fail may the PM mark that worker `weak` or `fail`, and the scorecard must say it was a worker recovery failure rather than a semantic model verdict.
6. PM takeover is allowed after recovery attempts or when the lane is non-critical and the PM can independently run the hard gates, but the final report must state that takeover happened because worker recovery failed.

Partial output is evidence, not approval. Do not accept a worker's incomplete answer as a review, verifier result, or final report until a replacement worker or the PM has checked it.

PM minimization rules:

- GPT PM should write the mission packet, ownership boundaries, and acceptance gates.
- GPT PM should monitor pane start, not narrate every worker thought.
- GPT PM should read reports first, then only inspect disputed diffs/screenshots/test output.
- GPT PM should patch manually only after one of these is true:
  - writer violates ownership or safety;
  - writer is idle or stuck past checkpoint after a concrete nudge;
  - user asks for immediate PM intervention;
  - final hard-gate failure is smaller than restarting the swarm.
- If PM patches manually, record why in the scorecard and do not treat the writer as a win.

Artifact expectations:

- For dashboard/admin/UI work, require workers to produce or verify actual screens, charts, tables, responsive behavior, and screenshots.
- For policy/settlement/stock/customer work, require at least one domain worker to attack the math and boundary assumptions.
- For graph-heavy requests, ask workers to propose multiple graph/table encodings before converging.
- For image-reference work, at least one worker must compare against the reference images and report concrete section-level gaps.
- For every substantial run, keep a next-goal backlog so Claude can continue with the next one-hour packet without GPT re-planning from scratch.

## Mode Profiles

Use the same orchestration machinery with different GPT involvement levels:

```text
LTSM = low-token mode. Claude workers do implementation, first-pass review, mechanical verification, and summarization. GPT PM defines the mission and performs compact release approval from summaries and staged files.
CFSM = Claude full swarm mode. Claude workers do parallel implementation/review/testing, and GPT PM also performs semantic hard verification, key diff inspection, and final commit.
FCFSM = Fable-gated Claude full swarm mode. Same visible pane orchestration as CFSM, but Fable owns a visible high-level gate or PM role and must be justified in the mission packet; this is distinct from one bounded quota-paced Fable advisory lane.
FCDFSM = Fable-gated Codex-dominant full swarm mode. Fable owns high-level PM/architecture/judgment, while GPT/Codex workers own most implementation and verification. Use when the user wants "Fable 설계 + GPT/Codex 개발" instead of Claude-heavy FCFSM.
Full Swarm = high-assurance mode. Multiple builders, reviewers, judges, or separate worktrees compete or cross-check; GPT PM applies stricter approval.
Solo GPT = use when the main task is product direction, architecture judgment, or another decision where delegation would add noise.
```

Verifier layers:

```text
Mechanical verifier: tests, build, lint, static contract checks, git diff --check, dry-run/rollback DB checks. Claude workers or scripts may run these.
Semantic hard verifier: user intent, workflow fit, scope drift, architecture boundary, production safety, and whether a blocked action is the correct result. CFSM requires GPT PM to do this.
Release approval: staging, commit, push/no-push, and final acceptance. Always GPT PM or the human user; never a worker.
```

In LTSM, Claude may own the first two layers as evidence collection, but GPT still owns compact release approval. In CFSM, GPT owns semantic hard verification directly.

## Hard Supervision Rules

CFSM workers are helpers, not approvers. Use these defaults unless the user explicitly overrides them:

1. In a shared worktree, assign at most one writer. All other workers are read-only reviewers, verifiers, or summarizers.
2. If more than one implementation worker is needed, create separate worktrees before letting them edit.
3. Read-only workers must not run: `git stash`, `git stash pop`, `git reset`, `git checkout`, `git restore`, `git clean`, `git add`, `git commit`, `apply_patch`, redirection writes, or scripts that rewrite tracked files.
4. Workers must not stage, commit, amend, rebase, push, or change branches. GPT PM owns all staging and commits.
5. Every worker prompt must include its ownership boundary, whether it may edit, forbidden commands, verification scope, and the exact report path.
6. If a worker violates ownership or read-only instructions, stop the pane, mark that model/run `weak` or `fail` in the scorecard, and do not use that worker as an approval signal.
7. Before launching workers in a dirty worktree, create a rollback branch/tag or document why no rollback is needed.
8. Before final commit, GPT PM must inspect `git diff --stat`, `git diff --staged --name-status`, relevant disputed diffs, and run the hard-gate commands directly.
9. Start every run with `git status --short` and a rollback tag named `<mode>-before-<project>-<area>-<job>-<YYYYMMDD-HHMM>` unless the task is explicitly read-only.
10. No worker starts without a mission packet that locks objective, success criteria, non-goals, allowed files, forbidden commands, verification commands, report path, and escalation conditions.
11. Production DB writes are forbidden without explicit user/PM approval. Prefer read-only inspect, preview, dry-run, or rollback fixtures for policy, settlement, customer, stock, and other official ledgers.
12. Distinguish success from blocked success. Some correct outcomes are publish blocked, unsafe rule rejected, actual settlement auto-confirmation denied, or custody mutation prevented.
13. If a worker changes files outside its owned allowlist, mark it fail, stop the pane, and reject the output until PM manually repairs or removes it.
14. A worker may not call its own output approved. Implementation worker and verifier must be different panes unless this is an LTSM trivial task.

## Model League and Convergence

CFSM is also a live model-evaluation loop. Do not assume one Claude model is always best. Do not assume the newest model is best for every role. Route work by observed performance and keep converging toward the model/effort pair that produces the least PM correction for the current project.

Default model experiment policy:

- Include at least one newest-available non-Fable Claude coding candidate in non-trivial coding CFSM runs unless unavailable or recently marked fail/unavailable.
- Keep known-good baselines such as Sonnet max and Opus max available when they have recent positive scores, because they provide continuity for scorecards.
- Use newest-available non-Fable reasoning models, Opus/max-effort workers, or other available Claude models for architecture, review, or hard product judgment when useful.
- Exclude Fable/Fable 5 from automatic *newest-model* intake in normal CFSM. Quota-paced high-leverage role eligibility is a separate policy: it may create a bounded Fable advisory/intake lane without promoting Fable or making the swarm FCFSM.
- Do not keep launching a candidate alias that failed to start in this environment. Record it as unavailable and re-test only when the CLI/version changes or the user asks.
- For high-value work, run a small A/B: one newest coding candidate implementation/review lane and one baseline or reasoning-model review/alternative lane, with disjoint ownership or read-only constraints.
- Do not let competing workers edit the same files at the same time unless they are in separate worktrees.
- GPT PM decides the winning output after inspecting diff, tests, scope control, and user-intent match.

Aggressive champion utilization:

- When a model/effort becomes the role champion for a project, use it aggressively for that role instead of continuing even-split experiments.
- A role champion is a model/effort with either: score >= 88 and `win`/strong `usable` in the latest comparable run, two wins in the latest three comparable runs, or clearly lower PM correction count than the baseline on the same task class.
- Allocate champion models to the highest-leverage panes first: primary writer, semantic verifier, skeptic, UI/product reviewer, or summarizer depending on the role it won.
- For important runs, give the champion the main lane and give challengers smaller read-only or isolated lanes. Do not make the champion re-prove itself from scratch every run.
- If a champion is available and the task matches its winning task class, prefer spending tokens on deeper champion work over adding weak or unproven extra lanes.
- Keep at least one different-model verifier or skeptic for high-risk work, even when one model dominates implementation. Good writers still need independent review.
- Demote a champion only after evidence: scope drift, invented evidence, unsafe command use, repeated PM correction, or two weak comparable runs. One transient connection failure does not demote it.

Role routing policy:

```text
writer: choose the model/effort with best recent implementation score for this repo and file type.
verifier: choose a different model or at least a different pane from the writer; prefer evidence discipline over creativity.
architect/skeptic: choose the model that catches boundary, product, and long-horizon risks, even if it writes slower code.
ui/surface reviewer: choose the model that best matches user workflow and visual/product intent.
db/security/ledger reviewer: choose the model with strongest caution and explicit command evidence.
summarizer: choose the cheapest/fastest model that preserves blockers, risks, changed files, and PM inspection targets.
```

Latest-model intake policy:

- When a new Claude model or effort level becomes available, add it as a candidate lane before making it the default.
- If the new model is Fable/Fable 5 or any Fable-class premium alias, discovery alone must not add it to normal CFSM candidate lanes or transfer predecessor scores. Route it through FCFSM, explicit model intake, or Stacker's fresh quota-paced high-leverage role policy; actual-model attestation and comparable scoring still apply.
- Prefer read-only review or isolated worktree trials for unproven new models.
- Promote a new model only after it beats the current role default on intent match, scope control, test evidence, PM correction count, and runtime/cost.
- Demote a new model immediately if it drifts scope, edits outside ownership, invents tests, or reports success without command evidence.
- Treat model aliases like "sonnet" and "opus" as role labels that may evolve; record the exact model/effort string observed in the worker report.
- Treat "fable" as a premium moving alias, never a blanket default. Launch it inside CFSM only for an explicit FCFSM contract, an exact named gate, or a role that the fresh quota-paced Stacker policy marked eligible.
- If a model alias appears in `claude --help` but fails at runtime, record `availability: unavailable` and the exact failure in the model league ledger. Do not keep using it in normal CFSM until revalidated.
- When an important non-Fable model is announced or locally observed, run a small intake loop within the next substantial CFSM: availability smoke, one read-only review lane, one scoped implementation or verifier lane, and one baseline comparison lane. Do not wait for a perfect benchmark before using the new model, but do not promote it without score evidence.
- If the new model is a Sonnet-class release such as Claude Sonnet 5, aggressively test it for writer, verifier, summarizer, and product/copy roles. Keep Opus or another strong reasoning model as the skeptic until Sonnet-class runs prove they catch the same blockers.
- Once a newest model wins a role, stop treating it as a tiny challenger for that role. Promote it to champion usage: primary lane for matching tasks, larger context budget, and first retry/replacement choice.
- If a newest model loses or is noisy, keep it in small read-only intake lanes until the CLI/model changes or new evidence justifies another trial.

Persistent model league ledger:

- Per-run scorecards live in `.swarm/<run>/model-scorecard.md`.
- Cross-session scorecards live outside the repo at:

```text
~/.codex/swarm/model-league.md
~/.codex/swarm/projects/<project>-model-league.md
```

- At CFSM startup, read the project model league if it exists and use it for role routing.
- At CFSM shutdown, append a compact scorecard entry for each model/role that did meaningful work. Prefer using `scripts/model_league_record.py` so timestamp, mode, score, and dashboard refresh stay consistent.
- The persistent scorecard should influence the next CFSM session, but it does not override PM judgment or current evidence.
- Every meaningful model entry must include a scalar `score_0_100` so the league can be plotted over time. Use the score only as routing memory, never as final approval.

Model score formula:

```text
score_0_100 =
  availability 10
  + intent_match 15
  + evidence_quality 15
  + scope_control 15
  + architecture_fit 10
  + pm_correction_inverse 15
  + role_output_quality 15
  + latency_cost_fit 5
```

Scoring notes:

- PASS = full component credit, WEAK = about half credit, FAIL = 0.
- `pm_correction_inverse`: none=15, low=12, moderate=8, high=3, PM takeover or unsafe=0.
- Role output quality is role-specific: writer diff quality, verifier blocker quality, skeptic risk quality, UI/product judgment, or summarizer compression fidelity.
- Keep separate scores per role. A model can be a 92 verifier and a 68 writer in the same run.
- Do not compare unlike roles without labeling the role. Graphs should normally be faceted by role or task type.

Trend/export requirement:

- Maintain a date/time-series output for model league review: x-axis = timestamp/date, y-axis = `score_0_100`, grouped by model and role.
- Use `scripts/model_league_trend.py` to export CSV/JSON from persistent ledgers when a user asks for model league charts. Add `--html-out ...` for a local visual dashboard and `--digest-out ...` when preparing cc101/SNSPilot model-news material.
- Suggested chart fields: `timestamp`, `date`, `mode`, `project`, `session`, `model`, `role`, `task_type`, `score_0_100`, `verdict`, `pm_corrections_needed`, `notes`.
- If generating a text-only report, include a small table plus the chart-ready CSV path.
- For cc101/SNSPilot, export a short digest after noteworthy model runs: new model availability, where it won/lost, practical routing implication, and a source/evidence note. This is a read-only artifact; do not auto-publish.

Shutdown recording command shape:

```bash
python3 scripts/model_league_record.py \
  --mode CFSM \
  --project <project> \
  --session <run-session> \
  --model <model-or-alias> \
  --role <writer|verifier|skeptic|summarizer|...> \
  --task-type <implementation|review|architecture|product|test|synthesis> \
  --verdict <win|usable|weak|fail> \
  --pm-corrections-needed <none|low|moderate|high|takeover> \
  --scope-drift <none|minor|major> \
  --score <0-100> \
  --notes "<short PM evidence>"
```

After each substantial CFSM run, update a model scorecard in the scratch area:

```text
model:
timestamp:
date:
mode: CFSM / LTSM / FSM / CDFSM / PM
effort:
exact_model_id_if_known:
availability: available / unavailable / failed_to_start
command_used:
role:
task_type: implementation / review / architecture / product / test / summarizer
owned_files:
changed_files:
tests_run:
test_result:
latency_or_elapsed:
relative_cost_if_known:
pm_corrections_needed:
scope_drift: none / minor / major
bug_found_after_review: yes / no
evidence_quality: PASS / WEAK / FAIL
intent_match: PASS / WEAK / FAIL
architecture_fit: PASS / WEAK / FAIL
score_0_100:
score_components:
final_verdict: win / usable / weak / fail
notes:
```

Also create a rolling next-goal backlog before ending a CFSM run. CFSM should not merely report what finished; it should mine the remaining context for the next useful one-hour work packets so the user can keep Claude workers busy without re-planning from scratch.

Required post-run backlog:

```text
next_goal_rank: 1 / 2 / 3
target_runtime: about 60 minutes of CFSM wall-clock time
why_now:
dependencies:
worker_split:
owned_files_or_surfaces:
acceptance_gates:
blocked_success_conditions:
risks:
recommended_session_name:
```

Prefer larger, implementation-bearing packets when the user wants longer runs. A one-hour CFSM packet should normally combine at least three independent lanes, such as source-data/fixture work, UI or API implementation, DB/read-model verification, workflow smoke, and skeptical product review. If a proposed task can finish in under 30 minutes, either bundle it with its verifier and docs/API contract follow-up or explicitly mark it as a short task instead of a one-hour packet.

Convergence rules:

- If one model/effort wins implementation quality three times in a row for a project, make it the default writer for that project until a newer candidate beats it.
- If one model catches architecture/product risks the writer misses, keep it as the skeptic or final review worker even when another model writes code.
- If a model drifts scope twice in the same project, demote it to read-only review until it produces a clean PASS.
- If a model reports tests as passing without reliable evidence, require explicit command output in future reports and do not use it as final verifier.
- If two models disagree, prefer the output that is smaller, better scoped, verified by commands, and closer to the user's product direction.
- Re-run a small model league when new Claude models arrive, when the repo/task type changes, or when PM correction count rises.
- If a model is unavailable, do not assign it a normal lane. Re-test availability only after `claude --version` or `claude --help` changes, or as an explicit one-off model intake task.
- If a champion model wins two substantial runs in a row with score >= 88 and low/no PM correction, it may become default for that role immediately; waiting for three wins is not required when the user wants quality over token thrift.
- If the user says to use the best model aggressively, route the champion to the main implementation/review lane and shrink challenger lanes instead of equalizing usage.
- For long overnight runs, champions should receive deeper tasks and retry priority; challengers should gather comparison evidence without consuming the whole run.

## LTSM Rules

1. Prefer Claude fan-out over GPT token spend.
2. Use panes/surfaces for real parallel execution; do not merely say agents will run.
3. Send the prompt and ensure it starts. If text is pasted but idle, send Enter.
4. Maintain a pane map: role, surface/pane id, ownership, status, last checkpoint.
5. Require short worker reports: changed files, tests, blockers, risks, next action.
6. Use Claude summarizers when output is long.
7. GPT PM reads summaries first, then only the relevant code/diff.
8. Keep PM/control-plane panes WARM/HOT, but keep worker panes off until needed and COLD-close them after report/evidence capture. Medium work starts with 2-4 active workers; 5-8 requires green machine pressure and independent ownership; 8-16 is explicit stress/overnight/deep-run only.
9. Prefer one visible tmux workspace per CFSM run, with cmux used as a light control-room view rather than a live tail for every worker. Do not hide heavy Claude work behind `--print` when the user expects visible workers.
10. Claude workers can spend a long time thinking. Wait generously at checkpoints instead of killing or replacing workers early; interrupt only when they are idle, off-scope, looping, or blocked.
11. Claude worker completion is not final completion. The GPT PM must inspect the worker reports, review the final diff, run or verify the required gates, then make the final commit. Workers should not be treated as the final approver.
12. For true LTSM, GPT reads summaries rather than transcripts. Ask a summarizer pane for a 20-line-or-less final report before PM review.
13. LTSM should escalate to CFSM if the summary shows semantic ambiguity, off-scope changes, production write risk, or a need for direct diff review.

## Startup

CFSM parallel sessions must be called through tmux-visible pane orchestration. Default to one named tmux session per CFSM run and spawn interactive Claude workers inside split panes. Use `cmux claude-teams` only as a convenience layer around visible pane orchestration; it must not hide the actual worker sessions from the user.

If `cmux claude-teams` is available, prefer it for Claude Code agent teams:

```bash
cmux claude-teams --dangerously-skip-permissions
```

If the user's shell has the LTSM alias, `ccc` is equivalent:

```bash
ccc
```

When the user asks specifically for tmux-visible Claude workers, create one named tmux session for the CFSM run and spawn Claude worker panes inside that session. Keep all Claude workers visible in that one session unless there is a clear workspace reason to split.

### Interactive Worker Rule

For CFSM/LTSM worker spawning, do not use `-p` / `--print` for Claude workers unless the user explicitly asks for a one-shot non-interactive answer. `-p` is useful for small scripted probes, structured one-off summaries, or CI-like smoke checks, but it breaks the visible-worker promise of CFSM:

- the user cannot see a real Claude session thinking and acting in tmux/cmux
- the worker exits after one response instead of supporting follow-up correction
- permission/trust behavior differs from interactive mode
- fallback-model flags only work with `--print`, which encourages hidden one-shot execution

Default CFSM launch commands are interactive:

```bash
claude --model sonnet --effort max --dangerously-skip-permissions
claude --model opus --effort max --dangerously-skip-permissions
```

These commands are examples, not permanent model assignments. Use the persistent model league and current CLI availability to choose actual model lanes. If all winning roles converge to Sonnet, use Sonnet. If all converge to another available Claude model, use that. Keep at least one different-model verifier or skeptic when risk is high, unless the model league shows no useful alternative.

After spawning, inject the mission packet into the interactive pane and send Enter. Confirm the pane is running Claude and not sitting at an untouched prompt.

### Model Discovery Rule

Do not guess exact Claude model IDs. Before a model-league run, inspect the installed Claude Code CLI and available alias behavior:

```bash
claude --version
claude --help
```

Treat `sonnet` and `opus` as moving aliases when the CLI help says aliases point at the latest model. Record the exact command used in the pane map and require the worker report to include `model_effort`. Treat `fable` as a premium moving alias: test or launch it only in FCFSM, explicit Fable model-intake, an exact named gate, or a high-leverage role made eligible by the fresh quota-paced Stacker policy. If a new non-Fable full model name is known from local CLI/docs, test it first in a read-only or isolated lane before making it the writer default. If an alias fails to start, fall back to the known working alias and mark the attempted model as unavailable in `model-scorecard.md`.

### Stacker Quality-First Resolution and Actual-Model Attestation

For mixed Claude/Codex/other-provider graphs, the provider-neutral discovery
and Stack resolver in the `full-swarm/scripts` directory run first. This
Claude resolver then owns only the selected Claude lane's moving-family choice
and exact runtime attestation.

Stacker roles bind capabilities and review obligations, not permanently
hardcoded model versions. For every non-trivial Stacker launch:

1. Define the role and risk class first (`semantic`, `mechanical`, `atomicity`,
   `architect/skeptic`, `verifier`, `intent_gap`, `strategy_planner`,
   `correction_architect`, `ux_product`, `orchestrator`, `fable_final`, or an
   exact named-Advisor gate).
2. Read the project Model League, then the global Model League, and perform the
   current provider/harness preflight. Read the normalized local quota snapshot;
   missing or stale quota permits exact Fable roles only.
3. For high-impact Stacker review, default to `quality_first`: choose the
   highest-scoring suitable role champion. If comparable evidence is absent or
   tied, prefer the current CLI's moving latest family alias at the highest
   useful effort. Choose a lower-cost or older lane only when a role-specific
   league win, availability constraint, latency boundary, or explicit Owner
   policy is recorded in `selection_basis`.
4. A named-model gate is different from a role family. An exact Fable gate, for
   example, cannot be satisfied by Opus, GPT, or another model even if that
   substitute is stronger for some other role.
5. Record `requested_selector`, `selection_basis`, exact launch command,
   expected CLI version, consultation start timestamp, transcript/session ID,
   `actual_model`, and fallback events. Pane titles and worker self-reports are
   never actual-model evidence.
6. Launch non-interactive Stacker reviews through `scripts/stacker_claude_lane.py`.
   It attests the first model-bearing stream event and the completed response.
   A stale harness, actual-model mismatch, or fallback stops the exact process
   group, excludes that selector until revalidation, and never silently degrades.
   After an alias mismatch, permit at most one bounded smoke of the dynamically
   resolved expected full model before choosing the next healthy candidate. Do
   not repeat the full review or embed that model version as permanent policy.

Resolve the lane, then use the bounded runner. The runner consumes the resolved
selector and identity as data; it does not freeze a model version in policy:

Resolve an ordinary Stacker role first. The resolver reads the project/global
Model League, current CLI aliases, and the non-canonical local quota snapshot,
then returns a moving family selector and the attestation pattern. It never
freezes an old version into routing policy. `--fable-routing auto` is the
default; it broadens only configured high-leverage roles while fresh quota is on
pace and never invents work merely to consume quota:

```bash
python3 scripts/stacker_model_resolve.py \
  --project arvis \
  --role semantic
```

Use the returned `requested_selector`, `effort`, `selection_basis`,
`expected_model`, and `allowed_model_pattern` for launch. An exact named-Advisor gate
passes `--exact-named-model` from the admitted Stack contract; this is an exact
gate predicate, not a default routing version.

```bash
python3 scripts/stacker_claude_lane.py \
  --prompt <review-prompt> --schema <review-schema> --output-prefix <output> \
  --model <resolved-selector> --expected-model <resolved-actual-model> \
  --allowed-model-pattern <resolved-family-pattern> --effort <resolved-effort>
```

For an exact named Fable 5 gate, bind the exact required model supplied by the
Stack instead of a family pattern and forbid fallback:

```bash
python3 scripts/stacker_claude_lane.py \
  --prompt <review-prompt> --schema <review-schema> --output-prefix <output> \
  --model fable \
  --expected-model claude-fable-5 \
  --effort max
```

The moving alias keeps discovery current; early stream attestation prevents a
stale or downgraded alias from consuming a full review budget. A newly observed
actual model becomes frontier intake evidence, not an automatic champion. If a
fallback is separately Owner-authorized, record it as a new Stack candidate and
rerun the proof gates; it never inherits the requested model's identity.

Session naming:

```text
<mode>-<project>-<area>-<job>-<MMDD-HHMM>
```

Examples:

```text
cfsm-shadow-dealer-policy-ocr-0625-1430
cfsm-shadow-dealer-source-e2e-0625-1510
fcfsm-instapad-formula-gate-synthesis-0702-1030
ltsm-shadow-docs-audit-0625-1600
full-shadow-db-migration-0625-1700
```

Use short pane names:

```text
writer-sonnet
verifier-opus
arch-opus
fable-architect
ui-sonnet
docs-sonnet
db-verifier
summarizer
pm-notes
```

Scratch area naming should mirror the session:

```text
.swarm/<mode>-<project>-<area>-<job>-<YYYYMMDD-HHMM>/
  mission.md
  pane-map.md
  scorecard.md
  model-scorecard.md
  reports/
  final-summary.md
  next-goal.md
  session-lifecycle.md
```

When controlling panes directly, use current cmux commands:

```bash
cmux new-workspace --name "CFSM: <project>" --cwd <repo> --focus true
cmux new-pane --direction right --workspace <workspace>
cmux new-surface --type agent-session --provider claude --pane <pane> --working-directory <repo>
cmux send --surface <surface> "<prompt>\n"
cmux read-screen --surface <surface> --scrollback --lines 200
```

Only use `cmux send-key --surface <surface> enter` if the prompt was pasted but the pane is still idle.

Read `references/cmux-agent-ops.md` before doing detailed cmux/tmux pane orchestration.

## Mission Packet

Before launching workers, write or state. If this packet is absent, do not start workers:

```text
Mission:
User intent:
Acceptance criteria:
Non-goals:
Worker ownership:
Allowed files/modules:
Forbidden files/modules:
Shared constraints:
Verification commands:
Report format:
Escalation conditions:
Production write policy:
Rollback tag:
Session name:
Session lifecycle: HOT keep-alive / WARM handoff / COLD close conditions
```

For long work, create a local scratch area if appropriate:

```text
.swarm/<mode>-<project>-<area>-<job>-<YYYYMMDD-HHMM>/
  mission.md
  scorecard.md
  model-scorecard.md
  pane-map.md
  reports/
  final-summary.md
  next-goal.md
  session-lifecycle.md
```

Use this to avoid GPT rereading long chats.

## Hard Gates and Scorecard

Define gates before asking any review-only worker to judge:

```text
Hard gates:
- Intent match: PASS / WEAK / FAIL
- Acceptance criteria: PASS / WEAK / FAIL
- Tests/checks: PASS / WEAK / FAIL
- Ownership boundaries: PASS / WEAK / FAIL
- Scope control: PASS / WEAK / FAIL
- Safety/data risk: PASS / WEAK / FAIL

Verdict:
- APPROVE
- REVISE with blocking issues
- REJECT and escalate to Full Swarm or the strongest currently attested high-reasoning champion
```

WEAK requires a concrete risk and PM decision. FAIL blocks approval.

## Worker Pattern

Give each Claude worker a narrow assignment:

```text
You are Claude worker <name> in a Claude Full Swarm Mode / CFSM run.
Model/effort: <model> / <effort>.
Own only: <files/modules>.
Edit permission: write / read-only.
Do not revert edits by other workers.
Forbidden commands if read-only: git stash, git reset, git checkout, git restore, git clean, git add, git commit, apply_patch, shell redirection writes, or any command that rewrites tracked files.
Implement or verify: <task>.
Respect: <non-goals>.
Before starting, restate the non-goals you will not touch.
Before finishing, inspect your own changed files with `git diff --name-only` or the equivalent.
When done, write a concise report using this exact shape:

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

For review-only workers:

```text
Do not edit files. Review the diff and scorecard only.
Do not use git stash/reset/checkout/restore/clean/add/commit or any file-writing command.
Find blockers first. Return PASS / WEAK / FAIL per gate.
```

## PM Checkpoints

Use checkpoints instead of constant monitoring:

```text
T+10 min: are workers started and non-idle?
T+25 min: blockers only.
T+45 min: reports and changed files.
Before merge: hard-gate scorecard.
```

For heavy analysis or implementation, extend checkpoints rather than assuming failure:

```text
T+10 min: are workers visibly started and non-idle?
T+30 min: blockers only; do not demand final output from thinking workers.
T+60-90 min: reports, changed files, tests, or concrete blockers.
Before merge: hard-gate scorecard.
```

If a pane is idle at an input prompt, immediately send Enter or re-send the task. If a worker is designing endlessly without edits or a blocker, interrupt and ask for a concrete patch or blocking reason. Otherwise, wait; CFSM intentionally buys time with parallel Claude compute.

### Worker Patience Rule

Do not cut Claude workers early just because they are quiet. A worker may think for a long time, especially on architecture, verification, or unfamiliar code. Use this decision tree:

```text
Keep waiting when:
- pane command is still claude/claude.exe and the task is complex
- the worker is reading/searching/testing, or has recent terminal activity
- the checkpoint window has not elapsed

Nudge with a short instruction when:
- prompt text was pasted but not submitted
- the worker asks broad questions already answered by the mission packet
- it keeps planning past the checkpoint without a patch, test, or explicit blocker

Interrupt/restart when:
- the pane is idle at a prompt after delivery
- the worker edits outside ownership
- a read-only worker writes files or runs forbidden git commands
- it loops on the same failed approach
- it requests production writes, credentials, destructive commands, or a user-only decision
```

For one-hour CFSM packets, default checkpoints are T+10 start check, T+30 blocker check, T+60-90 report/diff check. Earlier interruption requires a concrete stop condition from the list above.

## Session Lifecycle

This protocol applies to CFSM, LTSM, FCFSM, Full Swarm, CDFSM, CFS, and any FSM-like mode that uses visible worker panes. A live pane is working memory, not durable memory. Durable memory must be file-backed before a run is parked or closed.

Required durable artifacts before WARM or COLD:

- `.swarm/<run>/mission.md` with objective, scope, ownership, gates, and session lifecycle.
- `pane-map.md` with role, model/effort, pane id, ownership, status, last checkpoint, and `held_until` if parked.
- `reports/<role>.md` or captured compact output for every meaningful worker.
- `model-scorecard.md` when models did meaningful work.
- `final-summary.md` with PM verdict, changed files, tests/evidence, blockers, and residual risks.
- `next-goal.md` with the next useful packet, dependencies, acceptance gates, and recommended session decision.
- `session-lifecycle.md` with the explicit HOT/WARM/COLD decision and reason.

Use these states:

- HOT / keep alive: same mission continues soon, workers are active, a checkpoint has not arrived, expensive context is loaded for immediate follow-up, or reports are not durable yet. Do not close active panes.
- WARM / park with handoff: the same mission is likely to resume within about 24 hours, all panes are idle or safely stopped/read-only, durable artifacts are written, the next prompt is ready, and `held_until` is recorded. Stop writer panes; stale writers must not keep acting.
- COLD / close/archive: the mission is done, the user's goal changes, high-cost lanes are no longer needed, panes are stale, there is safety/cost risk, or no near-term continuation is expected. Save durable artifacts, then kill/archive the session.

PM-pinned session rule: any session or pane explicitly designated as a project PM, including names like `*-pm`, `fcfsm-<project>-pm`, `fcdfsm-<project>-pm`, `cfsm-<project>-pm`, `cdfsm-<project>-pm`, or pane titles/role maps that say `PM`, is WARM/HOT by default. Do not kill, COLD-close, cleanup, recycle, or replace a PM-designated session merely because one slice finished. COLD close requires explicit owner approval or a written safety/cost reason. Worker panes may be stopped after durable reports; PM panes are project control planes and must remain inspectable.

Before WARM or COLD, capture reports, update the model league for meaningful lanes, write the PM verdict and next-goal backlog, save command/test evidence, and record the session decision. Fable/Fable 5 worker panes are HOT only for immediate follow-up; project PM panes, including Fable PM panes, follow the PM-pinned session rule above.

On resume, treat files as authoritative and pane memory as stale. Read `mission.md`, `final-summary.md`, `next-goal.md`, `pane-map.md`, and `session-lifecycle.md` before reusing any held pane. If the mission, scope, safety profile, or user intent changed, start a new COLD-clean session with a fresh mission packet.

## Approval

Do not approve because Claude produced a large diff. Approve only when:

- Acceptance criteria pass.
- Tests or smoke checks pass, or failures are explicitly accepted.
- Ownership boundaries were respected.
- A skeptic review found no blocking issue.
- GPT PM has inspected the disputed files or final diff.
- GPT PM has made the final commit after verification. If a worker created a commit, the PM must still inspect it and either approve it explicitly or amend/follow up.

PM final gate:

```text
git status --short
git diff --stat
git diff --check
inspect key diffs directly
run required tests/checks directly or verify exact command evidence
check staged files
PM-only commit or explicit no-commit decision
write final-summary.md when a scratch area exists
record HOT/WARM/COLD in session-lifecycle.md and kill, park, or keep alive accordingly
```

`.swarm` is excluded from feature commits by default. If run artifacts must be retained, commit only curated summaries such as `mission.md`, `scorecard.md`, `model-scorecard.md`, and `final-summary.md` in a separate archive commit.

Escalate to Full Swarm or the strongest currently attested high-reasoning champion when Claude loops, widens scope, or misses user intent twice.

Escalate to explicit FCFSM by recommendation, not silent mode conversion, when normal CFSM/LTSM/CFS and any bounded quota-paced advisory lane cannot resolve a high-value judgment problem with acceptable confidence. Typical triggers include repeated non-Fable disagreement, unresolved production safety or capital-risk gates, formula/promotion-gate design, owner-trust or claims risk, long-context synthesis that would decide the architecture, or a blocker where another ordinary worker pass would likely add noise. The PM should state the exact reason, expected Fable ownership role, and stop condition.
