"""Bearish and bullish port of the Swing Sweep Validity Pine v6 script."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Candle:
    time: int  # open timestamp in milliseconds
    open: float
    high: float
    low: float
    close: float

def pivot_high(candles, i, strength):
    """Confirm a pivot strength bars after its occurrence.
    Equal highs: prefer most-recent high (Pine parity should be checked on-chart)."""
    j = i - strength
    if j < strength:
        return None
    value = candles[j].high
    if any(candles[k].high >= value for k in range(j+1, i+1)):
        return None
    if any(candles[k].high > value for k in range(j-strength, j)):
        return None
    return value

def bearish_signals(candles, strength=3, max_active=50, mode="sweep_candle"):
    """Scans *closed* candles; old swing highs are removed if breached.
    Mode sweep_candle flags the rejection candle even when the extra Pine
    midpoint-validity filter fails. Mode original_strict retains that rule.
    Matches processing order of the provided Pine: register pivot then check highs
    from newest to oldest; first qualifying reject is the only signal per candle.
    """
    active = []  # list (swing-level, pivot-index)
    signals = []
    if mode not in ("sweep_candle", "original_strict"):
        raise ValueError("Unsupported signal mode")
    if strength < 1 or max_active < 5:
        raise ValueError("strength must be >=1 and max_active >=5")
    for i, bar in enumerate(candles):
        p = pivot_high(candles, i, strength)
        if p is not None:
            active.append((p, i-strength))
            if len(active) > max_active:
                active.pop(0)
        if i == 0:
            continue
        previous = candles[i-1]
        found = False
        for index in range(len(active)-1, -1, -1):
            level, pivot_index = active[index]
            crossed = bar.high > level
            rejected = crossed and bar.close < level
            if rejected:
                took_prior_high_and_rejected = bar.high > previous.high and bar.close < previous.high
                if not found and took_prior_high_and_rejected:
                    found = True
                    valid = mode == "sweep_candle" or bar.low > (previous.high + previous.low) / 2
                    if valid:
                        signals.append({
                            "time": bar.time, "bar_index": i, "pivot_time": candles[pivot_index].time,
                            "pivot_index": pivot_index, "swept_level": level, "close": bar.close,
                            "high":bar.high, "low":bar.low, "previous_midpoint":(previous.high+previous.low)/2,
                            "signal_mode": mode, "candle_color": "green" if bar.close > bar.open else "red" if bar.close < bar.open else "doji"
                        })
                active.pop(index)
            elif crossed or bar.close > level:
                active.pop(index)
    return signals


def pivot_low(candles, i, strength):
    """Mirror of pivot_high but for lows. Confirmed `strength` bars after occurrence."""
    j = i - strength
    if j < strength:
        return None
    value = candles[j].low
    if any(candles[k].low <= value for k in range(j+1, i+1)):
        return None
    if any(candles[k].low < value for k in range(j-strength, j)):
        return None
    return value


def bullish_signals(candles, strength=3, max_active=50, mode="sweep_candle"):
    """Port of the Pine bullish (swing-low sweep) branch.

    A bullish sweep occurs when price dips below a prior swing low, then
    *closes back above* that level AND above the previous candle's low
    (tookPriorLowAndReclaimed). Valid mode additionally requires the sweep
    candle's HIGH to stay BELOW the previous candle's midpoint.

    mode='sweep_candle'  – mark whenever tookPriorLowAndReclaimed is true
                           (midpoint filter disabled, wider detection).
    mode='original_strict' – also enforce high < avg(prev.high, prev.low).
    """
    active = []   # list of (swing-level, pivot-index)
    signals = []
    if mode not in ("sweep_candle", "original_strict"):
        raise ValueError("Unsupported signal mode")
    if strength < 1 or max_active < 5:
        raise ValueError("strength must be >=1 and max_active >=5")

    for i, bar in enumerate(candles):
        p = pivot_low(candles, i, strength)
        if p is not None:
            active.append((p, i - strength))
            if len(active) > max_active:
                active.pop(0)
        if i == 0:
            continue
        previous = candles[i - 1]
        found = False
        for index in range(len(active) - 1, -1, -1):
            level, pivot_index = active[index]
            crossed = bar.low < level
            reclaimed = crossed and bar.close > level

            if reclaimed:
                took_prior_low_and_reclaimed = bar.low < previous.low and bar.close > previous.low
                if not found and took_prior_low_and_reclaimed:
                    found = True
                    valid = (
                        mode == "sweep_candle"
                        or bar.high < (previous.high + previous.low) / 2
                    )
                    if valid:
                        signals.append({
                            "time": bar.time,
                            "bar_index": i,
                            "pivot_time": candles[pivot_index].time,
                            "pivot_index": pivot_index,
                            "swept_level": level,
                            "close": bar.close,
                            "high": bar.high,
                            "low": bar.low,
                            "previous_midpoint": (previous.high + previous.low) / 2,
                            "signal_mode": mode,
                            "direction": "bullish",
                            "candle_color": (
                                "green" if bar.close > bar.open
                                else "red" if bar.close < bar.open
                                else "doji"
                            ),
                        })
                active.pop(index)
            elif crossed or bar.close < level:
                active.pop(index)

    return signals
