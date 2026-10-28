"""Asia odds for chart POIs: how often price reaches each level during Asia (7-11 PM CT), by 4 AM and by 8:29 AM,
on 2024-26 days where that kind of level sat at a similar distance from the 7 PM price, vs a placebo (any price at
the same distance). Descriptive odds, not a signal.

Kinds tested from history (1-min grid, volume spread evenly over each bar's range, 1-pt rows, 70% value area):
  PD POC / VAH / VAL   prior day's RTH (8:30 AM-3 PM CT) volume profile, as MotiveWave's rthProfiles
  7-day POC/VAH/VAL    the 7 prior full sessions (5 PM-4 PM), as MotiveWave's compositeProfile
  PDH / PDL            prior full session high / low (TFO's PDH/PDL)
Everything else (GEX walls, TPO tails, single prints) has no history here: placebo only.

python -I poi_asia.py [--px 29666] [--anchor 19:00] [--check]    levels come from ~/motivewave-claude/poi/levels.json
"""
import json, math, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cso_live as C

A0 = 120                      # 7:00 PM = minutes after 5 PM
ENDS = (('by 11 PM', 360), ('by 4 AM', 660), ('by 8:29 AM', 930))
RUN = 20                      # after a touch: 20 pts further through vs 20 pts back, whichever first (within 60 min)


def profile(H, L, V, lo_row=None):
    """1-pt rows: POC, VAH, VAL (70%, grow toward the bigger neighbour row, as most VA code does)"""
    ok = ~(np.isnan(H) | np.isnan(L) | np.isnan(V))
    H, L, V = H[ok], L[ok], V[ok]
    if not len(V) or V.sum() <= 0:
        return np.nan, np.nan, np.nan
    b0 = int(np.floor(L.min()))
    rows = np.zeros(int(np.ceil(H.max())) - b0 + 1)
    for h, l, v in zip(H, L, V):
        a, b = int(np.floor(l)) - b0, int(np.floor(h)) - b0
        rows[a:b + 1] += v / (b - a + 1)
    p = int(np.argmax(rows))
    lo = hi = p
    tot, need = rows[p], 0.7 * rows.sum()
    while tot < need:
        up = rows[hi + 1] if hi + 1 < len(rows) else -1
        dn = rows[lo - 1] if lo > 0 else -1
        if up >= dn:
            hi += 1
            tot += up
        else:
            lo -= 1
            tot += dn
    return float(b0 + p), float(b0 + hi), float(b0 + lo)


def history_levels(g):
    """per day i: the kinds' prices as they stood at that night's 7 PM"""
    n = len(g.days)
    out = {k: np.full(n, np.nan) for k in ('PD POC', 'PD VAH', 'PD VAL', '7-day POC', '7-day VAH', '7-day VAL', 'PDH', 'PDL')}
    gap = np.r_[99, np.diff(g.days.values).astype('timedelta64[D]').astype(int)]
    for i in range(8, n):
        if gap[i] > 4:
            continue
        j = i - 1
        out['PD POC'][i], out['PD VAH'][i], out['PD VAL'][i] = profile(g.H[j, 930:1320], g.L[j, 930:1320], g.V[j, 930:1320])
        out['PDH'][i], out['PDL'][i] = np.nanmax(g.H[j, :1380]), np.nanmin(g.L[j, :1380])
        if (gap[i - 6:i + 1] <= 4).all():
            sl = slice(i - 7, i)
            out['7-day POC'][i], out['7-day VAH'][i], out['7-day VAL'][i] = profile(
                g.H[sl, :1380].ravel(), g.L[sl, :1380].ravel(), g.V[sl, :1380].ravel())
    return out


def outcome(g, i, lvl, p0):
    """None if already touched 5-7 PM (set aside); else dict: minute of first touch from 7 PM (or None), through/back"""
    up = lvl > p0
    pre = (np.nanmax(g.H[i, :A0]) >= lvl) if up else (np.nanmin(g.L[i, :A0]) <= lvl)
    if pre:
        return None
    x = g.H[i, A0:930] >= lvl if up else g.L[i, A0:930] <= lvl
    j = np.flatnonzero(x)
    if not len(j):
        return dict(t=None)
    t = A0 + int(j[0])
    seg = slice(t, min(t + 61, 1380))
    thru = np.flatnonzero((g.H[i, seg] >= lvl + RUN) if up else (g.L[i, seg] <= lvl - RUN))
    back = np.flatnonzero((g.L[i, seg] <= lvl - RUN) if up else (g.H[i, seg] >= lvl + RUN))
    a, b = (thru[0] if len(thru) else 999), (back[0] if len(back) else 999)
    first = 'through' if a < b else 'back' if b < a else 'neither'
    far = (np.nanmax(g.H[i, seg]) - lvl) if up else (lvl - np.nanmin(g.L[i, seg]))
    return dict(t=t - A0, first=first, far=float(far))


