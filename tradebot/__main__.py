import argparse
import csv
from datetime import date, timedelta
import json
import math
from pathlib import Path
import sys
import time

from .alpaca import Alpaca
from .core import Config, Ledger


def run_paper(args, config):
    import fcntl
    from .paper import PaperRunner
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    with open(args.db + ".lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another paper runner owns this journal") from None
        clients = {"oil_continuation": Alpaca("CONTINUATION"), "oil_reversal": Alpaca("REVERSAL")}
        runner = PaperRunner(args.db, config, clients)
        try:
            runner.preflight()
            while True:
                # Refresh fills even outside the execution window.
                for name in clients:
                    runner.reconcile(name)
                snapshot = clients["oil_continuation"].snapshot(config.lookback)
                result = runner.tick(snapshot, args.submit_paper) if snapshot else {"status": "outside_execution_window"}
                print(json.dumps(result), flush=True)
                if not args.loop:
                    break
                time.sleep(300)
        finally:
            runner.close()


def replay(rows, ledger, source):
    """Signal from previous closes; simulated execution at next supplied open."""
    history = []
    previous = None
    for row in rows:
        session = str(date.fromisoformat(row["date"]))
        if previous is not None and session <= previous:
            raise ValueError("CSV dates must be unique and ascending")
        oil, gold = float(row["oil_close"]), float(row["gold_open"])
        if not all(math.isfinite(x) and x > 0 for x in (oil, gold)):
            raise ValueError("CSV prices must be finite and positive")
        if len(history) >= ledger.config.lookback + 1:
            ledger.step(session, history[-ledger.config.lookback - 1:], gold, gold,
                        {"source": source, "execution": "hypothetical_next_open", "signal_cutoff": previous})
        history.append(oil)  # Today's close is never visible to today's decision.
        previous = session


def synthetic_rows():
    day = date(2025, 1, 2)
    oil, gold = 70.0, 200.0
    for i in range(120):
        while day.weekday() > 4:
            day += timedelta(days=1)
        # Artificial sign changes exercise both hypotheses; NOT market evidence.
        oil *= 1 + (0.009 if (i // 15) % 2 == 0 else -0.009)
        gold *= 1 + 0.004 * math.sin(i / 4)
        yield {"date": str(day), "oil_close": oil, "gold_open": gold}
        day += timedelta(days=1)


def main():
    parser = argparse.ArgumentParser(description="Parallel Alpaca PAPER accounts plus an offline simulator. No live trading.")
    parser.add_argument("mode", choices=("demo", "replay", "paper", "report"))
    parser.add_argument("--db", required=True)
    parser.add_argument("--csv")
    parser.add_argument("--loop", action="store_true", help="Poll Alpaca every 5 minutes; one decision/session")
    parser.add_argument("--submit-paper", action="store_true", help="Submit orders to Alpaca paper accounts")
    parser.add_argument("--slippage-bps", type=float, default=10.0)
    args = parser.parse_args()
    config = Config(slippage_bps=args.slippage_bps)
    if args.submit_paper and args.mode != "paper":
        raise ValueError("--submit-paper requires paper mode")
    if args.mode == "paper":
        run_paper(args, config)
        return
    if args.mode == "report":
        import sqlite3
        with sqlite3.connect(f"file:{Path(args.db).resolve()}?mode=ro", uri=True) as db:
            saved = json.loads(db.execute("SELECT value FROM metadata WHERE key='signature'").fetchone()[0])
        ledger = Ledger(args.db, Config(**saved["config"]), saved["mode"])
    else:
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
        mode = {"demo": "synthetic", "replay": "historical"}[args.mode]
        ledger = Ledger(args.db, config, mode)
    try:
        if args.mode == "demo":
            replay(synthetic_rows(), ledger, "SYNTHETIC_NOT_MARKET_DATA")
        elif args.mode == "replay":
            if not args.csv:
                raise ValueError("replay requires --csv with date,oil_close,gold_open")
            with open(args.csv, newline="") as handle:
                replay(csv.DictReader(handle), ledger, "user_supplied_csv")
        print(json.dumps(ledger.report(), indent=2))
    finally:
        ledger.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
