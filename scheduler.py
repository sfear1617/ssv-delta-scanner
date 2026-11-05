"""Background scheduler: fires every 4-hour candle close and sends Telegram alerts.

The 4h candle closes at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC.
We wait 90 seconds after the close so Delta's API has time to publish the bar,
then run a full scan (both bearish and bullish) across the top-100 perpetuals.

Environment variables (all optional with sensible defaults)
-----------------------------------------------------------
SCHEDULER_TIMEFRAME         Timeframe to auto-scan.  Default: 4h
SCHEDULER_STRENGTH          Pivot strength.          Default: 3
SCHEDULER_MAX_ACTIVE        Active swing pool size.  Default: 50
SCHEDULER_SIGNAL_MODE       sweep_candle | original_strict.  Default: sweep_candle
SCHEDULER_RECENT            Candles back to check.   Default: 1  (latest closed only)
SCHEDULER_MIN_TURNOVER_USD  Only alert if 24h USD turnover >= this.  Default: 0
TELEGRAM_ENABLED            Set to 'false' to disable alerts.  Default: true
"""
import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

import httpx

from delta_api import top_perpetuals, historical_candles, TIMEFRAMES
from ssv import bearish_signals, bullish_signals
from telegram_alert import send_bulk_alerts, send_summary

log = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30), name="IST")

# ── config helpers ──────────────────────────────────────────────────────────

def _env(key: str, default: str) -> str:
    return os.environ.get(key, default).strip()

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except ValueError:
        return default

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except ValueError:
        return default

def _telegram_enabled() -> bool:
    return _env("TELEGRAM_ENABLED", "true").lower() not in ("false", "0", "no")


# ── core scan ────────────────────────────────────────────────────────────────

