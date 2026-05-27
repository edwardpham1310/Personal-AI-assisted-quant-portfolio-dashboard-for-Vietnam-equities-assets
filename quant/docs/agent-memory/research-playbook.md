# Agent Research Playbook

Use this workflow when an agent is asked to analyze, extend, or review trading
logic.

## Step 1: Confirm Inputs

- Symbol or universe.
- Date range.
- Data source.
- Adjusted or unadjusted prices.
- Strategy or signal family.
- Cost assumptions.

If any of these materially affect the answer and cannot be inferred, ask the
user to verify.

## Step 2: Check Data

- Ensure data exists in SQLite.
- Check date range coverage.
- Validate OHLCV consistency.
- Look for stale final dates.

## Step 3: Compute Evidence

- Trend: moving averages, returns, breakout state.
- Momentum: RSI, ROC, recent acceleration.
- Volume: volume ratio and volume confirmation.
- Volatility: ATR percent and drawdown.
- Optional strategy evidence: backtest metrics and trade distribution.

## Step 4: Produce Recommendation

Write recommendations as research notes:

- Label.
- Score.
- Confidence.
- Reasons.
- Risks.
- Data caveats.

## Step 5: Verify

- Avoid lookahead.
- Avoid in-sample overclaiming.
- Keep assumptions visible.
- Add or update tests if code behavior changes.
