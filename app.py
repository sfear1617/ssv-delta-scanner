"""Delta SSV scanner — bearish + bullish sweep detection with Telegram alerts."""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from delta_api import top_perpetuals, historical_candles, TIMEFRAMES
from ssv import bearish_signals, bullish_signals
from scheduler import scheduler_loop, run_scan_and_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Start the background 4h scheduler when the app boots."""
    task = asyncio.create_task(scheduler_loop())
    log.info("4h SSV scheduler started.")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    log.info("4h SSV scheduler stopped.")


app = FastAPI(
    title="SSV Delta | Bearish + Bullish Intelligence",
    version="1.3.0",
    lifespan=lifespan,
)

@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.3.0"}


def date_bounds(date_text: str, *, today=None):
    """Selected date is IST. A 1-year calendar window, inclusive of both ends."""
    try: chosen = date.fromisoformat(date_text)
    except (ValueError, TypeError): raise ValueError("Select a valid date (YYYY-MM-DD)")
    today = today or datetime.now(IST).date()
    try: earliest = today.replace(year=today.year - 1)
    except ValueError: earliest = today.replace(year=today.year - 1, day=28)
    if not earliest <= chosen <= today:
        raise ValueError(f"Backtest date must be between {earliest} and {today} (IST)")
    start = datetime.combine(chosen, dtime.min, tzinfo=IST)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())


def signal_close_time(signal, seconds):
    return signal["time"] // 1000 + seconds


@app.get("/api/scan")
async def scan(timeframe: str = "4h", recent: int = Query(3, ge=1, le=60),
               strength: int = Query(3, ge=1, le=20), max_active: int = Query(50, ge=5, le=150),
               backtest_date: str | None = None, signal_mode: str = "sweep_candle",
               direction: str = "bearish"):
    """Scan for bearish or bullish sweep signals.

    direction: 'bearish' | 'bullish' | 'both'
    """
    if timeframe not in TIMEFRAMES:
        raise HTTPException(400, "Unsupported timeframe")
    if signal_mode not in ("sweep_candle", "original_strict"):
        raise HTTPException(400, "Unsupported signal mode")
    if direction not in ("bearish", "bullish", "both"):
        raise HTTPException(400, "direction must be bearish, bullish, or both")
    historical = bool(backtest_date)
    try:
        day_start, day_end = date_bounds(backtest_date) if historical else (None, None)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    timeout = httpx.Timeout(28, connect=10)
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": "SSV-Delta-Scanner/1.3"},
        ) as client:
            products = await top_perpetuals(client, 100)
            if not products:
                raise HTTPException(502, "Delta returned no eligible perpetual contracts")
            sem = asyncio.Semaphore(5)

            async def process(t, rank):
                async with sem:
                    for attempt in range(2):
                        try:
                            candles = await historical_candles(
                                client, t["symbol"], timeframe,
                                end_time=day_end if historical else None, lookback=1200,
                            )
                            if len(candles) < 2 * strength + 2:
                                raise ValueError("Not enough completed candles")
                            matches = []

                            # Bearish
                            if direction in ("bearish", "both"):
                                for s in bearish_signals(candles, strength=strength,
                                                         max_active=max_active, mode=signal_mode):
                                    closed_at = signal_close_time(s, TIMEFRAMES[timeframe])
                                    if historical:
                                        if not (day_start <= closed_at < day_end):
                                            continue
                                    else:
                                        age = len(candles) - 1 - s["bar_index"]
                                        if age >= recent:
                                            continue
                                    age = len(candles) - 1 - s["bar_index"]
                                    matches.append({
                                        **s,
                                        "symbol": t["symbol"], "direction": "bearish",
                                        "candles_ago": age, "confirmed_at": closed_at * 1000,
                                        "timeframe": timeframe, "rank": rank,
                                        "turnover_usd": t["turnover_usd"], "price": t["price"],
                                        "change_24h": t["change_24h"],
                                    })

                            # Bullish
                            if direction in ("bullish", "both"):
                                for s in bullish_signals(candles, strength=strength,
                                                         max_active=max_active, mode=signal_mode):
                                    closed_at = signal_close_time(s, TIMEFRAMES[timeframe])
                                    if historical:
                                        if not (day_start <= closed_at < day_end):
                                            continue
                                    else:
                                        age = len(candles) - 1 - s["bar_index"]
                                        if age >= recent:
                                            continue
                                    age = len(candles) - 1 - s["bar_index"]
                                    matches.append({
                                        **s,
                                        "symbol": t["symbol"], "direction": "bullish",
                                        "candles_ago": age, "confirmed_at": closed_at * 1000,
                                        "timeframe": timeframe, "rank": rank,
                                        "turnover_usd": t["turnover_usd"], "price": t["price"],
                                        "change_24h": t["change_24h"],
                                    })

                            return matches, None
                        except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                            if attempt == 0:
                                await asyncio.sleep(.7)
                                continue
                            return [], {"symbol": t["symbol"], "reason": str(e)[:160]}
                        except Exception as e:
                            return [], {"symbol": t["symbol"], "reason": str(e)[:160]}

            checked = await asyncio.gather(*(process(t, i + 1) for i, t in enumerate(products)))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, "Delta market-data connection failed: " + str(e)[:230])

    matches = [s for signals, _ in checked for s in signals]
    errors = [err for _, err in checked if err]
    matches.sort(key=lambda s: (-s["confirmed_at"], s["rank"]))
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "timeframe": timeframe, "recent": recent, "signal_mode": signal_mode,
        "direction": direction,
        "backtest_date": backtest_date if historical else None,
        "backtest_timezone": "Asia/Kolkata",
        "ranking_basis": "Current 24h USD turnover, not historical ranking",
        "target": 100, "eligible": len(products), "scanned": len(products) - len(errors),
        "failures": errors, "signals": matches,
        "top_symbols": [
            {"symbol": p["symbol"], "rank": i + 1, "turnover_usd": p["turnover_usd"]}
            for i, p in enumerate(products)
        ],
    }


@app.post("/api/scan/trigger")
async def trigger_scan(timeframe: str = "4h"):
    """Manually trigger a scheduler scan (also sends Telegram alerts).

    Useful to test your Telegram setup after deployment.
    """
    if timeframe not in TIMEFRAMES:
        raise HTTPException(400, "Unsupported timeframe")
    result = await run_scan_and_alert(timeframe=timeframe)
    return {
        "triggered": True,
        "timeframe": timeframe,
        "signals_found": result.get("signal_count", 0),
        "scanned": result.get("scanned", 0),
    }
