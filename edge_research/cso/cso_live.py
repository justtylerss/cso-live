"""CSO Live: ask any event-shaped "what are the odds" question about NQ and get state-matched odds from 2024-26 (side notes: 2020-23,
2011-19 with --old). Every question runs a fresh backtest over the cached 1-min grid (2010-26), so a state with no stored stats
still gets an answer. Thin answers loosen one condition at a time (timing first by +50%, then dropping) until n >= 30.

A question is a chain of clauses separated by ';'. Clauses run left to right on every past day. Events move the "anchor" (the last bar
seen); state clauses only filter. Outcomes are measured from the bar after the final anchor, and a level that was ALREADY touched
before the anchor is not counted as a hit: that day is set aside for that outcome and the share set aside is printed as a warning.

  python -I cso_live.py --serve                       the watcher: grid in memory, a live read every minute (5 PM-4 PM CT) into
                                                       cso/live_latest.txt + .json; --ask / --q / --now use it automatically (~1-3 s)
  python -I cso_live.py --now [--fast] [--draw] [--old]   read the TradingView chart: impulse + fib levels, sweeps, NY context -> answers
                                                       --fast: only the answer rung + the shape rung, one compact table each
  python -I cso_live.py --q "odds of hitting .786" [--draw]   plain English on top of the live read (see PHRASES)
  python -I cso_live.py --ask "<question>" [--live] [--old]   your own question; --live adds today's prices, 'now' / 'now-30' times,
                                                             the shape rung (nearest past paths) and the calibration log
  python -I cso_live.py --calibration                  resolve logged live answers and print predicted vs actual (reliability, Brier)
  python -I cso_live.py --draw / --clear               after --now/--q: fib levels with odds on TradingView (never saved) / remove them
  python -I cso_live.py --alerts                       dry run: which known setups are live now (Discord posting waits for a webhook)
  python -I cso_live.py --journal 2026-10-28 [--trades fills.csv]   session journal page: chart, levels, questions asked, what happened
  python -I cso_live.py --test | --cache               self-check | rebuild the grid cache (nq_all_1m + es_all_1m)

HOW TO ASK (times CT: 2:45, 3:59am, 15:00 or 3pm all work; output is 12-hour)
  Levels   asia_hi asia_lo (7-11 PM)  london_hi london_lo (1 AM .. anchor)  on_hi on_lo (5 PM-8:29 AM, so far)  pdh pdl pdc (prior NY 8:30-3)
           NY: open (8:30 open)  fb_hi fb_lo (8:30-8:44 bar, from 8:45)  ib_hi ib_lo (8:30-9:29, from 9:30)  vwap (NY VWAP so far)
               rth_hi rth_lo (NY so far)  pm_hi pm_lo (yesterday noon-3 PM)  pa_hi pa_lo (5-7 PM pre-Asia)
           X.level X.low X.high (event X)  X.top X.base X.size (impulse X)  X.r0.786 (the 78.6% retrace level of impulse X)
           any level +/- pts: asia_lo-20
  State    at 2:45                      state known through 2:44; events search from 2:45
           swept asia_hi | unswept asia_lo   traded past it this session (asia_*: since 1 AM; pd*: since 7 PM; others: since 5 PM)
           inside asia | pos asia 0.6 1      price inside the range / at 60-100% of it (also london, on, pd)
           above LEVEL | below LEVEL | dow 1 2 3 4 (Mon=0) | event fomc|cpi|nfp|red|none
           cond retrace I >= 0.382 within 12   impulse I pulled back 38.2%+ in its first 12 min (also: < 0.5)
           volspike I >= 3                  volume on the turn bar >= 3x the median minute of the 30 before (I = impulse base / event bar)
           delta I > 0 | delta I < 0        buy minus sell volume on the turn bar (bv/sv: about 21% of 2024+ minutes have it)
           smt B | esconfirm B              at event B (a break or a new session low/high), ES did NOT / did make the same move within 5 min
           opendrive up|down|none           Dalton open-drive at 8:44 (dalton_bot rule: low never 0.02 ATR under the open, close 0.1 ATR up)
           firstbar up|down|none            8:44 close more than 0.15 ATR from the 8:30 open (openbar_bot rule)
           crabel up|down|none              first close past open +/- 1.5 x the 10-day stretch, 8:31-10:29 (stretch_bot rule, without ES)
           above open | below vwap | above fb_hi | swept ib_hi | pos on 0.6 1   (NY position, IB break side, overnight-range position)
  News     on a red-folder day --now adds 'event fomc|cpi|nfp|red': same-kind days first; the ladder drops it last and says so
  Events   break LEVEL [from T] [to T] [before LEVEL2] [any] [as X]   first bar trading through the level (before LEVEL2 is touched)
           newlow london [from T] [to T] [any] [as X]   first bar making a new low of that session (any = try later ones too); newhigh
           impulse up|down PTS within N [from T to T] [as X]   PTS move within N min from the event bar; anchor -> impulse top
           reclaim X within N [maxdepth D] [above LEVEL|below LEVEL]   closes back across X.level within N min of the break
           nohigh LEVEL N | nolow LEVEL N   no trade past the level for N more minutes (elapsed time);  wait N
  Outcomes ?hit LEVEL [by T ..] [within N ..]   ?retrace X 0.382 0.5 0.618 0.786 1 [within N ..] [by T ..]
           ?race above LEVEL vs retrace X 0.618   (sides: above L | below L | hit L | retrace X r)   ?extremes by T ..   ?lodhod
  Filters commit: 'any' retries a later event only when a later EVENT fails; once a filter is reached the day keeps its first event.
  No look-ahead: a 'cond ... within N' (and smt) reads bars up to X.t+N, so it moves the anchor there. Rungs report COUNTED days
  (matched minus set aside); 'when' = median minutes after the anchor and the clock time that lands today.
  Examples
   Q2  at 2:45; dow 1 2 3 4; swept asia_hi; unswept asia_lo; inside asia; break london_lo to 3:59 as B;
       reclaim B within 5 maxdepth 20 above asia_lo; ?hit london_hi by 3:59 8:29 15:00
   Q3  newlow london from 1:30 to 3:59 any as L; impulse up 60 within 7 as I; ?retrace I 0.382 0.5 1 within 30 60 by 3:59 8:29 15:00
   Q5  newlow london from 1:30 to 3:59 any as L; impulse up 60 within 7 as I; nohigh I.top 12; ?race above I.top vs retrace I 0.618
   .75 first, then which: newlow london from 1:30 to 3:59 any as L; impulse up 60 within 7 as I; break I.r0.75 before I.top as R;
       ?race above I.top vs hit I.r1
PHRASES (--q): "odds of hitting .786" / "will it retrace 62%" / "new london high" / "back to the asia low" /
  "which first .618 or new high" / "london high or london low first"
Descriptive odds, not an edge. Every % carries an 80% Wilson range and n; rungs under 15 days are thin.
"""
import asyncio, json, math, os, re, sys, time, warnings
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cso  # noqa: E402  (events calendar, clock, buckets)

DATA = os.path.join(cso.ROOT, 'ema_backtest', 'data')
GRID = os.path.join(HERE, 'cso_grid')           # one .npy per array (memory-mapped, so a query starts in about a second)
ct_now = lambda: datetime.now(ZoneInfo('America/Chicago')).replace(tzinfo=None)  # CT whatever the PC's clock zone
CAL = os.path.join(HERE, 'calibration.jsonl')
DRAWN = os.path.join(HERE, 'drawn.json')
LAST = os.path.join(HERE, 'last_answer.json')
SESS = {'asia': (120, 360), 'london': (480, 660), 'on': (0, 930), 'rth': (930, 1320), 'day': (0, 1380), 'fb': (930, 945), 'ib': (930, 990),
        'pa': (0, 120)}
SET = {'fb', 'ib'}  # these levels exist only once their window is complete (first 15-min bar, 8:30-9:30 IB)
SINCE = {'asia': 480, 'pd': 120, 'pm': 120, 'pa': 120, 'on': 930, 'ib': 990, 'fb': 945}  # where 'swept' starts looking
CONDMOVE = True  # a cond / smt reads bars up to X.t+N, so it moves the anchor there (no look-ahead); off only to reproduce 10/28 hand-built
FIBS = [0.382, 0.5, 0.618, 0.786, 1.0]
OLD = '--old' in sys.argv
GUARD = True  # set aside levels already reached before the anchor (off only to reproduce pre-guard hand-built answers)


def tmin(s):
    """'2:45' / '3:59am' / '3pm' / '15:00' -> minutes after 5 PM CT"""
    m = re.fullmatch(r'(\d{1,2})(?::(\d{1,2}))?\s*(am|pm)?', str(s).strip().lower())
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == 'pm' and h < 12:
        h += 12
    if ap == 'am' and h == 12:
        h = 0
    return ((h * 60 + mi) - 1020) % 1440


def hhmm(m):
    """minutes after 5 PM -> '2:45' / '15:00' (the --ask input format)"""
    return f'{((m + 1020) % 1440) // 60}:{(m + 1020) % 60:02d}'


clock = cso.clock


# ---------------------------------------------------------------- data
def grid_arrays(df):
    m = ((df.ct.dt.hour * 60 + df.ct.dt.minute).values - 1020) % 1440
    days = np.sort(df.day.unique())
    i = np.searchsorted(days, df.day.values)
    adj = df.adj.values if 'adj' in df else 0
    A = {}
    for k in ('open', 'high', 'low', 'close', 'volume', 'bv', 'sv'):
        A[k] = np.full((len(days), 1440), np.nan, np.float32)
        if k in df:
            A[k][i, m] = df[k].values + (adj if k in ('open', 'high', 'low', 'close') else 0)
    roll = df.groupby('day').sym.nunique().reindex(days).values > 1
    return pd.DatetimeIndex(days), A, roll


def build_cache():
    os.makedirs(GRID, exist_ok=True)
    cols = ['ct', 'open', 'high', 'low', 'close', 'volume', 'bv', 'sv', 'sym', 'adj', 'day']
    days, A, roll = grid_arrays(pd.read_parquet(os.path.join(DATA, 'nq_all_1m.parquet'), columns=cols))
    edays, E, eroll = grid_arrays(pd.read_parquet(os.path.join(DATA, 'es_all_1m.parquet'), columns=cols))
    j = np.searchsorted(edays, days)
    ok = (j < len(edays)) & (edays[np.minimum(j, len(edays) - 1)] == days)
    for k in ('high', 'low', 'close'):  # ES aligned to the NQ day index
        x = np.full_like(A['close'], np.nan)
        x[ok] = E[k][j[ok]]
        x[ok & eroll[np.minimum(j, len(edays) - 1)]] = np.nan
        np.save(os.path.join(GRID, f'es_{k}.npy'), x)
    for k, v in A.items():
        np.save(os.path.join(GRID, f'{k}.npy'), v)
    np.save(os.path.join(GRID, 'roll.npy'), roll)
    np.save(os.path.join(GRID, 'days.npy'), days.values.astype('datetime64[D]').astype(str))


class Grid:
    def __init__(self, days, A, roll, es=None):
        self.days = pd.DatetimeIndex(days)
        self.O, self.H, self.L, self.C = (A[k] for k in ('open', 'high', 'low', 'close'))
        self.V, self.BV, self.SV = (A.get(k) for k in ('volume', 'bv', 'sv'))
        self.es = es  # dict high/low/close or None
        n = len(self.days)
        cov = lambda a, b: (~np.isnan(self.C[:, a:b])).mean(1)
        self.valid = ~np.asarray(roll) & (cov(480, 1321) >= 0.83)
        aok = cov(120, 360) >= 0.8
        self.asia_hi = np.where(aok, np.nanmax(self.H[:, 120:360], 1), np.nan)
        self.asia_lo = np.where(aok, np.nanmin(self.L[:, 120:360], 1), np.nan)
        rok = cov(930, 1320) >= 0.8
        rh, rl, rc = np.nanmax(self.H[:, 930:1320], 1), np.nanmin(self.L[:, 930:1320], 1), cso._last(np.asarray(self.C, float), 930, 1320)
        prev = np.r_[-1, np.arange(n - 1)]
        prev[1:][np.diff(self.days.values).astype('timedelta64[D]').astype(int) > 4] = -1
        ok = (prev >= 0) & rok[np.maximum(prev, 0)]
        pv = lambda x: np.where(ok, x[np.maximum(prev, 0)], np.nan)
        self.pdh, self.pdl, self.pdc = pv(rh), pv(rl), pv(rc)
        self.pm_hi, self.pm_lo = pv(np.nanmax(self.H[:, 1200:1320], 1)), pv(np.nanmin(self.L[:, 1200:1320], 1))  # yesterday noon-3 PM
        # NY open reads, as the bots: ATR = 14-session Wilder ATR of the cash-session true range, prior sessions only
        ro = self.O[:, 930]
        tr = np.fmax(rh - rl, np.fmax(np.abs(rh - pv(rc)), np.abs(rl - pv(rc))))
        tr = np.where(rok, tr, np.nan)
        self.atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False, ignore_na=True).mean().shift(1).values
        st_ = np.where(rok, np.fmin(rh - ro, ro - rl), np.nan)
        self.stretch = pd.Series(st_).rolling(10, min_periods=8).mean().shift(1).values
        h15, l15, c44 = np.nanmax(self.H[:, 930:945], 1), np.nanmin(self.L[:, 930:945], 1), self.C[:, 944]
        up, dn, cc = (h15 - ro) / self.atr, (ro - l15) / self.atr, (c44 - ro) / self.atr
        self.opendrive = np.where((dn <= 0.02) & (cc >= 0.1), 1, np.where((up <= 0.02) & (cc <= -0.1), -1, 0))   # dalton_bot rule
        self.firstbar = np.where(np.abs(c44 - ro) > 0.15 * self.atr, np.sign(c44 - ro), 0).astype(int)        # openbar_bot rule
        cz = self.C[:, 931:1050]                                                                                 # crabel: 8:31-10:29 closes
        upx, dnx = cz > (ro + 1.5 * self.stretch)[:, None], cz < (ro - 1.5 * self.stretch)[:, None]
        tu = np.where(upx.any(1), upx.argmax(1) + 931, 9999)
        td = np.where(dnx.any(1), dnx.argmax(1) + 931, 9999)
        self.crabel_t = np.minimum(tu, td)
        self.crabel = np.where(self.crabel_t == 9999, 0, np.where(tu < td, 1, -1))
        if es is not None:
            self.es_asia_hi = np.nanmax(es['high'][:, 120:360], 1)
            self.es_asia_lo = np.nanmin(es['low'][:, 120:360], 1)
            self.es_pdh = pv(np.nanmax(es['high'][:, 930:1320], 1))
            self.es_pdl = pv(np.nanmin(es['low'][:, 930:1320], 1))
        try:
            self.ev = cso.events(self.days)
        except Exception:
            self.ev = np.zeros(n, int)
        self.end = str(self.days.max().date())


