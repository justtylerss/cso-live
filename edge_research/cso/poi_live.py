"""Live POI odds map for the CSO Live page: every POI on the chart with the odds price reaches it in the current
session (and later windows), timing, the 'any price this far' placebo, what happened after a touch, and an
'if this happens' panel of high-probability conditional odds. The watcher calls tick() every 15 s.

Matching (2024-26 1-min grid, cso_grid):
  - anchor = the current minute; a past day counts when price was at a comparable spot at the same clock time
  - tested kinds (PD POC/VAH/VAL, 7-day POC/VAH/VAL, PDH/PDL): days where that kind sat at a similar distance
    (+/- max(15 pts, 30%)) on the same side, and was / wasn't already touched this session like tonight
  - every other POI (GEX walls, tails, single prints, session highs/lows, VWAP): distance only
  - placebo = any price at the same distance on days whose ATR is within 20% (busy days vs busy days)
Descriptive odds, not a signal.

python -I poi_live.py [--at "2026-10-15 03:10"]    one snapshot (replay from history with --at), writes live_map.json/.png
python -I poi_live.py --cache                     rebuild poi_hist.npz (past PD / 7-day profile levels, ~1 min)
"""
import json, math, os, sys, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cso_live as C
from poi_asia import profile, history_levels, wilson

HIST = os.path.join(HERE, 'poi_hist.npz')
OUT = os.path.join(HERE, 'live_map')
LEVELS = os.path.expanduser('~/motivewave-claude/poi/levels.json')
KINDS = ('PD POC', 'PD VAH', 'PD VAL', '7-day POC', '7-day VAH', '7-day VAL', 'PDH', 'PDL')
# sessions (minutes after 5 PM CT, end = last minute): the map always follows the one that's live
SESSIONS = (('Pre-Asia', 0, 119), ('Asia', 120, 359), ('Asia-London gap', 360, 479), ('London', 480, 659), ('Pre-NY', 660, 929),
            ('NYAM', 930, 1079), ('Midday', 1080, 1169), ('NY PM', 1170, 1319))


def SESSION(a):
    return next((n for n, s0, s1 in SESSIONS if s0 <= a <= s1), 'After the close')


def windows(a):
    """rest of this session, end of the next session, and 3 PM (deduplicated, each still ahead)"""
    k = next((j for j, (_, s0, s1) in enumerate(SESSIONS) if s0 <= a <= s1), None)
    if k is None:
        return []
    if SESSIONS[k][0] in ('Pre-Asia', 'Asia-London gap'):  # quiet stretches: lead with the session that's next
        k += 1
    w = [SESSIONS[k][2]]
    nxt = [x for x in SESSIONS[k + 1:] if x[0] not in ('Pre-Asia', 'Asia-London gap')]
    if nxt:
        w.append(nxt[0][2])
    w.append(1319)
    out = []
    for e in w:
        if e > a and e not in [x for x, _ in out]:
            out.append((e, f'by {C.clock(e + 1) if e < 1319 else "3 PM"}' if e in (359, 659, 1319) else f'by {C.clock(e)}'))
    return out[:3]
RUN = 20
PMIN, NMIN = 0.65, 30           # 'if this happens' rows: at least 65% on 30+ days, and 5+ pts above the base
_H = {}


def hist():
    """grid + past PD / 7-day levels per day (cached on disk) + pool of 2024+ valid days"""
    if not _H:
        g = C.load_grid()
        if os.path.exists(HIST) and str(np.load(HIST)['end']) == g.end:
            z = np.load(HIST)
            lv = {k: z[k.replace(' ', '_').replace('-', '_')] for k in KINDS}
        else:
            lv = history_levels(g)
            np.savez(HIST, end=g.end, **{k.replace(' ', '_').replace('-', '_'): v for k, v in lv.items()})
        lo = int(np.searchsorted(g.days, pd.Timestamp('2024-01-01')))
        pool = np.array([i for i in range(lo, len(g.days)) if g.valid[i]])
        _H.update(g=g, lv=lv, pool=pool, y26=g.days[pool] >= pd.Timestamp('2026-01-01'))
    return _H


