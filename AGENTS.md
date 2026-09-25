# Agent handoff

Read README.md, docs/status.md, docs/strategy.md and docs/decisions.md first.
This directory is an unintegrated starter. Before copying it into the target repo,
read that repo's existing AGENTS.md and preserve existing user work.

- Python 3.11+, standard library only. Keep dependencies and abstractions minimal.
- Check: `python3 -m unittest discover -s tests -v`.
- Paper only. Never add or switch to a live endpoint without a new explicit request.
- Never log/commit API secrets or runtime databases. Keys come from environment.
- Each strategy uses its own actual Alpaca PAPER account. Never share accounts.
- Same historical information cutoff and comparable sizing for both hypotheses.
- Do not optimize thresholds on the evaluation set or call synthetic results alpha.
- Version experimental changes; do not mutate an active experiment's rules.
- Preserve deterministic order IDs and reconciliation; never retry unknown POSTs.
- Use one feature branch and small reviewable commits once GitHub is available.
- Test meaningful failure cases: timing, duplication, partial fills, account isolation.
- Update docs/status.md after each work session: changes, checks, blockers, next action.
- Record consequential decisions in docs/decisions.md; no framework for trivial choices.
- Do not claim a daemon, paper order or commit exists without verification.
