# Experiment 001: oil/gold sign ambiguity

## User intent

User proposes oil is guiding markets and may precede gold adjustments via inflation
and Fed expectations. User explicitly requests two or more simultaneous paper
strategies to test the ambiguity; clarified these must use Alpaca paper trading.
Initial eventual real capital $100-200, tolerable loss 25%, horizon 12-24 months.
No empirical finding about the current oil/gold relationship has been established.

## Frozen initial rules (provisional, not optimized)

Feature at session t: USO close at t-1 / USO close at t-6 - 1.
Threshold +/-2%; 50% equity allocation; GLD long or cash; no short exposure.
Continuation: buy/hold gold above +2%; otherwise exit.
Reversal: buy/hold gold below -2%; otherwise exit.
Within the band both sit in cash. Daily sizing tolerates adjustments below $5.
15% observed drawdown triggers a persistent strategy stop and attempted exit.
Execution: first valid market-hours poll >=30 minutes after open, same snapshot
for both accounts, then separate real Alpaca paper orders. Run continuously for
comparable decision timing; late startup is recorded, not backfilled.

## What this does and does not test

It tests two trading interpretations: positive vs negative lagged oil/gold sign.
It does NOT isolate inflation expectations, Fed expectations or causality.
Under a positive oil shock reversal is cash, not short gold. Therefore winning
by avoiding a decline is distinct from profiting on a short position. There is
no requirement to hold a trade for a fixed number of days: signals update daily.

USO is a futures-based oil ETF, not physical spot oil. Roll, holdings changes,
corporate actions, market hours and fund tracking can affect its returns.
GLD is a gold ETF, not directly traded spot gold. Verify instrument permissions.
Free IEX history/quotes may differ from consolidated closes and NBBO. Log feed
and adjustment policy; never silently substitute a different feed mid-experiment.
Daily aggregation may miss a minutes-long effect. A null daily result is not a
test of every possible intraday lag. Do not label this an arbitrage strategy.

## Evaluation (not yet performed on market data)

1. Validate historical data, corporate actions, session alignment and publication
   timing before using performance statistics. Current replay is an initial harness.
2. Predeclare chronological development, validation and final untouched holdout
   periods once data coverage is known. Freeze parameters before holdout evaluation.
3. Compare net returns, observed drawdown, turnover, exposure and number of oil
   events with cash and a 50% gold buy-and-hold reference. Track gain per event,
   not only win rate. Both variants share shocks, so observations are dependent.
4. Model spread, slippage, funding/FX, fees and later tax separately. Alpaca paper
   fills do not establish achievable live execution. Stress assumed slippage.
5. Report both variants including the loser. Do not pick a winner after a handful
   of trades, repeatedly tune it and call the same period out-of-sample.

## Next research extension

Add real yields, breakeven inflation expectations and dollar changes to compare
an oil-free baseline against an oil-augmented model. Respect source release times
and revisions. Do not equate a TIPS ETF price ratio with a measured breakeven or
a Treasury ETF return with Fed policy expectations. A conditional strategy can
be added as experiment 002 after the data definition and evaluation are agreed.

## Sources reviewed 2026-09-26 (Istanbul)

- https://docs.alpaca.markets/us/docs/paper-trading
- https://docs.alpaca.markets/us/reference/stockbars
- https://docs.alpaca.markets/us/reference/postorder
- https://docs.alpaca.markets/us/reference/getorderbyclientorderid
- https://docs.alpaca.markets/us/docs/fractional-trading
- https://www.gold.org/goldhub/research/gold-most-effective-commodity-investment-2021-edition
- https://www.gold.org/goldhub/research/beyond-cpi-gold-as-a-strategic-inflation-hedge