# ---------------------------------------------------------------- tonight's POIs
def tonight_levels(lv, a, use_map=True):
    """[(name, price, kind or None)] from the live bars (PD / 7-day profile, PDH/PDL, finished session highs/lows,
    NY VWAP) plus the Level Map lines (levels.json) for everything else"""
    i = len(lv.days) - 1
    out = []
    j = i - 1
    if j >= 0:
        poc, vah, val = profile(lv.H[j, 930:1320], lv.L[j, 930:1320], lv.V[j, 930:1320])
        out += [('PD POC', poc, 'PD POC'), ('PD VAH', vah, 'PD VAH'), ('PD VAL', val, 'PD VAL'),
                ('PDH', float(np.nanmax(lv.H[j, :1380])), 'PDH'), ('PDL', float(np.nanmin(lv.L[j, :1380])), 'PDL')]
    if i >= 7:
        sl = slice(i - 7, i)
        poc, vah, val = profile(lv.H[sl, :1380].ravel(), lv.L[sl, :1380].ravel(), lv.V[sl, :1380].ravel())
        out += [('7-day POC', poc, '7-day POC'), ('7-day VAH', vah, '7-day VAH'), ('7-day VAL', val, '7-day VAL')]
    H_, L_ = lv.H[i], lv.L[i]
    hl = lambda s0, s1: (float(np.nanmax(H_[s0:s1])), float(np.nanmin(L_[s0:s1]))) if (~np.isnan(H_[s0:s1])).any() else (np.nan, np.nan)
    for nm, s0, s1 in (('Asia', 120, 360), ('London', 480, 660), ('NYAM', 930, 1080)):
        if a >= s1:        # finished session: its high / low
            h, l = hl(s0, s1)
            out += [(f'{nm} high', h, None), (f'{nm} low', l, None)]
        elif a >= s0 + 30:  # live session, 30+ min in: its high / low so far
            h, l = hl(s0, a + 1)
            out += [(f'{nm} high so far', h, None), (f'{nm} low so far', l, None)]
    if a >= 930:
        h, l = hl(0, 930)
        out += [('Overnight high', h, None), ('Overnight low', l, None)]
    if a >= 990:
        h, l = hl(930, 990)
        out += [('IB high', h, None), ('IB low', l, None)]
    if a >= 480:           # overnight value area (5 PM to now, frozen at 8:30 AM)
        e = min(a + 1, 930)
        poc, vah, val = profile(lv.H[i, :e], lv.L[i, :e], lv.V[i, :e])
        out += [('ON POC', poc, None), ('ON VAH', vah, None), ('ON VAL', val, None)]
        v = C.Day(lv, i).level('vwap', dict(a=a, vars={}, ev=False))
        if not np.isnan(v):
            out.append(('NY VWAP', float(v), None))
    src = 'live bars'
    try:  # the Level Map's lines: MotiveWave's own PD / 7-day values win (they match the chart), the rest are added
        L = json.load(open(LEVELS))
        age = time.time() - L['at']
        start = pd.Timestamp.now(tz='America/Chicago').normalize() + pd.Timedelta(hours=17)
        if pd.Timestamp.now(tz='America/Chicago') < start:
            start -= pd.Timedelta(days=1)
        if use_map and L['at'] >= start.timestamp():   # written this CME day (after 5 PM): its PD is today's PD
            src = f'Level Map ({int(age // 60)} min old)'
            mw = {n: p for _, n, p, _ in L['levels']}
            out = [(n, mw.get(n, p), k) for n, p, k in out]
            have = {n for n, _, _ in out}
            out += [(n, float(p), None) for _, n, p, _ in L['levels'] if n not in have and not n.startswith(('today', 'ON '))]
    except (OSError, ValueError, KeyError):
        pass
    return [(n, round(p * 4) / 4, k) for n, p, k in out if p == p], src


