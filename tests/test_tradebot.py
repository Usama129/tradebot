from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from tradebot.alpaca import ApiError, validate_quote
from tradebot.core import Config, Ledger, signals
from tradebot.__main__ import replay
from tradebot.paper import PaperRunner


UP = [100, 101, 102, 103, 104, 105]
DOWN = list(reversed(UP))
FRAME = ("2026-09-25", UP, 200.0, 200.1, {"source": "mock"})


class FakeAlpaca:
    def __init__(self, account_id):
        self.account = {"id": account_id, "equity": "200", "cash": "200", "status": "ACTIVE"}
        self.positions = []
        self.orders = {}
        self.submissions = []
        self.lose_response = False

    def get(self, path, params=None):
        if path == "/v2/account":
            return self.account
        if path == "/v2/positions":
            return self.positions
        if path == "/v2/assets/GLD":
            return {"tradable": True, "fractionable": True}
        if path == "/v2/clock":
            return {"is_open": True}
        if path == "/v2/orders":
            return [o for o in self.orders.values() if o["status"] not in ("filled", "rejected")]
        if path == "/v2/orders:by_client_order_id":
            if params["client_order_id"] not in self.orders:
                raise ApiError(404)
            return self.orders[params["client_order_id"]]
        raise AssertionError(path)

    def submit_paper(self, payload):
        self.submissions.append(payload)
        order = {**payload, "id": "mock-order", "status": "filled", "filled_qty": "0.5", "filled_avg_price": "200"}
        self.orders[payload["client_order_id"]] = order
        if self.lose_response:
            raise RuntimeError("Simulated response lost after acceptance")
        return order


