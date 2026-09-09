# AGENTS.md

## Mandatory completion protocol

For implementation, bug-fix, refactor, CI, release, deployment, and repository-maintenance work, do not treat the task as complete merely because code was written or a pull request was opened.

Before reporting a task as complete:

1. Synchronize the working branch with the current target branch (normally `main`). Resolve conflicts deliberately and preserve intended changes from both sides. Re-check synchronization immediately before merge.
2. Verify the complete relevant CI suite on the **final head SHA**. A previous green run does not validate a newer commit.
3. Inspect every failed check or workflow job down to the failing step/log. Fix the root cause instead of bypassing, disabling, or weakening the check unless the task explicitly requires changing that check.
4. Repeat the fix-and-verify cycle until every required workflow/check is successful. `queued`, `pending`, `in_progress`, `cancelled`, or tests/builds skipped because an earlier step failed do not count as a successful final verification.
5. Run or verify all repository checks relevant to the change when they exist, including lint, type checking, unit tests, contract tests, builds, bundle/budget gates, integration/E2E tests, security/dependency analysis, and installation/upgrade/smoke tests.
6. Confirm that the pull request is mergeable, the branch is not behind the target branch, and the CI results being reported belong to the current head SHA.
7. Keep the pull-request description accurate. Before completion, update it with the final architecture/behavior, important fixes, synchronization state, final head SHA, and actual verification results.
8. If the user has **not** explicitly authorized merging, stop only at a verified `ready to merge` state and report that clearly.
9. If the user **has explicitly authorized merging**, merge only after the final head has satisfied the checks above. Use an expected-head/SHA guard when supported so a moved branch cannot be merged using stale verification.
10. After merging, verify the pull request is actually merged/closed, record the merge commit SHA, and verify the target branch contains the result before reporting success.
11. If local execution is unavailable, use the repository CI as the authoritative executable verification and state that clearly. Do not invent local test results.
12. Never claim `done`, `green`, `ready to merge`, or `merged` from assumptions or stale state. Perform a fresh final verification first.

This protocol is the default Definition of Done for repository work. It may only be shortened when the user explicitly asks to stop earlier or when a required external condition cannot be completed; in that case, report the exact blocker and the furthest verified state instead of claiming completion.
