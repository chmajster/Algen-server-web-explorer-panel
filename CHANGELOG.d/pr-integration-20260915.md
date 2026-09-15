### Fixed

- Integrate the pending React and React DOM upgrades together, including both
  TypeScript type packages. This fixes npm peer-dependency resolution and the
  blank application caused by mismatched React runtime versions. Dependabot
  now groups these four packages for subsequent upgrades.
- Make the desktop settings interaction test await its real lazy-loaded module
  before measuring interactions, removing a cold-transform timing race without
  replacing the component or increasing assertion timeouts.
- Reject truncated module API responses even when their received prefix is
  valid JSON. Preserve address failover for GET and HEAD, but never replay a
  mutating request after an ambiguous transport failure.
- Apply the shared JSON nesting and finite-number limits to module API replies
  and normalize decoding failures without exposing response content.

The integration retains the original commits from PRs #261, #263 and #265–#275,
including file-worker boundaries, network transport hardening, persisted-state
validation and dependency updates. New module API regressions exercise the real
HTTP parser with controlled in-memory socket responses.