# ---------------------------------------------------------------- odds, vectorized over past days
class Frame:
    """past days at the same clock minute a: price, what was touched since 5 PM, and running extremes ahead"""
    def __init__(self, a):
        H = hist()
        g, pool = H['g'], H['pool']
        self.a, self.g = a, g
        c = g.C[pool, :a + 1]
        last = np.where(~np.isnan(c), np.arange(a + 1), -1).max(1)
        ok = last >= max(0, a - 5)
        self.days = pool[ok]
        self.y26 = H['y26'][ok]
        self.p0 = g.C[self.days, last[ok]]
        self.s0 = s0 = next((x for _, x, y in SESSIONS if x <= a <= y), 0)   # "already touched" = since this session began
        self.preH = np.nanmax(g.H[self.days, s0:a + 1], 1)
        self.preL = np.nanmin(g.L[self.days, s0:a + 1], 1)
        e = 1320
        fh, fl = g.H[self.days, a + 1:e], g.L[self.days, a + 1:e]
        self.fH = np.fmax.accumulate(np.where(np.isnan(fh), -np.inf, fh), 1)
        self.fL = np.fmin.accumulate(np.where(np.isnan(fl), np.inf, fl), 1)
        self.atr = g.atr[self.days]
        self.lv = {k: H['lv'][k][self.days] for k in KINDS}
        self.ends = windows(a)

    def reach(self, L, up, touched, mask):
        """L per day; rows kept where the level sat on the same side and was / wasn't touched like tonight.
        -> (rows mask, first-touch minute offset or -1)"""
        pre = (self.preH >= L) if up else (self.preL <= L)
        side = (L > self.p0) if up else (L < self.p0)
        # untouched tonight: past days where it was also untouched; already traded through tonight: any day with it on that side
        keep = mask & side & (~pre if not touched else True)
        hit = (self.fH >= L[:, None]) if up else (self.fL <= L[:, None])
        t = np.where(hit.any(1), hit.argmax(1), -1)
        return keep, t

    def stats(self, keep, t, L, up):
        n = int(keep.sum())
        r = dict(n=n, wins=[])
        for e, lab in self.ends:
            k = int(((t >= 0) & (t <= e - self.a - 1) & keep).sum())
            r['wins'].append(dict(win=lab, p=k / n if n else None, ci=list(wilson(k, n)) if n else None))
        first = self.ends[0][0] - self.a - 1
        tt = t[keep & (t >= 0) & (t <= first)]
        r['t'] = float(np.median(tt)) + 1 if len(tt) >= 5 else None
        # after the first touch (within the headline window): 20 pts through vs 20 back, within 60 min
        th = bk = 0
        for d in np.flatnonzero(keep & (t >= 0) & (t <= first)):
            m0 = self.a + 1 + t[d]
            hh, ll = self.g.H[self.days[d], m0:m0 + 61], self.g.L[self.days[d], m0:m0 + 61]
            a_ = np.flatnonzero(hh >= L[d] + RUN if up else ll <= L[d] - RUN)
            b_ = np.flatnonzero(ll <= L[d] - RUN if up else hh >= L[d] + RUN)
            x, y = (a_[0] if len(a_) else 999), (b_[0] if len(b_) else 999)
            th += x < y
            bk += y < x
        nh = int((keep & (t >= 0) & (t <= first)).sum())
        r['after'] = dict(n=nh, through=th / nh, back=bk / nh) if nh >= 5 else None
        k26 = keep & self.y26
        n26 = int(k26.sum())
        r['y26'] = dict(n=n26, p=int(((t >= 0) & (t <= first) & k26).sum()) / n26) if n26 else None
        return r

    def level_odds(self, d, kind, touched, atr_now):
        """odds for a POI at signed distance d (pts from now): tested kind if given, plus the vol-matched placebo"""
        up = d > 0
        vm = np.abs(self.atr / atr_now - 1) <= 0.2
        Lp = self.p0 + d
        keep, t = self.reach(Lp, up, touched, vm)
        plc = self.stats(keep, t, Lp, up)
        if not kind:
            return dict(main=plc, placebo=None)
        Lk = self.lv[kind]
        dist = Lk - self.p0
        near = ~np.isnan(Lk) & (np.sign(dist) == np.sign(d)) & (np.abs(dist - d) <= max(15, 0.3 * abs(d)))
        keep, t = self.reach(Lk, up, touched, near)
        main = self.stats(keep, t, Lk, up)
        # placebo at the matched days' own distances and ATRs (so the comparison isn't a volatility effect)
        P = []
        for j in np.flatnonzero(keep)[:150]:
            vm_j = np.abs(self.atr / self.atr[j] - 1) <= 0.2
            Lj = self.p0 + dist[j]
            kj, tj = self.reach(Lj, up, touched, vm_j)
            P.append([((tj >= 0) & (tj <= e - self.a - 1) & kj).sum() / max(1, kj.sum()) for e, _ in self.ends])
        pl = dict(wins=[dict(win=lab, p=float(np.mean([x[k] for x in P]))) for k, (_, lab) in enumerate(self.ends)]) if P else None
        return dict(main=main, placebo=pl)