async def run_scan_and_alert(*, timeframe: str | None = None) -> dict:
    """Full scan + Telegram dispatch. Returns a summary dict."""
    tf = timeframe or _env("SCHEDULER_TIMEFRAME", "4h")
    if tf not in TIMEFRAMES:
        log.error("Unknown timeframe '%s' in scheduler config", tf)
        return {}

    strength = _env_int("SCHEDULER_STRENGTH", 3)
    max_active = _env_int("SCHEDULER_MAX_ACTIVE", 50)
    mode = _env("SCHEDULER_SIGNAL_MODE", "sweep_candle")
    recent = _env_int("SCHEDULER_RECENT", 1)
    min_turnover = _env_float("SCHEDULER_MIN_TURNOVER_USD", 0)

    log.info("[Scheduler] Starting %s scan (strength=%d, mode=%s, recent=%d)",
             tf, strength, mode, recent)

    seconds = TIMEFRAMES[tf]
    timeout = httpx.Timeout(40, connect=10)

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": "SSV-Delta-Scheduler/1.0"},
        ) as client:
            products = await top_perpetuals(client, 100)
            if not products:
                log.warning("[Scheduler] No products returned from Delta.")
                return {}

            # Apply minimum turnover filter early to reduce noise
            if min_turnover > 0:
                products = [p for p in products if p["turnover_usd"] >= min_turnover]

            sem = asyncio.Semaphore(5)

            async def process(t: dict, rank: int):
                async with sem:
                    for attempt in range(2):
                        try:
                            candles = await historical_candles(
                                client, t["symbol"], tf, lookback=1200
                            )
                            if len(candles) < 2 * strength + 2:
                                return [], None

                            matches = []

                            # ── Bearish signals ──────────────────────────
                            for s in bearish_signals(
                                candles, strength=strength, max_active=max_active, mode=mode
                            ):
                                age = len(candles) - 1 - s["bar_index"]
                                if age >= recent:
                                    continue
                                closed_at = s["time"] // 1000 + seconds
                                matches.append({
                                    **s,
                                    "symbol": t["symbol"],
                                    "direction": "bearish",
                                    "candles_ago": age,
                                    "confirmed_at": closed_at * 1000,
                                    "timeframe": tf,
                                    "rank": rank,
                                    "turnover_usd": t["turnover_usd"],
                                    "price": t["price"],
                                    "change_24h": t["change_24h"],
                                })

                            # ── Bullish signals ──────────────────────────
                            for s in bullish_signals(
                                candles, strength=strength, max_active=max_active, mode=mode
                            ):
                                age = len(candles) - 1 - s["bar_index"]
                                if age >= recent:
                                    continue
                                closed_at = s["time"] // 1000 + seconds
                                matches.append({
                                    **s,
                                    "symbol": t["symbol"],
                                    "direction": "bullish",
                                    "candles_ago": age,
                                    "confirmed_at": closed_at * 1000,
                                    "timeframe": tf,
                                    "rank": rank,
                                    "turnover_usd": t["turnover_usd"],
                                    "price": t["price"],
                                    "change_24h": t["change_24h"],
                                })

                            return matches, None

                        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                            if attempt == 0:
                                await asyncio.sleep(0.8)
                                continue
                            return [], {"symbol": t["symbol"], "reason": str(exc)[:160]}
                        except Exception as exc:
                            return [], {"symbol": t["symbol"], "reason": str(exc)[:160]}

            checked = await asyncio.gather(
                *(process(t, i + 1) for i, t in enumerate(products))
            )

    except Exception as exc:
        log.error("[Scheduler] Scan failed: %s", exc)
        return {}

    signals = [s for results, _ in checked for s in results]
    errors = [e for _, e in checked if e]
    signals.sort(key=lambda s: (-s["confirmed_at"], s["rank"]))

    scan_meta = {
        "timeframe": tf,
        "scanned": len(products) - len(errors),
        "eligible": len(products),
        "failures": len(errors),
        "signal_count": len(signals),
    }

    log.info(
        "[Scheduler] Scan complete: %d signals across %d markets (%d errors).",
        len(signals), scan_meta["scanned"], len(errors),
    )

    # ── Telegram dispatch ────────────────────────────────────────────────────
    if _telegram_enabled() and signals:
        # Send a summary first, then individual alerts (most-recent first)
        await send_summary(signals, tf, scan_meta)
        await asyncio.sleep(1)
        result = await send_bulk_alerts(signals, tf)
        log.info("[Scheduler] Alerts: sent=%d skipped=%d failed=%d",
                 result["sent"], result["skipped"], result["failed"])
    elif not _telegram_enabled():
        log.info("[Scheduler] Telegram disabled — skipping alerts.")
    else:
        log.info("[Scheduler] No signals found — no alerts sent.")

    return {**scan_meta, "signals": signals}


# ── scheduler loop ───────────────────────────────────────────────────────────

def _next_4h_candle_close_utc() -> datetime:
    """Return the next 4h bar close in UTC, plus 90s buffer for API publish lag."""
    now = datetime.now(timezone.utc)
    # 4h closes: 00, 04, 08, 12, 16, 20 UTC
    closes_today = [now.replace(hour=h, minute=0, second=0, microsecond=0) for h in range(0, 24, 4)]
    future = [t for t in closes_today if t > now]
    if not future:
        # next close is 00:00 UTC tomorrow
        base = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        base = future[0]
    return base + timedelta(seconds=90)   # 90s after close for API lag


async def scheduler_loop() -> None:
    """Runs forever, sleeping until each 4h candle close, then scanning."""
    log.info("[Scheduler] Started. Waiting for next 4h candle close…")
    while True:
        fire_at = _next_4h_candle_close_utc()
        now = datetime.now(timezone.utc)
        wait = (fire_at - now).total_seconds()
        ist_fire = fire_at.astimezone(IST).strftime("%d %b %Y  %H:%M:%S IST")
        log.info("[Scheduler] Next scan at %s (in %.0f s)", ist_fire, wait)
        await asyncio.sleep(max(wait, 0))
        try:
            await run_scan_and_alert()
        except Exception as exc:
            log.error("[Scheduler] Unhandled error in scan cycle: %s", exc)
        # small guard so we don't fire twice for the same close
        await asyncio.sleep(5)
