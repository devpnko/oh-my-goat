# cmux Agent Operations

Use this reference for Claude Full Swarm Mode, CFSM, and LTSM pane orchestration.

CFSM is a Claude-heavy, cost-heavy, time-saving mode. The PM should actively use parallel Claude workers instead of serially asking one agent to do everything. Medium work should default to about 5 visible workers: writer, verifier, skeptic/architect, domain reviewer, and summarizer. For large work, spawning 8-16 independent Claude workers in one visible tmux/cmux session is acceptable when ownership is disjoint and rate limits allow. The goal is to spend parallel Claude tokens to save GPT PM tokens and wall-clock time.

Fable/Fable 5 is not a blanket CFSM worker or mechanical default. Use it for explicit FCFSM ownership, exact named gates, or bounded high-value intent, strategy, correction-architecture, UX, orchestration, or final-synthesis roles that fresh quota-paced Stacker policy makes eligible. Otherwise use the current non-Fable role champion. Quota eligibility never promotes Fable or invents work solely to consume allowance.

When CFSM says to call session-level parallel processing, interpret that as tmux-visible pane fan-out. Create or reuse one named tmux session, split panes, launch interactive Claude workers, inject prompts, and track the pane map. `cmux` may wrap or automate this, but the workers must remain visible. Do not substitute a hidden localhost proxy, OpenRouter/API router, background-only runner, or `claude --print` one-shot execution for CFSM parallel sessions unless the user explicitly requests that mode.

Worker completion is not final completion. After all changed work is ready, the GPT PM must inspect reports, review the final diff, run or verify gates, and make the final git commit. Claude workers may prepare patches and reports, but PM owns final approval and commit.

Hard safety default:
- Use only one writer in a shared worktree. Put additional writers in separate worktrees.
- Read-only panes must not run `git stash`, `git stash pop`, `git reset`, `git checkout`, `git restore`, `git clean`, `git add`, `git commit`, `apply_patch`, shell redirection writes, or any command that rewrites tracked files.
- If a worker violates read-only or ownership boundaries, stop that pane and mark it weak/fail in the model scorecard.

## Current Commands

Check availability:

```bash
command -v cmux
command -v claude
command -v codex
cmux claude-teams --help
```

Launch Claude Code with agent teams enabled:

```bash
cmux claude-teams --dangerously-skip-permissions
```

Useful aliases seen in this environment:

```bash
cc='claude --dangerously-skip-permissions'
ccc='cmux claude-teams --dangerously-skip-permissions'
cdc='codex --dangerously-bypass-approvals-and-sandbox'
```

Example model/effort worker commands for CFSM evaluation:

```bash
claude --model sonnet --effort max --dangerously-skip-permissions
claude --model opus --effort max --dangerously-skip-permissions
```

Do not add `-p` / `--print` to CFSM worker commands unless the user explicitly requests a hidden one-shot probe. CFSM workers should be interactive Claude panes the user can see, correct, and keep alive for follow-up. `-p` is acceptable only for tiny scripted checks or non-CFSM summaries; it is not the default worker mode.

Do not treat these commands as fixed role assignments. Use the persistent model league to choose actual non-Fable lanes. Sonnet max and Opus max are known-good baselines only when the scorecard supports them. Fable wins do not promote Fable into normal CFSM defaults; they only inform FCFSM or explicit Fable lane routing.

For high-value work, run model comparisons with disjoint ownership or read-only constraints, then record the result in both:

```text
.swarm/<run>/model-scorecard.md
~/.codex/swarm/projects/<project>-model-league.md
```

Before choosing model lanes, inspect the local CLI rather than guessing full model IDs:

```bash
claude --version
claude --help
```

If the help says aliases like `sonnet` or `opus` point at latest models, treat those aliases as moving candidates and record the exact command in the pane map. Treat `fable` as premium opt-in: test or launch it only in FCFSM or explicit Fable model-intake, never as normal CFSM's automatic newest candidate.

Create and control panes/surfaces:

```bash
cmux new-workspace --name "CFSM: <name>" --cwd <repo> --focus true
cmux list-panes --workspace <workspace>
cmux new-pane --direction right --workspace <workspace>
cmux new-surface --type agent-session --provider claude --pane <pane> --working-directory <repo>
cmux send --surface <surface> "<prompt>\n"
cmux read-screen --surface <surface> --scrollback --lines 200
cmux capture-pane --surface <surface> --scrollback --lines 200
```

`cmux send` accepts `\n` and `\r` as Enter. If a pane has text but did not start, then run `cmux send-key --surface <surface> enter`.

For tmux-visible CFSM, keep one named session per run and split panes inside it:

```bash
tmux new-session -d -s "cfsm-<project>" -c <repo>
tmux split-window -t "cfsm-<project>" -h -c <repo>
tmux split-window -t "cfsm-<project>" -v -c <repo>
tmux send-keys -t "cfsm-<project>:0.<pane>" "claude --model sonnet --effort max --dangerously-skip-permissions" C-m
tmux send-keys -t "cfsm-<project>:0.<pane>" "claude --model opus --effort max --dangerously-skip-permissions" C-m
```

Use one session with many panes before creating many sessions. The user should be able to see Claude workers doing the heavy work.

PM-pinned session rule: if a session or pane is explicitly designated as PM, for example `*-pm`, `cfsm-<project>-pm`, `fcfsm-<project>-pm`, `cdfsm-<project>-pm`, `fcdfsm-<project>-pm`, or a pane title/role map says `PM`, treat it as a project control plane. Do not kill, recycle, cleanup, or COLD-close that PM session after a slice finishes unless the owner explicitly approves or a concrete safety/cost reason is written. Worker panes may be closed after durable reports; PM panes stay WARM/HOT for continuity and inspection.

