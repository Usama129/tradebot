"""Two separate Alpaca paper accounts driven by the same immutable signal frame."""
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import json
import math
import sqlite3

from .alpaca import ApiError
from .core import signals

NAMES = ("oil_continuation", "oil_reversal")
TERMINAL = {"filled", "canceled", "expired", "rejected", "replaced"}


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite broker value")
    return result


def make_order(name, session, target, account, positions, mid, config, risk=False):
    if any(p["symbol"] != "GLD" or p["side"] != "long" for p in positions):
        raise ValueError("Dedicated account contains an unexpected position")
    qty = sum(number(p["qty"]) for p in positions)
    equity, cash = number(account["equity"]), number(account["cash"])
    if equity <= 0 or cash < -0.01 or qty < 0:
        raise ValueError("Account has invalid equity, borrowing or negative quantity")
    delta = target * equity - qty * mid
    if abs(delta) < config.min_trade and not (target == 0 and qty > 0):
        return None
    payload = {"symbol": "GLD", "type": "market", "time_in_force": "day",
               "extended_hours": False,
               "client_order_id": f"tb01-{name}-{session}" + ("-risk" if risk else "")}
    if delta > 0:
        amount = min(delta, cash - 1.0)  # Reserve cash; ignore margin buying_power.
        if amount < config.min_trade:
            return None
        payload.update(side="buy", notional=str(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)))
    else:
        amount = qty if target == 0 else min(qty, -delta / mid)
        rounded = Decimal(str(amount)).quantize(Decimal("0.000000001"), rounding=ROUND_DOWN)
        if rounded <= 0:
            return None
        payload.update(side="sell", qty=str(rounded))
    return payload