_G = None


def load_grid():
    global _G
    if _G is None:
        if not os.path.exists(os.path.join(GRID, 'days.npy')):
            build_cache()
        ld = lambda k: np.load(os.path.join(GRID, f'{k}.npy'), mmap_mode='r')
        days = pd.to_datetime(np.load(os.path.join(GRID, 'days.npy')))
        lo = int(np.searchsorted(days, pd.Timestamp('2011-01-01' if OLD else '2019-12-01')))
        A = {k: np.asarray(ld(k)[lo:]) for k in ('open', 'high', 'low', 'close', 'volume', 'bv', 'sv')}
        es = {k: np.asarray(ld(f'es_{k}')[lo:]) for k in ('high', 'low', 'close')}
        _G = Grid(days[lo:], A, np.load(os.path.join(GRID, 'roll.npy'))[lo:], es)
    return _G


# ---------------------------------------------------------------- one day
class Day:
    def __init__(self, g, i):
        self.g, self.i = g, i
        self.H, self.L, self.C = g.H[i], g.L[i], g.C[i]

    def px(self, a):
        if a < 0:
            return np.nan
        c = self.C[:a + 1]
        j = np.flatnonzero(~np.isnan(c))
        return float(c[j[-1]]) if len(j) else np.nan

    def level(self, name, ctx, es=False):
        m = re.fullmatch(r'(.+?)([+-]\d+(?:\.\d+)?)?', name.strip())
        base, off = m.group(1), float(m.group(2) or 0)
        a = ctx['a']
        if '.' in base and not es:
            var, f = base.split('.', 1)
            X = ctx['vars'][var]
            if f.startswith('r'):
                r = float(f[1:])
                return (X['top'] - r * X['size'] if X['dir'] == 'up' else X['top'] + r * X['size']) + off
            return X[f] + off
        g = self.g
        if base in ('asia_hi', 'asia_lo', 'pdh', 'pdl', 'pdc', 'pm_hi', 'pm_lo'):
            src = getattr(g, ('es_' if es else '') + base, None)
            return (src[self.i] if src is not None else np.nan) + off
        if base == 'open':
            return (g.O[self.i][930] if a >= 930 else np.nan) + off
        if base == 'vwap':  # NY session VWAP (typical price), 8:30 AM to the anchor
            if a < 930 or g.V is None:
                return np.nan
            sl = slice(930, a + 1)
            v = g.V[self.i][sl]
            tp = (self.H[sl] + self.L[sl] + self.C[sl]) / 3
            ok = ~np.isnan(v) & ~np.isnan(tp)
            return float((tp[ok] * v[ok]).sum() / v[ok].sum()) + off if ok.any() and v[ok].sum() > 0 else np.nan
        s, side = base.rsplit('_', 1)
        lo, hi = SESS[s][0], min(a + 1, SESS[s][1])
        if hi <= lo or (s in SET and a + 1 < SESS[s][1]):
            return np.nan
        H, L = (g.es['high'][self.i], g.es['low'][self.i]) if es else (self.H, self.L)
        x = H[lo:hi] if side == 'hi' else L[lo:hi]
        return float((np.nanmax(x) if side == 'hi' else np.nanmin(x)) + off) if (~np.isnan(x)).any() else np.nan

    def rng(self, s, ctx):
        if s == 'pd':
            return self.g.pdl[self.i], self.g.pdh[self.i]
        return self.level(s + '_lo', ctx), self.level(s + '_hi', ctx)

    def touch(self, a, lvl, up, end):
        """first minute in (a, end] that trades at/through lvl; NaN if never"""
        seg = slice(a + 1, end + 1)
        x = self.H[seg] >= lvl if up else self.L[seg] <= lvl
        j = np.flatnonzero(x)
        return a + 1 + j[0] if len(j) else np.nan

    def touched(self, s, a, lvl, up):
        """traded at/through lvl in [s, a] (the already-passed guard)"""
        if a < s:
            return False
        return bool(np.nanmax(self.H[s:a + 1]) >= lvl) if up else bool(np.nanmin(self.L[s:a + 1]) <= lvl)


def name_is_hi(name):
    b = re.sub(r'[+-][\d.]+$', '', name)
    return b.endswith('_hi') or b == 'pdh' or b.endswith('.top') or b.endswith('.high')


def var_of(name):
    return name.split('.')[0] if '.' in re.sub(r'[+-][\d.]+$', '', name) else None


# ---------------------------------------------------------------- parse
def parse(q):
    cl, outs = [], []
    for raw in [c.strip() for c in q.replace('\n', ' ').split(';') if c.strip()]:
        out = raw.startswith('?')
        w = raw.lstrip('?').split()
        (outs if out else cl).append(dict(op=w[0].lower(), w=w[1:], text=raw))
    return cl, outs


STOP = ('from', 'to', 'as', 'within', 'by', 'any', 'maxdepth', 'above', 'below', 'vs', '>=', '<=', '<', '>', 'before')


def kw(w, key, n=1):
    if key not in w:
        return None
    v = []
    for x in w[w.index(key) + 1:]:
        if x in STOP:
            break
        v.append(x)
    return v if n is None else (v[0] if v else None)


STATE = {'at', 'swept', 'unswept', 'inside', 'pos', 'above', 'below', 'dow', 'event', 'cond', 'volspike', 'delta', 'smt', 'esconfirm',
         'opendrive', 'firstbar', 'crabel'}
LAST_DROP = {'event'}  # news: same-kind days first; the ladder drops this only when nothing else is left
LOOSEN = {'cond', 'nohigh', 'nolow'}  # timing clauses: loosened by 50% before they are dropped
EV = {'fomc': 1, 'cpi': 2, 'nfp': 3}


def turn(X):
    return X.get('tb', X['t'])


def check_state(d, c, ctx):
    op, w = c['op'], c['w']
    a = ctx['a']
    px = d.px(a)
    g = d.g
    if op == 'at':
        return True
    if op in ('swept', 'unswept'):
        lvl = d.level(w[0], ctx)
        fam = 'pd' if w[0] in ('pdh', 'pdl') else w[0].split('_')[0]
        lo = SINCE.get(fam, 0)
        if a < lo:
            return op == 'unswept'
        up = name_is_hi(w[0])
        x = d.H[lo:a + 1] if up else d.L[lo:a + 1]
        hit = bool(np.nanmax(x) > lvl) if up else bool(np.nanmin(x) < lvl)
        return hit if op == 'swept' else (not hit and not np.isnan(lvl))
    if op in ('inside', 'pos'):
        lo, hi = d.rng(w[0], ctx)
        if np.isnan(lo) or np.isnan(hi) or hi <= lo:
            return False
        p = (px - lo) / (hi - lo)
        return 0 <= p <= 1 if op == 'inside' else float(w[1]) <= p <= float(w[2])
    if op in ('above', 'below'):
        lv = d.level(w[0], ctx)
        return px > lv if op == 'above' else px < lv
    if op in ('opendrive', 'firstbar', 'crabel'):  # opendrive up|down|none (known 8:45), firstbar (8:45), crabel (once it fires)
        want = {'up': 1, 'down': -1, 'none': 0}[w[0]]
        if op == 'crabel':
            fired = g.crabel_t[d.i] <= a
            return bool(g.crabel[d.i] == want and fired) if want else not fired
        return a >= 944 and getattr(g, op)[d.i] == want
    if op == 'dow':
        return g.days[d.i].dayofweek in [int(x) for x in w]
    if op == 'event':
        e = g.ev[d.i]
        return {'none': e == 0, 'red': e > 0}.get(w[0], e == EV.get(w[0], -9))
    if op == 'cond':  # cond retrace I >= 0.382 within 12
        X = ctx['vars'][w[1]]
        n = int(kw(w, 'within'))
        seg = slice(X['t'] + 1, X['t'] + n + 1)
        r = (X['top'] - np.nanmin(d.L[seg])) / X['size'] if X['dir'] == 'up' else (np.nanmax(d.H[seg]) - X['top']) / X['size']
        thr = float(w[3])
        return r >= thr if w[2] == '>=' else r < thr
    if op == 'volspike':  # volspike I >= 3
        if g.V is None:
            return False
        t = turn(ctx['vars'][w[0]])
        base = np.nanmedian(g.V[d.i][max(0, t - 30):t])
        return bool(base > 0 and g.V[d.i][t] / base >= float(w[2]))
    if op == 'delta':  # delta I > 0 (turn bar +/- 1)
        if g.BV is None:
            return False
        t = turn(ctx['vars'][w[0]])
        dl = np.nansum(g.BV[d.i][t - 1:t + 2] - g.SV[d.i][t - 1:t + 2]) if not np.isnan(g.BV[d.i][t]) else np.nan
        return bool(dl > float(w[2])) if w[1] == '>' else bool(dl < float(w[2])) if not np.isnan(dl) else False
    if op in ('smt', 'esconfirm'):  # ES did not / did make the same move as event X within 5 min
        if g.es is None:
            return False
        X = ctx['vars'][w[0]]
        if 'name' not in X:
            return False
        win = int(kw(w, 'within') or 5)
        t = X['t']
        ectx = dict(ctx, a=X['a0'])
        lvl = d.level(X['name'], ectx, es=True)
        eh, el = g.es['high'][d.i], g.es['low'][d.i]
        if np.isnan(lvl):
            return False
        seg = slice(max(0, t - win), t + win + 1)
        did = bool(np.nanmax(eh[seg]) > lvl) if X['dir'] == 'up' else bool(np.nanmin(el[seg]) < lvl)
        return (not did) if op == 'smt' else did
    raise ValueError(f'unknown clause: {c["text"]}')


def candidates(d, c, ctx):
    """yield (new anchor, var dict) for an event clause"""
    op, w = c['op'], c['w']
    a = ctx['a']
    end = min(tmin(kw(w, 'to')) if kw(w, 'to') else 1379, 1379)
    start = max(a + 1, tmin(kw(w, 'from')) if kw(w, 'from') else 0)
    many = 'any' in w
    if op == 'break':
        lvl = d.level(w[0], ctx)
        if np.isnan(lvl):
            return
        px = d.px(a)
        up = name_is_hi(w[0]) if not var_of(w[0]) else lvl > px
        x = d.H[start:end + 1] >= lvl if var_of(w[0]) and up else d.H[start:end + 1] > lvl if up else \
            (d.L[start:end + 1] <= lvl if var_of(w[0]) else d.L[start:end + 1] < lvl)
        hits = np.flatnonzero(x) + start
        if kw(w, 'before'):
            l2 = d.level(kw(w, 'before'), ctx)
            t2 = d.touch(a, l2, l2 > px, 1379)
            hits = hits[hits < (t2 if not np.isnan(t2) else 9999)]
        for t in hits[: None if many else 1]:
            yield t, dict(t=t, level=lvl, low=d.L[t], high=d.H[t], dir='up' if up else 'down', name=w[0], a0=a)
    elif op in ('newlow', 'newhigh'):
        s0 = SESS[w[0]][0]
        lo = d.L if op == 'newlow' else -d.H
        run_ = np.fmin.accumulate(np.where(np.isnan(lo[s0:end + 1]), np.inf, lo[s0:end + 1]))
        prior = np.r_[np.inf, run_[:-1]]
        hit = np.flatnonzero(lo[s0:end + 1] <= prior) + s0  # a touch of the running low counts (10/28 Q3 rule)
        hit = hit[(hit >= start) & (hit > s0)]
        for t in hit[: None if many else 1]:
            yield t, dict(t=t, level=(prior[t - s0] if op == 'newlow' else -prior[t - s0]), low=d.L[t], high=d.H[t],
                          dir='down' if op == 'newlow' else 'up', name=f'{w[0]}_{"lo" if op == "newlow" else "hi"}', a0=t - 1)
    elif op == 'impulse':
        up, pts, n = w[0] == 'up', float(w[1]), int(kw(w, 'within'))
        bases = [a] if (ctx['ev'] and not kw(w, 'from')) else range(start, end + 1)
        for b in bases:
            seg = slice(b, b + n + 1)
            if np.isnan(d.H[seg]).all() or np.isnan(d.L[b]) or np.isnan(d.H[b]):
                continue
            if up:
                hi = np.nanmax(d.H[seg])
                if hi - d.L[b] >= pts:
                    t = b + int(np.nanargmax(d.H[seg]))
                    yield t, dict(t=t, tb=b, top=hi, base=d.L[b], size=hi - d.L[b], dir='up', level=hi)
                    return
            else:
                lo = np.nanmin(d.L[seg])
                if d.H[b] - lo >= pts:
                    t = b + int(np.nanargmin(d.L[seg]))
                    yield t, dict(t=t, tb=b, top=lo, base=d.H[b], size=d.H[b] - lo, dir='down', level=lo)
                    return
    elif op == 'reclaim':
        X = ctx['vars'][w[0]]
        n = int(kw(w, 'within'))
        seg = slice(X['t'], X['t'] + n + 1)
        if X['dir'] == 'down':
            ok = np.nanmax(d.C[seg]) > X['level']
            depth, ext = X['level'] - np.nanmin(d.L[seg]), np.nanmin(d.L[seg])
        else:
            ok = np.nanmin(d.C[seg]) < X['level']
            depth, ext = np.nanmax(d.H[seg]) - X['level'], np.nanmax(d.H[seg])
        if kw(w, 'maxdepth'):
            ok &= depth <= float(kw(w, 'maxdepth'))
        if kw(w, 'above'):
            ok &= ext > d.level(kw(w, 'above'), ctx)
        if kw(w, 'below'):
            ok &= ext < d.level(kw(w, 'below'), ctx)
        if ok:
            yield X['t'] + n, dict(X, t=X['t'] + n, depth=depth, ext=ext)
    elif op in ('nohigh', 'nolow'):
        lvl, n = d.level(w[0], ctx), int(w[1])
        seg = slice(a + 1, a + n + 1)
        bad = np.nanmax(d.H[seg]) > lvl if op == 'nohigh' else np.nanmin(d.L[seg]) < lvl
        if not bad:
            yield a + n, None
    elif op == 'wait':
        yield a + int(w[0]), None
    else:
        raise ValueError(f'unknown clause: {c["text"]}')


