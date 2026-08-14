"""ES trend-following backtest — Donchian breakout (both directions) + ATR stops + 1% risk.

Both long and short. Regime filter = 200 SMA. ATR-based stops/targets.
"""
import yfinance as yf
import pandas as pd
import numpy as np

# ===== DATA =====
df = yf.download('ES=F', period='5y', interval='1d', progress=False)
df.columns = [c[0] for c in df.columns]
df = df.dropna()

close = df['Close'].astype(float)
high = df['High'].astype(float)
low = df['Low'].astype(float)

# ===== INDICATORS =====
sma200 = close.rolling(200).mean()
atr = (high - low).rolling(14).mean()
donchian_hi = high.rolling(20).max().shift(1)   # 20-day high (entry long)
donchian_lo = low.rolling(20).min().shift(1)    # 20-day low (entry short)

# ===== BACKTEST LOOP =====
equity = 100_000.0
risk_pct = 0.01
commission = 4.5      # $ round-trip per ES contract
slippage = 0.25       # points per side
MULT = 50             # ES = $50 per point

position = 0          # 0=flat, +n=long, -n=short
entry_price = 0.0
stop_price = 0.0
target_price = 0.0
direction = 0

trades = []
equity_curve = []

for i in range(200, len(df)):   # start after 200 SMA warmup
    c = close.iloc[i]; h = high.iloc[i]; l = low.iloc[i]
    a = atr.iloc[i]

    if position == 0:
        # Long: breakout above 20-day high, above 200 SMA
        if c > donchian_hi.iloc[i] and c > sma200.iloc[i] and a > 0:
            entry_price = c + slippage
            stop_price = entry_price - 2.0 * a
            target_price = entry_price + 3.0 * a
            direction = 1
        # Short: breakout below 20-day low, below 200 SMA
        elif c < donchian_lo.iloc[i] and c < sma200.iloc[i] and a > 0:
            entry_price = c - slippage
            stop_price = entry_price + 2.0 * a
            target_price = entry_price - 3.0 * a
            direction = -1
        else:
            equity_curve.append(equity)
            continue

        risk_per_contract = abs(entry_price - stop_price)
        if risk_per_contract <= 0:
            continue
        risk_amount = equity * risk_pct
        size = max(1, int(risk_amount / (risk_per_contract * MULT)))
        position = size * direction
        equity -= size * commission
        trades.append({'dir': direction, 'entry': entry_price, 'stop': stop_price,
                       'target': target_price, 'size': size, 'date': df.index[i]})

    else:
        exit_reason = None; exit_price = None
        if direction == 1:
            if l <= stop_price:
                exit_reason = 'stop'; exit_price = stop_price
            elif h >= target_price:
                exit_reason = 'target'; exit_price = target_price
            elif c < sma200.iloc[i]:
                exit_reason = 'trend_break'; exit_price = c
        else:
            if h >= stop_price:
                exit_reason = 'stop'; exit_price = stop_price
            elif l <= target_price:
                exit_reason = 'target'; exit_price = target_price
            elif c > sma200.iloc[i]:
                exit_reason = 'trend_break'; exit_price = c

        if exit_reason:
            exit_price = exit_price - slippage if direction == 1 else exit_price + slippage
            pnl = (exit_price - entry_price) * direction * MULT * abs(position)
            equity += pnl - abs(position) * commission
            trades[-1].update({'exit': exit_price, 'exit_date': df.index[i],
                               'pnl': pnl, 'exit_reason': exit_reason,
                               'r': ((exit_price - entry_price) * direction) / abs(entry_price - stop_price)})
            position = 0

    equity_curve.append(equity)

# ===== METRICS =====
eq = pd.Series(equity_curve)
closed = [t for t in trades if 'exit_reason' in t]
wins = [t for t in closed if t['pnl'] > 0]
losses = [t for t in closed if t['pnl'] <= 0]
gross_win = sum(t['pnl'] for t in wins)
gross_loss = abs(sum(t['pnl'] for t in losses))
profit_factor = gross_win / gross_loss if gross_loss > 0 else float('inf')
win_rate = len(wins) / len(closed) if closed else 0
peak = eq.cummax(); drawdown = (eq - peak) / peak; max_dd = drawdown.min()
rets = eq.pct_change().dropna()
sharpe = (rets.mean() / rets.std()) * np.sqrt(252) if rets.std() > 0 else 0

print('='*62)
print(f'ES TREND-FOLLOWING (long+short) — Donchian breakout + ATR stops')
print(f'Period: {df.index[0].date()} → {df.index[-1].date()} ({len(df)} bars)')
print('='*62)
print(f'Starting equity:   ${100_000:,.0f}')
print(f'Final equity:      ${equity:,.0f}')
print(f'Net return:        {(equity/100_000 - 1)*100:,.1f}%')
print(f'Total trades:      {len(closed)}')
print(f'Win rate:          {win_rate*100:.1f}%')
print(f'Profit factor:     {profit_factor:.2f}')
print(f'Max drawdown:      {max_dd*100:.1f}%')
print(f'Sharpe:            {sharpe:.2f}')
print(f'Avg R per trade:   {np.mean([t["r"] for t in closed]):.2f}' if closed else 'Avg R: n/a')
longs = [t for t in closed if t['dir'] == 1]
shorts = [t for t in closed if t['dir'] == -1]
print(f'Long trades:       {len(longs)}  |  Short trades: {len(shorts)}')
print('='*62)
print('Last 8 trades:')
for t in closed[-8:]:
    d = 'LONG ' if t['dir'] == 1 else 'SHORT'
    print(f"  {str(t['exit_date'])[:10]}  {d}  {t['exit_reason']:<11} R={t['r']:+.2f}  PnL=${t['pnl']:+,.0f}")
