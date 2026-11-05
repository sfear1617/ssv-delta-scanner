"""Read-only Delta Exchange India market data, including date-specific historical OHLC."""
import time
from ssv import Candle

BASE = "https://api.india.delta.exchange"
TIMEFRAMES = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


def as_float(value, default=0):
    try: return float(value)
    except (ValueError, TypeError): return default


def unwrap(payload):
    if not isinstance(payload, dict) or not payload.get("success"):
        raise ValueError("Delta API returned an unsuccessful response")
    return payload.get("result")


async def top_perpetuals(client, limit=100):
    """Top active perpetuals ranked by their CURRENT 24h USD turnover."""
    resp = await client.get(BASE + "/v2/tickers", params={"contract_types": "perpetual_futures"})
    resp.raise_for_status()
    tickers = unwrap(resp.json())
    if not isinstance(tickers, list): raise ValueError("Unexpected Delta ticker payload")
    eligible = []
    for t in tickers:
        if not isinstance(t, dict): continue
        symbol, typ = t.get("symbol"), t.get("contract_type")
        if typ != "perpetual_futures" or not symbol: continue
        turnover = as_float(t.get("turnover_usd"), -1)
        if turnover < 0: continue
        eligible.append({"symbol": symbol, "turnover_usd": turnover,
                         "price": as_float(t.get("close")),
                         "change_24h": as_float(t.get("ltp_change_24h")),
                         "volume": as_float(t.get("volume"))})
    eligible.sort(key=lambda x: (-x["turnover_usd"], x["symbol"]))
    return eligible[:limit]


async def historical_candles(client, symbol, timeframe, *, end_time=None, lookback=1200):
    """Fetch up to lookback closed candles ending at end_time (UNIX seconds).

    We partition into windows of <= 1400 bars because Delta documents a 2000-bar
    limit per call. A complete 1200-bar warm-up plus the target day is fetched
    even when the selected historical day is a year in the past.
    """
    seconds = TIMEFRAMES[timeframe]
    end = int(end_time if end_time is not None else time.time())
    start = end - (lookback + 6) * seconds
    result = []
    window = 1400 * seconds
    cursor = start
    while cursor < end:
        until = min(end, cursor + window)
        resp = await client.get(BASE + "/v2/history/candles",
            params={"resolution": timeframe, "symbol": symbol, "start": cursor, "end": until})
        resp.raise_for_status()
        raw = unwrap(resp.json())
        if not isinstance(raw, list): raise ValueError("Unexpected OHLC response")
        for row in raw:
            if not isinstance(row, dict): continue
            ts = int(row["time"])
            # Only fully closed bars, relative to both target timestamp and now.
            if ts + seconds > min(end, int(time.time())): continue
            result.append(Candle(time=ts * 1000, open=float(row["open"]),
                      high=float(row["high"]), low=float(row["low"]), close=float(row["close"])))
        cursor = until
    result.sort(key=lambda c:c.time)
    dedup = {c.time:c for c in result}
    return list(dedup.values())[-lookback:]