def wilson(k, n, z=1.2816):
    if not n:
        return (np.nan, np.nan)
    p = k / n
    c = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    m = (p + z * z / (2 * n)) / (1 + z * z / n)
    return max(0, m - c), min(1, m + c)


def summarize(rows):
    """rows = outcome dicts (set-aside days already dropped)"""
    n = len(rows)
    r = dict(n=n)
    for lab, e in ENDS:
        k = sum(1 for x in rows if x['t'] is not None and x['t'] < e - A0)
        r[lab] = (k / n if n else np.nan, wilson(k, n))
    hits = [x for x in rows if x['t'] is not None]
    asia = [x for x in hits if x['t'] < 360 - A0]
    r['t_med'] = float(np.median([x['t'] for x in asia])) if len(asia) >= 5 else None  # timing only with 5+ Asia hits
    r['through'] = (sum(x['first'] == 'through' for x in hits) / len(hits)) if hits else np.nan
    r['back'] = (sum(x['first'] == 'back' for x in hits) / len(hits)) if hits else np.nan
    r['far'] = float(np.median([x['far'] for x in hits])) if hits else None
    r['nhit'] = len(hits)
    return r


def main():
    a = sys.argv
    if '--check' in a:  # the profile maths on TradingView's bars vs MotiveWave's rthProfiles (export) for recent days
        lv, _, _ = C._live_grid(8000)
        mw = {p['open'][:10]: (p['poc'], p['vah'], p['val'])
              for p in json.load(open(os.path.expanduser('~/motivewave-claude/_NQ.json')))['rthProfiles']['days']}
        for i, d in enumerate(lv.days):
            k = str(d.date())
            if k in mw:
                print(k, 'ours POC/VAH/VAL', profile(lv.H[i, 930:1320], lv.L[i, 930:1320], lv.V[i, 930:1320]), 'MotiveWave', mw[k])
        return
    g = C.load_grid()
    lo = int(np.searchsorted(g.days, pd.Timestamp('2024-01-01')))
    days = [i for i in range(lo, len(g.days)) if g.valid[i] and not np.isnan(g.C[i, A0 - 1])]
    p0s = {i: float(g.C[i, A0 - 1]) for i in days}
    H = history_levels(g)
    px = float(a[a.index('--px') + 1]) if '--px' in a else None
    lv = json.load(open(os.path.expanduser('~/motivewave-claude/poi/levels.json')))['levels']
    kind = {'PD POC': 'PD POC', 'PD VAH': 'PD VAH', 'PD VAL': 'PD VAL', '7-day POC': '7-day POC', '7-day VAH': '7-day VAH',
            '7-day VAL': '7-day VAL'}
    extra = [x for x in a if x.startswith('PDH=') or x.startswith('PDL=')]
    pois = [(name, float(p), kind.get(name)) for _, name, p, _ in lv]
    pois += [(x[:3], float(x[4:]), x[:3]) for x in extra]
    # placebo cache: for each day, outcome of a level at signed distance d (5-pt steps)
    plc = {}

    atr = {i: g.atr[i] for i in days}
    if '--atr' in a:
        atr_now = float(a[a.index('--atr') + 1])
    else:  # tonight's 14-session RTH ATR, from the chart (the grid's rule)
        lvg, _, _ = C._live_grid(20000)
        atr_now = float(lvg.atr[-1])
    print(f'ATR now {atr_now:.0f} pts')

    def placebo(d, ar):
        """any price at distance d, on days whose ATR is within 20% of ar (so a busy day isn't compared with quiet ones)"""
        key = (int(round(d / 5) * 5) or (5 if d > 0 else -5), round(math.log(ar) / 0.05))
        if key not in plc:
            ref = math.exp(key[1] * 0.05)
            plc[key] = [o for i in days if abs(atr[i] / ref - 1) <= 0.2
                        for o in [outcome(g, i, p0s[i] + key[0], p0s[i])] if o is not None]
        return plc[key]

    res = []
    for name, p, k in sorted(pois, key=lambda x: -x[1]):
        d = p - px
        tol = max(15, 0.3 * abs(d))
        typed = None
        if k:
            rows, dists = [], []
            for i in days:
                L = H[k][i]
                if np.isnan(L):
                    continue
                di = L - p0s[i]
                if np.sign(di) == np.sign(d) and abs(di - d) <= tol:
                    o = outcome(g, i, L, p0s[i])
                    if o is not None:
                        rows.append(o)
                        dists.append((di, atr[i]))
            typed = summarize(rows)
            # placebo at the matched days' own distances: average over those distances
            P = [summarize(placebo(di, ar)) for di, ar in dists[:200]]
            pl = {lab: (float(np.nanmean([x[lab][0] for x in P])) if P else np.nan,) for lab, _ in ENDS}
            pl['through'] = float(np.nanmean([x['through'] for x in P])) if P else np.nan
        else:
            P0 = summarize(placebo(d, atr_now))
            pl = {lab: (P0[lab][0],) for lab, _ in ENDS}
            pl['through'] = P0['through']
            pl['_full'] = P0
        res.append(dict(name=name, price=p, dist=d, kind=k, typed=typed, placebo=pl))
    json.dump(res, open(os.path.join(HERE, 'poi_asia.json'), 'w'), default=float, indent=1)
    for r in res:
        t, pl = r['typed'], r['placebo']
        src = t if t else pl['_full']
        cells = '  '.join(f'{lab} {src[lab][0] * 100:3.0f}% ({src[lab][1][0] * 100:.0f}-{src[lab][1][1] * 100:.0f})' for lab, _ in ENDS)
        tm = f"median {src['t_med']:.0f}m" if src['t_med'] is not None else ''
        pls = '  placebo ' + ' / '.join(f"{pl[lab][0] * 100:.0f}%" for lab, _ in ENDS) + f" thru {pl['through'] * 100:.0f}%" if t else '  (placebo = the odds)'
        print(f"{r['name'][:42]:42s} {r['price']:9.2f} {r['dist']:+6.0f}  n {src['n']:3d}  {cells}  {tm:>11s}  "
              f"thru {src['through'] * 100:.0f}% back {src['back'] * 100:.0f}%{pls}")