# ---------------------------------------------------------------- 'if this happens': conditional odds that open up
TRIG = (('touch', 'touches'), ('sweep', 'trades through and closes back within 5 min'), ('hold', 'breaks and closes beyond for 5 min'))


def conditionals(F, pois, px, atr_now, live_day):
    """for the 2 nearest POIs each side (+ the next one beyond): if trigger at X -> odds of reaching Y within 60 min
    / by the session end. Kept only if p >= 65%, n >= 30 and above the same-window odds from now (base) by 5+ pts."""
    g, a = F.g, F.a
    vm = np.abs(F.atr / atr_now - 1) <= 0.35   # wider than the map's 20%: the trigger itself already filters the days
    merged = []  # levels within 6 pts act as one
    for p in sorted(pois, key=lambda p: p['price']):
        if merged and p['price'] - merged[-1]['price'] <= 6:
            merged[-1] = dict(merged[-1], name=merged[-1]['name'] + ' · ' + p['name'])
        else:
            merged.append(dict(p))
    above = sorted([p for p in merged if p['dist'] > 0], key=lambda p: p['dist'])
    below = sorted([p for p in merged if p['dist'] < 0], key=lambda p: -p['dist'])
    rows = []
    end = F.ends[0][0]
    for side, lst, other in (('up', above, below), ('dn', below, above)):
        for k, X in enumerate(lst[:2]):
            targets = [(Y, 'beyond') for Y in lst[k + 1:k + 3] if abs(Y['dist'] - X['dist']) >= 10][:1]
            if other:
                targets.append((other[0], 'back'))
            targets.append((None, 'back to now'))
            dX = X['dist']
            up = dX > 0
            for code, words in TRIG:
                res = {}
                for di in np.flatnonzero(vm):
                    day = F.days[di]
                    LX = F.p0[di] + dX
                    if (F.preH[di] >= LX) if up else (F.preL[di] <= LX):
                        continue
                    H, L, Cc = g.H[day], g.L[day], g.C[day]
                    seg = (H[a + 1:end + 1] >= LX) if up else (L[a + 1:end + 1] <= LX)
                    j = np.flatnonzero(seg)
                    if not len(j):
                        res[di] = None   # the trigger never happened: not in the conditional sample
                        continue
                    m0 = a + 1 + j[0]
                    if code == 'sweep':
                        cc = Cc[m0:m0 + 5]
                        if not ((cc < LX).any() if up else (cc > LX).any()):
                            res[di] = None
                            continue
                        m0 += int(np.flatnonzero((cc < LX) if up else (cc > LX))[0])
                    elif code == 'hold':
                        cc = Cc[m0:m0 + 5]
                        if len(cc) < 5 or not ((cc > LX).all() if up else (cc < LX).all()):
                            res[di] = None
                            continue
                        m0 += 4
                    res[di] = m0
                fired = {di: m0 for di, m0 in res.items() if m0 is not None}
                for Y, rel in targets:
                    dY = Y['dist'] if Y else 0.0
                    upY = dY > dX if rel != 'back to now' else not up
                    for wl, wend in (('within 60 min', None), (F.ends[0][1], end)):
                        k = n = 0
                        tm, k26, n26 = [], 0, 0
                        for di, m0 in fired.items():
                            if m0 >= (wend or 9999):
                                continue
                            day = F.days[di]
                            LY = F.p0[di] + dY
                            e = m0 + 61 if wend is None else wend + 1
                            hh, ll = g.H[day, m0 + 1:e], g.L[day, m0 + 1:e]
                            j = np.flatnonzero(hh >= LY if upY else ll <= LY)
                            n += 1
                            k += len(j) > 0
                            if len(j):
                                tm.append(j[0] + 1)
                            if F.y26[di]:
                                n26 += 1
                                k26 += len(j) > 0
                        if n < NMIN or k / n < PMIN:
                            continue
                        # base: the same target, same window length, measured from now (no trigger)
                        LYb = F.p0 + dY
                        win = 60 if wend is None else wend - a
                        hb = (F.fH[:, :win] >= LYb[:, None]).any(1) if upY else (F.fL[:, :win] <= LYb[:, None]).any(1)
                        okb = vm & ((F.preH < LYb) if upY else (F.preL > LYb))
                        base = hb[okb].mean() if okb.sum() else np.nan
                        if not (k / n >= base + 0.05):
                            continue
                        lo, hi = wilson(k, n)
                        rows.append(dict(x=X['name'], x_price=X['price'], trig=code, trig_words=words,
                                         y=(Y['name'] if Y else f'back to {px:,.2f} (now)'), y_price=(Y['price'] if Y else px),
                                         win=wl, p=k / n, ci=[lo, hi], n=n, base=float(base), t=float(np.median(tm)) if tm else None,
                                         y26=dict(p=k26 / n26, n=n26) if n26 else None, live=trigger_live(live_day, a, X['price'], up, code)))
    rows.sort(key=lambda r: (-r['live'], -r['p']))
    return rows[:12]


