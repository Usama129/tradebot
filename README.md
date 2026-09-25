# Tradebot v0.1 starter

Two **actual Alpaca paper accounts** can test opposite oil/gold directional
hypotheses. No real-money trading endpoint exists. This repository starts from
the v0.1 starter; the offline simulator is for software validation only.

Python 3.11+ on macOS/Linux; standard library only. No install step, UI, Docker,
LLM trading dependency, or paid data subscription. Windows requires replacing the
Unix `fcntl` process lock or using WSL. Run commands from this directory.

## Experiment

| Paper account | Signal from USO's previous 6 completed daily closes | GLD target |
|---|---|---|
| Continuation | 5-session return >= +2% | 50% of account equity; otherwise cash |
| Reversal | 5-session return <= -2% | 50% of account equity; otherwise cash |

Each starts with $200 **simulated** cash. Shared inputs; separate broker balances,
orders, fills and P&L. Long/cash only. These are opposite sign hypotheses, not a
causal test of inflation or Fed expectations. Read `docs/strategy.md`.

## Offline validation (no credentials)

```sh
python3 -m unittest discover -s tests -v
python3 -m tradebot demo --db runs/demo.sqlite
python3 -m tradebot report --db runs/demo.sqlite
```

The demo uses explicitly synthetic prices and includes cash and 50% gold
buy-and-hold references. Results are software checks, NOT performance evidence.

For a historical CSV with `date,oil_close,gold_open`:

```sh
python3 -m tradebot replay --db runs/history.sqlite --csv historical.csv
```

Rows must be unique, chronological, complete aligned sessions. Oil prices should
be split-adjusted. This simplified replay marks gold at the supplied open only,
does not handle gold splits/dividends, and does not validate exchange holidays.
It is not suitable for arbitrary instruments or investment conclusions without
additional data validation. Use GLD data consistently adjusted over the test
period or restrict to a period without relevant corporate actions. Increasing
`--slippage-bps` requires a NEW experiment database.

## Alpaca paper setup

1. Create two separate paper accounts in Alpaca, each with $200 simulated cash,
   no positions and no outstanding orders. The runner rejects shared account IDs
   or a fresh account with the default $100,000 balance.
2. Generate paper API keys for each. Configure these four environment variables
   **locally** through your shell or secret manager (never paste keys into chat,
   source control, screenshots or issue bodies):
   `CONTINUATION_API_KEY_ID`, `CONTINUATION_API_SECRET_KEY`,
   `REVERSAL_API_KEY_ID`, `REVERSAL_API_SECRET_KEY`.
   `.env` is not automatically loaded.
3. Run a read-only order preview:

```sh
python3 -m tradebot paper --db runs/paper.sqlite
```

4. To enable orders **only on Alpaca's paper service**:

```sh
python3 -m tradebot paper --db runs/paper.sqlite --submit-paper --loop
```

The process polls every five minutes. Ordinary strategy decisions occur once per
US trading session, on the first valid poll >=30 minutes after the exchange open.
Use Alpaca's calendar/clock, not Istanbul wall-clock assumptions. All strategies
consume the same snapshot; API submissions are sequential and fills may differ.
No missed historical trades are inserted when a runner starts late.

Use the SAME database after restarting. Only one process may own its lock.
Run on an awake machine with working network access. This bundle does not install
a service or claim 24/7 operation. Unexpected errors stop the process for review.
Partial/unfilled orders also stop a poll/process until a subsequent run reconciles
them; a service supervisor/alerts remain a deployment task.

## Execution and monitoring

- Hardcoded paper host: `https://paper-api.alpaca.markets`.
- Real broker paper fills are authoritative; the offline simulator is separate.
- Fractional market/day orders, no extended hours, no shorts, no use of margin
  buying power. Available cash retains a $1 buffer for buys.
- Minimum normal adjustment $5; full exits can be smaller. Target 50% is a sizing
  objective, not an exact hard exposure cap after price movement/slippage.
- Persisted 15% peak-to-current-equity drawdown shutdown per strategy, checked
  during valid execution polls. It attempts a full exit and never auto-resets.
  This is not a guaranteed loss limit; outages and gaps can exceed it.
- Quote age <=120 seconds, noncrossed market, spread <=50bp. Missing prior oil
  sessions or unsupported fractional assets stop execution. IEX is a single
  exchange; it is not consolidated NBBO or a complete market view.
- Immutable daily decisions, deterministic client order IDs, write-ahead intents,
  broker reconciliation. Unknown submissions never get blindly retried.
- Account equity/positions/inputs live in `observations`; returned broker order
  status, cumulative filled quantity and average fill price live in `intents`.
  Partial fills are not locally invented. No separate fill-by-fill activity feed yet.

View actual orders, holdings and P&L in each Alpaca paper dashboard. The `report`
command is for OFFLINE simulator databases; do not use it on `paper.sqlite`.
The journal contains account identifiers: keep `runs/` private and backed up.

## Recovery

If a submission times out, the runner queries its deterministic client order ID
on restart. If Alpaca finds it, its real status is recorded. If not found, it
stops for manual review rather than risk duplication. Do not delete the journal
or place compensating trades blindly. Inspect Alpaca orders/account activity,
record the resolution, and only then resolve the specific journal entry.
Unexpected positions or changing account IDs require review. Dedicate these paper
accounts to this experiment; don't place manual trades or reset their balances.

## Current status

The starter implementation is integrated in this repository. Offline tests and a
synthetic demo pass. No credentials were supplied, no Alpaca orders were sent,
and no hosted runner is active. See `docs/status.md` for next steps.
