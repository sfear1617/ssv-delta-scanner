import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ssv import Candle, bearish_signals, pivot_high

def c(t,h,l,close):
    return Candle(t, (h+l)/2,h,l,close)

def test_valid_bearish():
    # pivot at index 3 confirmed at 6; sweep at 7
    a=[c(i,hi,lo,cl) for i,(hi,lo,cl) in enumerate([
        (8,6,7),(9,7,8),(10,8,9),(14,10,12),
        (12,8,11),(11,7,10),(12,8,11),(15,11,11.5)])]
    out=bearish_signals(a,mode="original_strict")
    assert len(out)==1
    assert out[0]["bar_index"]==7 and out[0]["swept_level"]==14

def test_invalid_previous_midpoint():
    a=[c(i,hi,lo,cl) for i,(hi,lo,cl) in enumerate([
        (8,6,7),(9,7,8),(10,8,9),(14,10,12),
        (12,8,11),(11,7,10),(12,8,11),(15,9,11.5)])]
    assert bearish_signals(a,mode="original_strict")==[]

def test_strict_comparisons():
    a=[c(i,hi,lo,cl) for i,(hi,lo,cl) in enumerate([
        (8,6,7),(9,7,8),(10,8,9),(14,10,12),
        (12,8,11),(11,7,10),(12,8,11),(14,11,11.5)])]
    assert bearish_signals(a,mode="original_strict")==[]


def test_backtest_ist_day_bounds():
    from app import date_bounds
    from datetime import date, datetime, timezone, timedelta
    start, end = date_bounds('2026-05-01', today=date(2026, 11, 3))
    assert end - start == 86400
    assert datetime.fromtimestamp(start, timezone(timedelta(hours=5, minutes=30))).strftime('%Y-%m-%d %H:%M') == '2026-05-01 00:00'
    assert datetime.fromtimestamp(end, timezone(timedelta(hours=5, minutes=30))).strftime('%Y-%m-%d %H:%M') == '2026-05-02 00:00'


def test_backtest_1year_limit():
    import pytest
    from datetime import date
    from app import date_bounds
    date_bounds('2025-11-03', today=date(2026, 11, 3))
    with pytest.raises(ValueError): date_bounds('2025-11-02', today=date(2026, 11, 3))
    with pytest.raises(ValueError): date_bounds('2026-11-04', today=date(2026, 11, 3))


def test_signal_uses_close_time_not_candle_open():
    from app import signal_close_time
    assert signal_close_time({'time': 1000_000}, 3600) == 4600


def test_screenshot_style_sweep_candle_detected_despite_midpoint_rule():
    # Green rejection candle: high breaches pivot, close remains below pivot,
    # but low lies below previous midpoint. Original strict mode rejects it.
    a=[c(i,hi,lo,cl) for i,(hi,lo,cl) in enumerate([
        (8,6,7),(9,7,8),(10,8,9),(14,10,12),
        (12,8,11),(11,7,10),(12,8,11),(15,9,11.5)])]
    matches=bearish_signals(a,mode='sweep_candle')
    assert len(matches)==1 and matches[0]['bar_index']==7
    assert matches[0]['signal_mode']=='sweep_candle'
    assert bearish_signals(a,mode='original_strict')==[]

def test_liquidity_sweep_requires_rejection_and_prior_high():
    a=[c(i,hi,lo,cl) for i,(hi,lo,cl) in enumerate([
        (8,6,7),(9,7,8),(10,8,9),(14,10,12),
        (12,8,11),(11,7,10),(12,8,11),(15,9,14.5)])]
    assert bearish_signals(a,mode='sweep_candle')==[]