def trigger_live(day, a, LX, up, code, look=60):
    """did the trigger happen on tonight's bars in the last `look` minutes"""
    if day is None:
        return False
    H, L, Cc = day
    s = max(0, a - look)
    seg = (H[s:a + 1] >= LX) if up else (L[s:a + 1] <= LX)
    j = np.flatnonzero(seg)
    if not len(j):
        return False
    m0 = s + j[0]
    cc = Cc[m0:min(a + 1, m0 + 5)]
    if code == 'touch':
        return True
    if code == 'sweep':
        return bool(((cc < LX) if up else (cc > LX)).any())
    return len(cc) == 5 and bool(((cc > LX) if up else (cc < LX)).all())


# ---------------------------------------------------------------- one snapshot
_PREV, _COND = {}, {}


def tick(at=None, png=True):
    t0 = time.time()
    health = dict(chart=False, read=None, levels_src=None, stale=[])
    if at:
        lv, m = C.replay_grid(at)
        src = f'replay {at} CT'
    else:
        lv, last, sym = C._live_grid(1500)
        m = C.tmin(f'{last.hour}:{last.minute}') + 1
        src = f'{sym} live'
        health['chart'] = True
    a = m - 1
    i = len(lv.days) - 1
    px = float(C.Day(lv, i).px(a))
    atr_now = float(lv.atr[-1]) if not np.isnan(lv.atr[-1]) else float(np.nanmedian(hist()['g'].atr[-60:]))
    levels, lsrc = tonight_levels(lv, a, use_map=not at)
    health['levels_src'] = lsrc
    try:
        mw = json.load(open(os.path.expanduser('~/motivewave-claude/_NQ.json')))['updated']
        age = (pd.Timestamp.now(tz='America/New_York').tz_localize(None) - pd.Timestamp(mw)).total_seconds()
        if age > 600 and a > 60:
            health['stale'].append(f'MotiveWave export frozen since {C.clock(C.tmin((pd.Timestamp(mw) - pd.Timedelta(hours=1)).strftime("%H:%M")))} CT')
    except (OSError, ValueError, KeyError):
        pass
    F = Frame(a)
    pois = []
    for name, p, kind in levels:
        d = p - px
        if abs(d) > 2.2 * atr_now or abs(d) < 0.25:
            continue
        up = d > 0
        touched = bool((np.nanmax(lv.H[i, F.s0:a + 1]) >= p) if up else (np.nanmin(lv.L[i, F.s0:a + 1]) <= p))
        o = F.level_odds(d, kind, touched, atr_now)
        head = o['main']['wins'][0]['p'] if o['main']['n'] else None
        o['main']['at'] = C.clock(a + o['main']['t']) if o['main']['t'] is not None else None
        key = f'{name}|{p}'
        prev = _PREV.get(key)
        pois.append(dict(name=name, price=p, dist=d, kind=kind, tested=bool(kind), touched=touched, odds=o['main'], placebo=o['placebo'],
                         prev=prev if prev is not None and head is not None and abs(prev - head) >= 0.03 else None))
        if head is not None:
            _PREV[key] = head
    pois.sort(key=lambda p: abs(p['dist']))   # nearest first; the chart and the list show the nearest ones
    pois = pois[:16]
    # conditionals: once a minute (heavier), reused between the 15 s ticks
    ck = (a, round(px))
    if _COND.get('k') != ck:
        live_day = (lv.H[i], lv.L[i], lv.C[i])
        _COND.update(k=ck, rows=conditionals(F, [p for p in pois if not p['touched']], px, atr_now, live_day))
    snap = dict(at=C.clock(a), src=src, px=px, session=SESSION(a), atr=atr_now, n_days=len(F.days), windows=[w for _, w in F.ends],
                bars=C.bars_out(lv, a), now_t=C.bar_time(lv, i, a), ends_t=[C.bar_time(lv, i, e) for e, _ in F.ends],
                ends=[e for e, _ in F.ends],
                pois=pois, cond=_COND['rows'], health=dict(health, read=C.clock(a), secs=round(time.time() - t0, 1)))
    json.dump(snap, open(OUT + '.json.tmp', 'w', encoding='utf-8'), default=C._js)
    os.replace(OUT + '.json.tmp', OUT + '.json')
    if png:
        picture(snap, lv, a, OUT + '.png')
    return snap


