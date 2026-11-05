SSV DELTA PREMIUM v1.2 | LIQUIDITY SWEEP CANDLE MODE

SSV DELTA PREMIUM BEARISH SCANNER v1.1.1 - WINDOWS TIMEZONE STARTUP FIX
==========================================================

QUICK START (Windows)
1. Extract the whole folder from the ZIP file.
2. Double-click START_SSV_SCANNER.bat.
3. The launcher creates its own Python environment if needed and opens the dashboard.
4. In Scanner controls, click Backtest date, navigate months and select a date.
5. Select the chart timeframe, then RUN BEARISH SCAN.
6. The signal table displays every valid bearish SSV event CONFIRMED on that
   calendar date, with confirmation timestamp in IST (including seconds).
7. Click "Live scan" in the calendar to revert to the original last-N-candle scan.

A date is optional. If blank, the original live scan operates normally.
Backtest dates are limited to today and the preceding one calendar year in IST.
The "Signal recency" control is intentionally disabled for a date backtest,
because ALL qualifying events on that date are returned.

All existing inputs and bearish-only rules are retained from the original scanner.
The data comes from Delta Exchange India public market-data endpoints.
The top 100 instruments are ranked by TODAY'S 24-hour USD turnover, even when
backtesting a historical day. This is NOT a historical top-100 membership snapshot.
Some current products may not have traded during the selected past date.

Historical detection fetches preceding OHLC candles (up to 1200 total) so
swing highs can be reconstructed. The very oldest pivot states may still differ
from a TradingView chart with much longer chart history. Exact Pine equal-high
pivot behavior and exchange-feed parity must still be validated chart-by-chart.
Only COMPLETED candles are considered. A pattern is dated by the moment its
candle closes in Asia/Kolkata, which may differ from its opening date.

Online access to Delta Exchange India is required to scan. API request failures
are counted in the dashboard; a zero-result scan is not proof of no pattern
if any market data requests failed. No keys or permissions to trade are needed.

No background scheduling, orders, or trading actions are included.

TECHNICAL
Run in this folder (alternative to double-click):
    py -m pip install -r requirements.txt
    py -m uvicorn app:app --host 127.0.0.1 --port 8765
Then visit http://127.0.0.1:8765

Test suite (optional):
    py -m pip install pytest
    py -m pytest -q tests

Main files:
    START_SSV_SCANNER.bat   Windows double-click launcher
    app.py                  Scan API and IST date filtering
    delta_api.py            Delta public market data and historical candles
    ssv.py                  Original Pine bearish SSV calculation port
    static/index.html       Original premium dashboard + calendar dropdown

NOTE: APIs are verified against documentation but live exchange execution is
not confirmed in the build environment. Test a known signal against TradingView.

WINDOWS TIMEZONE FIX (v1.1.1)
India Standard Time is defined as UTC+05:30 directly, so the scanner no longer
requires Windows timezone database files or the optional tzdata package.
This addresses ZoneInfoNotFoundError on Python 3.15.
You may extract this version to a new folder and double-click the same BAT file.


CHANGE IN v1.2
The default "Liquidity sweep candle (marked pattern)" mode identifies the
SWEEP/REJECTION CANDLE, not the later follow-through move. It detects an
already-confirmed swing high taken by the candle wick, followed by a close
below that swing high AND below the previous candle high. It does not
require the sweep candle low to stay above the prior candle midpoint.
This is deliberately BROADER than the supplied original Pine strict validity
rule; choose "Original SSV strict" to preserve that rule exactly.
The signal happens when the sweep candle CLOSES; both green and red candles
can qualify. Backtest timestamps are that candle's CLOSE in IST.
Compare actual OHLC on the exact matching exchange and timeframe to validate
marked examples; screenshot alone cannot verify exact prices.
All other controls, Delta volume ranking, calendar, and BAT launcher preserved.
