# Strategy (draft, pending backtest)

Status: **setup**. These rules are a draft. In Step 2 each sleeve is backtested on
2–3+ years of history, including the 2022 bear market. A sleeve that doesn't beat its
benchmark on a risk-adjusted basis gets proposed fixes instead of being traded.
Every number referenced here lives in `config.yaml`.

## Big picture
- 70% stocks/ETFs (40% core growth + 30% swing momentum) and 30% crypto.
- Rebalance when either side drifts more than 10 points from 70/30.
- Every position has a stop at entry. The stop is placed as a real order at Robinhood,
  so it protects the account between scheduled checks. Stops only move up.

## Sleeve 1: Core growth (~40%)
- Holdings: 2–4 growth ETFs or large growth stocks (e.g. QQQ, SMH, XLK, or a leader in one
  of those groups).
- Enter when the close is above the 50-day moving average AND the 50-day average is
  rising (higher than 10 trading days ago).
- Exit on a daily close below the 50-day average, or if a trailing stop is hit
  (draft: 2.5 x ATR(14) below the highest close since entry).
- Hold time: weeks to months.

## Sleeve 2: Swing momentum (~30%)
- Universe: liquid growth names passing the filters (price > $5, market cap > $2B,
  average volume > 1M shares/day).
- Draft entry, either:
  - Breakout: close at a 20-day high, 20-day MA above 50-day MA, relative volume > 1.5,
    and 3-month return beating QQQ; or
  - Pullback: in an uptrend (20 > 50 MA), RSI(14) dips under 40 then closes back above
    it near the 20-day MA.
- Stop: below the breakout/pullback low, or 2 x ATR(14), whichever is tighter
  (and still within the 3% account-risk cap).
- Target: 2R (twice the risk), with a trailing stop after +1R.
- Hold time: days to weeks. Day trades only as rare exceptions.

## Sleeve 3: Crypto (~30%)
- At least 2/3 in BTC/ETH; at most 1/3 in large-cap altcoins.
- Trend rule adapted to 24/7 markets: hold while the price is above a rising 50-day MA
  (calendar days); exit on a daily close below it or on the trailing stop.
- Altcoins: only when above their own 50-day MA and outperforming BTC over 30 days;
  max 15% of equity in any one.

## Position sizing (applies to every trade)
1. Max risk = equity x 3%.
2. Shares = max risk / (entry - stop).
3. Cap at 20% of equity (15% for an altcoin) and at the sleeve's available settled cash.
4. Halve the size if earnings fall inside the expected holding window (or skip).
5. Halve all new sizes while the drawdown from the high-water mark is 25% or more.

## Hard stops on the system
- 50% drawdown from the high-water mark -> close everything, stop, notify, and wait for the owner.
- Bad data, a stale quote (> 5 min) or an order error -> do nothing and log it.
- Never: margin, options, leverage, shorting, deposits/withdrawals, account setting changes.