def picture(s, lv, a, path, W=180):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    BG, FG, MUTED, GRIDC, UP, DN = '#181818', '#d1d4dc', '#808080', '#242424', '#089981', '#f23645'
    i = len(lv.days) - 1
    bars = [(m - 1440, lv.O[i - 1][m], lv.H[i - 1][m], lv.L[i - 1][m], lv.C[i - 1][m]) for m in range(1440 - max(0, W - a), 1380)] if i else []
    bars += [(m, lv.O[i][m], lv.H[i][m], lv.L[i][m], lv.C[i][m]) for m in range(max(0, a - W), a + 1)]
    bars = [b for b in bars if not np.isnan(b[4])]
    px = s['px']
    end = s['ends'][0] if s.get('ends') else a + 60
    fut = max(60, min(end - a, 240))
    fig = Figure(figsize=(12, 6.6), facecolor=BG)
    ax = fig.add_axes([0.02, 0.07, 0.86, 0.9], facecolor=BG)
    for x, o, h, l, c in bars:
        col = '#b8b8b8' if c >= o else '#5a5a5a'
        ax.vlines(x, l, h, color=col, lw=0.7)
        ax.vlines(x, min(o, c), max(o, c) + 0.01, color=col, lw=2)
    ax.axvspan(a, a + fut, color='#1f1f1f', zorder=0)
    ax.axvline(a, color=MUTED, lw=0.8, ls='--')
    ax.text(a + fut / 2, 1.0, f'ahead: {s["windows"][0] if s["windows"] else ""}', transform=ax.get_xaxis_transform(),
            color=MUTED, fontsize=9, ha='center', va='bottom')
    ax.axhline(px, color=FG, lw=0.6)
    show = s['pois'][:10]   # the 10 nearest POIs (the list on the page has the rest)
    ys = [b[2] for b in bars] + [b[3] for b in bars] + [p['price'] for p in show]
    lo, hi = min(ys), max(ys)
    pad = (hi - lo) * 0.04 or 5
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(bars[0][0] if bars else a - W, a + fut)
    ticks = list(range(int(np.ceil((bars[0][0] if bars else a - W) / 60) * 60), a + fut + 1, 60))
    ax.set_xticks(ticks, [C.clock(t % 1440) for t in ticks])
    ax.tick_params(colors=MUTED, labelsize=8.5)
    ax.yaxis.tick_right()
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.grid(color=GRIDC, lw=0.5)
    cols = [[], [], []]   # label columns: a label that would sit on top of another moves one column left
    for p in show:
        col = UP if p['dist'] > 0 else DN
        w = p['odds']['wins'][0]['p'] if p['odds']['n'] else None
        ax.hlines(p['price'], a, a + fut, color=col, lw=1.6 if p['tested'] else 1.0, ls='-' if p['tested'] else (0, (4, 3)),
                  alpha=0.55 if p['touched'] else 1)
        if w is None:
            continue
        col_i = next((k for k, c in enumerate(cols) if all(abs(p['price'] - u) >= (hi - lo) * 0.03 for u in c)), None)
        if col_i is None:
            continue
        cols[col_i].append(p['price'])
        x = a + fut - 2 - col_i * fut * 0.33
        ax.text(x, p['price'], f'{w * 100:.0f}%', color=col, fontsize=12, fontweight='bold', ha='right', va='bottom')
        ax.text(x - fut * 0.075, p['price'], p['name'][:20], color=col, fontsize=7.5, ha='right', va='bottom', alpha=0.8)
    ax.text(a + fut, px, f' {px:,.2f}', color='#fff', fontsize=9, va='center', fontweight='bold',
            bbox=dict(facecolor='#2962ff', edgecolor='none', pad=2))
    fig.savefig(path, dpi=110, facecolor=BG)


