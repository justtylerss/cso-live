"""Pull the bars loaded on the user's TradingView chart over the debug port (9222), straight to a CSV, and compare them
with the merged 1-min history (data/nq_1m.parquet). Read-only: it asks the chart for more history, nothing else.
Usage: python -I tv_pull.py [max_bars]        -> data/tv_<symbol>_<resolution>.csv + the comparison printed"""
import asyncio, json, os, sys

import aiohttp
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
API = 'window.TradingViewApi._activeChartWidgetWV.value()'
READ = f"""(() => {{ const w = {API}; const ms = w._chartWidget.model().mainSeries(); const b = ms.bars();
  const out = []; for (let i = b.firstIndex(); i <= b.lastIndex(); i++) {{ const v = b.valueAt(i); if (v) out.push(v.slice(0, 6)); }}
  return JSON.stringify({{sym: w.symbol(), res: w.resolution(), bars: out}}); }})()"""
MORE = f"(() => {{ {API}._chartWidget.model().mainSeries().requestMoreData(5000); return 1; }})()"


async def evaluate(ws, expr, n=[0]):
    n[0] += 1
    await ws.send_json({'id': n[0], 'method': 'Runtime.evaluate', 'params': {'expression': expr, 'returnByValue': True}})
    while True:
        msg = await ws.receive_json()
        if msg.get('id') == n[0]:
            r = msg['result']
            if 'exceptionDetails' in r:
                raise RuntimeError(r['exceptionDetails'].get('text'))
            return r['result'].get('value')


async def pull(max_bars):
    async with aiohttp.ClientSession() as s:
        pages = await (await s.get('http://127.0.0.1:9222/json')).json()
        page = next(p for p in pages if p.get('type') == 'page' and 'tradingview.com/chart' in p.get('url', ''))
        async with s.ws_connect(page['webSocketDebuggerUrl'], max_msg_size=0) as ws:
            last = 0
            for _ in range(40):
                d = json.loads(await evaluate(ws, READ))
                n = len(d['bars'])
                if n >= max_bars or n == last:
                    break
                last = n
                await evaluate(ws, MORE)
                await asyncio.sleep(2.5)
            return d


def main():
    max_bars = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    d = asyncio.run(pull(max_bars))
    df = pd.DataFrame(d['bars'], columns=['t', 'open', 'high', 'low', 'close', 'volume'])
    df['ct'] = pd.to_datetime(df.t, unit='s', utc=True).dt.tz_convert('America/Chicago').dt.tz_localize(None)
    name = f"tv_{d['sym'].split(':')[-1].replace('!', '')}_{d['res']}.csv"
    df.to_csv(os.path.join(HERE, 'data', name), index=False)
    print(f"{d['sym']} {d['res']}: {len(df):,} bars {df.ct.iloc[0]} .. {df.ct.iloc[-1]} CT -> data/{name}")
    if d['res'] == '1':
        m = pd.read_parquet(os.path.join(HERE, 'data', 'nq_1m.parquet'), columns=['ct', 'open', 'high', 'low', 'close', 'volume'])
        j = df.merge(m, on='ct', suffixes=('_tv', ''))
        for c in ('open', 'high', 'low', 'close'):
            dv = (j[c + '_tv'] - j[c]).abs()
            print(f'  {c}: {len(j):,} shared minutes, median |diff| {dv.median():.2f}, exact {(dv == 0).mean():.1%}, within 1 pt {(dv <= 1).mean():.1%}')
        vr = (j.volume_tv / j.volume).replace([float('inf')], float('nan'))
        print(f'  volume ratio TV / ours: median {vr.median():.3f}')
        miss = set(df.ct) - set(m.ct)
        print(f'  TV minutes missing from ours: {len(miss)}; after our last bar: {(df.ct > m.ct.iloc[-1]).sum()}')


if __name__ == '__main__':
    main()