class CoreTests(unittest.TestCase):
    def test_opposing_signals(self):
        _, up = signals(UP, Config())
        _, down = signals(DOWN, Config())
        self.assertEqual((up["oil_continuation"], up["oil_reversal"]), (.5, 0))
        self.assertEqual((down["oil_continuation"], down["oil_reversal"]), (0, .5))

    def test_isolation_restart_and_costs(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "state.db")
            ledger = Ledger(path, Config(), "synthetic")
            self.assertTrue(ledger.step(*FRAME))
            initial = ledger.report()
            self.assertLess(next(p for p in initial["portfolios"] if p["strategy"] == "oil_continuation")["equity"], 200)
            self.assertEqual(next(p for p in initial["portfolios"] if p["strategy"] == "oil_reversal")["qty"], 0)
            ledger.close()
            ledger = Ledger(path, Config(), "synthetic")
            self.assertFalse(ledger.step(*FRAME))
            self.assertEqual(initial, ledger.report())
            ledger.close()
            with self.assertRaises(ValueError):
                Ledger(path, Config(), "historical")

    def test_halt_persists(self):
        ledger = Ledger(":memory:", Config(), "synthetic")
        ledger.step(*FRAME)
        ledger.step("2026-09-28", UP, 100, 100, {})
        ledger.step("2026-09-29", UP, 220, 220, {})
        book = ledger.db.execute("SELECT * FROM books WHERE strategy='oil_continuation'").fetchone()
        self.assertEqual((book["halted"], book["qty"]), (1, 0))
        ledger.close()

    def test_no_current_close_lookahead(self):
        rows = [{"date": f"2026-09-{i+1:02d}", "oil_close": 100, "gold_open": 200} for i in range(7)]
        rows[-1]["oil_close"] = 10000
        ledger = Ledger(":memory:", Config(), "synthetic")
        replay(rows, ledger, "test")
        self.assertEqual(ledger.db.execute("SELECT qty FROM books WHERE strategy='oil_continuation'").fetchone()[0], 0)
        ledger.close()

    def test_quote_validation(self):
        now = datetime.now(timezone.utc)
        for observed, bid, ask in [(now - timedelta(minutes=3), 200, 201), (now, 201, 200), (now, 200, 220), (now, float('nan'), 200)]:
            with self.assertRaises(ValueError):
                validate_quote(now, observed, bid, ask)


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "paper.db")
        self.a, self.b = FakeAlpaca("a"), FakeAlpaca("b")
        self.clients = {"oil_continuation": self.a, "oil_reversal": self.b}
        self.runner = PaperRunner(self.path, Config(), self.clients)

    def tearDown(self):
        self.runner.close()
        self.temp.cleanup()

    def test_same_account_rejected(self):
        self.b.account["id"] = "a"
        with self.assertRaises(ValueError):
            self.runner.preflight()
        self.assertFalse(self.a.submissions)

    def test_initial_capital_must_match(self):
        self.a.account["equity"] = "100000"
        with self.assertRaises(ValueError):
            self.runner.preflight()

    def test_dry_run_does_not_submit_or_consume_day(self):
        self.runner.preflight()
        self.runner.tick(FRAME)
        self.assertFalse(self.a.submissions)
        self.runner.tick(FRAME, True)
        self.runner.tick(FRAME, True)
        self.assertEqual(len(self.a.submissions), 1)
        self.assertFalse(self.b.submissions)

    def test_response_loss_then_restart_never_duplicates(self):
        self.runner.preflight()
        self.a.lose_response = True
        with self.assertRaises(RuntimeError):
            self.runner.tick(FRAME, True)
        self.runner.close()
        self.runner = PaperRunner(self.path, Config(), self.clients)
        self.runner.preflight()
        self.runner.tick(FRAME, True)
        self.assertEqual(len(self.a.submissions), 1)
        stored = self.runner.db.execute("SELECT response FROM intents").fetchone()[0]
        self.assertEqual(json.loads(stored)["filled_avg_price"], "200")

    def test_unknown_submission_does_not_retry(self):
        self.runner.preflight()
        self.a.lose_response = True
        with self.assertRaises(RuntimeError):
            self.runner.tick(FRAME, True)
        self.a.orders.clear()
        with self.assertRaises(RuntimeError):
            self.runner.tick(FRAME, True)
        self.assertEqual(len(self.a.submissions), 1)

    def test_partial_fill_blocks_new_orders(self):
        self.runner.preflight()
        self.runner.tick(FRAME, True)
        order = next(iter(self.a.orders.values()))
        order["status"] = "partially_filled"
        self.runner.db.execute("UPDATE intents SET status='partially_filled'")
        self.runner.db.commit()
        with self.assertRaises(RuntimeError):
            self.runner.tick(("2026-09-28", DOWN, 200, 200, {}), True)
        self.assertEqual(len(self.a.submissions), 1)

    def test_reversal_uses_its_own_account(self):
        self.runner.preflight()
        self.runner.tick(("2026-09-25", DOWN, 200, 200, {}), True)
        self.assertFalse(self.a.submissions)
        self.assertEqual(len(self.b.submissions), 1)

    def test_drawdown_sells_actual_position_and_stays_halted(self):
        self.runner.preflight()
        self.a.account.update(equity="150", cash="50")
        self.a.positions = [{"symbol": "GLD", "side": "long", "qty": "0.5"}]
        self.runner.tick(FRAME, True)
        order = self.a.submissions[0]
        self.assertEqual((order["side"], order["qty"]), ("sell", "0.500000000"))
        self.a.account.update(equity="200", cash="200")
        self.a.positions = []
        self.runner.tick(("2026-09-28", UP, 200, 200, {}), True)
        self.assertEqual(len(self.a.submissions), 1)
        self.assertEqual(self.runner.db.execute("SELECT halted FROM accounts WHERE strategy='oil_continuation'").fetchone()[0], 1)

    def test_unexpected_position_rejected(self):
        self.runner.preflight()
        self.a.positions = [{"symbol": "AAPL", "side": "long", "qty": "1"}]
        with self.assertRaises(ValueError):
            self.runner.tick(FRAME, True)
        self.assertFalse(self.a.submissions)


if __name__ == "__main__":
    unittest.main()
