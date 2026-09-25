"""Alpaca market data and paper-only execution. Hosts cannot be overridden."""
from datetime import datetime, timedelta, timezone
import json
import math
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def parse_time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware")
    return result


class ApiError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Alpaca HTTP {status}")


class Alpaca:
    def __init__(self, prefix="APCA"):
        self.key = os.environ.get(prefix + "_API_KEY_ID")
        self.secret = os.environ.get(prefix + "_API_SECRET_KEY")
        if not self.key or not self.secret:
            raise ValueError(f"Set {prefix}_API_KEY_ID and {prefix}_API_SECRET_KEY locally; use paper keys")

    def get(self, path, params=None, *, data=False):
        base = "https://data.alpaca.markets" if data else "https://paper-api.alpaca.markets"
        request = Request(base + path + ("?" + urlencode(params) if params else ""),
                          headers={"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret})
        try:
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as exc:
            raise ApiError(exc.code) from None
        except URLError:
            raise RuntimeError("Alpaca read failed") from None

    def submit_paper(self, payload):
        request = Request("https://paper-api.alpaca.markets/v2/orders",
                          data=json.dumps(payload).encode(), method="POST",
                          headers={"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret,
                                   "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError):
            # Acceptance is unknown: caller has already journaled the attempt.
            raise RuntimeError("Paper submission outcome unknown; reconcile by client_order_id before proceeding") from None

    def snapshot(self, lookback):
        clock = self.get("/v2/clock")
        now = parse_time(clock["timestamp"])
        if abs((datetime.now(timezone.utc) - now).total_seconds()) > 120:
            raise ValueError("Broker clock is stale")
        if not clock["is_open"]:
            return None
        today = now.astimezone(NY).date()
        calendar = self.get("/v2/calendar", {"start": str(today - timedelta(days=max(45, lookback * 4))), "end": str(today)})
        dates = [d["date"] for d in calendar if d["date"] < str(today)]
        current = next(d for d in calendar if d["date"] == str(today))
        opening = datetime.fromisoformat(f"{today}T{current['open']}").replace(tzinfo=NY)
        if now < opening + timedelta(minutes=30):
            return None
        if len(dates) < lookback + 1:
            raise ValueError("Insufficient calendar history")
        expected = dates[-lookback - 1:]
        params = {"symbols": "USO", "timeframe": "1Day", "start": expected[0],
                  "end": today.isoformat(), "feed": "iex", "adjustment": "split", "limit": 10000}
        bars = []
        seen_tokens = set()
        while True:
            response = self.get("/v2/stocks/bars", params, data=True)
            bars.extend((response.get("bars") or {}).get("USO", []))
            token = response.get("next_page_token")
            if not token:
                break
            if token in seen_tokens:
                raise ValueError("Repeated data pagination token")
            seen_tokens.add(token)
            params["page_token"] = token
        by_date = {}
        for bar in bars:
            day = str(parse_time(bar["t"]).astimezone(NY).date())
            if day in by_date:
                raise ValueError("Duplicate oil bar")
            by_date[day] = float(bar["c"])
        if any(d not in by_date for d in expected):
            raise ValueError("Missing prior-session IEX bars; refusing to use stale history")
        quote = self.get("/v2/stocks/GLD/quotes/latest", {"feed": "iex"}, data=True)["quote"]
        observed = parse_time(quote["t"])
        bid, ask = float(quote["bp"]), float(quote["ap"])
        validate_quote(now, observed, bid, ask)
        return str(today), [by_date[d] for d in expected], bid, ask, {
            "source": "alpaca_iex", "observed_at": now.isoformat(), "quote_timestamp": quote["t"],
            "oil_symbol": "USO", "gold_symbol": "GLD", "history_dates": expected,
            "oil_adjustment": "split", "execution": "local_shadow_not_broker_fill"}


def validate_quote(now, observed, bid, ask):
    age = (now - observed).total_seconds()
    if not 0 <= age <= 120:
        raise ValueError("Gold quote is stale or future-dated")
    if not all(math.isfinite(x) and x > 0 for x in (bid, ask)) or ask < bid:
        raise ValueError("Gold quote invalid")
    if (ask - bid) / ((bid + ask) / 2) > 0.005:
        raise ValueError("Gold spread exceeds 50 basis points")
