"""Conditional Scenario Odds (CSO) for NQ Asia (7:00-11:00 PM CT) and London (1:00-4:00 AM CT).

Match the state at a checkpoint (session start, every 30 min, session end) to past days and count what came next:
new session high / low, sweep of the prior session's high / low (+ reclaimed by the close), where the session closes,
range expansion, and the hand-off (next session's first break, NY taking the overnight extreme, low/high-of-day bucket).
Descriptive, not an edge. Cells that differ from the all-days base rate: binomial z + Benjamini-Hochberg on 2024-25,
then re-checked on 2026 (unseen) and 2020-23 (side note; the 1-min data starts 2019-12).

  python -I cso.py              build cso_days.pkl, cso_universe.json, cso_page.json (explorer data)
  python -I cso.py --page       re-render NQ_CSO_Explorer.html from cso_page.json
  python -I cso.py --test       reproduce the 10/28 prototype numbers
  python -I cso.py --now [--at "2026-10-15 02:45"]   live state from the TradingView chart (or a past time) -> scenario tables
"""
import itertools, json, math, os, sys, warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..')
PQ = os.path.join(ROOT, 'ema_backtest', 'data', 'nq_1m.parquet')
EV = os.path.join(ROOT, 'ema_backtest', 'external', 'events_calendar.csv')

# minutes after 5:00 PM CT (the CME day starts at 5 PM). Killzones are fixed in CT, so DST does not move them;
# only the real Tokyo cash open moves (7 PM CT summer, 6 PM CT winter), which is before / at the Asia killzone start.
SESS = {'asia': dict(name='Asia', s0=120, s1=360, prior='prior NY (8:30 AM-3 PM)', nxt=(480, 660), nxt_name='London (1-4 AM)'),
        'london': dict(name='London', s0=480, s1=660, prior='Asia (7-11 PM)', nxt=(660, 1320), nxt_name='4 AM-3 PM')}
RTH = (930, 1320)
BUCKETS = [('Asia', 0, 480), ('London', 480, 660), ('Pre-NY', 660, 930), ('NY open', 930, 1020), ('Midday', 1020, 1200), ('Afternoon', 1200, 1380)]
PERIODS = {'2024-26': ('2024-01-01', '2027-01-01'), '2024-25': ('2024-01-01', '2026-01-01'), '2026': ('2026-01-01', '2027-01-01'),
           '2020-23': ('2020-01-01', '2024-01-01')}


def checkpoints(sk):
    s = SESS[sk]
    return list(range(s['s0'], s['s1'] + 1, 30))  # start, every 30 min, end


def clock(m):
    """minutes after 5 PM -> '2:45 AM'"""
    if m is None or (isinstance(m, float) and math.isnan(m)):
        return '-'
    t = (int(round(m)) + 1020) % 1440
    h, mi = divmod(t, 60)
    return f'{(h - 1) % 12 + 1}:{mi:02d} {"AM" if h < 12 else "PM"}'