class PaperRunner:
    def __init__(self, path, config, clients):
        if set(clients) != set(NAMES):
            raise ValueError("Exactly two strategy paper accounts required")
        self.config, self.clients = config, clients
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS setup (signature TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS accounts (strategy TEXT PRIMARY KEY, account_id TEXT UNIQUE,
                peak REAL NOT NULL, halted INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS intents (client_id TEXT PRIMARY KEY, strategy TEXT NOT NULL,
                session TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, response TEXT);
            CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL,
                strategy TEXT NOT NULL, session TEXT NOT NULL, equity REAL NOT NULL,
                cash REAL NOT NULL, positions TEXT NOT NULL, evidence TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS decisions (strategy TEXT NOT NULL, session TEXT NOT NULL,
                target REAL NOT NULL, PRIMARY KEY(strategy, session));
        """)
        signature = json.dumps({"version": "0.1.0-paper", "config": asdict(config)}, sort_keys=True)
        row = self.db.execute("SELECT signature FROM setup").fetchone()
        if row and row[0] != signature:
            raise ValueError("Paper experiment config changed; review and start a new experiment")
        if not row:
            self.db.execute("INSERT INTO setup VALUES (?)", (signature,))
            self.db.commit()

    def close(self):
        self.db.close()

    def preflight(self):
        records = {}
        for name, client in self.clients.items():
            account = client.get("/v2/account")
            if account["status"] != "ACTIVE" or account.get("trading_blocked") or account.get("account_blocked"):
                raise ValueError(f"{name}: account is not active for trading")
            positions = client.get("/v2/positions")
            orders = client.get("/v2/orders", {"status": "open", "limit": 500})
            saved = self.db.execute("SELECT * FROM accounts WHERE strategy=?", (name,)).fetchone()
            if saved and saved["account_id"] != account["id"]:
                raise ValueError("Account identity changed; do not reuse the journal")
            if not saved and (positions or orders or abs(number(account["equity"]) - self.config.initial_cash) > 0.01):
                raise ValueError(f"{name}: start with an empty paper account containing exactly $200 simulated equity")
            asset = client.get("/v2/assets/GLD")
            if not asset.get("tradable") or not asset.get("fractionable"):
                raise ValueError("GLD fractional trading unavailable")
            records[name] = account
        if len({a["id"] for a in records.values()}) != len(records):
            raise ValueError("Strategies must use different Alpaca paper account IDs")
        with self.db:
            for name, account in records.items():
                self.db.execute("INSERT OR IGNORE INTO accounts VALUES (?, ?, ?, 0)",
                                (name, account["id"], number(account["equity"])))

    def reconcile(self, name):
        client = self.clients[name]
        for row in self.db.execute("SELECT * FROM intents WHERE strategy=?", (name,)).fetchall():
            if row["status"] in TERMINAL:
                continue
            try:
                order = client.get("/v2/orders:by_client_order_id", {"client_order_id": row["client_id"]})
            except ApiError as exc:
                if exc.status == 404:
                    raise RuntimeError("Journaled order not found; manual review required. Never blindly resubmit.") from None
                raise
            with self.db:
                self.db.execute("UPDATE intents SET status=?, response=? WHERE client_id=?",
                                (order["status"], json.dumps(order), row["client_id"]))
        if client.get("/v2/orders", {"status": "open", "limit": 500}):
            raise RuntimeError(f"{name}: open/partially filled order; waiting for reconciliation")

    def tick(self, snapshot, submit=False):
        session, closes, bid, ask, evidence = snapshot
        move, targets = signals(closes, self.config)
        outputs = []
        for name, client in self.clients.items():
            self.reconcile(name)
            account = client.get("/v2/account")
            if account["status"] != "ACTIVE" or account.get("trading_blocked") or account.get("account_blocked"):
                raise ValueError("Paper account blocked")
            positions = client.get("/v2/positions")
            saved = self.db.execute("SELECT * FROM accounts WHERE strategy=?", (name,)).fetchone()
            if not saved or account["id"] != saved["account_id"]:
                raise ValueError("Run preflight with the correct account")
            equity = number(account["equity"])
            peak = max(saved["peak"], equity)
            halted = bool(saved["halted"] or 1 - equity / peak >= self.config.stop_drawdown)
            target = 0.0 if halted else targets[name]
            payload = make_order(name, session, target, account, positions, (bid + ask) / 2, self.config, halted)
            # Risk exits may bypass the ordinary once-per-day decision, but not duplicate an intent.
            done = self.db.execute("SELECT 1 FROM decisions WHERE strategy=? AND session=?", (name, session)).fetchone()
            if done and not halted:
                payload = None
            if payload and self.db.execute("SELECT 1 FROM intents WHERE client_id=?", (payload["client_order_id"],)).fetchone():
                payload = None
            with self.db:
                self.db.execute("UPDATE accounts SET peak=?, halted=? WHERE strategy=?", (peak, halted, name))
                self.db.execute("INSERT INTO observations VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)",
                                (datetime.now(timezone.utc).isoformat(), name, session, equity, number(account["cash"]),
                                 json.dumps(positions), json.dumps({**evidence, "oil_return": move, "oil_closes": closes,
                                                                 "bid": bid, "ask": ask, "execution": "alpaca_paper"})))
            outputs.append({"strategy": name, "equity": equity, "halted": halted,
                            "mode": "submit_paper" if submit else "dry_run", "planned_order": payload})
            if submit:
                with self.db:
                    self.db.execute("INSERT OR IGNORE INTO decisions VALUES (?, ?, ?)", (name, session, target))
                    if payload:
                        self.db.execute("INSERT INTO intents VALUES (?, ?, ?, ?, 'sending', NULL)",
                                        (payload["client_order_id"], name, session, json.dumps(payload)))
                if payload:
                    if not client.get("/v2/clock")["is_open"]:
                        raise RuntimeError("Market closed before submission; review journal before next run")
                    response = client.submit_paper(payload)
                    with self.db:
                        self.db.execute("UPDATE intents SET status=?, response=? WHERE client_id=?",
                                        (response["status"], json.dumps(response), payload["client_order_id"]))
                    outputs[-1]["order_status"] = response["status"]
        return outputs