## Pane Map

Maintain a pane map in the PM notes or `.swarm/.../pane-map.md`:

```text
surface | role | owner | status | last action | next checkpoint
surface:1 | opus-builder-api | src/api/** | running | prompt sent | T+25
surface:2 | sonnet-tests | tests/** | running | prompt sent | T+25
surface:3 | skeptic | read-only diff | waiting | needs diff | after builder
```

For normal CFSM runs, keep PM/control-plane panes persistent and worker panes ephemeral. Start 2-4 workers for the current wave, scale to 5-8 only when machine pressure is green and ownership is disjoint, and treat 8-16 as explicit stress/overnight/deep-run rather than the default:

```text
pane | model/effort | role | owner | status | last action | next checkpoint
0.1 | sonnet/max | claude-builder-rsl | verifier/docs RSL only | running | prompt sent | T+30
0.2 | sonnet/max | claude-verifier-db | DB/preflight gates read-only | running | prompt sent | T+30
0.3 | opus/max | claude-skeptic | staged diff review only | waiting | after patch | T+60
```

At startup, read the project model league if present:

```bash
ls ~/.codex/swarm/projects/*-model-league.md 2>/dev/null || true
```

Use it to decide model lanes, but do not let it override current run evidence or PM judgment.

## Prompt Delivery Checklist

- Include objective, ownership, non-goals, verification, and report format.
- Include edit permission and forbidden commands. For read-only panes, explicitly forbid `git stash/reset/checkout/restore/clean/add/commit`, `apply_patch`, and file-writing commands.
- End the prompt with a newline or send Enter.
- Confirm the pane is no longer sitting at an untouched prompt.
- If a worker asks broad design questions, answer with the mission packet and require a patch or blocker.
- If a worker touches another worker's files, stop it and reassign ownership.
- Claude can spend a long time thinking. Wait generously at checkpoints; do not interrupt simply because there is no output yet.
- Before interrupting, classify the pane. If it is reading, searching, running tests/builds/browsers, composing, showing a thinking/spinner/status line, or waiting on a long command, it is `active`; wait until the declared checkpoint and use passive polling only.
- Interrupt only when a stop condition is concrete: idle prompt after prompt delivery, explicit blocker, unowned edits, forbidden commands, repeated failed loop, production-write request, credentials request, raw-secret request, or a user-only decision.
- If the PM interrupts an active pane early, record `pm_orchestration_error`, resume/restart the lane if needed, and do not score the worker/model weak because the PM cut it off.

## Low-GPT-Token Pattern

When output is long, assign a Claude summarizer:

```text
Summarize surface <id> for the GPT PM.
Return only: completed work, changed files, failing checks, blockers, risks, and exact files the PM must inspect.
Do not include narrative.
```

The GPT PM should read:

1. mission packet
2. pane map
3. short reports
4. per-run model scorecard and persistent project model league
5. `git diff --stat`
6. disputed diffs and test failures only
7. final staged diff before commit

Commit rule: do not treat a worker's “done” report as completion. PM commits only after acceptance criteria and verification gates pass. If workers created commits, PM reviews them and either approves, amends, or follows up.

## Transient Worker Failure Recovery

Apply this to CFSM, LTSM, Full Swarm, and CDFSM whenever visible worker panes are used.

Recover before judging the worker when a pane shows:

- `API Error: Connection closed mid-response`
- "response may be incomplete"
- stream closed / network reset / timeout / provider 5xx
- partial output followed by an idle prompt without the required report

Protocol:

1. Capture the pane output with `tmux capture-pane` or the cmux equivalent and save/record it in `.swarm/<run>/`.
2. Mark pane-map status as `interrupted_transient`; do not score it `fail` yet.
3. Retry once in the same pane with a compact continuation prompt that asks it to write the report path first.
4. If it fails again, start a fresh replacement pane with the same mission, role, ownership, forbidden commands, and report path.
5. If the replacement also fails, switch model/effort/provider when available. If the error is an explicit rate-limit or hard quota, back off or fall back instead of looping.
6. Only after those attempts may the PM mark the lane weak/fail or take over manually, and the scorecard must record the recovery attempts.

Incomplete worker output is never an approval signal. It can guide PM inspection, but another worker or PM hard gate must verify it.

## Stop Conditions

Stop or interrupt a pane when:

- It is idle after prompt delivery.
- It keeps planning without editing when assigned implementation.
- It changes unowned files.
- It is read-only but runs `git stash`, `git reset`, `git checkout`, `git restore`, `git clean`, `git add`, `git commit`, or any tracked-file write.
- It repeats a failed approach.
- It needs credentials, production writes, destructive commands, or user-only decisions.

Do not stop a worker merely for long reasoning, no report yet, or quiet output when pane/session activity suggests it is still working and the task is complex. CFSM trades Claude compute for wall-clock speed through parallelism.

Default patience checkpoints for a one-hour CFSM packet:

```text
T+10: confirm all panes started and prompt was submitted.
T+30: ask for blockers only; do not demand final output from active workers.
T+60-90: collect reports, changed files, tests, and blocker evidence.
```

For overnight or explicitly deep CFSM runs, declare longer checkpoints in the mission packet, such as T+120, T+240, or morning collection. Active workers should be allowed to run until those checkpoints unless a concrete stop condition appears.
