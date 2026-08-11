# Evaluation Rubric

Use this reference when judging builder output in Full Swarm.

## Judge Contract

The evaluator is not a second implementer. It should not rewrite the patch unless asked. It should find reasons to block approval.

Required output:

```text
Verdict: APPROVE / REVISE / REJECT

Hard gates:
- Intent match: PASS / WEAK / FAIL
- Tests/checks: PASS / WEAK / FAIL
- Scope ownership: PASS / WEAK / FAIL
- Architecture fit: PASS / WEAK / FAIL
- Safety/data risk: PASS / WEAK / FAIL

Blocking issues:
1. File/line:
   Impact:
   Reproduction or evidence:
   Required fix:

Quality score:
- Correctness: __/30
- Edge cases: __/20
- Architecture fit: __/20
- Scope control: __/10
- Test coverage: __/10
- Maintainability: __/10
```

## Scoring Rules

- A hard-gate FAIL forces REJECT, regardless of score.
- A hard-gate WEAK forces REVISE unless the PM explicitly accepts the risk.
- Do not award points for unrelated cleanup.
- Penalize unrequested rewrites, new abstractions, or changed public behavior.
- Prefer concrete evidence over model preference.

## PM Integration Rule

The PM may accept a judge finding only after tying it back to the mission packet. If judges disagree, the PM reads the disputed code and decides. Do not average contradictory verdicts.
