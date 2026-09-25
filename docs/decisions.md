# Decisions

- 2026-09-26: User confirmed actual Alpaca paper trading. Use two dedicated paper
  accounts, not two agents trading a netted shared account. Local simulation is
  only a development aid. Account IDs must differ.
- 2026-09-26: Start with opposite sign, long/cash hypotheses. No leverage or shorts
  to keep the eventual small-account strategy feasible. This does not prove the
  inflation/rates mechanism. 2%/5-session parameters are provisional, unoptimized.
- 2026-09-26: Daily data, same decision snapshot, regular hours. Free IEX is an
  explicit data compromise. Intraday research and macro conditioning are deferred.
- 2026-09-26: Python standard library starter minimizes setup while source repo
  access is unavailable. Reassess integration against actual repo conventions;
  do not blindly overwrite an existing TypeScript or other project.
- 2026-09-26: SQLite records intents before submission. Lost responses reconcile
  by deterministic client IDs; unexplained missing orders require manual review.
- 2026-09-26: $200 per paper account, 50% target allocation, 15% observed drawdown
  shutdown. Stops are software controls, not guarantees. Use paper endpoint only.
- 2026-09-26: No daemon deployment in a transient workspace, no external account
  setup and no fabricated performance results. A durable host and credentials are
  required before starting continuous runs.
- 2026-09-26: The supplied v0.1 starter is the baseline implementation because
  the target checkout was otherwise empty. Preserve its paper-only boundary and
  conservative journal/reconciliation behavior while integrating and validating.