HARD = 'hard'  # a filter failed after an event: the day is out (no retrying a later event)
FILTERS = STATE | {'reclaim', 'nohigh', 'nolow'}


def match(d, cl, k=0, ctx=None):
    """first chain of events that fits. 'any' retries later candidates only when a later EVENT fails;
    once the chain reaches a filter, the day commits (the 10/28 rule: first qualifying event, then condition on it)."""
    r = _match(d, cl, k, ctx)
    return None if r is HARD else r


def _match(d, cl, k=0, ctx=None):
    ctx = ctx or dict(a=-1, vars={}, ev=False)
    if k == len(cl):
        return ctx
    c = cl[k]
    if c['op'] == 'at':
        ctx = dict(ctx, a=tmin(c['w'][0]) - 1)
    if c['op'] in STATE:
        if not check_state(d, c, ctx):
            return HARD if ctx['ev'] else None
        if CONDMOVE and c['op'] in ('cond', 'smt', 'esconfirm'):  # it read bars up to X.t+N: the anchor can't be earlier than that
            X = ctx['vars'][c['w'][1] if c['op'] == 'cond' else c['w'][0]]
            ctx = dict(ctx, a=max(ctx['a'], X['t'] + int(kw(c['w'], 'within') or 5)))
        return _match(d, cl, k + 1, ctx)
    got = False
    for t, v in candidates(d, c, ctx):
        if t > 1379:
            continue
        got = True
        nv = dict(ctx['vars'])
        if v is not None and kw(c['w'], 'as'):
            nv[kw(c['w'], 'as')] = v
        r = _match(d, cl, k + 1, dict(a=int(t), vars=nv, ev=True))
        if r is HARD or r is not None:
            return r
    return HARD if (c['op'] in FILTERS and ctx['ev'] and not got) else None


# ---------------------------------------------------------------- outcomes
def ends_of(w, a):
    return [(f'by {clock(tmin(t))}', tmin(t)) for t in (kw(w, 'by', None) or [])] + \
           [(f'within {n} min', a + int(n)) for n in (kw(w, 'within', None) or [])]


def side_of(d, ctx, part):
    """race side words -> (label, level, up, var)"""
    a, px = ctx['a'], d.px(ctx['a'])
    if part[0] == 'retrace':
        X, th = ctx['vars'][part[1]], float(part[2])
        lv = X['top'] - th * X['size'] if X['dir'] == 'up' else X['top'] + th * X['size']
        return ' '.join(part), lv, X['dir'] == 'down', part[1]
    nm = part[-1]
    lv = d.level(nm, ctx)
    up = part[0] == 'above' if part[0] in ('above', 'below') else lv > px
    return ' '.join(part), lv, up, var_of(nm)


def outcomes(d, outs, ctx):
    """rows: (label, value 1/0/NaN, depth, minutes, level, already-passed 0/1, meta for live logging)"""
    a, R = ctx['a'], []
    px = d.px(a)
    for o in outs:
        w = o['w']
        if o['op'] == 'hit':
            lvl = d.level(w[0], ctx)
            up = lvl > px
            v = var_of(w[0])
            pre = (d.touched(ctx['vars'][v]['t'] + 1, a, lvl, up) if v else False) and GUARD
            for lab, e in ends_of(w, a) or [('by 3:00 PM', 1320)]:
                lab = f'hit {w[0]} {lab}'
                meta = dict(kind='touch', lvl=lvl, up=up, end=e)
                if e <= a or np.isnan(lvl) or pre:
                    R.append((lab, np.nan, np.nan, np.nan, lvl, int(bool(pre)), meta))
                    continue
                t = d.touch(a, lvl, up, e)
                seg = slice(a + 1, e + 1)
                dep = (np.nanmax(d.H[seg]) - lvl) if up else (lvl - np.nanmin(d.L[seg]))
                R.append((lab, float(not np.isnan(t)), dep if not np.isnan(t) else np.nan, t - a, lvl, 0, meta))
        elif o['op'] == 'retrace':
            X = ctx['vars'][w[0]]
            stop = min([w.index(k) for k in ('within', 'by') if k in w] + [len(w)])
            ths = [float(x) for x in w[1:stop]]
            seg0 = slice(X['t'] + 1, a + 1)
            r_pre = (((X['top'] - np.nanmin(d.L[seg0])) if X['dir'] == 'up' else (np.nanmax(d.H[seg0]) - X['top'])) / X['size']) if a > X['t'] else 0
            for lab, e in ends_of(w, a):
                seg = slice(a + 1, e + 1)
                ok = e > a and (~np.isnan(d.L[seg])).any()
                r = ((X['top'] - np.nanmin(d.L[seg])) if X['dir'] == 'up' else (np.nanmax(d.H[seg]) - X['top'])) / X['size'] if ok else np.nan
                for th in ths:
                    lvl = X['top'] - th * X['size'] if X['dir'] == 'up' else X['top'] + th * X['size']
                    meta = dict(kind='touch', lvl=lvl, up=X['dir'] == 'down', end=e)
                    if r_pre >= th and GUARD:  # already there before the anchor: not a hit, set aside
                        R.append((f'retrace {th:g} of {w[0]} {lab}', np.nan, np.nan, np.nan, lvl, 1, meta))
                        continue
                    t = d.touch(a, lvl, X['dir'] == 'down', e) if ok else np.nan
                    R.append((f'retrace {th:g} of {w[0]} {lab}', np.nan if not ok else float(r >= th), np.nan, t - a, lvl, 0, meta))
        elif o['op'] == 'race':
            j = w.index('vs')
            S = [side_of(d, ctx, p) for p in (w[:j], w[j + 1:])]
            pre = GUARD and any(d.touched(ctx['vars'][v]['t'] + 1, a, lv, up) if v else d.touched(a, a, lv, up) for _, lv, up, v in S)
            meta = dict(kind='race', a=[S[0][1], S[0][2]], b=[S[1][1], S[1][2]], la=S[0][0], lb=S[1][0], end=1379)
            if pre:
                for lab, lv, _, _ in S:
                    R.append((f'race: {lab} first', np.nan, np.nan, np.nan, lv, 1, dict(meta, side=lab)))
                R.append(('race: same bar / neither', np.nan, np.nan, np.nan, np.nan, 1, None))
                continue
            ts = [d.touch(a, lv, up, 1379) for _, lv, up, _ in S]
            t0, t1 = [np.inf if np.isnan(t) else t for t in ts]
            first = 'neither' if t0 == t1 == np.inf else 'same bar' if t0 == t1 else S[0][0] if t0 < t1 else S[1][0]
            mins = min(t0, t1) - a if min(t0, t1) < np.inf else np.nan
            for lab, lv, _, _ in S:
                R.append((f'race: {lab} first', float(first == lab), np.nan, mins if first == lab else np.nan, lv, 0, dict(meta, side=lab)))
            R.append(('race: same bar / neither', float(first in ('same bar', 'neither')), np.nan, np.nan, np.nan, 0, None))
        elif o['op'] == 'extremes':
            for t in kw(w, 'by', None) or ['15:00']:
                seg = slice(a + 1, tmin(t) + 1)
                if tmin(t) <= a:
                    continue
                e = tmin(t)
                R.append((f'max up by {clock(e)} (pts)', np.nan, np.nanmax(d.H[seg]) - px, np.nan, np.nan, 0, dict(kind='ext', up=True, end=e)))
                R.append((f'max down by {clock(e)} (pts)', np.nan, px - np.nanmin(d.L[seg]), np.nan, np.nan, 0, dict(kind='ext', up=False, end=e)))
        elif o['op'] == 'lodhod':
            lo, hi = np.nanargmin(d.L[:1380]), np.nanargmax(d.H[:1380])
            for nm, t in (('low', lo), ('high', hi)):
                for b, s, e in cso.BUCKETS:
                    R.append((f'{nm} of day in {b}', float(s <= t < e), np.nan, np.nan, np.nan, 0, None))
        else:
            raise ValueError(f'unknown outcome: {o["text"]}')
    return R


# ---------------------------------------------------------------- run + ladder
_MC = {}


def matches(g, cl, lo, hi):
    """[(day index, ctx)] for every day the clause chain matches; cached (history doesn't change while the process runs)"""
    key = (id(g), tuple(c['text'] for c in cl), lo, hi, GUARD, CONDMOVE)
    if key not in _MC:
        if len(_MC) > 400:
            _MC.clear()
        out = []
        for i in np.flatnonzero(g.valid & (g.days >= lo) & (g.days < hi)):
            ctx = match(Day(g, i), cl)
            if ctx is not None:
                out.append((i, ctx))
        _MC[key] = out
    return _MC[key]


def run(g, cl, outs, lo=None, hi='2027-01-01'):
    lo = lo or ('2011-01-01' if OLD else '2020-01-01')
    rows = []
    for i, ctx in matches(g, cl, lo, hi):
        d = Day(g, i)
        for lab, v, dep, mins, lvl, pre, _ in outcomes(d, outs, ctx):
            rows.append((g.days[i], lab, v, dep, mins, pre))
    return pd.DataFrame(rows, columns=['day', 'out', 'v', 'dep', 'min', 'pre'])


def wilson(k, n, z=1.2816):
    if n == 0:
        return np.nan, np.nan
    p = k / n
    c = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    m = (p + z * z / (2 * n)) / (1 + z * z / n)
    return max(0.0, m - c), min(1.0, m + c)


PERS = (('24-26', '2024', '2027'), ('24-25', '2024', '2026'), ('2026', '2026', '2027'), ('20-23', '2020', '2024'), ('11-19', '2011', '2020'))


def summarize(df, allp=False):
    out = []
    for lab in dict.fromkeys(df.out):
        x = df[df.out == lab]
        per = {}
        for nm, a, b in PERS:
            if allp and nm == '24-26':
                a = "2011"
            y = x[(x.day >= a) & (x.day < b)]
            v = pd.to_numeric(y.v, errors='coerce').astype(float).dropna()  # never average an object column (the 10/28 9% bug)
            per[nm] = (float(v.sum()), len(v), y)
        k, n, y = per['24-26']
        out.append(dict(out=lab, k=k, n=n, ci=wilson(k, n), per=per, dep=y.dep.dropna(), mins=y['min'].dropna(),
                        pre=float(y.pre.mean()) if len(y) else 0.0, days=len(y)))
    return out


