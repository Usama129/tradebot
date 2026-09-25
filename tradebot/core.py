"""Deterministic strategy decisions and atomic portfolio accounting."""
from dataclasses import asdict, dataclass
import json
import math
import sqlite3

STRATEGIES = ("oil_continuation", "oil_reversal", "gold_hold", "cash")


@dataclass(frozen=True)
class Config:
    initial_cash: float = 200.0
    allocation: float = 0.5
    shock: float = 0.02
    lookback: int = 5
    slippage_bps: float = 10.0
    fee: float = 0.0
    stop_drawdown: float = 0.15
    min_trade: float = 5.0

    def __post_init__(self):
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError("Configuration must be finite")
        if self.initial_cash <= 0 or not 0 < self.allocation <= 1:
            raise ValueError("Invalid capital/allocation")
        if not 0 < self.shock < 1 or not 0 < self.stop_drawdown < 1:
            raise ValueError("Invalid shock/drawdown")
        if type(self.lookback) is not int or self.lookback < 1:
            raise ValueError("Lookback must be a positive integer")
        if not 0 <= self.slippage_bps < 10000 or self.fee < 0 or self.min_trade < 0:
            raise ValueError("Invalid costs")


def signals(oil_closes, config):
    if len(oil_closes) < config.lookback + 1:
        raise ValueError("Insufficient oil history")
    if not all(math.isfinite(x) and x > 0 for x in oil_closes):
        raise ValueError("Invalid oil history")
    move = oil_closes[-1] / oil_closes[-config.lookback - 1] - 1
    return move, {
        "oil_continuation": config.allocation if move >= config.shock else 0.0,
        "oil_reversal": config.allocation if move <= -config.shock else 0.0,
        "gold_hold": config.allocation,
        "cash": 0.0,
    }


class Ledger:
    def __init__(self, path, config, mode):
        if mode not in ("synthetic", "historical", "shadow"):
            raise ValueError("Unknown mode")
        self.config = config
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS books (
                strategy TEXT PRIMARY KEY, cash REAL NOT NULL, qty REAL NOT NULL,
                peak REAL NOT NULL, halted INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS frames (
                session TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS marks (
                session TEXT NOT NULL, strategy TEXT NOT NULL, equity REAL NOT NULL,
                drawdown REAL NOT NULL, target REAL NOT NULL, halted INTEGER NOT NULL,
                PRIMARY KEY(session, strategy));
            CREATE TABLE IF NOT EXISTS fills (
                session TEXT NOT NULL, strategy TEXT NOT NULL, qty REAL NOT NULL,
                price REAL NOT NULL, fee REAL NOT NULL);
        """)
        signature = json.dumps({"version": "0.1.0", "config": asdict(config), "mode": mode}, sort_keys=True)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.db.execute("SELECT value FROM metadata WHERE key='signature'").fetchone()
            if existing and existing[0] != signature:
                raise ValueError("Config/mode differs: start a new database for a new experiment")
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('signature', ?)", (signature,))
            for name in STRATEGIES:
                self.db.execute("INSERT OR IGNORE INTO books VALUES (?, ?, 0, ?, 0)",
                                (name, config.initial_cash, config.initial_cash))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def step(self, session, oil_closes, bid, ask, evidence):
        from datetime import date
        date.fromisoformat(session)
        if not all(math.isfinite(x) and x > 0 for x in (bid, ask)) or ask < bid:
            raise ValueError("Invalid quote")
        move, targets = signals(oil_closes, self.config)
        mid = (bid + ask) / 2
        c = self.config
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("SELECT 1 FROM frames WHERE session=?", (session,)).fetchone():
                self.db.execute("ROLLBACK")
                return False
            last = self.db.execute("SELECT MAX(session) FROM frames").fetchone()[0]
            if last and session <= last:
                raise ValueError("Cannot insert an older session")
            payload = {"oil_return": move, "oil_closes": oil_closes, "bid": bid, "ask": ask,
                       "evidence": evidence}
            self.db.execute("INSERT INTO frames VALUES (?, ?)", (session, json.dumps(payload)))
            for book in self.db.execute("SELECT * FROM books").fetchall():
                name, cash, qty, peak, halted = tuple(book)
                equity = cash + qty * mid
                peak = max(peak, equity)
                # Passive reference portfolios have no strategy shutdown overlay.
                if name.startswith("oil_") and 1 - equity / peak >= c.stop_drawdown:
                    halted = 1
                target = 0.0 if halted else targets[name]
                desired = target * equity / mid
                if name == "gold_hold" and last is not None:
                    desired = qty  # Buy once; never rebalance the reference.
                delta = desired - qty
                if abs(delta) * mid >= c.min_trade or (desired == 0 and qty > 0):
                    price = ask * (1 + c.slippage_bps / 10000) if delta > 0 else bid * (1 - c.slippage_bps / 10000)
                    if delta > 0:
                        # Allocation accounts for execution price and fees; no borrowing.
                        delta = min(delta, max(0, (cash - c.fee) / price),
                                    max(0, (target * equity - qty * mid - c.fee) / price))
                    else:
                        delta = max(delta, -qty)
                    if abs(delta) > 1e-10:
                        if delta < 0 and cash - delta * price < c.fee:
                            raise ValueError("Insufficient cash/proceeds for modeled fee")
                        cash -= delta * price + c.fee
                        qty += delta
                        self.db.execute("INSERT INTO fills VALUES (?, ?, ?, ?, ?)",
                                        (session, name, delta, price, c.fee))
                if cash < -1e-8 or qty < -1e-8:
                    raise ValueError("Portfolio invariant violated")
                equity = cash + qty * mid
                drawdown = 1 - equity / peak
                self.db.execute("UPDATE books SET cash=?, qty=?, peak=?, halted=? WHERE strategy=?",
                                (cash, qty, peak, halted, name))
                self.db.execute("INSERT INTO marks VALUES (?, ?, ?, ?, ?, ?)",
                                (session, name, equity, drawdown, target, halted))
            self.db.execute("COMMIT")
            return True
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def report(self):
        result = []
        last = self.db.execute("SELECT MAX(session) FROM frames").fetchone()[0]
        for book in self.db.execute("SELECT * FROM books ORDER BY strategy"):
            name = book["strategy"]
            mark = self.db.execute("SELECT equity FROM marks WHERE strategy=? AND session=?", (name, last)).fetchone()
            equity = mark[0] if mark else self.config.initial_cash
            max_dd = self.db.execute("SELECT MAX(drawdown) FROM marks WHERE strategy=?", (name,)).fetchone()[0] or 0
            fills = self.db.execute("SELECT COUNT(*) FROM fills WHERE strategy=?", (name,)).fetchone()[0]
            result.append({**dict(book), "equity": round(equity, 4),
                           "return_pct": round(100 * (equity / self.config.initial_cash - 1), 4),
                           "max_observed_drawdown_pct": round(max_dd * 100, 4), "fills": fills})
        return {"experiment": json.loads(self.db.execute("SELECT value FROM metadata WHERE key='signature'").fetchone()[0]),
                "last_session": last, "portfolios": result}