if __name__ == '__main__':
    a_ = sys.argv
    if '--cache' in a_:
        if os.path.exists(HIST):
            os.remove(HIST)
        hist()
        print('poi_hist.npz rebuilt')
    else:
        s = tick(a_[a_.index('--at') + 1] if '--at' in a_ else None)
        for p in s['pois']:
            o = p['odds']
            print(f"{p['name'][:30]:30s} {p['price']:9.2f} {p['dist']:+6.0f} {'T' if p['tested'] else ' '} n {o['n']:4d}  "
                  + '  '.join(f"{w['p'] * 100 if w['p'] is not None else 0:3.0f}% {w['win']}" for w in o['wins'])
                  + (f"  placebo {p['placebo']['wins'][0]['p'] * 100:.0f}%" if p['placebo'] else ''))
        print('IF THIS HAPPENS')
        for r in s['cond']:
            print(f"  if {r['x']} {r['trig']} -> {r['y']} {r['win']}: {r['p'] * 100:.0f}% (n {r['n']}, base {r['base'] * 100:.0f}%)"
                  f"{' 2026 ' + str(round(r['y26']['p'] * 100)) + '% n ' + str(r['y26']['n']) if r['y26'] else ''}{' LIVE' if r['live'] else ''}")
        print(s['health'])
