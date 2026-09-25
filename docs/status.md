# Handoff — 2026-09-26 Europe/Istanbul

## Current state

- The provided `tradebot-v0.1-starter.zip` has been integrated as the initial
  implementation in this repository: Python package, tests, docs, and CI workflow.
- Offline validation: all 14 unittest cases pass. The synthetic 120-session demo
  and simulator report also run and produce four portfolios. Synthetic output is
  a software check, not market evidence.
- The worktree is on a feature branch. No commit or pull request has been created.
- No Alpaca credentials were supplied; no live API calls, paper-account creation,
  or order submissions have been performed. No continuous runner is active.

## Next actions

1. Review and extend the paper-runner failure handling and broker reconciliation
   with mocked edge-case tests before using credentials.
2. Configure two dedicated Alpaca paper accounts at $200 simulated equity, empty
   of positions/orders, with separate environment-variable credentials. Never
   put keys in chat or source control.
3. Run a read-only paper preflight during market hours and verify actual data
   entitlements, account fields, and quote/history responses.
4. Only after reviewing that output, explicitly enable paper submissions; monitor
   broker fills and restart reconciliation on a durable host.
5. Add an account-level comparison report for actual broker marks/fills; the
   existing `report` command is only for offline simulator databases.
6. Obtain and validate historical data and predeclare chronological evaluation
   periods before drawing conclusions about either strategy.

## Known limitations

- This is a starter, not a proven strategy or an operated trading service.
- Signals are daily; drawdown checks happen only during valid execution polls.
- The poll loop stops on errors/open orders and has no supervisor or alerting.
- Sequential account orders may receive different fills despite shared signals.
- No historical market-data edge, paper execution quality, or real-money result
  has been established.