def picture(res, px, path, W=240):
    """the live chart's last W minutes + one line per POI with its Asia odds (the cso_live.chart style). Measured numbers only."""
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    BG, FG, MUTED, GRIDC, UP, DN = '#181818', '#d1d4dc', '#808080', '#242424', '#089981', '#f23645'
    lv, last, _ = C._live_grid(3000)
    i = len(lv.days) - 1
    a = C.tmin(f'{last.hour}:{last.minute}')
    if a > 1380:  # still in the previous CME day's minutes: none
        a = 0
    O, H, L, Cc = lv.O[i], lv.H[i], lv.L[i], lv.C[i]
    # bars: the end of yesterday's session + tonight so far, on one continuous axis
    yb = [(m - 1440, lv.O[i - 1][m], lv.H[i - 1][m], lv.L[i - 1][m], lv.C[i - 1][m]) for m in range(1440 - max(0, W - a), 1380)]
    tb = [(m, O[m], H[m], L[m], Cc[m]) for m in range(0, a + 1)]
    bars = [b for b in yb + tb if not np.isnan(b[4])]
    near = [r for r in res if abs(r['dist']) <= 400]
    fig = Figure(figsize=(14, 10.5), facecolor=BG)
    ax = fig.add_axes([0.04, 0.07, 0.5, 0.82], facecolor=BG)
    for x, o, h, l, c in bars:
        col = '#b8b8b8' if c >= o else '#5a5a5a'
        ax.vlines(x, l, h, color=col, lw=0.7)
        ax.vlines(x, min(o, c), max(o, c) + 0.01, color=col, lw=2)
    x0, xn = bars[0][0], a
    fut = 240                                                  # Asia (7-11 PM) drawn as a band ahead of now
    ax.axvspan(A0, 360, color='#202020', zorder=0)
    ax.text((A0 + 360) / 2, 1.005, 'Asia 7-11 PM', transform=ax.get_xaxis_transform(), color=MUTED, fontsize=9, ha='center')
    ax.axvline(xn, color=MUTED, lw=0.8, ls='--')
    ax.axhline(px, color=FG, lw=0.6)
    ax.text(max(xn, 360), px, f'{px:,.2f} now ', color=FG, fontsize=8.5, ha='right', va='bottom')
    ys = [b[2] for b in bars] + [b[3] for b in bars] + [r['price'] for r in near]
    lo_y, hi_y = min(ys), max(ys)
    pad = (hi_y - lo_y) * 0.04
    ax.set_ylim(lo_y - pad, hi_y + pad)
    ax.set_xlim(x0, max(xn, 360) + 10)
    ticks = list(range(int(np.ceil(x0 / 60) * 60), int(max(xn, 360)) + 1, 60))
    ax.set_xticks(ticks, [C.clock(t % 1440) for t in ticks])
    ax.tick_params(colors=MUTED, labelsize=8.5)
    ax.yaxis.tick_right()
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.grid(color=GRIDC, lw=0.5)
    side = fig.add_axes([0.57, 0.07, 0.42, 0.82], facecolor=BG, sharey=ax)
    side.axis('off')
    side.set_xlim(0, 1)
    groups = []  # levels within 6 pts share one label; a tested kind speaks for the group
    for r in sorted(near, key=lambda r: r['price']):
        if groups and r['price'] - groups[-1][-1]['price'] <= 6 and not (r['typed'] and any(x['typed'] for x in groups[-1])):
            groups[-1].append(r)
        else:
            groups.append([r])
    span = hi_y - lo_y + 2 * pad
    slots = np.linspace(lo_y - pad + span * 0.04, hi_y + pad - span * 0.1, len(groups)) if groups else []
    chart_y = []  # on-chart % labels: a close neighbour moves left so they never overlap
    for gr, y in zip(groups, slots):
        r = next((x for x in gr if x['typed']), gr[0])
        p, up = r['price'], r['price'] > px
        col = UP if up else DN
        for x in gr:
            ax.hlines(x['price'], xn, max(xn, 360) + 10, color=col, lw=1.1)
        src = r['typed'] or r['placebo']['_full']
        asia = f"{src['by 11 PM'][0] * 100:.0f}%"
        # the Asia % is the headline: big on the label, and again at the end of the line on the chart
        xl = max(xn, 360) + 8 if not chart_y or abs(p - chart_y[-1][0]) > span * 0.025 or chart_y[-1][1] != 'R' else 300
        ax.text(xl, p, asia, color=col, fontsize=11, fontweight='bold', ha='right', va='bottom')
        chart_y.append((p, 'R' if xl != 300 else 'L'))
        side.plot([0, 0.025], [p, y], color=col, lw=0.7, clip_on=False)
        names = ' · '.join(dict.fromkeys(x['name'].replace(' + ', ' · ') for x in gr))
        when = f"   ·   usually ~{C.clock(A0 + src['t_med'])}" if src['t_med'] is not None else ''
        l1 = f"in Asia   {names[:36]}  {p:,.2f}  ({'+' if up else '-'}{abs(r['dist']):.0f})"
        l2 = '   '.join(f"{src[lab][0] * 100:.0f}% {lab}" for lab, _ in ENDS[1:]) + when
        pl = ' / '.join(f"{r['placebo'][lab][0] * 100:.0f}%" for lab, _ in ENDS)
        fine = [f"any price this far: {pl}"
                if r['typed'] else 'untested kind: distance only']
        if src['nhit'] >= 5:
            fine.append(f"after touch: {src['through'] * 100:.0f}% through, {src['back'] * 100:.0f}% back")
        fine.append(f"n {src['n']}")
        side.text(0.04, y, asia, color=col, fontsize=24, fontweight='bold', va='center')
        side.text(0.205, y + span * 0.006, l1, color='#ffffff', fontsize=9.5, fontweight='bold', va='bottom')
        side.text(0.205, y + span * 0.004, l2, color=FG, fontsize=8.8, va='top')
        side.text(0.205, y - span * 0.02, '  ·  '.join(fine), color=MUTED, fontsize=7.3, va='top')
    fig.text(0.04, 0.962, 'Odds price reaches each POI in Asia (7-11 PM CT)', color='#fff', fontsize=14, fontweight='bold')
    fig.text(0.04, 0.938, f'NQ {px:,.2f} at {C.clock(xn)} CT  ·  matched 2024-26 days with that kind of level at a similar distance '
             'from the 7 PM price  ·  descriptive odds, not a signal', color=MUTED, fontsize=9)
    fig.savefig(path, dpi=110, facecolor=BG)


if __name__ == '__main__':
    main()
    if '--png' in sys.argv:
        res = json.load(open(os.path.join(HERE, 'poi_asia.json')))
        px = float(sys.argv[sys.argv.index('--px') + 1])
        picture(res, px, os.path.join(HERE, 'poi_asia.png'))
        print('Chart:', os.path.join(HERE, 'poi_asia.png'))
