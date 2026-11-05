"""Telegram alert dispatcher for SSV sweep signals.

Required environment variables
--------------------------------
TELEGRAM_BOT_TOKEN  – Bot token from @BotFather
TELEGRAM_CHAT_ID    – Target chat / channel / group ID (can be negative for groups)

Optional
--------
TELEGRAM_ALERT_COOLDOWN_MIN  – Minimum minutes between two alerts for the
                                same symbol+direction. Default: 240 (4 h).
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone, timedelta

import httpx

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

# In-memory cooldown store:  key=(symbol, direction)  value=last_sent_epoch
_last_sent: dict[tuple[str, str], float] = {}


def _bot_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN env variable is not set. "
            "Create a bot via @BotFather and paste the token."
        )
    return token


def _chat_id() -> str:
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID env variable is not set. "
            "Use your user/group/channel ID."
        )
    return chat


def _cooldown_seconds() -> float:
    val = os.environ.get("TELEGRAM_ALERT_COOLDOWN_MIN", "240")
    try:
        return float(val) * 60
    except ValueError:
        return 240 * 60


def _is_on_cooldown(symbol: str, direction: str) -> bool:
    key = (symbol, direction)
    last = _last_sent.get(key, 0)
    return (time.time() - last) < _cooldown_seconds()


def _mark_sent(symbol: str, direction: str) -> None:
    _last_sent[(symbol, direction)] = time.time()


def _format_message(signal: dict, timeframe: str) -> str:
    """Build a clean, readable Telegram message from a signal dict."""
    direction = signal.get("direction", "bearish")
    ist_time = datetime.fromtimestamp(signal["time"] / 1000, tz=IST)
    confirmed_ist = datetime.fromtimestamp(signal["confirmed_at"] / 1000, tz=IST)

    if direction == "bullish":
        emoji = "🟢"
        sweep_label = "Swing-Low Sweep"
        level_label = "Swept Low"
        validity = "High stayed below prev midpoint" if signal.get("signal_mode") == "original_strict" else "Reclaimed prev candle low"
    else:
        emoji = "🔴"
        sweep_label = "Swing-High Sweep"
        level_label = "Swept High"
        validity = "Low stayed above prev midpoint" if signal.get("signal_mode") == "original_strict" else "Rejected below prev candle high"

    rank_str = f"#{signal.get('rank', '?')}"
    tv_url = f"https://www.tradingview.com/chart/?symbol=DELTAIN:{signal['symbol']}"

    lines = [
        f"{emoji} *SSV Alert — {sweep_label}*",
        f"",
        f"📌 *{signal['symbol']}*  {rank_str} by 24h turnover",
        f"⏱ Timeframe: `{timeframe}`",
        f"🕐 Candle close (IST): `{ist_time.strftime('%d %b %Y  %H:%M')}`",
        f"✅ Confirmed at (IST): `{confirmed_ist.strftime('%d %b %Y  %H:%M:%S')}`",
        f"",
        f"📊 {level_label}: `{signal['swept_level']:.6g}`",
        f"📉 Close: `{signal['close']:.6g}`",
        f"📐 Validity: _{validity}_",
        f"💰 24h Turnover: `${round(signal.get('turnover_usd', 0)):,}`",
        f"",
        f"[View on TradingView]({tv_url})",
    ]
    return "\n".join(lines)


async def send_signal_alert(signal: dict, timeframe: str) -> bool:
    """Send one signal alert. Returns True if sent, False if skipped or failed."""
    direction = signal.get("direction", "bearish")
    symbol = signal.get("symbol", "UNKNOWN")

    if _is_on_cooldown(symbol, direction):
        log.debug("Cooldown active for %s/%s — skipping alert.", symbol, direction)
        return False

    try:
        token = _bot_token()
        chat_id = _chat_id()
    except RuntimeError as exc:
        log.error("Telegram not configured: %s", exc)
        return False

    text = _format_message(signal, timeframe)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        _mark_sent(symbol, direction)
        log.info("Telegram alert sent: %s %s @ %s", direction, symbol, timeframe)
        return True
    except Exception as exc:
        log.error("Failed to send Telegram alert for %s: %s", symbol, exc)
        return False


async def send_bulk_alerts(signals: list[dict], timeframe: str) -> dict:
    """Send alerts for a list of signals (with per-symbol cooldown).

    Returns a summary dict with sent/skipped/failed counts.
    """
    sent = skipped = failed = 0
    for sig in signals:
        result = await send_signal_alert(sig, timeframe)
        if result is True:
            sent += 1
            # Small delay between sends to avoid Telegram rate limits (30 msg/s)
            await asyncio.sleep(0.5)
        elif result is False:
            # Could be cooldown or config error — both counted as skipped
            skipped += 1

    return {"sent": sent, "skipped": skipped, "failed": failed}


async def send_summary(signals: list[dict], timeframe: str, scan_meta: dict) -> None:
    """Send a single summary message if there are multiple new signals."""
    if not signals:
        return
    try:
        token = _bot_token()
        chat_id = _chat_id()
    except RuntimeError:
        return

    bearish = [s for s in signals if s.get("direction", "bearish") == "bearish"]
    bullish = [s for s in signals if s.get("direction") == "bullish"]
    ist_now = datetime.now(IST).strftime("%d %b %Y  %H:%M IST")

    lines = [
        f"📡 *SSV Scan Summary — {timeframe} | {ist_now}*",
        f"",
        f"🔴 Bearish sweeps: `{len(bearish)}`",
        f"🟢 Bullish sweeps: `{len(bullish)}`",
        f"🔢 Markets scanned: `{scan_meta.get('scanned', '?')}`",
        f"",
    ]
    for s in (bearish + bullish)[:10]:   # cap at 10 in summary
        d_emoji = "🔴" if s.get("direction", "bearish") == "bearish" else "🟢"
        lines.append(f"{d_emoji} {s['symbol']}  `{s['swept_level']:.6g}`")
    if len(signals) > 10:
        lines.append(f"_… and {len(signals) - 10} more_")

    text = "\n".join(lines)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown",
               "disable_web_page_preview": True}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        log.info("Telegram summary sent: %d signals on %s", len(signals), timeframe)
    except Exception as exc:
        log.error("Failed to send Telegram summary: %s", exc)