def loosen(c):
    """timing clause +50%: cond ... within N -> 1.5N ; nohigh L N -> N/2 (half the quiet time required)"""
    w = list(c['w'])
    if c['op'] == 'cond':  # '>=' gets more days with a longer window, '<' with a shorter one
        j = w.index('within') + 1
        w[j] = str(max(1, int(round(int(w[j]) * (1.5 if w[2] == '>=' else 0.5)))))
    else:
        w[1] = str(max(1, int(w[1]) // 2))
    return dict(c, w=w, text=f'{c["op"]} {" ".join(w)}', loose=True)


def ladder(g, cl, outs, need=30, fast=False):
    """tightest first; then the single change that frees the most days (loosen a timing clause by 50%, or drop a state /
    already-loosened clause), again and again, until n >= need. Ends with the events-only base for contrast."""
    def days(df):  # counted days: the most-counted outcome row, 2024-26 (a day set aside by the guard doesn't count)
        x = df[df.day >= '2024']
        if not len(x):
            return 0
        c = pd.to_numeric(x.v, errors='coerce').notna() | x.dep.notna()
        return int(x[c].groupby('out').day.nunique().max()) if c.any() else 0
    probe = lambda c2: days(run(g, c2, outs, lo='2024-01-01'))  # choose on 2024-26 (the n that counts), fast
    lo = '2024-01-01' if fast else None
    df = run(g, cl, outs, lo=lo)
    cur = list(cl)
    canshrink = lambda c: (c['op'] in STATE and c['op'] != 'at') or c['op'] in LOOSEN
    rungs = [dict(label='TIGHTEST', n=days(df), df=df, cl=cur, base=not any(canshrink(c) for c in cl))]
    while rungs[-1]['n'] < need:
        best = None
        others = any(canshrink(c) and c['op'] not in LAST_DROP for c in cur)
        for j, c in enumerate(cur):
            if not canshrink(c) or (others and c['op'] in LAST_DROP):
                continue
            if c['op'] in LOOSEN and not c.get('loose'):  # timing: exact -> +/-50% -> any (dropped)
                opts = [(cur[:j] + [loosen(c)] + cur[j + 1:], f'timing +/-50%: {c["text"]} -> {loosen(c)["text"]}')]
            else:
                opts = [(cur[:j] + cur[j + 1:], f'dropped: {c["text"]}')]
            for c2, lab in opts:
                n = probe(c2)
                if best is None or n > best[1]:
                    best = (c2, n, lab)
        if best is None:
            break
        cur = best[0]
        d2 = run(g, cur, outs, lo=lo)
        rungs.append(dict(label=best[2], n=days(d2), df=d2, cl=cur, base=not any(canshrink(c) for c in cur)))
    if not rungs[-1]['base']:
        c2 = [c for c in cl if not canshrink(c)]
        d2 = run(g, c2, outs, lo=lo)
        rungs.append(dict(label='BASE (events only)', n=days(d2), df=d2, cl=c2, base=True))
    else:
        rungs[-1]['label'] = (rungs[-1]['label'] + '  = BASE') if len(rungs) > 1 else 'BASE (events only)'
    return rungs


def pct(k, n):
    return f'{k / n * 100:3.0f}%' if n else '  - '


def answer_rung(rungs):
    return next((r for r in rungs if r['n'] >= 30), rungs[-1])


def when(s, now_a):
    """median minutes after the anchor -> '18m 10:14 AM' (today's clock time when the anchor is now)"""
    if not len(s['mins']):
        return ''
    m = float(s['mins'].median())
    return f'{m:.0f}m' + (f' {clock(now_a + m)}' if now_a is not None else '')


def show(rungs, today=None, shape=None, now_a=None, fast=False):
    base = rungs[-1]
    bsum = {s['out']: s for s in summarize(base['df'])} if len(base['df']) else {}
    ans = answer_rung(rungs)
    cols = [] if fast else ['24-25', '2026', '20-23'] + (['11-19'] if OLD else [])
    for r in ([ans] if fast else rungs) + ([shape] if shape else []):
        thin = '  [thin: under 15 days]' if r['n'] < 15 else '  [under 30]' if r['n'] < 30 else ''
        star = '   <- answer' if r is ans else ''
        md = r['df'][r['df'].day >= '2024'].day.nunique() if not r.get('shape') else r['n']
        print(f'\n-- {r["label"]}: {r["n"]} days counted {"2020-26" if r.get("shape") else "2024-26"}'
              + (f' ({md} matched, {md - r["n"]} set aside: already past)' if md > r['n'] else '') + f'{thin}{star}')
        if fast and r is ans and len(rungs) > 1:
            print('   ladder: ' + ' -> '.join(f'{x["n"]}' + (' (answer)' if x is ans else '') for x in rungs)
                  + '  [' + ' | '.join(x['label'] for x in rungs[1:]) + ']')
        if r.get('note'):
            print('   ' + r['note'])
        if not len(r['df']):
            continue
        S = summarize(r['df'], allp=r.get('shape', False))
        if all(s['n'] == 0 for s in S) and any(s['pre'] for s in S):
            print(f'   every matched day was already past these levels at the anchor: nothing to count')
            continue
        print(f'   {"outcome":46s} {"2024-26":>7s} {"80% range":>11s} {"n":>4s} {"base":>5s} ' + ' '.join(f'{c:>8s}' for c in cols)
              + f'  {"depth":>16s} {"when (median)":>15s}  today')
        for s in S:
            if s['n'] == 0 and not len(s['dep']) and not s['pre']:
                continue
            k, n = s['k'], s['n']
            b = bsum.get(s['out'])
            bp = pct(b['k'], b['n']) if b and b['n'] else '  - '
            cells = []
            for c in cols:
                kc, nc, _ = s['per'][c]
                mark = ''
                if c == '2026' and b and r is not base and nc >= 5:
                    bk5, bn5, _ = b['per']['24-25']
                    bk6, bn6, _ = b['per']['2026']
                    k5, n5, _ = s['per']['24-25']
                    if bn5 and bn6 and n5:
                        s5, s6 = np.sign(k5 / n5 - bk5 / bn5), np.sign(kc / nc - bk6 / bn6)
                        mark = '=' if s5 == 0 else ('ok' if s5 == s6 else 'x')
                cells.append(f'{pct(kc, nc) + mark:>8s}')
            ci = f'{s["ci"][0] * 100:3.0f}-{s["ci"][1] * 100:3.0f}%' if n else ''
            med = f'{s["dep"].median():.0f} pts ({s["dep"].quantile(.25):.0f}-{s["dep"].quantile(.75):.0f})' if len(s['dep']) else ''
            tp = today.get(s['out'], '') if today else ''
            print(f'   {s["out"][:46]:46s} {pct(k, n) if n else "":>7s} {ci:>11s} {n:4d} {bp:>5s} ' + ' '.join(cells) + f'  {med:>16s} {when(s, now_a):>15s}  {tp}')
            if s['pre'] > 0:
                print(f'   {"":46s} ! {s["pre"] * 100:.0f}% of matched days were already past this level at the anchor: set aside, not counted')
    print('\n   n = days counted for that row (matched days minus any set aside). 80% range = Wilson. base = last rung (events only).'
          + ('' if fast else ' 2026 ok/x = same / opposite side of the base as 2024-25.') + ' Times CT.')


# ---------------------------------------------------------------- live: today's context, shape rung, calibration
def today_ctx(live, cl, outs, over=None, a=None):
    """today's levels for each outcome. over = the impulse read off the chart: used as-is, so prices match the drawn fib lines"""
    d = Day(live, len(live.days) - 1)
    ctx = dict(a=a, vars=over, ev=True) if over else match(d, cl)
    if ctx is None:
        return None, {}, []
    lv, metas = {}, []
    for lab, v, dep, mins, lvl, pre, meta in outcomes(d, outs, ctx):
        if lvl is not None and not (isinstance(lvl, float) and np.isnan(lvl)):
            lv[lab] = f'{lvl:.2f}' + (' (already past today)' if pre else '')
        if meta and not pre:
            metas.append((lab, meta))
    return ctx, lv, metas


def shape_rung(hist, live, now_m, metas, W=75, k=40):
    """nearest past paths: the last W minutes, normalized by their own range, vs every 2020+ day at the same clock time +/-30 min"""
    d = Day(live, len(live.days) - 1)
    a = now_m - 1
    cur = pd.Series(d.C[a - W + 1:a + 1]).ffill().bfill().values
    if a - W + 1 < 0 or np.isnan(cur).any():
        return None
    rng_l = max(cur.max() - cur.min(), 5.0)
    z = (cur - cur[-1]) / rng_l
    px = cur[-1]
    idx = np.flatnonzero(hist.valid & (hist.days >= '2020-01-01') & (hist.days < live.days[-1]))
    best = {}
    for off in range(-30, 31, 5):
        b = a + off
        if b - W + 1 < 0 or b + 1 > 1380:
            continue
        X = pd.DataFrame(hist.C[idx, b - W + 1:b + 1]).ffill(axis=1).bfill(axis=1).values
        ok = ~np.isnan(X).any(1)
        rg = np.maximum(X.max(1) - X.min(1), 5.0)
        Z = (X - X[:, -1:]) / rg[:, None]
        dist = np.sqrt(((Z - z) ** 2).mean(1))
        for j in np.flatnonzero(ok):
            if idx[j] not in best or dist[j] < best[idx[j]][0]:
                best[idx[j]] = (dist[j], off, rg[j], X[j, -1])
    top = sorted(best.items(), key=lambda kv: kv[1][0])[:k]
    rows = []
    for i, (dist, off, rg, pxn) in top:
        dn = Day(hist, i)
        an = a + off
        conv = lambda lv: pxn + (lv - px) / rng_l * rg
        for lab, m in metas:
            if m['kind'] == 'touch':
                lvn, end = conv(m['lvl']), min(1379, m['end'] + off)
                if end <= an:
                    continue
                if dn.touched(an, an, lvn, m['up']):
                    rows.append((hist.days[i], lab, np.nan, np.nan, np.nan, 1))
                    continue
                t = dn.touch(an, lvn, m['up'], end)
                rows.append((hist.days[i], lab, float(not np.isnan(t)), np.nan, t - an, 0))
            elif m['kind'] == 'ext':
                end = min(1379, m['end'] + off)
                if end <= an:
                    continue
                seg = slice(an + 1, end + 1)
                mv = (np.nanmax(dn.H[seg]) - pxn) if m['up'] else (pxn - np.nanmin(dn.L[seg]))
                rows.append((hist.days[i], lab, np.nan, mv / rg * rng_l, np.nan, 0))  # in today's points
            elif m['kind'] == 'race':
                ta = dn.touch(an, conv(m['a'][0]), m['a'][1], 1379)
                tb = dn.touch(an, conv(m['b'][0]), m['b'][1], 1379)
                ta, tb = (np.inf if np.isnan(x) else x for x in (ta, tb))
                first = m['la'] if ta < tb else m['lb'] if tb < ta else None
                rows.append((hist.days[i], lab, float(first == m['side']), np.nan, (min(ta, tb) - an) if first == m['side'] else np.nan, 0))
    df = pd.DataFrame(rows, columns=['day', 'out', 'v', 'dep', 'min', 'pre'])
    near = ', '.join(f'{hist.days[i]:%m/%d/%y} {clock(a + o)}' for i, (dd, o, _, _) in top[:12])
    return dict(label=f'SHAPE: {len(top)} nearest past paths (last {W} min, scaled to their range; 2020-26)', n=len(top), df=df,
                note=f'closest: {near}  (replay these on the chart)', shape=True)


def _js(o):
    return o.item() if hasattr(o, 'item') else str(o)


def log_answer(q, rungs, metas, live, now_m, src):
    """append the live answer (answer rung) to calibration.jsonl; --calibration resolves it later"""
    ans = answer_rung(rungs)
    S = {s['out']: s for s in summarize(ans['df'])}
    day = str(live.days[-1].date())
    with open(CAL, 'a', encoding='utf-8') as f:
        for lab, m in metas:
            s = S.get(lab)
            if not s or not s['n']:
                continue
            f.write(json.dumps(dict(ts=ct_now().isoformat(timespec='seconds'), day=day, asked=now_m, src=src, q=q, out=lab,
                                    rung=ans['label'], n=s['n'], p=round(s['k'] / s['n'], 4), meta=m), default=_js) + '\n')


def resolve(live=None):
    """fill in what happened for logged answers whose window has closed. Uses the cache when it covers the day, else the live chart."""
    if not os.path.exists(CAL):
        return []
    rows = [json.loads(x) for x in open(CAL, encoding='utf-8') if x.strip()]
    g = load_grid()
    todo = [r for r in rows if 'hit' not in r]
    if todo and live is None and any(r['day'] > g.end for r in todo):
        try:
            live = live_grid()[0]
        except Exception:
            live = None
    for r in todo:
        src = g if r['day'] <= g.end else live
        if src is None:
            continue
        j = np.flatnonzero(src.days == pd.Timestamp(r['day']))
        if not len(j):
            continue
        d, m, a = Day(src, j[0]), r['meta'], r['asked'] - 1
        last = int(np.flatnonzero(~np.isnan(d.C))[-1]) if (~np.isnan(d.C)).any() else -1
        if m['kind'] == 'touch':
            t = d.touch(a, m['lvl'], m['up'], m['end'])
            if not np.isnan(t):
                r['hit'] = 1
            elif last >= m['end']:
                r['hit'] = 0
        else:
            ta, tb = d.touch(a, m['a'][0], m['a'][1], 1379), d.touch(a, m['b'][0], m['b'][1], 1379)
            if not (np.isnan(ta) and np.isnan(tb)):
                ta, tb = (np.inf if np.isnan(x) else x for x in (ta, tb))
                if ta != tb:
                    r['hit'] = int((m['la'] if ta < tb else m['lb']) == m['side'])
            elif last >= 1379:
                r['hit'] = 0
    with open(CAL, 'w', encoding='utf-8') as f:
        f.writelines(json.dumps(r, default=_js) + '\n' for r in rows)
    return rows


def calibration(rows=None):
    rows = [r for r in (rows if rows is not None else resolve()) if 'hit' in r]
    if not rows:
        print('No resolved live answers yet. Every --now / --q / --ask --live answer is logged; check back after the windows close.')
        return None
    df = pd.DataFrame(rows)
    df['b'] = pd.cut(df.p, [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0001], right=False)
    print(f'\nCalibration: {len(df)} resolved live answers ({df.day.nunique()} sessions)')
    print(f'   {"called":>9s} {"n":>5s} {"avg call":>9s} {"happened":>9s}  80% range')
    for b, x in df.groupby('b', observed=True):
        lo, hi = wilson(x.hit.sum(), len(x))
        print(f'   {str(b):>9s} {len(x):5d} {x.p.mean() * 100:8.0f}% {x.hit.mean() * 100:8.0f}%  {lo * 100:.0f}-{hi * 100:.0f}%')
    brier = float(((df.p - df.hit) ** 2).mean())
    ref = float(((df.hit.mean() - df.hit) ** 2).mean())
    print(f'   Brier {brier:.3f} (always calling the overall rate: {ref:.3f}; lower is better)')
    df['where'] = [('London' if 480 <= m - 1 < 660 else 'NYAM' if 930 <= m - 1 < 1110 else 'Asia' if 120 <= m - 1 < 360 else 'other') for m in df.asked]
    print(f'\n   {"session":>8s} {"n":>5s} {"avg call":>9s} {"happened":>9s} {"Brier":>6s}')
    for w, x in df.groupby('where'):
        print(f'   {w:>8s} {len(x):5d} {x.p.mean() * 100:8.0f}% {x.hit.mean() * 100:8.0f}% {((x.p - x.hit) ** 2).mean():6.3f}')
    return brier


# ---------------------------------------------------------------- live chart
_LIVE = {}


def live_grid(bars=6000, max_age=15):
    if _LIVE and time.time() - _LIVE['t'] < max_age:
        return _LIVE['v']
    v = _live_grid(bars)
    _LIVE.update(t=time.time(), v=v)
    return v


def _live_grid(bars=6000):
    sys.path.insert(0, os.path.join(cso.ROOT, 'ema_backtest'))
    import tv_pull
    d = asyncio.run(asyncio.wait_for(tv_pull.pull(bars), 30))  # never hang the watcher on a stuck chart read
    if d['res'] != '1':
        sys.exit(f'chart is on {d["res"]}: switch it to 1 minute')
    tv = pd.DataFrame(d['bars'], columns=['t', 'open', 'high', 'low', 'close', 'volume'])
    tv['ct'] = pd.to_datetime(tv.t, unit='s', utc=True).dt.tz_convert('America/Chicago').dt.tz_localize(None)
    tv['sym'], tv['adj'] = 'TV', 0.0
    tv['day'] = (tv.ct + pd.Timedelta(hours=7)).dt.normalize()
    days, A, _ = grid_arrays(tv)
    return Grid(days, A, np.zeros(len(days), bool)), tv.ct.iloc[-1], d['sym']


def replay_grid(at):
    """a past minute from the cache as if it were live: that day cut at the minute"""
    g = load_grid()
    ts = pd.Timestamp(at)
    day = (ts + pd.Timedelta(hours=7)).normalize()
    i = int(np.flatnonzero(g.days == day)[0])
    m = tmin(f'{ts.hour}:{ts.minute}')
    A = {k: np.array(x[: i + 1], copy=True) for k, x in (('open', g.O), ('high', g.H), ('low', g.L), ('close', g.C), ('volume', g.V))}
    for k in A:
        A[k][i, m:] = np.nan
    return Grid(g.days[: i + 1], A, np.zeros(i + 1, bool)), m


def read_state(lv, m):
    """the chart, read: session, latest impulse with fib levels (today's prices), deepest retrace, minutes since, sweeps"""
    d = Day(lv, len(lv.days) - 1)
    a = m - 1
    H, L = d.H, d.L
    sess = 'london' if 480 <= a < 660 else 'asia' if 120 <= a < 360 else 'on' if a < 930 else 'rth'
    s0 = SESS[sess][0]
    st = dict(a=a, m=m, sess=sess, s0=s0, px=d.px(a), end={'london': 659, 'asia': 359, 'on': 929, 'rth': 1319}[sess])
    # impulse: the most recent move within 10 min that is at least 60% of the biggest one in the last 90 min (and >= 25 pts)
    moves = []
    for b in range(max(s0, a - 90), a + 1):
        seg = slice(b, min(a, b + 10) + 1)
        if np.isnan(L[b]) or np.isnan(H[b]) or np.isnan(H[seg]).all():
            continue
        moves.append(('up', np.nanmax(H[seg]) - L[b], b + int(np.nanargmax(H[seg])), b))
        moves.append(('down', H[b] - np.nanmin(L[seg]), b + int(np.nanargmin(L[seg])), b))
    if moves:
        big = max(x[1] for x in moves)
        cand = [x for x in moves if x[1] >= max(25, 0.6 * big)]
        if cand:
            dirn, sz, top, b = max(cand, key=lambda x: (x[2], x[1]))  # latest top, then the biggest
            # extend the top to the real extreme since (the move may have kept going)
            if dirn == 'up':
                top = b + int(np.nanargmax(H[b:a + 1]))
                sz = H[top] - L[b]
            else:
                top = b + int(np.nanargmin(L[b:a + 1]))
                sz = H[b] - L[top]
            topv, basev = (H[top], L[b]) if dirn == 'up' else (L[top], H[b])
            seg = slice(top + 1, a + 1)
            if a > top:
                deep_t = top + 1 + int(np.nanargmin(L[seg]) if dirn == 'up' else np.nanargmax(H[seg]))
                r_now = ((topv - L[deep_t]) if dirn == 'up' else (H[deep_t] - topv)) / sz
            else:
                deep_t, r_now = top, 0.0
            vol = None
            if lv.V is not None and not np.isnan(lv.V[-1][b]):
                med = np.nanmedian(lv.V[-1][max(0, b - 30):b])
                vol = float(lv.V[-1][b] / med) if med > 0 else None
            made_ext = L[b] <= np.nanmin(L[s0:b]) if dirn == 'up' and b > s0 else H[b] >= np.nanmax(H[s0:b]) if b > s0 else False
            st['imp'] = dict(dir=dirn, size=float(sz), b=b, top=top, topv=float(topv), basev=float(basev), r_now=float(r_now),
                             deep_t=deep_t, since=a - top, speed=deep_t - top, vol=vol, made_ext=bool(made_ext),
                             fibs={r: float(topv - r * sz if dirn == 'up' else topv + r * sz) for r in FIBS})
    sw = []
    ctx = dict(a=a, vars={}, ev=False)
    for nm in ('asia_hi', 'asia_lo', 'pdh', 'pdl'):
        lvl = d.level(nm, ctx)
        if np.isnan(lvl) or a < SINCE.get('asia' if nm.startswith('asia') else 'pd', 0):
            continue
        lo = SINCE.get('asia' if nm.startswith('asia') else 'pd', 0)
        x = H[lo:a + 1] > lvl if name_is_hi(nm) else L[lo:a + 1] < lvl
        if x.any():
            t = lo + int(np.argmax(x))
            sw.append(dict(name=nm, lvl=float(lvl), t=t, back=bool(d.px(a) < lvl if name_is_hi(nm) else d.px(a) > lvl)))
    st['swept'] = sw
    st['asia'] = (lv.asia_lo[-1], lv.asia_hi[-1])
    st['pd'] = (lv.pdl[-1], lv.pdh[-1])
    st['lv'] = lv
    st['news'] = {1: 'fomc', 2: 'cpi', 3: 'nfp', 4: 'red'}.get(int(lv.ev[-1]))
    if st.get('imp'):
        i = st['imp']
        st['over'] = {'I': dict(t=i['top'], tb=i['b'], top=i['topv'], base=i['basev'], size=i['size'], dir=i['dir'], level=i['topv'])}
    st['london'] = (np.nanmin(L[480:m]), np.nanmax(H[480:m])) if m > 480 else (np.nan, np.nan)
    return st


def news_today(day):
    try:
        e = pd.read_csv(cso.EV)
        e = e[(e.impact == 'high') & (e.date == str(day.date()))]
        return ', '.join(f'{r.event.split(" (")[0]} {r.time_ct} CT' for r in e.itertuples())
    except Exception:
        return ''


def print_state(st):
    if st.get('news'):
        print(f'NEWS DAY ({st["news"].upper()}): {news_today(st["lv"].days[-1])}. Matches use same-kind days first, then fall back (flagged).')
    print(f'Price {st["px"]:.2f} | {st["sess"]} session | Asia {st["asia"][1]:.2f} / {st["asia"][0]:.2f} | prior NY {st["pd"][1]:.2f} / {st["pd"][0]:.2f}'
          + (f' | London so far {st["london"][1]:.2f} / {st["london"][0]:.2f}' if not np.isnan(st['london'][0]) else ''))
    for s in st['swept']:
        print(f'Swept {s["name"]} {s["lvl"]:.2f} at {clock(s["t"])} CT; now {"back inside" if s["back"] else "still beyond"}')
    i = st.get('imp')
    if i:
        print(f'Impulse {"up" if i["dir"] == "up" else "down"} {i["size"]:.0f} pts: {clock(i["b"])} {i["basev"]:.2f} -> {clock(i["top"])} {i["topv"]:.2f} CT'
              + (f', off a new {st["sess"]} {"low" if i["dir"] == "up" else "high"}' if i['made_ext'] else '')
              + (f', turn-bar volume {i["vol"]:.1f}x the 30-min median' if i['vol'] else ''))
        print(f'  deepest pullback so far {i["r_now"] * 100:.0f}% at {clock(i["deep_t"])} ({i["speed"]} min after the top); {i["since"]} min since the top')
        print('  fib  ' + '  '.join(f'{r:g}: {p:.2f}{" (hit)" if i["r_now"] >= r else ""}' for r, p in i['fibs'].items()))


def context_prefix(st):
    """the event chain that reproduces the live impulse, with timing (#3) and volume as loosenable / droppable conditions"""
    i = st.get('imp')
    if not i:
        return None
    t = hhmm
    s0, end = st['s0'], st['end']
    pts = int(i['size'] * 0.8 // 5 * 5)
    win = max(3, min(i['top'] - i['b'], 10) + 2)
    pre = ''
    if i['made_ext'] and i['b'] > s0:
        pre = f'{"newlow" if i["dir"] == "up" else "newhigh"} {st["sess"]} from {t(max(s0 + 1, i["b"] - 20))} to {t(min(end, i["b"] + 20))} any as E; '
    q = pre + f'impulse {i["dir"]} {pts} within {win}' + ('' if pre else f' from {t(max(s0, i["b"] - 20))} to {t(i["b"] + 20)}') + ' as I'
    if i['vol'] and i['vol'] >= 2:
        q += f'; volspike I >= {min(3, int(i["vol"]))}'
    lo_t = max([x for x in FIBS if x <= i['r_now']], default=None)
    hi_t = min([x for x in FIBS if x > i['r_now']], default=None)
    if i['since'] >= 1:
        q += f'; {"nohigh" if i["dir"] == "up" else "nolow"} I.top {i["since"]}'   # elapsed: no new extreme since the top
    if lo_t and i['speed'] >= 1:
        q += f'; cond retrace I >= {lo_t:g} within {i["speed"]}'          # how fast it got this deep (window ends before now)
    if hi_t and i['since'] >= 1:
        q += f'; cond retrace I < {hi_t:g} within {i["since"]}'
    return q


def later_ends(st):
    e = {hhmm(st['end']), '8:29', '15:00'} - ({'8:29'} if st['a'] >= 929 else set())
    if st['end'] >= 1318:
        e.discard(hhmm(st['end']))
    return ' '.join(sorted(e, key=tmin))


def auto_questions(st):
    Q = []
    pre = context_prefix(st)
    i = st.get('imp')
    L_ = later_ends(st)
    if pre:
        ahead = [x for x in FIBS if x > i['r_now']]
        if ahead:
            Q.append((f'{"Bounce" if i["dir"] == "up" else "Drop"} of {i["size"]:.0f} pts, {i["r_now"] * 100:.0f}% retraced so far: does it pull back further?',
                      pre + f'; ?retrace I {" ".join(f"{x:g}" for x in ahead)} within 20 60 by {L_}'))
            nxt = next((x for x in ahead if x >= 0.5), ahead[0])
            Q.append((f'...a {nxt:g} retrace or a new extreme past the impulse first?',
                      pre + f'; ?race {"above" if i["dir"] == "up" else "below"} I.top vs retrace I {nxt:g}'))
    for s in st['swept'][-2:]:
        nm, up = s['name'], name_is_hi(s['name'])
        other = {'pdh': 'pdl', 'pdl': 'pdh'}.get(nm, nm[:-2] + ('lo' if up else 'hi'))
        back = 'below' if up == s['back'] else 'above'  # where price is now vs the swept level
        far = f'{nm}{"+" if up else "-"}40' if not s['back'] else other  # extension if still beyond, the other side if back inside
        Q.append((f'Swept {nm} at {clock(s["t"])} CT, now {"back inside" if s["back"] else "still beyond"}: retest it or {"run 40 more" if not s["back"] else "reach " + other} first?',
                  f'at {hhmm(max(0, s["t"] - 15))}; break {nm} to {hhmm(s["t"] + 15)} as B; wait {max(0, st["a"] - s["t"])}; {back} {nm}; '
                  f'?race hit {nm} vs hit {far}; ?hit {nm} within 30 60 by {L_}; ?hit {other} by {L_}'))
    if st['sess'] == 'rth':
        Q += ny_questions(st, L_)
    if st['sess'] == 'london' and not np.isnan(st['asia'][0]):
        lo, hi = st['asia']
        p = (st['px'] - lo) / (hi - lo)
        band = [x for x in [(-9, 0), (0, .4), (.4, .6), (.6, 1), (1, 9)] if x[0] <= p < x[1]][0]
        sw = '; '.join(f'{"swept" if any(s["name"] == n for s in st["swept"]) else "unswept"} {n}' for n in ('asia_hi', 'asia_lo'))
        Q.append((f'Price at {p * 100:.0f}% of the Asia range: London high or London low first?',
                  f'at {hhmm(st["m"])}; {sw}; pos asia {band[0]} {band[1]}; ?race above london_hi vs below london_lo; ?hit asia_hi by {L_}; ?hit asia_lo by {L_}'))
    if st.get('news'):  # news day: same-kind days first; the ladder drops this clause last and says so
        Q = [(t, f'event {st["news"]}; ' + q if not q.startswith('newlow') and not q.startswith('newhigh') and not q.startswith('impulse')
              else q.replace('; ?', f'; event {st["news"]}; ?', 1)) for t, q in Q]
    if not Q:  # never print nothing: the plain where-from-here read
        hl = {'asia': 'asia', 'london': 'london', 'rth': 'rth'}.get(st['sess'], 'on')
        Q.append((f'No impulse or sweep in view: {hl} high or low first from here?',
                  f'at {hhmm(st["m"])}; ?race above {hl}_hi vs below {hl}_lo; ?extremes by {L_}'))
    return Q[:5]


def ny_questions(st, L_):
    """NYAM: price vs the 8:30 open, VWAP and the first 15-min bar, the open-drive / first-bar / Crabel reads, IB break side"""
    lv, m, a = st['lv'], st['m'], st['a']
    d = Day(lv, len(lv.days) - 1)
    ctx = dict(a=a, vars={}, ev=False)
    px = st['px']
    side = lambda nm: (None if np.isnan(d.level(nm, ctx)) else ('above' if px > d.level(nm, ctx) else 'below'))
    st_ = [f'{side(n)} {n}' for n in ('open', 'vwap') if side(n)]
    if a >= 944:
        for nm, arr in (('opendrive', lv.opendrive), ('firstbar', lv.firstbar)):
            st_.append(f'{nm} {({1: "up", -1: "down"}.get(int(arr[-1]), "none"))}')
    if lv.crabel_t[-1] <= a:
        st_.append(f'crabel {"up" if lv.crabel[-1] > 0 else "down"}')
    Q = [(f'NY at {clock(a)}: ' + ', '.join(st_) + ': which side of the overnight range next?',
          f'at {hhmm(m)}; ' + '; '.join(st_) + f'; ?race above on_hi vs below on_lo; ?hit pdh by 15:00; ?hit pdl by 15:00; ?lodhod')]
    if a >= 989:
        ib = [f'{"swept" if np.nanmax(d.H[990:m]) > d.level("ib_hi", ctx) else "unswept"} ib_hi',
              f'{"swept" if np.nanmin(d.L[990:m]) < d.level("ib_lo", ctx) else "unswept"} ib_lo'] if m > 990 else []
        Q.append((f'IB {d.level("ib_lo", ctx):.2f} - {d.level("ib_hi", ctx):.2f}: ' + (', '.join(ib) or 'just set') + ': which IB side breaks next?',
                  f'at {hhmm(m)}; ' + '; '.join(ib + [f'{side("vwap")} vwap'] if side('vwap') else ib) +
                  f'; ?race above ib_hi vs below ib_lo; ?extremes by 15:00'))
    elif a >= 944:
        Q.append((f'First 15-min bar {d.level("fb_lo", ctx):.2f} - {d.level("fb_hi", ctx):.2f}: which side breaks first?',
                  f'at {hhmm(m)}; {side("open")} open; ?race above fb_hi vs below fb_lo; ?hit ib_hi by 9:29; ?hit ib_lo by 9:29'))
    return Q


# -- plain English -> question (a small template mapper over the live read)
WORDS = [(r'(london|asia|overnight|on) (high|low)', lambda m: f'{ {"overnight": "on"}.get(m.group(1), m.group(1))}_{"hi" if m.group(2) == "high" else "lo"}'),
         (r"(prior|previous|yesterday'?s?)( day| ny)? (high|low)|pd([hl])", lambda m: 'pdh' if (m.group(3) == 'high' or m.group(4) == 'h') else 'pdl'),
         (r'(0?\.\d+|1\.0|100%?|\d\d(\.\d)?%)', lambda m: 'FIB:' + m.group(1)),
         (r'new (high|low)', lambda m: 'NEW:' + m.group(1))]


def fib_of(s):
    s = s.rstrip('%')
    v = float(s)
    return v / 100 if v > 1.0 else v


def phrase_level(s, st):
    for pat, f in WORDS:
        m = re.search(pat, s)
        if m:
            x = f(m)
            if x.startswith('FIB:'):
                return f'I.r{fib_of(x[4:]):g}', 'fib'
            if x.startswith('NEW:'):
                i = st.get('imp')
                if i and ((x[4:] == 'high') == (i['dir'] == 'up')):
                    return 'I.top+0.25' if i['dir'] == 'up' else 'I.top-0.25', 'top'
                return f'{st["sess"] if st["sess"] in ("asia", "london") else "on"}_{"hi" if x[4:] == "high" else "lo"}', 'lvl'
            return x, 'lvl'
    return None, None


def from_phrase(text, st):
    s = text.lower().strip()
    pre = context_prefix(st) or f'at {hhmm(st["m"])}'
    if st.get('news'):
        pre += f'; event {st["news"]}'
    L_ = later_ends(st)
    m = re.search(r'which (comes )?first[:,]? (.+?) or (.+)$', s) or re.search(r'^(.+?) or (.+?) first', s)
    if m:
        a, b = (m.group(2), m.group(3)) if m.re.pattern.startswith('which') else (m.group(1), m.group(2))
        sides = []
        for p in (a, b):
            lv, kind = phrase_level(p, st)
            if lv is None:
                return None, f'could not read a level in "{p}"'
            sides.append(f'retrace I {lv[3:]}' if kind == 'fib' else f'hit {lv}')
        return pre + f'; ?race {sides[0]} vs {sides[1]}', None
    lv, kind = phrase_level(s, st)
    if lv is None:
        return None, 'no level found. Try: "odds of hitting .786", "new london high", "back to the asia low", "which first .618 or new high"'
    if kind == 'fib':
        if not st.get('imp'):
            return None, 'no impulse on the chart in the last 90 min to measure a retrace from'
        side = 'above' if st['imp']['dir'] == 'up' else 'below'
        return pre + f'; ?retrace I {lv[3:]} within 20 60 by {L_}; ?race {side} I.top vs retrace I {lv[3:]}', None
    return pre + f'; ?hit {lv} within 30 60 by {L_}', None


# ---------------------------------------------------------------- ask / now / q
def ask(q, g=None, live=None, now_m=None, src='ask', quiet=False, fast=False, over=None):
    g = g or load_grid()
    cl, outs = parse(q)
    print(f'\nQ: {q}')
    rungs = ladder(g, cl, outs, fast=fast)
    today, shape = None, None
    if live is not None:
        ctx, today, metas = today_ctx(live, cl, outs, over, now_m - 1 if now_m else None)
        if ctx is None:
            print('   (today does not match this question: prices, shape rung and logging skipped)')
        else:
            shape = shape_rung(g, live, now_m, metas) if now_m else None
            if src != 'replay':
                log_answer(q, rungs, metas, live, now_m, src)
    show(rungs, today, shape, now_m - 1 if (now_m and live is not None) else None, fast)
    json.dump(dict(q=q, rungs=[dict(label=r['label'], n=r['n'], rows=[(s['out'], s['k'], s['n']) for s in summarize(r['df'])]) for r in rungs]),
              open(LAST, 'w'), default=float)
    return rungs


def live_or_replay(at):
    if at:
        lv, m = replay_grid(at)
        return lv, m, f'replay {at} CT (history)', 'replay'
    lv, last, sym = live_grid()
    m = tmin(f'{last.hour}:{last.minute}') + 1
    return lv, m, f'{sym} live, last bar {clock(m - 1)} CT', 'now'


def now(at=None, q_text=None, draw_it=False, fast=False, out=None):
    """the live read. out: a list that collects (title, question, answer rung) for live_latest.json"""
    g = load_grid()
    lv, m, src, kind = live_or_replay(at)
    if kind != 'replay':
        resolve(lv)
    st = read_state(lv, m)
    print(f'CSO LIVE  {src}  (computed {ct_now():%I:%M:%S %p} CT)')
    print_state(st)
    if q_text:
        q, err = from_phrase(q_text, st)
        if err:
            print(err)
            return
        qs = [(f'"{q_text}"', q)]
    else:
        qs = auto_questions(st)
    first = None
    for title, q in qs:
        print('\n' + '=' * 120 + f'\n{title}')
        try:
            r = ask(q, g, lv, m, 'q' if q_text else kind, fast=fast, over=st.get('over') if ' as I' in q else None)
        except Exception as e:  # one bad question must not blank the whole read
            print(f'   (skipped: {type(e).__name__}: {e})')
            continue
        first = first or (q, r, title)
        if out is not None:
            ans = answer_rung(r)
            out.append(dict(title=title, q=q, rung=ans['label'], n=ans['n'],
                            rows=[dict(out=x['out'], p=round(x['k'] / x['n'], 3) if x['n'] else None, n=x['n'], ci=[round(c, 3) for c in x['ci']]
                                       if x['n'] else None, mins=float(x['mins'].median()) if len(x['mins']) else None)
                                  for x in summarize(ans['df'])]))
    print('\nDescriptive odds from matched past days, not a signal.')
    if draw_it and st.get('imp') and first:
        draw(st, first[1])
    if first:
        try:
            png = LATEST + '.png' if out is not None else ANSWER_PNG
            chart(st, lv, m, *first, png)
            print(f'Chart: {png}')
            view = view_data(st, lv, m, src, *first)
            json.dump(view, open(png[:-4] + '_view.json', 'w', encoding='utf-8'), default=_js)
        except Exception as e:
            print(f'(chart skipped: {type(e).__name__}: {e})')
    return st


def plain(lab):
    """an outcome label in words: 'hit london_lo by 3:59 AM' -> 'Reach London low by 3:59 AM'"""
    m = re.match(r'hit (\S+) (.+)', lab)
    if m:
        return f'Reach {level_name(m.group(1))} {m.group(2)}'
    m = re.match(r'retrace (\S+) of \S+ (.+)', lab)
    if m:
        return f'Pull back to the {m.group(1)} {m.group(2)}'
    m = re.match(r'race: (.+) first', lab)
    if m:
        w = m.group(1).split()
        return ('Same bar / neither first' if w[0] in ('same', 'neither') else
                f'{w[-1]} retrace first' if w[0] == 'retrace' else f'{level_name(w[-1])} first')
    return lab[0].upper() + lab[1:]


def bar_time(lv, i, m):
    """minute m of grid day i -> epoch seconds of that CT wall-clock time (so the page's chart axis reads CT)"""
    return int((lv.days[i] - pd.Timedelta(hours=7) + pd.Timedelta(minutes=int(m))).value // 10**9)


def bars_out(lv, a, W=240):
    """the last W one-minute bars up to minute a (yesterday's tail too), as [t, o, h, l, c] for the page's live chart"""
    i = len(lv.days) - 1
    out = []
    if a < W and i > 0:
        for m in range(1380 - (W - a), 1380):
            if not np.isnan(lv.C[i - 1][m]):
                out.append([bar_time(lv, i - 1, m), *(round(float(x[i - 1][m]), 2) for x in (lv.O, lv.H, lv.L, lv.C))])
    for m in range(max(0, a - W), a + 1):
        if not np.isnan(lv.C[i][m]):
            out.append([bar_time(lv, i, m), *(round(float(x[i][m]), 2) for x in (lv.O, lv.H, lv.L, lv.C))])
    return out


def view_data(st, lv, m, src, q, rungs, title):
    """everything the page shows for one answer, as plain data: state, the sample, each level's odds by window, other rows"""
    import contextlib, io
    a = m - 1
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_state(st)
    _, today, _ = today_ctx(lv, *parse(q), st.get('over') if ' as I' in q else None, a)
    L = chart_rows(rungs, today, a)
    px = float(st['px'])
    levels = []
    for p, e in sorted(L.items(), key=lambda x: -x[0]):
        up = p > px
        name = ('New high' if up else 'New low') if e['name'].startswith('past the impulse') else e['name']
        rows = sorted(e['rows'], key=lambda r: r['end'])
        levels.append(dict(name=name, price=p, dist=p - px, rows=rows,
                           dep=dict(zip(('win', 'med', 'q1', 'q3', 'n'), e['dep'])) if e['dep'] else None))
    ans = answer_rung(rungs)
    other = []
    for s in summarize(ans['df']):
        tp = (today or {}).get(s['out'], '')
        if not s['n'] or (tp and 'already past' not in tp and re.match(r'(hit|retrace|race: (?!same))', s['out'])):
            continue
        other.append(dict(label=plain(s['out']), p=s['k'] / s['n'], ci=[float(c) for c in s['ci']], n=s['n'],
                          t=float(s['mins'].median()) if len(s['mins']) else None,
                          dep=[float(s['dep'].median()), float(s['dep'].quantile(.25)), float(s['dep'].quantile(.75))] if len(s['dep']) >= 5 else None,
                          past='already past' in tp))
    return dict(title=title.strip('"'), q=q, src=src, at=clock(a), px=px, sess=st['sess'], news=st.get('news'),
                bars=bars_out(lv, a), now_t=bar_time(lv, len(lv.days) - 1, a),
                state=[x for x in buf.getvalue().splitlines() if x.strip()],
                sample=dict(label=ans['label'], n=ans['n'], ladder=[dict(label=r['label'], n=r['n']) for r in rungs]),
                levels=levels, other=other, swept=st['swept'], imp=st.get('imp') and {k: st['imp'][k] for k in ('dir', 'size', 'basev', 'topv', 'r_now')})


# ---------------------------------------------------------------- the chart picture: today's bars + every level the answer measured
ANSWER_PNG = os.path.join(HERE, 'answer.png')
NAMES = {'asia': 'Asia', 'london': 'London', 'on': 'Overnight', 'rth': 'NY', 'ib': 'IB', 'fb': 'First 15-min bar', 'pm': 'NY PM'}


def level_name(tok):
    """'london_lo' -> 'London low', 'I.r0.5' -> '0.5 retrace', 'I.top' -> 'impulse extreme'"""
    tok = re.sub(r'[+-]\d+(\.\d+)?$', '', tok)
    if tok.startswith('I.r'):
        return f'{tok[3:]} retrace'
    if tok == 'I.top':
        return 'past the impulse extreme'
    fixed = {'pdh': 'Prior-day high', 'pdl': 'Prior-day low', 'pdc': 'Prior-day close', 'open': '8:30 open', 'vwap': 'VWAP'}
    if tok in fixed:
        return fixed[tok]
    s, _, side = tok.rpartition('_')
    return f'{NAMES.get(s, s)} {"high" if side == "hi" else "low"}' if side in ('hi', 'lo') else tok


def chart_rows(rungs, today, a):
    """one entry per price level: name, the measured odds rows (% / window / median time), and how far it ran past on days it hit"""
    S = summarize(answer_rung(rungs)['df'])
    L = {}
    for s in S:
        lab, tp = s['out'], (today or {}).get(s['out'], '')
        if not tp or 'already past' in tp or not s['n']:
            continue
        m = re.match(r'hit (\S+) (.+)', lab) or re.match(r'retrace (\S+) of \S+ (.+)', lab) or re.match(r'race: (.+) first', lab)
        if not m:
            continue
        if lab.startswith('hit'):
            name, win = level_name(m.group(1)), m.group(2)
        elif lab.startswith('retrace'):
            name, win = f'{m.group(1)} retrace', m.group(2)
        else:
            side = m.group(1).split()
            name, win = (f'{side[-1]} retrace' if side[0] == 'retrace' else level_name(side[-1])), 'reached first'
        p = float(tp.split()[0])
        e = L.setdefault(round(p * 4) / 4, dict(name=name, rows=[], dep=None))
        t = float(s['mins'].median()) if len(s['mins']) else None
        w = re.match(r'within (\d+)', win)
        end = a + int(w.group(1)) if w else tmin(win[3:]) if win.startswith('by ') else 9999
        e['rows'].append(dict(win=win, end=end, p=s['k'] / s['n'], n=s['n'], t=t, at=clock(a + t) if t is not None else None,
                              ci=[float(c) for c in s['ci']]))
        if len(s['dep']) >= 5 and (e['dep'] is None or win == 'within 60 min'):  # 'how far past' over the next hour when we have it
            e['dep'] = (win, s['dep'].median(), s['dep'].quantile(.25), s['dep'].quantile(.75), len(s['dep']))
    return L


def chart(st, lv, m, q, rungs, title, path, W=150):
    """clean markup: bars up to now, then one line per measured level with its odds and timing. Measured numbers only."""
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    BG, FG, MUTED, GRIDC, UP, DN = '#181818', '#d1d4dc', '#808080', '#242424', '#089981', '#f23645'
    a = m - 1
    d = Day(lv, len(lv.days) - 1)
    ctx, today, _ = today_ctx(lv, *parse(q), st.get('over') if ' as I' in q else None, a)
    L = chart_rows(rungs, today, a)
    s0 = max(0, a - W + 1)
    x = np.arange(s0, a + 1)
    O, H, Lo, C = (lv.O[-1][s0:a + 1], d.H[s0:a + 1], d.L[s0:a + 1], d.C[s0:a + 1])
    fig = Figure(figsize=(13, 7), facecolor=BG)
    ax = fig.add_axes([0.04, 0.08, 0.6, 0.8], facecolor=BG)
    for xi, o, h, l, c in zip(x, O, H, Lo, C):
        if np.isnan(c):
            continue
        col = '#b8b8b8' if c >= o else '#5a5a5a'
        ax.vlines(xi, l, h, color=col, lw=0.8)
        ax.vlines(xi, min(o, c), max(o, c) + 0.01, color=col, lw=2.6)
    px = st['px']
    i = st.get('imp')
    if i:  # the impulse the odds are measured from
        ax.plot([i['b'], i['top']], [i['basev'], i['topv']], color=MUTED, lw=1, ls=':')
    fut = 70  # minutes of empty space after now, where the lines run
    ax.axvline(a, color=MUTED, lw=0.8, ls='--')
    ax.text(a, 1.01, f' now {clock(a)}', transform=ax.get_xaxis_transform(), color=MUTED, fontsize=9)
    ax.axhline(px, color=FG, lw=0.6)
    ax.text(a + fut, px, f'{px:,.2f} now ', color=FG, fontsize=8.5, ha='right', va='bottom')
    ys = [px] + [p for p in L] + list(H[~np.isnan(H)]) + list(Lo[~np.isnan(Lo)])
    lo_y, hi_y = min(ys), max(ys)
    pad = (hi_y - lo_y) * 0.06 or 5
    ax.set_ylim(lo_y - pad, hi_y + pad)
    ax.set_xlim(s0, a + fut)
    ticks = [t for t in range(s0, a + fut, 30) if t % 30 == 0]
    ax.set_xticks(ticks, [clock(t) for t in ticks])
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.yaxis.tick_right()
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.grid(color=GRIDC, lw=0.6)
    # labels: one block per level, in a right panel, spread so they never overlap, joined to their line
    side = fig.add_axes([0.66, 0.08, 0.33, 0.8], facecolor=BG, sharey=ax)
    side.axis('off')
    side.set_xlim(0, 1)
    gap = (hi_y - lo_y + 2 * pad) / max(9, 2.8 * len(L) + 1)
    pos, last = {}, None
    for p in sorted(L):
        y = p if last is None or p - last >= gap * 2.6 else last + gap * 2.6
        pos[p], last = y, y
    shift = max(0, last - (hi_y + pad - gap)) if last is not None else 0
    for p, e in L.items():
        up = p > px
        col = UP if up else DN
        ax.hlines(p, a, a + fut, color=col, lw=1.2)
        ax.text(a + fut, p, f'{p:,.2f} ', color=col, fontsize=8.5, ha='right', va='bottom')
        y = pos[p] - shift
        side.plot([0, 0.03], [p, y], color=col, lw=0.8, clip_on=False)
        name = ('New high' if up else 'New low') if e['name'].startswith('past the impulse') else e['name']
        lines = [f'{name}   {abs(p - px):.0f} pts {"above" if up else "below"}']
        rows = sorted(e['rows'], key=lambda r: r['end'])[:6]
        cells = [f'{r["p"] * 100:.0f}% {r["win"]}' for r in rows]
        lines += ['   '.join(cells[k:k + 3]) for k in range(0, len(cells), 3)]
        lines[-1] += f'   (n {rows[-1]["n"]})'
        last = rows[-1]
        if last['t'] is not None:
            lines.append(f'when it hit: median {last["t"]:.0f} min after now (~{last["at"]})')
        if e['dep']:
            win, md, q1, q3, nd = e['dep']
            lines.append(f'then, {win}: ran {md:.0f} pts further (middle half {q1:.0f}-{q3:.0f}, {nd} days)')
        side.text(0.05, y, lines[0], color=col, fontsize=10, fontweight='bold', va='bottom')
        side.text(0.05, y, '\n'.join(lines[1:]), color=FG, fontsize=8.8, va='top', linespacing=1.35)
    fig.text(0.04, 0.955, title.strip('"'), color='#ffffff', fontsize=13, fontweight='bold')
    n = answer_rung(rungs)['n']
    fig.text(0.04, 0.925, f'NQ {clock(a)} CT  ·  price {px:,.2f}  ·  {n} matched past days (2024-26)  ·  '
             'descriptive odds, not a signal', color=MUTED, fontsize=9.5)
    if not L:
        side.text(0.05, px, 'No price levels in this answer to mark.', color=MUTED, fontsize=10)
    fig.savefig(path, dpi=110, facecolor=BG)


# ---------------------------------------------------------------- TradingView drawing (never saved to the layout)
APPLY = """(async function(remove, add) {
  var api = window.TradingViewApi._activeChartWidgetWV.value();
  if (!/NQ/.test(api.symbol())) return {skip: api.symbol()};
  var have = {}; api.getAllShapes().forEach(function(s) { have[s.id] = 1; });
  remove.forEach(function(id) { if (have[id]) api.removeEntity(id); });
  var made = [];
  for (var i = 0; i < add.length; i++) {
    var a = add[i];
    try {
      made.push(String(await api.createShape({time: a.time, price: a.price}, {shape: 'horizontal_line', text: a.text, lock: true,
        disableSelection: true, disableSave: true, disableUndo: true, showInObjectsTree: false, overrides: a.overrides})));
    } catch (e) {}
  }
  return {made: made};
})"""


async def _cdp(expr):
    import aiohttp
    async with aiohttp.ClientSession() as s:
        pages = await (await s.get('http://127.0.0.1:9222/json', timeout=aiohttp.ClientTimeout(total=5))).json()
        pages = [p for p in pages if p.get('type') == 'page' and 'tradingview.com/chart' in p.get('url', '')]
        page = next((p for p in pages if '/chart/iNmrhguD' in p['url']), pages[0] if pages else None)
        async with s.ws_connect(page['webSocketDebuggerUrl'], max_msg_size=0) as ws:
            await ws.send_json({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': expr, 'awaitPromise': True, 'returnByValue': True}})
            while True:
                msg = await ws.receive_json()
                if msg.get('id') == 1:
                    return msg['result'].get('result', {}).get('value')


def fib_labels(st, rungs):
    """'0.786 · 64% in 60 min · n 41' per fib level, from the answer rung"""
    ans = answer_rung(rungs)
    S = {s['out']: s for s in summarize(ans['df'])}
    out = []
    for r, p in st['imp']['fibs'].items():
        if st['imp']['r_now'] >= r:
            out.append((p, f'{r:g} · hit already'))
            continue
        s = S.get(f'retrace {r:g} of I within 60 min') or S.get(f'retrace {r:g} of I within 20 min')
        lab = f'{r:g} · {s["k"] / s["n"] * 100:.0f}% in 60 min · n {s["n"]}' if s and s['n'] else f'{r:g}'
        out.append((p, lab))
    return out


def draw(st, rungs):
    clear(quiet=True)
    t = int(time.time()) // 60 * 60
    add = [dict(time=t, price=round(p, 2), text=f'CSO {lab}', overrides={'linecolor': '#9598a1', 'linestyle': 2, 'linewidth': 1, 'showLabel': True,
            'textcolor': '#d1d4dc', 'horzLabelsAlign': 'right', 'vertLabelsAlign': 'top', 'fontsize': 11, 'bold': False, 'showPrice': True})
           for p, lab in fib_labels(st, rungs)]
    r = asyncio.run(_cdp(f'{APPLY}([], {json.dumps(add)})'))
    if r and 'made' in r:
        json.dump(r['made'], open(DRAWN, 'w'))
        print(f'\nDrew {len(r["made"])} fib lines on TradingView (not saved to the layout). Remove: cso_live.py --clear')
    else:
        print(f'\nDrawing skipped: {r}')


def clear(quiet=False):
    ids = json.load(open(DRAWN)) if os.path.exists(DRAWN) else []
    if ids:
        asyncio.run(_cdp(f'{APPLY}({json.dumps(ids)}, [])'))
        os.remove(DRAWN)
    if not quiet:
        print(f'Removed {len(ids)} CSO lines.')


# ---------------------------------------------------------------- alerts (dry run until a webhook exists)
SETUPS = {
    'stop_run': ('London-low stop run that snapped back',
                 'at 2:45; swept asia_hi; unswept asia_lo; inside asia; break london_lo to 3:59 as B; reclaim B within 5 maxdepth 20 above asia_lo; '
                 '?hit london_hi by 3:59 8:29 15:00; ?hit asia_lo by 3:59 8:29 15:00'),
    'fast_bounce': ('60+ pt bounce within 7 min off a new London low',
                    'newlow london from 1:30 to 3:59 any as L; impulse up 60 within 7 as I; ?retrace I 0.382 0.5 0.618 1 within 30 60 by 3:59 8:29 15:00'),
    'asia_sweep_back': ('London swept the Asia high and is back inside',
                        'at {now}; swept asia_hi; unswept asia_lo; inside asia; ?race above london_hi vs below london_lo; ?hit asia_lo by 3:59 8:29 15:00'),
}


def alerts(at=None):
    g = load_grid()
    lv, m, src, kind = live_or_replay(at)
    d = Day(lv, len(lv.days) - 1)
    a = m - 1
    fired = []
    for key, (title, q) in SETUPS.items():
        q = q.replace('{now}', hhmm(m))
        cl, _ = parse(q)
        ctx = match(d, cl)
        if ctx is None or not (a - 15 <= ctx['a'] <= a):  # only setups that completed in the last 15 min
            continue
        fired.append(key)
        print(f'\nALERT (dry run, not posted): {title} at {clock(ctx["a"])} CT')
        ask(q, g, lv, m, 'alert')
    if not fired:
        print(f'{src}: no known setup completed in the last 15 min.')
    print('\nPosting to Discord needs the user\'s webhook for a new channel (make-bot conventions); signals only, never orders.')
    return fired


# ---------------------------------------------------------------- journal
def journal(day, trades=None):
    g = load_grid()
    D = pd.Timestamp(day)
    if day <= g.end:
        src = g
    else:
        src = live_grid(9000)[0]
    j = np.flatnonzero(src.days == D)
    if not len(j):
        sys.exit(f'no bars for {day}')
    d = Day(src, j[0])
    lo_m, hi_m = 0, int(np.flatnonzero(~np.isnan(d.C[:930 + 90]))[-1]) + 1
    # 5-min candles, 5 PM -> 10 AM CT (or the last bar)
    bars = []
    for s in range(lo_m, hi_m, 5):
        c = d.C[s:s + 5]
        if np.isnan(c).all():
            continue
        o = d.g.O[d.i][s:s + 5]
        bars.append((s, float(o[~np.isnan(o)][0]), float(np.nanmax(d.H[s:s + 5])), float(np.nanmin(d.L[s:s + 5])), float(c[~np.isnan(c)][-1])))
    lv = dict(asia_hi=src.asia_hi[j[0]], asia_lo=src.asia_lo[j[0]], pdh=src.pdh[j[0]], pdl=src.pdl[j[0]],
              london_hi=np.nanmax(d.H[480:660]), london_lo=np.nanmin(d.L[480:660]))
    asked = [r for r in (resolve() if os.path.exists(CAL) else []) if r['day'] == day]
    tr = []
    if trades:
        t = pd.read_csv(trades)
        cols = {c.lower(): c for c in t.columns}
        tc = next((cols[c] for c in cols if 'time' in c or 'date' in c), None)
        pc = next((cols[c] for c in cols if 'price' in c), None)
        sc = next((cols[c] for c in cols if c in ('side', 'action', 'b/s', 'buy/sell')), None)
        qc = next((cols[c] for c in cols if 'qty' in c or 'quantity' in c or 'size' in c), None)
        for _, r in t.iterrows():
            ts = pd.Timestamp(r[tc])
            tr.append(dict(m=tmin(f'{ts.hour}:{ts.minute}'), price=float(r[pc]), side=str(r[sc]) if sc else '', qty=str(r[qc]) if qc else ''))
    out = os.path.join(cso.ROOT, 'journal', f'{day}_NQ_London')
    os.makedirs(out, exist_ok=True)
    data = dict(day=day, bars=bars, levels={k: (None if np.isnan(v) else float(v)) for k, v in lv.items()},
                asked=[dict(m=r['asked'], q=r['q'], out=r['out'], p=r['p'], n=r['n'], rung=r['rung'], hit=r.get('hit'),
                            lvl=r['meta'].get('lvl') if r['meta']['kind'] == 'touch' else None) for r in asked], trades=tr)
    tpl = open(os.path.join(HERE, 'journal_page.html'), encoding='utf-8').read()
    open(os.path.join(out, 'index.html'), 'w', encoding='utf-8').write(tpl.replace('__DATA__', json.dumps(data, default=float)).replace('__DAY__', day))
    print(f'journal -> {os.path.join(out, "index.html")}  ({len(bars)} 5-min bars, {len(asked)} logged answers, {len(tr)} fills)')
    return out


# ---------------------------------------------------------------- watcher: grid in memory, a live read every minute, ~1 s answers
PORT = 8765
LATEST = os.path.join(HERE, 'live_latest')


def dispatch(argv):
    """run one cso_live command line in this process (the server uses it; prints go to stdout)"""
    a = argv
    arg = lambda k: a[a.index(k) + 1] if k in a else None
    if '--q' in a:
        now(arg('--at'), arg('--q'), '--draw' in a, '--fast' in a)
    elif '--ask' in a:
        q = arg('--ask')
        if '--live' in a or '--at' in a:
            lv, m, src, kind = live_or_replay(arg('--at'))
            q = re.sub(r'\bnow(-\d+)?\b', lambda x: hhmm(m + int(x.group(1) or 0)), q)
            print(f'({src})')
            ask(q, live=lv, now_m=m, src='ask' if kind != 'replay' else 'replay', fast='--fast' in a)
        else:
            ask(q, fast='--fast' in a)
    elif '--now' in a:
        now(arg('--at'), None, '--draw' in a, '--fast' in a)
    elif '--calibration' in a:
        calibration()
    elif '--alerts' in a:
        alerts(arg('--at'))
    else:
        print(__doc__)


def serve(port=PORT):
    import contextlib, io, threading, urllib.parse
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    load_grid()
    lock = threading.Lock()

    def capture(fn):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                fn()
            except SystemExit as e:
                print(e)
            except Exception as e:
                print(f'error: {type(e).__name__}: {e}')
        return buf.getvalue()

    def watch():
        while True:
            t0 = ct_now()
            if t0.hour != 16:  # 5 PM - 4 PM CT: the CME reopens at 5 PM, the 4-5 PM break is skipped
                with lock:
                    _LIVE.clear()
                    out = []
                    txt = capture(lambda: now(None, None, False, True, out))
                    st = _LIVE.get('v')
                    open(LATEST + '.txt', 'w', encoding='utf-8').write(txt)
                    json.dump(dict(at=t0.isoformat(timespec='seconds'), text_file=LATEST + '.txt', questions=out),
                              open(LATEST + '.json', 'w', encoding='utf-8'), default=_js, indent=1)
            time.sleep(max(5, 60 - ct_now().second + 3))

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            kind = 'text/plain'
            if u.path == '/ping':
                body = 'ok'
            elif u.path == '/run':
                argv = json.loads(urllib.parse.parse_qs(u.query)['argv'][0])
                fresh = os.path.exists(LATEST + '.txt') and time.time() - os.path.getmtime(LATEST + '.txt') < 70
                if argv[:1] == ['--now'] and '--fast' in argv and '--at' not in argv and fresh:
                    body = open(LATEST + '.txt', encoding='utf-8').read() + '\n(from the watcher read, ' + \
                        f'{int(time.time() - os.path.getmtime(LATEST + ".txt"))} s old)\n'
                else:
                    with lock:
                        body = capture(lambda: dispatch(argv))
            elif u.path == '/latest':
                body = open(LATEST + '.txt', encoding='utf-8').read() if os.path.exists(LATEST + '.txt') else \
                    'No live read yet (the watcher reads the chart each minute, 5 PM-4 PM CT).'
            elif u.path == '/map.json':
                f = os.path.join(HERE, 'live_map.json')
                ok = os.path.exists(f)
                d = json.load(open(f, encoding='utf-8')) if ok else None
                ef = os.path.join(HERE, 'live_map_error.json')
                err = json.load(open(ef)) if os.path.exists(ef) and (not ok or os.path.getmtime(ef) > os.path.getmtime(f)) else None
                body = json.dumps(dict(map=d, age=int(time.time() - os.path.getmtime(f)) if ok else None, error=err), default=_js)
                kind = 'application/json'
            elif u.path in ('/latest.png', '/answer.png', '/map.png'):
                f = {'/latest.png': LATEST + '.png', '/answer.png': ANSWER_PNG, '/map.png': os.path.join(HERE, 'live_map.png')}[u.path]
                b = open(f, 'rb').read() if os.path.exists(f) else b''
                self.send_response(200 if b else 404)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(b)))
                self.end_headers()
                self.wfile.write(b)
                return
            elif u.path == '/ask':  # the page's question: the text answer + the structured view written beside answer.png
                q = urllib.parse.parse_qs(u.query).get('q', [''])[0]
                vf, t0 = ANSWER_PNG[:-4] + '_view.json', time.time()
                with lock:
                    txt = capture(lambda: dispatch(['--q', q, '--fast']))
                view = json.load(open(vf, encoding='utf-8')) if os.path.exists(vf) and os.path.getmtime(vf) >= t0 else None
                body, kind = json.dumps(dict(text=txt, view=view), default=_js), 'application/json'
            elif u.path == '/view/latest':
                vf = LATEST + '_view.json'
                ok = os.path.exists(vf)
                body = json.dumps(dict(view=json.load(open(vf, encoding='utf-8')) if ok else None,
                                       text=open(LATEST + '.txt', encoding='utf-8').read() if os.path.exists(LATEST + '.txt') else '',
                                       age=int(time.time() - os.path.getmtime(vf)) if ok else None), default=_js)
                kind = 'application/json'
            elif u.path == '/':
                body = open(os.path.join(HERE, 'live_page.html'), encoding='utf-8').read()
                kind = 'text/html'
            else:
                body = 'GET / | /ask?q= | /view/latest | /latest | /ping | /run?argv=[...]'
            b = body.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', kind + '; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    def watch_map():  # the live POI map: every 15 s off the forming bar (poi_live.py)
        import traceback
        err = os.path.join(HERE, 'live_map_error.json')
        while True:
            t1 = time.time()
            if ct_now().hour != 16:
                try:
                    import poi_live
                    poi_live.tick()
                except BaseException as e:   # never let the thread die quietly: the page shows the last error
                    json.dump(dict(error=f'{type(e).__name__}: {e}', at=ct_now().strftime('%I:%M:%S %p'),
                                   trace=traceback.format_exc()[-1500:]), open(err, 'w'))
            time.sleep(max(1, 15 - (time.time() - t1)))

    # load matplotlib (and its font cache) and the map engine once, here, before the two threads start drawing:
    # both doing it at the same time on a fresh start could hang the map thread with no error
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import font_manager
    font_manager.findfont('DejaVu Sans')
    import poi_live
    poi_live.hist()
    threading.Thread(target=watch, daemon=True).start()
    threading.Thread(target=watch_map, daemon=True).start()
    print(f'CSO watcher on http://127.0.0.1:{port}  (live read every minute -> {LATEST}.txt / .json)')
    host = '127.0.0.1'
    if '--lan' in sys.argv:  # phone on the same Wi-Fi; no login, so home network only, never port-forward it
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))  # no packet sent: just picks the LAN address
            print(f'Phone (same Wi-Fi): http://{s.getsockname()[0]}:{port}')
        host = '0.0.0.0'
    ThreadingHTTPServer((host, port), H).serve_forever()


def via_server(argv):
    """send the command to a running watcher; None if it isn't up"""
    import urllib.parse, urllib.request
    try:
        urllib.request.urlopen(f'http://127.0.0.1:{PORT}/ping', timeout=0.3).read()
    except Exception:
        return None
    q = urllib.parse.urlencode({'argv': json.dumps(argv)})
    return urllib.request.urlopen(f'http://127.0.0.1:{PORT}/run?{q}', timeout=300).read().decode('utf-8')


# ---------------------------------------------------------------- self-check
def test():
    g = load_grid()
    g24 = lambda df: df[(df.day >= '2024-01-02') & (df.day <= '2026-10-27')]
    ok = True

    def eq(name, got, want, tol):
        nonlocal ok
        good = abs(got - want) <= tol
        ok &= bool(good)
        print(f'  {"OK " if good else "BAD"} {name}: got {got:.1f}, expected {want}')

    def rate(df, lab):
        v = pd.to_numeric(df[df.out == lab].v, errors='raise').astype(float).dropna()
        return v.mean() * 100, len(v)

    print('Q2  shallow London-low stop run that snapped back -> London high')
    cl, outs = parse('at 2:45; dow 1 2 3 4; swept asia_hi; unswept asia_lo; inside asia; break london_lo to 3:59 as B; '
                     'reclaim B within 5 maxdepth 20 above asia_lo; ?hit london_hi by 3:59 8:29 15:00')
    df = g24(run(g, cl, outs))
    eq('days', df.day.nunique(), 22, 2)
    eq('London high by 4 AM %', rate(df, 'hit london_hi by 3:59 AM')[0], 0, 5)
    eq('by 8:29 %', rate(df, 'hit london_hi by 8:29 AM')[0], 50, 6)
    eq('by 3 PM %', rate(df, 'hit london_hi by 3:00 PM')[0], 68, 6)
    q3 = 'newlow london from 1:30 to 3:59 any as L; impulse up 60 within 7 as I'
    print('Q3  new London low + 60-pt bounce within 7 min -> retrace')
    df = g24(run(g, *parse(q3 + '; ?retrace I 0.382 0.5 1 within 30 60')))
    eq('days', df.day.nunique(), 48, 2)
    eq('38% in 30 min', rate(df, 'retrace 0.382 of I within 30 min')[0], 81, 5)
    eq('100% in 60 min', rate(df, 'retrace 1 of I within 60 min')[0], 56, 5)
    print('Q4  ...38% already hit within 12 min -> 62% within 30 min')
    global GUARD, CONDMOVE
    GUARD, CONDMOVE = False, False  # as hand-built: the 30-min window started at the top, so it included the first 12 min
    df = g24(run(g, *parse(q3 + '; cond retrace I >= 0.382 within 12; ?retrace I 0.618 within 30')))
    GUARD, CONDMOVE = True, True
    eq('days', df.day.nunique(), 32, 2)
    eq('62% in 30 min (look-ahead + no guard, as hand-built)', rate(df, 'retrace 0.618 of I within 30 min')[0], 69, 6)
    df = g24(run(g, *parse(q3 + '; cond retrace I >= 0.382 within 12; ?retrace I 0.618 within 30')))
    p, n = rate(df, 'retrace 0.618 of I within 30 min')
    print(f'      fixed (clock starts at +12 min, 62%-already-hit days set aside): {p:.0f}% of {n}')
    print('Q5  ...no new high in the first 12 min -> 62% retrace before a new high')
    GUARD = False  # tonight's hand-built answer had no already-passed guard
    df = g24(run(g, *parse(q3 + '; nohigh I.top 12; ?race above I.top vs retrace I 0.618')))
    GUARD = True
    eq('days', df.day.nunique(), 17, 2)
    eq('62% first % (guard off, as hand-built)', rate(df, 'race: retrace I 0.618 first')[0], 82, 6)
    df = g24(run(g, *parse(q3 + '; nohigh I.top 12; ?race above I.top vs retrace I 0.618')))
    p, n = rate(df, 'race: retrace I 0.618 first')
    print(f'      with the guard: 62% first {p:.0f}% of the {n} days where 62% was still untouched at +12 min')
    eq('guard sets 62%-already-hit days aside (counted < 17)', float(n < 17), 1, 0)
    print('#1  already-passed guard (the 3:40 AM question): levels reached during the 38-min wait are set aside, not instant hits')
    q = q3 + '; cond retrace I >= 0.5 within 20; nohigh I.top 38; ?retrace I 0.786 1 within 20 60'
    df = g24(run(g, *parse(q)))
    x = df[df.out == 'retrace 0.786 of I within 20 min']
    eq('share of matched days set aside for .786 (> 0)', float(x.pre.mean() > 0), 1, 0)
    counted = x[x.pre == 0]
    eq('no counted hit at minute 0 or before', float((counted['min'] <= 0).sum()), 0, 0)
    print('#1b the hand-built 3:40 AM read: .75 reached before a new high -> 1.0 before a new high (92%, n 12)')
    df = g24(run(g, *parse(q3 + '; break I.r0.75 to 3:59 before I.top as R; ?race above I.top vs hit I.r1')))
    p, n = rate(df, 'race: hit I.r1 first')
    eq('days counted', n, 12, 2)
    eq('1.0 first %', p, 92, 6)
    print('#3  timing-aware ladder: a slow-retrace question loosens timing by 50% before dropping it')
    cl, outs = parse(q3 + '; cond retrace I >= 0.5 within 20; nohigh I.top 38; cond retrace I < 0.786 within 38; ?retrace I 0.786 within 60')
    R = ladder(g, cl, outs)
    labs = [r['label'] for r in R]
    eq('a "timing +/-50%" rung exists', float(any(l.startswith('timing') for l in labs)), 1, 0)
    eq('n never shrinks down the ladder', float(all(R[k]['n'] <= R[k + 1]['n'] for k in range(len(R) - 2))), 1, 0)
    print('#5  calibration: resolve two logged answers on a known day, then Brier')
    global CAL
    keep = CAL
    CAL = os.path.join(HERE, '_test_cal.jsonl')
    i = int(np.flatnonzero(g.days == pd.Timestamp('2026-10-15'))[0])
    hi = float(np.nanmax(g.H[i][540:660]))
    rows = [dict(day='2026-10-15', asked=540, q='t', out='a', rung='t', n=30, p=0.8, meta=dict(kind='touch', lvl=hi - 1, up=True, end=659)),
            dict(day='2026-10-15', asked=540, q='t', out='b', rung='t', n=30, p=0.3, meta=dict(kind='touch', lvl=hi + 500, up=True, end=659))]
    open(CAL, 'w').writelines(json.dumps(r) + '\n' for r in rows)
    res = resolve()
    eq('hit / miss resolved', float(res[0].get('hit', -1) * 10 + res[1].get('hit', -1)), 10, 0)
    eq('Brier', calibration(res) * 100, ((0.8 - 1) ** 2 + 0.3 ** 2) / 2 * 100, 0.01)
    os.remove(CAL)
    CAL = keep
    print('(c) today price column on a DOWN impulse = the fib lines (top + r x size), from the chart read')
    i = int(np.flatnonzero(g.days == pd.Timestamp('2026-10-15'))[0])
    imp = dict(dir='down', size=40.0, b=930, top=940, topv=25000.0, basev=25040.0, r_now=0.2, deep_t=945, since=5, speed=5, vol=None,
               made_ext=False, fibs={r: 25000.0 + r * 40 for r in FIBS})
    over = {'I': dict(t=940, tb=930, top=25000.0, base=25040.0, size=40.0, dir='down', level=25000.0)}
    cl, outs = parse('impulse down 30 within 10 from 9:00 to 9:30 as I; ?retrace I 0.382 1 within 30; ?race below I.top vs retrace I 0.618')
    _, tp, _ = today_ctx(g, cl, outs, over, 945)
    eq('0.382 price', float(tp['retrace 0.382 of I within 30 min'].split()[0]), imp['fibs'][0.382], 0.01)
    eq('1.0 price', float(tp['retrace 1 of I within 30 min'].split()[0]), imp['fibs'][1.0], 0.01)
    eq('0.618 race side', float(tp['race: retrace I 0.618 first'].split()[0]), imp['fibs'][0.618], 0.01)
    print('(d) rung n / % alignment: row n = counted days; no rung reads bars after its anchor')
    cl, outs = parse(q3 + '; cond retrace I >= 0.5 within 20; nohigh I.top 38; ?race above I.top vs retrace I 0.786')
    R_ = ladder(g, cl, outs)
    ok_n = all(sm['n'] == int(pd.to_numeric(r['df'][r['df'].out == sm['out']].pipe(lambda x: x[x.day >= '2024']).v, errors='coerce').notna().sum())
               for r in R_ for sm in summarize(r['df']))
    eq('row n = non-blank rows, every rung', float(ok_n), 1, 0)
    d0 = Day(g, i)
    cl2, _ = parse(q3 + '; cond retrace I >= 0.5 within 20')
    leak = 0
    for j in np.flatnonzero(g.valid & (g.days >= '2024-01-01')):
        c = match(Day(g, j), cl2)
        if c is not None and c['a'] < c['vars']['I']['t'] + 20:
            leak += 1
    eq('days whose anchor is before the end of the cond window', leak, 0, 0)
    print('NYAM levels: first bar / IB exist only once set; VWAP and open from 8:30')
    ctx = dict(a=940, vars={}, ev=False)
    eq('fb_hi at 8:40 is blank', float(np.isnan(d0.level('fb_hi', ctx))), 1, 0)
    ctx = dict(a=960, vars={}, ev=False)
    eq('fb_hi at 9:00 = 8:30-8:44 high', d0.level('fb_hi', ctx), float(np.nanmax(g.H[i][930:945])), 0.01)
    eq('ib_hi at 9:00 is blank', float(np.isnan(d0.level('ib_hi', ctx))), 1, 0)
    eq('open = 8:30 open', d0.level('open', ctx), float(g.O[i][930]), 0.01)
    v = d0.level('vwap', ctx)
    eq('vwap inside the 8:30-9:00 range', float(np.nanmin(g.L[i][930:961]) <= v <= np.nanmax(g.H[i][930:961])), 1, 0)
    print('News: the event clause is dropped last')
    cl, outs = parse('event cpi; at 9:00; above open; above vwap; ?race above on_hi vs below on_lo')
    R_ = ladder(g, cl, outs)
    drops = [r['label'] for r in R_ if r['label'].startswith('dropped')]
    eq('event dropped only after the others', float(not drops or 'event' not in ' '.join(drops[:-1])), 1, 0)
    print('Guard: an object column of True/None must not average to the 10/28 9%')
    s = pd.Series([True, None, False, True], dtype=object)
    eq('guarded mean %', pd.to_numeric(s, errors='coerce').astype(float).dropna().mean() * 100, 66.7, 0.1)
    print('SELF-CHECK', 'PASSED' if ok else 'FAILED')
    return ok


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    a = sys.argv
    arg = lambda k: a[a.index(k) + 1] if k in a else None
    if any(k in a for k in ('--ask', '--q', '--now', '--calibration', '--alerts')) and not any(k in a for k in ('--old', '--local', '--draw')):
        r = via_server(a[1:])
        if r is not None:
            print(r, end='')
            sys.exit(0)
    if '--serve' in a:
        serve()
    elif '--cache' in a:
        build_cache()
    elif '--test' in a:
        sys.exit(0 if test() else 1)
    elif '--clear' in a:
        clear()
    elif '--calibration' in a:
        calibration()
    elif '--alerts' in a:
        alerts(arg('--at'))
    elif '--journal' in a:
        journal(arg('--journal'), arg('--trades'))
    elif any(k in a for k in ('--q', '--ask', '--now')):
        dispatch(a[1:])
    elif '--draw' in a:
        print('use with --now or --q')
    else:
        print(__doc__)
