# CSO Live (Conditional Scenario Odds)

Reads your live NQ chart, finds past NQ days in the same situation, and tells you what happened next on those days:
the % for each outcome, how far it went (in today's prices), and how soon.

**These are descriptive odds from history. They are not a tested edge or trade advice.** Every % shows its sample size (n) and an 80% range, and small samples are flagged.

## What you need
- Windows
- **Python 3.11 or newer, 64-bit**: https://www.python.org/downloads/ (tick "Add python.exe to PATH" in the installer)
- **TradingView Desktop**, with real-time CME data. Without it, the live read is 10 minutes behind.
- Git, to clone and update

## Setup (once)
1. `git clone <this repo>`
2. Double-click **`setup.bat`**. It installs the packages into a `.venv` folder inside the project and runs the self-check.
   You should see `SELF-CHECK PASSED`.

## Each day
1. Double-click **`start.bat`**. It:
   - opens TradingView in debug mode. If TradingView is already open without debug mode, it restarts it, and your layout reloads.
   - starts the watcher in the background
   - opens **http://127.0.0.1:8765** in your browser
2. In TradingView, open a **`CME_MINI:NQ1!` 1-minute** chart. Keep that chart on NQ.
3. On the page:
   - **Ask** a question in plain English, for example:
     - `odds of new london low`
     - `odds of new high by 10 am`
     - `retrace to .618 or new low first`
   - Every answer comes with a **chart**: today's bars, a line at each level the odds were measured for, and next to it the % for each time window, the median time it hit, and how far price ran past it on the days it did. Only measured numbers are shown, no predicted paths.
   - **Live read** refreshes every 30 seconds. It updates from 6 PM to 4 PM CT, with the 4–6 PM break skipped.

Times are Central (CT), whatever time zone your PC is set to.

## Command line (optional)
From `edge_research\cso`, run any of these with `..\..\.venv\Scripts\python -I cso_live.py` followed by:
- `--q "odds of new low" --fast`: one question
- `--now`: the full auto-read of the chart
- `--test`: the self-check
- `--calibration`: how past answers turned out

Run `cso_live.py` with no arguments to see every option.

## Updating
Double-click **`update.bat`**. It pulls the latest version and stops the old watcher. Then run `start.bat`.

## What's inside
- `edge_research/cso/cso_live.py`: the engine and the watcher
- `edge_research/cso/cso.py`: sessions and the news calendar
- `edge_research/cso/cso_grid/`: NQ and ES 1-minute history, 2010–Oct 2026, in a ready-to-use form
- `ema_backtest/tv_pull.py`: reads the bars from your TradingView chart (read-only)
- `ema_backtest/external/events_calendar.csv`: news days (FOMC, CPI, NFP)
- `edge_research/cso/NQ_CSO_Explorer.html`: the Asia/London odds tables, opened in a browser

## Troubleshooting
- **"No live read yet" / errors about port 9222:** TradingView isn't in debug mode. Close it fully and run `start.bat` again.
- **Live read shows ES or the wrong prices:** switch the active chart to `CME_MINI:NQ1!` on 1-minute.
- **The page won't load:** the watcher isn't running. Run `start.bat`.