STATES = {  # name: (label, bucket labels)
    'pr_rng': ('Prior NY range vs 20-day median', ['narrow (<0.8x)', 'normal', 'wide (>1.25x)']),
    'pr_close': ('Prior NY close in its range', ['bottom third', 'middle third', 'top third']),
    'pr_type': ('Prior NY day type', ['inside day', 'up day', 'down day']),
    'gap': ('Session open vs 3 PM close', ['down >0.1x prior range', 'flat', 'up >0.1x prior range']),
    'loc': ('Price vs prior NY range', ['below PDL', 'lower half', 'upper half', 'above PDH']),
    'ploc': ('Price vs prior session range', ['below its low', 'bottom 40%', 'middle 20%', 'top 40%', 'above its high']),
    'pv_rng': ('Asia range vs 20-day median', ['narrow (<0.75x)', 'normal', 'wide (>1.33x)']),
    'srng': ('This session range so far vs 20-day median', ['narrow (<0.75x)', 'normal', 'wide (>1.33x)']),
    'took': ('Prior session high/low taken this session', ['neither', 'high only, back inside', 'high only, still above',
                                                          'low only, back inside', 'low only, still below', 'both']),
    'spos': ('Price in this session range so far', ['bottom third', 'middle third', 'top third']),
    'last': ('Which extreme was set more recently', ['the low', 'the high']),
    'dow': ('Day of week (trading day)', ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']),
    'event': ('Red-folder news on the trading day', ['none', 'FOMC', 'CPI', 'NFP', 'other high-impact']),
}


def state_names(sk, T):
    s = SESS[sk]
    n = ['pr_rng', 'pr_close', 'pr_type', 'gap', 'ploc', 'dow', 'event']
    if sk == 'london':
        n += ['loc', 'pv_rng']
    if T > s['s0']:
        n += ['srng', 'took', 'spos', 'last']
    return n


OUT = {  # name: plain label (binary outcomes; NaN = not eligible on that day)
    'new_hi': 'New session high after now', 'new_lo': 'New session low after now',
    'sw_ph': 'Sweeps the prior session high', 'sw_pl': 'Sweeps the prior session low',
    'rc_ph': '...high sweep reclaimed (closes back below by session end)', 'rc_pl': '...low sweep reclaimed (closes back above by session end)',
    'cl_top': 'Session closes in top third of its range', 'cl_mid': 'Session closes in middle third', 'cl_bot': 'Session closes in bottom third',
    'nx_hi': 'Next session breaks this session high first', 'nx_lo': 'Next session breaks this session low first', 'nx_none': 'Next session breaks neither',
    'rth_hi': 'NY (8:30 AM-3 PM) goes above the overnight high', 'rth_lo': 'NY (8:30 AM-3 PM) goes below the overnight low',
    **{f'lod{i}': f'Low of day in {b[0]}' for i, b in enumerate(BUCKETS)}, **{f'hod{i}': f'High of day in {b[0]}' for i, b in enumerate(BUCKETS)},
}
DEPTH = ['new_hi', 'new_lo', 'sw_ph', 'sw_pl', 'nx_hi', 'nx_lo', 'rth_hi', 'rth_lo']  # also carry depth (pts), x range, time


# ---------------------------------------------------------------- data
def load(df=None):
    if df is None:
        df = pd.read_parquet(PQ, columns=['ct', 'open', 'high', 'low', 'close', 'sym', 'adj', 'day'])
    df = df[df.day >= '2019-12-17']
    m = ((df.ct.dt.hour * 60 + df.ct.dt.minute).values - 1020) % 1440
    days = np.sort(df.day.unique())
    i = np.searchsorted(days, df.day.values)
    A = {}
    for k in ('open', 'high', 'low', 'close'):
        A[k] = np.full((len(days), 1440), np.nan)
        A[k][i, m] = (df[k] + df.adj).values  # back-adjusted, so prior-day levels are right across a roll
    roll = df.groupby('day').sym.nunique().reindex(days).values > 1  # a day (5 PM-4 PM) must stay in one contract
    return pd.DatetimeIndex(days), A, roll


def events(days):
    e = pd.read_csv(EV)
    e = e[e.impact == 'high']
    e['date'] = pd.to_datetime(e.date)
    code = pd.Series(0, index=days)
    for d, g in e.groupby('date'):
        if d in code.index:
            c = g.category.tolist()
            code[d] = 1 if any(x.startswith('FOMC rate') for x in c) else 2 if 'CPI' in c else 3 if any(x.startswith('Nonfarm') for x in c) else 4
    return code.values


def _hi(X, a, b):
    return np.nanmax(X[:, a:b], 1) if b > a else np.full(len(X), np.nan)


def _lo(X, a, b):
    return np.nanmin(X[:, a:b], 1) if b > a else np.full(len(X), np.nan)


def _last(X, a, b):
    s = X[:, a:b]
    ok = ~np.isnan(s)
    j = s.shape[1] - 1 - np.argmax(ok[:, ::-1], 1)
    v = s[np.arange(len(s)), j]
    v[~ok.any(1)] = np.nan
    return v


def _argx(X, a, b, f):  # minute of the max (f=nanargmax) / min, NaN when the slice is empty
    s = X[:, a:b]
    ok = (~np.isnan(s)).any(1)
    r = np.full(len(X), np.nan)
    r[ok] = f(s[ok], 1) + a
    return r


def _first(mask, a):  # first minute where mask is true, NaN if never
    r = np.where(mask.any(1), mask.argmax(1) + a, np.nan)
    return r


def _cov(X, a, b):
    return (~np.isnan(X[:, a:b])).mean(1)


def _med20(x, ok):
    return pd.Series(np.where(ok, x, np.nan)).rolling(20, min_periods=10).median().shift(1).values


def _cut(x, edges):
    r = np.digitize(x, edges).astype(float)
    r[np.isnan(x)] = np.nan
    return r


def day_tables(days, A, roll, ev=None, extra=()):
    """{(session, T): DataFrame indexed by day with state codes, outcome flags (1/0/NaN), depth, x-range and time columns}"""
    O, H, L, C = A['open'], A['high'], A['low'], A['close']
    nd = len(days)
    ev = events(days) if ev is None else ev
    prev = np.r_[-1, np.arange(nd - 1)]
    prev[1:][np.diff(days.values).astype('timedelta64[D]').astype(int) > 4] = -1
    pv = lambda x: np.where(prev >= 0, x[np.maximum(prev, 0)], np.nan)
    rH, rL, rO, rC = _hi(H, *RTH), _lo(L, *RTH), O[:, RTH[0]], _last(C, *RTH)
    rok = (_cov(C, *RTH) >= 0.8) & ~roll
    prH, prL, prO, prC = pv(rH), pv(rL), pv(rO), pv(rC)
    pok = pv(rok.astype(float)) == 1
    prR = prH - prL
    pp = lambda x: np.where(prev >= 0, x[np.maximum(prev, 0)], np.nan)
    inside = (prH <= pp(prH)) & (prL >= pp(prL))
    day_ok = ~roll & (_cov(C, 0, 1380) >= 0.75) & pok
    full = day_ok & (_cov(C, *RTH) >= 0.8)
    common = dict(
        pr_rng=_cut(prR / _med20(prR, pok), [0.8, 1.25]),
        pr_close=_cut((prC - prL) / prR, [1 / 3, 2 / 3]),
        pr_type=np.where(inside, 0, np.where(prC > prO, 1, 2)).astype(float),
        dow=days.dayofweek.values.astype(float), event=ev.astype(float))
    common['pr_type'][np.isnan(prC)] = np.nan
    lod, hod = _argx(L, 0, 1380, np.nanargmin), _argx(H, 0, 1380, np.nanargmax)
    onH, onL = _hi(H, 0, 930), _lo(L, 0, 930)
    out = {}
    for sk, s in SESS.items():
        s0, s1 = s['s0'], s['s1']
        if sk == 'asia':
            ph, pl = prH, prL
        else:
            ph, pl = _hi(H, 120, 360), _lo(L, 120, 360)
        pr = ph - pl
        fh, fl, fc = _hi(H, s0, s1), _lo(L, s0, s1), _last(C, s0, s1)
        sok = day_ok & (_cov(C, s0, s1) >= 0.8) & (pr > 0)
        n0, n1 = s['nxt']
        th = _first(H[:, n0:n1] > fh[:, None], n0)
        tl = _first(L[:, n0:n1] < fl[:, None], n0)
        gap = (_last(C, 0, s0) - prC) / prR
        for T in checkpoints(sk) + [e for k, e in extra if k == sk]:
            px = _last(C, 0, T)
            sh, sl = (_hi(H, s0, T), _lo(L, s0, T)) if T > s0 else (np.full(nd, np.nan),) * 2
            sr = sh - sl
            t = dict(common, gap=_cut(gap, [-0.1, 0.1]), ploc=_cut((px - pl) / pr, [0, 0.4, 0.6, 1.0000001]),
                     loc=_cut((px - prL) / prR, [0, 0.5, 1.0000001]))
            if sk == 'london':
                t['pv_rng'] = _cut(pr / _med20(pr, sok), [0.75, 1.33])
            if T > s0:
                t['srng'] = _cut(sr / _med20(sr, sok), [0.75, 1.33])
                th_, tl_ = sh > ph, sl < pl
                t['took'] = np.select([th_ & tl_, th_ & (px <= ph), th_, tl_ & (px >= pl), tl_], [5, 1, 2, 3, 4], 0).astype(float)
                t['spos'] = _cut((px - sl) / np.where(sr > 0, sr, np.nan), [1 / 3, 2 / 3])
                t['last'] = (_argx(H, s0, T, np.nanargmax) > _argx(L, s0, T, np.nanargmin)).astype(float)
            o = {}
            nan = np.full(nd, np.nan)
            if s0 < T < s1:
                rh, rl = _hi(H, T, s1), _lo(L, T, s1)
                for k, hit, dep in (('new_hi', rh > sh, rh - sh), ('new_lo', rl < sl, sl - rl)):
                    o[k] = hit.astype(float)
                    o[k + '_d'] = np.where(hit, dep, np.nan)
                    o[k + '_x'] = o[k + '_d'] / sr
                o['new_hi_t'] = np.where(o['new_hi'] == 1, _argx(H, T, s1, np.nanargmax), np.nan)
                o['new_lo_t'] = np.where(o['new_lo'] == 1, _argx(L, T, s1, np.nanargmin), np.nan)
                o['exp'] = (fh - fl) / np.where(sr > 0, sr, np.nan)
            if T < s1:
                rh, rl = _hi(H, T, s1), _lo(L, T, s1)
                takenh = (sh > ph) if T > s0 else np.zeros(nd, bool)
                takenl = (sl < pl) if T > s0 else np.zeros(nd, bool)
                for k, el, hit, dep, msk, lvl, rc in (
                        ('sw_ph', ~takenh & (px <= ph), rh > ph, rh - ph, H[:, T:s1] > ph[:, None], ph, fc < ph),
                        ('sw_pl', ~takenl & (px >= pl), rl < pl, pl - rl, L[:, T:s1] < pl[:, None], pl, fc > pl)):
                    o[k] = np.where(el, hit, np.nan)
                    o[k + '_d'] = np.where(o[k] == 1, dep, np.nan)
                    o[k + '_x'] = o[k + '_d'] / pr
                    o[k + '_t'] = np.where(o[k] == 1, _first(msk, T), np.nan)
                    o['rc' + k[2:]] = np.where(o[k] == 1, rc, np.nan)
                pos = (fc - fl) / (fh - fl)
                for k, a, b in (('cl_bot', -1, 1 / 3), ('cl_mid', 1 / 3, 2 / 3), ('cl_top', 2 / 3, 2)):
                    o[k] = np.where(np.isnan(pos), np.nan, (pos >= a) & (pos < b))
                o['frng'] = fh - fl
            # hand-off (defined at every checkpoint; it is about the future of the whole day)
            hf = np.where(np.isnan(th), np.inf, th) < np.where(np.isnan(tl), np.inf, tl)
            o['nx_hi'] = np.where(full, ~np.isnan(th) & hf, np.nan)
            o['nx_lo'] = np.where(full, ~np.isnan(tl) & ~hf, np.nan)
            o['nx_none'] = np.where(full, np.isnan(th) & np.isnan(tl), np.nan)
            o['nx_hi_d'] = np.where(o['nx_hi'] == 1, _hi(H, n0, n1) - fh, np.nan)
            o['nx_lo_d'] = np.where(o['nx_lo'] == 1, fl - _lo(L, n0, n1), np.nan)
            o['nx_hi_x'], o['nx_lo_x'] = o['nx_hi_d'] / (fh - fl), o['nx_lo_d'] / (fh - fl)
            o['nx_hi_t'], o['nx_lo_t'] = np.where(o['nx_hi'] == 1, th, np.nan), np.where(o['nx_lo'] == 1, tl, np.nan)
            o['rth_hi'] = np.where(full, rH > onH, np.nan)
            o['rth_lo'] = np.where(full, rL < onL, np.nan)
            o['rth_hi_d'] = np.where(o['rth_hi'] == 1, rH - onH, np.nan)
            o['rth_lo_d'] = np.where(o['rth_lo'] == 1, onL - rL, np.nan)
            o['rth_hi_x'], o['rth_lo_x'] = o['rth_hi_d'] / (onH - onL), o['rth_lo_d'] / (onH - onL)
            o['rth_hi_t'] = np.where(o['rth_hi'] == 1, _argx(H, *RTH, np.nanargmax), np.nan)
            o['rth_lo_t'] = np.where(o['rth_lo'] == 1, _argx(L, *RTH, np.nanargmin), np.nan)
            for i, (_, a, b) in enumerate(BUCKETS):
                o[f'lod{i}'] = np.where(full, (lod >= a) & (lod < b), np.nan)
                o[f'hod{i}'] = np.where(full, (hod >= a) & (hod < b), np.nan)
            df = pd.DataFrame({**{k: t[k] for k in state_names(sk, T)}, **o}, index=days)
            df['ok'] = sok
            df['px'], df['sh'], df['sl'], df['ph'], df['pl'] = px, sh, sl, ph, pl
            df['onh'], df['onl'] = _hi(H, 0, T), _lo(L, 0, T)
            out[(sk, T)] = df
    return out


# ---------------------------------------------------------------- the universe
BIN = list(OUT)


def _per(df, p):
    a, b = PERIODS[p]
    return df[(df.index >= a) & (df.index < b)]


def cells(tabs):
    """every combo of 1-3 states, every bucket -> counts per period. Returns long DataFrame (one row per cell x outcome)."""
    rows = []
    for (sk, T), df in tabs.items():
        df = df[df.ok & (df.index >= '2020-01-01')].copy()
        df['per'] = np.select([df.index >= '2026-01-01', df.index >= '2024-01-01'], ['2026', '2024-25'], '2020-23')
        outs = [k for k in BIN if k in df]
        ind = df[outs]
        el = ind.notna().astype(int).add_suffix('#n')
        hit = ind.fillna(0).add_suffix('#k')
        X = pd.concat([df[state_names(sk, T)], df[['per']], hit, el], axis=1)
        base = X.groupby('per')[[*hit.columns, *el.columns]].sum()
        names = state_names(sk, T)
        combos = [()] + [c for r in (1, 2, 3) for c in itertools.combinations(names, r)]
        for c in combos:
            g = X.dropna(subset=list(c)).groupby([*c, 'per'])[[*hit.columns, *el.columns]].sum() if c else base
            g = g.reset_index()
            g['days'] = (X.dropna(subset=list(c)).groupby([*c, 'per']).size().values if c else X.groupby('per').size().values)
            g['sess'], g['T'] = sk, T
            g['key'] = g[list(c)].astype(int).astype(str).agg('|'.join, axis=1).radd('|'.join(c) + '=') if c else 'all'
            rows.append(g[['sess', 'T', 'key', 'per', 'days', *hit.columns, *el.columns]])
    return pd.concat(rows, ignore_index=True)


def _z(k, n, p0):
    se = np.sqrt(p0 * (1 - p0) / np.where(n > 0, n, np.nan))
    return (k / np.where(n > 0, n, np.nan) - p0) / se


def _p2(z):
    return np.array([math.erfc(abs(v) / math.sqrt(2)) if np.isfinite(v) else np.nan for v in z])


def _p1(z):  # one-sided upper tail
    return np.array([0.5 * math.erfc(v / math.sqrt(2)) if np.isfinite(v) else np.nan for v in z])


def universe(U):
    """wide -> long per (cell, outcome), add pooled 2024-26, z vs base, BH on 2024-25, 2026 + 2020-23 checks"""
    U = U.copy()
    pooled = U[U.per != '2020-23'].groupby(['sess', 'T', 'key'], as_index=False).sum(numeric_only=True)
    pooled['per'] = '2024-26'
    U = pd.concat([U, pooled], ignore_index=True)
    long = []
    for o in BIN:
        if f'{o}#k' not in U:
            continue
        x = U[['sess', 'T', 'key', 'per', 'days', f'{o}#k', f'{o}#n']].rename(columns={f'{o}#k': 'k', f'{o}#n': 'n'})
        x = x[x.n > 0]
        x['out'] = o
        long.append(x)
    L = pd.concat(long, ignore_index=True)
    base = L[L.key == 'all'].set_index(['sess', 'T', 'out', 'per'])
    L = L.join((base.k / base.n).rename('p0'), on=['sess', 'T', 'out', 'per'])
    L['pct'] = L.k / L.n
    L['z'] = _z(L.k, L.n, L.p0)
    W = L.pivot_table(index=['sess', 'T', 'key', 'out'], columns='per', values=['k', 'n', 'pct', 'p0', 'z', 'days'])
    W.columns = [f'{a}_{b}' for a, b in W.columns]
    W = W.reset_index()
    W = W[(W.key != 'all') & (W['n_2024-26'] >= 15)].copy()
    # discovery 2024-25: n>=30 there, base strictly between 0 and 1
    test = (W['n_2024-25'] >= 30) & (W['p0_2024-25'] > 0) & (W['p0_2024-25'] < 1)
    W['p_disc'] = np.nan
    W.loc[test, 'p_disc'] = _p2(W.loc[test, 'z_2024-25'].values)
    m = int(test.sum())
    p = W.loc[test, 'p_disc'].values
    order = np.argsort(p)
    q = np.empty(m)
    q[order] = np.minimum.accumulate((p[order] * m / np.arange(1, m + 1))[::-1])[::-1]
    W['q'] = np.nan
    W.loc[test, 'q'] = np.minimum(q, 1)
    W['flag'] = W.q <= 0.05
    sgn = np.sign(W['z_2024-25'])

    def check(per):
        z = W[f'z_{per}'] * sgn
        p1 = _p1(z.fillna(np.nan).values)
        ok = W[f'n_{per}'] >= 10
        return np.where(~ok, 'too few', np.where(p1 < 0.05, 'held', np.where(z > 0, 'same sign', 'flipped')))

    W['y2026'] = check('2026')
    W['y2023'] = check('2020-23')
    ctx = {'pr_rng', 'pr_close', 'pr_type', 'dow', 'event', 'pv_rng'}
    W['kind'] = np.where(W.key.str.split('=').str[0].str.split('|').apply(lambda v: set(v) <= ctx), 'context', 'location')
    zcut = float(W.loc[W.flag, 'z_2024-25'].abs().min())
    return W, m, zcut


# ---------------------------------------------------------------- self-check vs the 10/28 prototype
def test(tabs=None):
    ok = True

    def eq(name, got, want, tol):
        nonlocal ok
        good = abs(got - want) <= tol
        ok &= good
        print(f'  {"OK " if good else "BAD"} {name}: got {got:.1f}, prototype {want}')

    # prototype quirk: the Asia window for a Monday was Friday evening (no data) -> Mondays never matched; data ends 10/16
    t = day_tables(*load(), extra=[('london', 585), ('london', 588)]) if tabs is None or ('london', 588) not in tabs else tabs
    print('Prototype 1: London swept Asia high, back inside, top 40% of Asia range (state through 2:47 AM) -> rest of London')
    x = t[('london', 588)]
    x = x[x.ok & (x.index >= '2024-01-02') & (x.index.dayofweek > 0)]
    M = x[(x.took == 1) & (x.ploc == 3)]
    eq('days', len(M), 61, 2)
    nl = M.new_lo == 1
    sw = M.sw_pl == 1
    eq('no new London low %', (~nl).mean() * 100, 51, 3)
    t2 = M[nl & ~sw]
    eq('new low holds above Asia low %', len(t2) / len(M) * 100, 31, 3)
    eq('sweeps Asia low %', sw.mean() * 100, 18, 3)
    eq('shallow low depth median pts', t2.new_lo_d.median(), 21, 3)
    eq('shallow low time median (min after 1 AM)', t2.new_lo_t.median() - 480, 152, 10)  # 3:32 AM
    # the prototype printed 9% here: pandas averaged an object column of True/None wrong. Its own rows say 5 of 11 = 45%.
    eq('reclaimed Asia low by 4 AM (of sweeps) %', M[sw].rc_pl.mean() * 100, 45, 5)
    print('Prototype 2: same state through 2:44 AM -> low-of-day bucket')
    x = t[('london', 585)]
    x = x[x.ok & (x.index >= '2024-01-02') & (x.index.dayofweek > 0)]
    M = x[(x.took == 1) & (x.ploc == 3) & x.lod0.notna()]
    eq('days', len(M), 61, 5)  # the engine drops holiday-short days (7/3, Thanksgiving, Juneteenth, day after Memorial Day)
    eq('LOD in London %', M.lod1.mean() * 100, 0, 2)
    eq('LOD in NY open %', M.lod3.mean() * 100, 25, 4)
    eq('LOD in afternoon %', M.lod5.mean() * 100, 25, 4)
    F = x[(x.event == 1) & x.lod0.notna()]
    eq('FOMC days n', len(F), 17, 2)
    eq('FOMC LOD in afternoon %', F.lod5.mean() * 100, 53, 6)
    print('SELF-CHECK', 'PASSED' if ok else 'FAILED')
    return ok


# ---------------------------------------------------------------- live read
def now_cp(ts):
    m = (ts.hour * 60 + ts.minute - 1020) % 1440
    for sk in ('london', 'asia'):
        s = SESS[sk]
        if s['s0'] <= m < s['s1']:
            return sk, s['s0'] + (m - s['s0']) // 30 * 30
    if 360 <= m < 480:
        return 'asia', 360
    return 'london', 660  # after London: its end / hand-off


def fmt_pct(v):
    return '  - ' if v is None or (isinstance(v, float) and math.isnan(v)) else f'{v * 100:3.0f}%'


def live(at=None):
    hist = pd.read_parquet(PQ, columns=['ct', 'open', 'high', 'low', 'close', 'sym', 'adj', 'day'])
    if at is None:
        sys.path.insert(0, os.path.join(ROOT, 'ema_backtest'))
        import asyncio
        import tv_pull
        d = asyncio.run(tv_pull.pull(30000))
        tv = pd.DataFrame(d['bars'], columns=['t', 'open', 'high', 'low', 'close', 'volume'])
        tv['ct'] = pd.to_datetime(tv.t, unit='s', utc=True).dt.tz_convert('America/Chicago').dt.tz_localize(None)
        if d['res'] != '1':
            sys.exit(f'chart is on {d["res"]}, switch it to 1 minute')
        tv['sym'], tv['adj'] = 'TV', 0.0
        tv['day'] = (tv.ct + pd.Timedelta(hours=7)).dt.normalize()
        last_tv_day = tv.day.min() + pd.Timedelta(days=1)  # first TV day may be partial
        hist = hist[hist.day < last_tv_day]
        # stitch: shift history so its last close meets TV (different contract / adjustment)
        j = tv.merge(hist[['ct', 'close', 'adj']], on='ct', suffixes=('', '_h'))
        off = float((j.close - (j.close_h + j.adj)).median()) if len(j) else 0.0
        hist = hist.assign(adj=hist.adj + off, sym='TV')
        df = pd.concat([hist, tv[tv.day >= last_tv_day][hist.columns]], ignore_index=True)
        ts = tv.ct.iloc[-1] + pd.Timedelta(minutes=1)
        src = f'{d["sym"]} live, last bar {clock((tv.ct.iloc[-1].hour * 60 + tv.ct.iloc[-1].minute - 1020) % 1440)} CT'
    else:
        ts = pd.Timestamp(at)
        df = hist[hist.ct < ts]
        src = f'replay at {at} CT (history)'
    sk, T = now_cp(ts)
    today = (ts + pd.Timedelta(hours=7)).normalize()
    days, A, roll = load(df[df.day >= today - pd.Timedelta(days=60)])
    roll[:] = False
    tabs = day_tables(days, A, roll)
    row = tabs[(sk, T)].loc[today]
    W = pd.read_parquet(os.path.join(HERE, 'cso_cells.parquet'))
    days_tab = pd.read_pickle(os.path.join(HERE, 'cso_days.pkl'))[(sk, T)]
    names = state_names(sk, T)
    st = {k: row[k] for k in names if not pd.isna(row[k])}
    s = SESS[sk]
    tag = 'start' if T == s['s0'] else 'end + hand-off' if T == s['s1'] else 'during'
    print(f'\nCSO  {s["name"]} {tag} checkpoint {clock(T)} CT   ({src})')
    print(f'Price {row.px:.2f} | session so far H {row.sh:.2f} L {row.sl:.2f} | {s["prior"]} H {row.ph:.2f} L {row.pl:.2f}')
    print('State: ' + '; '.join(f'{STATES[k][0]} = {STATES[k][1][int(v)]}' for k, v in st.items()))
    hist_tab = days_tab[days_tab.ok & (days_tab.index >= '2024-01-01')]
    # cells that match now: all 1-3 state combos of the current state, n>=30; show the 3 with most flagged outcomes
    keys = {'|'.join(c) + '=' + '|'.join(str(int(st[k])) for k in c) for r in (1, 2, 3) for c in itertools.combinations(names, r) if all(k in st for k in c)}
    m = W[(W.sess == sk) & (W['T'] == T) & W.key.isin(keys)]
    score = m.groupby('key').agg(n=('days_2024-26', 'max'), flags=('flag', 'sum'), held=('y2026', lambda v: (v == 'held').sum()),
                                 zmax=('z_2024-26', lambda v: v.abs().max()), k=('key', lambda v: v.iloc[0].split('=')[0].count('|') + 1))
    score = score[score.n >= 30].sort_values(['held', 'flags', 'zmax'], ascending=False)
    shown = []
    for k in (3, 2, 1):  # most specific first, then wider; skip a cell that matches the same days as one already shown
        for key, r in score[score.k == k].iterrows():
            if r.n not in [score.loc[x, 'n'] for x in shown]:
                shown.append(key)
                break
    for key in ['all'] + shown:
        if key == 'all':
            sub, title = hist_tab, 'ALL DAYS (base rate)'
        else:
            c, v = key.split('=')
            mask = np.ones(len(hist_tab), bool)
            for a, b in zip(c.split('|'), v.split('|')):
                mask &= hist_tab[a].values == int(b)
            sub = hist_tab[mask]
            title = ' + '.join(f'{STATES[a][1][int(b)]} ({STATES[a][0].lower()})' for a, b in zip(c.split('|'), v.split('|')))
        print(f'\n== {title}: {len(sub)} days 2024-26' + ('   [15-29 days: thin]' if len(sub) < 30 else ''))
        _table(sub, hist_tab, row, W if key != 'all' else None, sk, T, key)
    print('\nBottom line: ' + bottom_line(W, sk, T, shown))
    print('Descriptive odds from 2024-26, not a signal. "FDR" = beat the base rate after the whole-universe correction (2024-25);'
          ' "2026 held" = same way on unseen 2026.')


def _levels(o, row, d):
    ref = {'new_hi': row.sh, 'sw_ph': row.ph, 'nx_hi': None, 'rth_hi': row.onh}.get(o)
    if o.endswith('lo') or o.endswith('pl'):
        ref = {'new_lo': row.sl, 'sw_pl': row.pl, 'nx_lo': None, 'rth_lo': row.onl}.get(o)
        sign = -1
    else:
        sign = 1
    return '' if ref is None or pd.isna(ref) or pd.isna(d) else f'{ref + sign * d:.0f}'


def _table(sub, base, row, W, sk, T, key):
    print(f'  {"outcome":58s} {"this":>5s} {"base":>5s}  {"depth pts med (p25-p75)":24s} {"x rng":>5s} {"level":>6s} {"time":>8s}  flag')
    flags = {} if W is None else W[(W.sess == sk) & (W['T'] == T) & (W.key == key)].set_index('out')
    pairs = [('new_hi', 'new_lo'), ('sw_ph', 'sw_pl'), ('rc_ph', 'rc_pl'), ('cl_top', 'cl_mid', 'cl_bot'), ('nx_hi', 'nx_lo', 'nx_none'),
             ('rth_hi', 'rth_lo')]
    for nm in ('lod', 'hod'):
        parts = []
        for i, b in enumerate(BUCKETS):
            o = f'{nm}{i}'
            v = sub[o].dropna()
            if not len(v):
                continue
            st = ''
            if o in getattr(flags, 'index', []) and flags.loc[o].flag:
                st = '*' if flags.loc[o].y2026 == 'held' else '~'
            parts.append(f'{b[0]} {v.mean() * 100:.0f}%{st} ({base[o].dropna().mean() * 100:.0f})')
        if parts:
            print(f'  {"Low" if nm == "lod" else "High"} of day: ' + ' | '.join(parts))
    print('  (bucket % this cell (all days); * = FDR + held 2026, ~ = FDR but not held)\n')
    for grp in pairs:
        for o in grp:
            if o not in sub or sub[o].notna().sum() == 0:
                continue
            v = sub[o].dropna()
            p, p0 = v.mean(), base[o].dropna().mean()
            dep = ''
            lvl = tm = ''
            x = ''
            if o in DEPTH:
                dd = sub.loc[sub[o] == 1, o + '_d']
                if len(dd):
                    dep = f'{dd.median():5.0f} ({dd.quantile(.25):.0f}-{dd.quantile(.75):.0f})'
                    x = f'{sub.loc[sub[o] == 1, o + "_x"].median():.2f}'
                    lvl = _levels(o, row, dd.median())
                    tm = clock(sub.loc[sub[o] == 1, o + '_t'].median())
            f = ''
            if o in getattr(flags, 'index', []):
                r = flags.loc[o]
                f = ('FDR ' + ('2026 held' if r.y2026 == 'held' else f'2026 {r.y2026}')) if r.flag else ('noise-level' if abs(r['z_2024-26']) < 2 else 'raw |z|>2, not FDR')
            print(f'  {OUT[o][:58]:58s} {fmt_pct(p):>5s} {fmt_pct(p0):>5s}  {dep:24s} {x:>5s} {lvl:>6s} {tm:>8s}  {f}  (n {len(v)})')
        print()
    if 'exp' in sub:
        e = sub.exp.dropna()
        if len(e):
            print(f'  Range expansion: final session range = {e.median():.2f}x the range so far (p25 {e.quantile(.25):.2f}, p75 {e.quantile(.75):.2f})')


def bottom_line(W, sk, T, keys):
    m = W[(W.sess == sk) & (W['T'] == T) & W.key.isin(keys) & W.flag]
    if not len(m):
        return 'nothing in the matching cells beats the all-days base rate after the correction: treat the base rates as the map.'
    m = m.assign(gap=m['pct_2024-26'] - m['p0_2024-26']).sort_values('y2026', key=lambda v: v != 'held')
    parts = []
    for _, r in m.head(3).iterrows():
        parts.append(f'{OUT[r.out]}: {r["pct_2024-26"] * 100:.0f}% vs {r["p0_2024-26"] * 100:.0f}% on all days'
                     f' ({"held in 2026" if r.y2026 == "held" else "2026 " + r.y2026})')
    return '; '.join(parts) + '. Both sides are in the tables above.'


# ---------------------------------------------------------------- build
def page_data(tabs, W, m):
    """compact 2024-26 per-day data for the explorer + verdicts"""
    P = {'states': {k: v for k, v in STATES.items()}, 'outs': OUT, 'buckets': [b[0] for b in BUCKETS], 'sess': {}, 'cp': {}}
    for sk, s in SESS.items():
        P['sess'][sk] = dict(name=s['name'], prior=s['prior'], nxt=s['nxt_name'], cps=[[T, clock(T)] for T in checkpoints(sk)])
    for (sk, T), df in tabs.items():
        df = df[df.ok & (df.index >= '2024-01-01')]
        cols = {}
        for c in df.columns:
            if c in ('ok',) or c in ('px', 'sh', 'sl', 'ph', 'pl', 'onh', 'onl', 'frng'):
                continue
            v = df[c].values.astype(float)
            r = 2 if c.endswith('_x') or c == 'exp' else 0
            cols[c] = [None if np.isnan(a) else (round(a, r) if r else int(round(a))) for a in v]
        cols['date'] = [d.strftime('%Y-%m-%d') for d in df.index]
        P['cp'][f'{sk}|{T}'] = dict(states=state_names(sk, T), cols=cols)
    F = W[W.flag & (W['days_2024-26'] >= 30) & (W.key.str.count('[|]') <= 1)].copy()
    F = F[F.y2026 == 'held'].sort_values('z_2024-25', key=abs, ascending=False).drop_duplicates(['sess', 'key', 'out']).head(400)
    F['gap'] = F['pct_2024-26'] - F['p0_2024-26']
    F = F.sort_values('z_2024-25', key=abs, ascending=False)
    P['verdicts'] = [dict(sess=r.sess, T=int(r['T']), key=r.key, out=r.out, n=int(r['n_2024-26']), pct=round(r['pct_2024-26'], 3),
                          p0=round(r['p0_2024-26'], 3), z=round(r['z_2024-25'], 1), q=float(f'{r.q:.2g}'), y2026=r.y2026,
                          p26=None if pd.isna(r['pct_2026']) else round(r['pct_2026'], 3), n26=0 if pd.isna(r['n_2026']) else int(r['n_2026']),
                          b26=None if pd.isna(r['p0_2026']) else round(r['p0_2026'], 3), y2023=r.y2023, kind=r.kind) for _, r in F.iterrows()]
    P['counts'] = dict(cells=int(W.drop_duplicates(['sess', 'T', 'key']).query('`days_2024-26` >= 30').shape[0]),
                       cells_thin=int(W.drop_duplicates(['sess', 'T', 'key']).query('`days_2024-26` < 30').shape[0]),
                       tests=m, flagged=int(W.flag.sum()), flagged_cells=int(W[W.flag].drop_duplicates(['sess', 'T', 'key']).shape[0]),
                       held=int((W.flag & (W.y2026 == 'held')).sum()), same=int((W.flag & (W.y2026 == 'same sign')).sum()),
                       flipped=int((W.flag & (W.y2026 == 'flipped')).sum()), few=int((W.flag & (W.y2026 == 'too few')).sum()),
                       ctx_flag=int((W.flag & (W.kind == 'context')).sum()), ctx_held=int((W.flag & (W.kind == 'context') & (W.y2026 == 'held')).sum()),
                       held_both=int((W.flag & (W.y2026 == 'held') & (W.y2023 == 'held')).sum()),
                       end=str(max(d.index.max() for d in tabs.values()).date()))
    return P


def build():
    days, A, roll = load()
    tabs = day_tables(days, A, roll, extra=[('london', 585), ('london', 588)])
    if not test(tabs):
        sys.exit('self-check failed')
    tabs = {k: v for k, v in tabs.items() if k[1] in checkpoints(k[0])}
    pd.to_pickle(tabs, os.path.join(HERE, 'cso_days.pkl'))
    U = cells(tabs)
    W, m, zcut = universe(U)
    cols = ['sess', 'T', 'key', 'out', 'kind', 'days_2024-26', 'n_2024-26', 'pct_2024-26', 'p0_2024-26', 'z_2024-26', 'z_2024-25', 'q', 'flag',
            'pct_2026', 'n_2026', 'p0_2026', 'y2026', 'pct_2020-23', 'n_2020-23', 'y2023']
    W = W[cols]
    W.to_parquet(os.path.join(HERE, 'cso_cells.parquet'))  # every cell with n >= 15 (the full universe)
    F = W[W.flag & (W['days_2024-26'] >= 30)]
    P = page_data(tabs, W, m)
    P['zcut'] = zcut
    json.dump(dict(counts=P['counts'], zcut=zcut, flagged=json.loads(F.round(4).to_json(orient='records'))),
              open(os.path.join(HERE, 'cso_universe.json'), 'w'), separators=(',', ':'))
    json.dump(P, open(os.path.join(HERE, 'cso_page.json'), 'w'), separators=(',', ':'))
    print(json.dumps(P['counts'], indent=1))
    render()


def render():
    P = open(os.path.join(HERE, 'cso_page.json'), encoding='utf-8').read()
    tpl = open(os.path.join(HERE, 'cso_page.html'), encoding='utf-8').read()
    open(os.path.join(HERE, 'NQ_CSO_Explorer.html'), 'w', encoding='utf-8').write(tpl.replace('__DATA__', P))


if __name__ == '__main__':
    if '--test' in sys.argv:
        sys.exit(0 if test() else 1)
    elif '--page' in sys.argv:
        render()
    elif '--now' in sys.argv:
        live(sys.argv[sys.argv.index('--at') + 1] if '--at' in sys.argv else None)
    else:
        build()
