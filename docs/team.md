# Agent team

SplitSnap is built and operated by a small team of Claude Code agents with one human in charge. Each agent is a Claude Code subagent defined in [`.claude/agents/`](../.claude/agents/). They all read [`AGENTS.md`](../AGENTS.md) first. They coordinate through **GitHub Issues and pull requests**, not through chat, so every hand-off leaves a public trace.

```
              ┌──────────────────────────── GitHub Issues (tracker) ────────────────────────────┐
              │                                                                                  │
 Human ──► Planner ──plan + acceptance criteria──► Implementer ──PR──► Reviewer ──approve──► Human merges
 (owner)      │                                     ▲     │                │                       │
              │                                     │     └──► QA ◄────────┘                       ▼
              │                                     │        (tests)                       CI ─► CD to dev
              │                                     │                                              │
              └──────────────── incident issue ◄── On-call ◄──── Grafana alert (dev/prod) ◄──────────┘
                                                      │
                                                      └──► fix PR (same review path)
```

## Roles

| Role | Subagent | Owns | Input | Output | Never does |
|---|---|---|---|---|---|
| **Human owner** | – | Priorities, merging, production promotion | – | Issue priorities, PR merges, prod approvals | – |
| **Planner** | [`planner`](../.claude/agents/planner.md) | Turning a request into a well-formed issue | A request or a vague issue | An issue with a goal, **acceptance criteria**, labels, milestone and an implementation plan comment | Write code |
| **Implementer** | [`implementer`](../.claude/agents/implementer.md) | Code changes | An issue with acceptance criteria | A branch and a PR that says `Closes #N`, with tests written first | Merge, deploy, or change scope silently |
| **QA** | [`qa`](../.claude/agents/qa.md) | Test strategy and the journey test | A PR or an issue | Unit and integration tests; a comment with the test run result | Change production code except to fix test seams |
| **Reviewer** | [`reviewer`](../.claude/agents/reviewer.md) | Quality gate | A PR | A PR review that checks each acceptance criterion against `CONTEXT.md`, ADRs and the guardrails | Push commits to the PR |
| **On-call** | [`oncall`](../.claude/agents/oncall.md) | Restoring service after an alert | An alert payload | An incident issue, a regression test, a fix PR and a postmortem in `docs/incidents/` | Push to `main`, deploy to production, or silence alerts |

## Hand-off rules

1. **The issue is the contract.** Work starts only from an issue with acceptance criteria. If an agent finds that the criteria are wrong, it comments on the issue and hands it back to the Planner. It does not quietly change scope.
2. **Agents announce themselves.** When an agent picks up an issue it comments `🤖 <Role> agent picked this up` with its plan. When it finishes, it comments with what changed and how it was verified.
3. **One issue, one branch, one PR.** Branch names are `<issue-number>-<slug>`, or `phase-N/<slug>` for a phase batch. The PR body says `Closes #N` and names the acting role.
4. **Labels show ownership.** The `agent:*` label says which role currently owns the issue. Moving the label is the hand-off.
5. **Humans hold the keys.** Only the human owner merges to `main` and approves the `production` environment. Agents can deploy to **dev** only indirectly: their merged PRs flow through CD.

## Escalation

| Situation | Who | Action |
|---|---|---|
| Acceptance criteria are ambiguous | Implementer → Planner | Comment on the issue and move the label to `agent:planner` |
| Review finds a blocking problem | Reviewer → Implementer | "Request changes" with the failing criterion quoted |
| CI fails on a PR | Implementer | Fix on the same branch; never skip hooks or delete tests |
| An alert cannot be reproduced | On-call → Human | Comment on the incident issue and @-mention the owner; leave the alert firing |
| A fix needs a production change (data, secrets, config) | On-call → Human | Describe the change in the incident issue; never perform it |

See [`process.md`](process.md) for the full delivery flow and [`runbooks/`](runbooks/) for on-call procedures.
