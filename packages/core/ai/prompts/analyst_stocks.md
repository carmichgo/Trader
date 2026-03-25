# US Equities Deep Analysis

You are performing a deep analysis on a US stock trading opportunity that passed the initial screening phase. Your job is to either **approve** the trade with a detailed plan or **reject** it with a clear reason.

## Opportunity Summary

| Field | Value |
|---|---|
| Symbol | {symbol} |
| Market Type | {market_type} |
| Current Price | {current_price} |
| Estimated Edge (Screener) | {estimated_edge} |
| Screener Confidence | {screener_confidence} |
| Title | {title} |
| Description | {description} |
| 24h Volume | {volume_24h} |
| Liquidity | {liquidity} |
| Volatility | {volatility} |
| Category | {category} |
| Tags | {tags} |

## Portfolio Context

### Current Portfolio State
{portfolio_state}

### Recent Trade Results
{recent_trades}

### Market Conditions
{market_conditions}

### Risk Limits
{risk_limits}

### Available Balance: ${available_balance}
### Max Position Size: {max_position_pct:.0%} of balance

---

## Analysis Framework

Perform the following analysis steps:

### 1. Technical Analysis
- Current trend identification on daily and weekly timeframes
- Key support and resistance levels from price history
- Moving average analysis (20, 50, 200 SMA) -- golden/death crosses?
- RSI (overbought/oversold), MACD (signal line crossovers), Bollinger Bands
- Volume analysis -- is volume confirming the move?
- Chart patterns and their measured move targets
- Relative strength vs. SPY and sector ETF

### 2. Fundamental Analysis
- Revenue growth trajectory (quarterly YoY)
- Earnings growth and estimate revisions
- Margin trends (gross, operating, net)
- Free cash flow generation and yield
- Balance sheet strength (debt/equity, current ratio, cash position)
- Valuation multiples vs. historical range and peer group (P/E, P/S, EV/EBITDA)
- PEG ratio for growth-adjusted valuation

### 3. Catalyst Analysis
- Upcoming earnings date and consensus estimates
- Scheduled product launches, FDA decisions, or regulatory milestones
- Management guidance and conference call commentary
- Analyst upgrades/downgrades and price target changes
- Insider buying/selling patterns (last 90 days)
- Institutional ownership changes (13F filings)
- Sector-wide tailwinds or headwinds

### 4. Sentiment & Flow Analysis
- Short interest as % of float -- is a squeeze possible?
- Options market implied volatility vs. realized volatility
- Unusual options activity (large block trades, call/put skew)
- Social media / news sentiment (if relevant data available)
- Dark pool activity indicators

### 5. Risk Assessment
- Macro risk factors (interest rates, recession probability, geopolitical)
- Sector-specific risks (regulation, competition, disruption)
- Company-specific risks (customer concentration, key person risk, litigation)
- Earnings risk -- how much is priced in? What happens on a miss?
- Correlation to existing portfolio positions and overall market beta
- Gap risk (stocks can gap 10%+ overnight on news)

### 6. Entry, Exit, and Position Sizing
- Optimal entry price/zone
- Stop loss placement (below key support, below recent swing low)
- Take profit targets with reasoning for each level
- Position size calculation based on:
  - Risk per trade (distance to stop loss)
  - Kelly criterion (adjusted for estimation error)
  - Maximum allocation constraint
- Time horizon and conditions for reassessment
- Pre-market/after-hours entry considerations

---

## Decision

Respond with a JSON object. If you APPROVE the trade:

```json
{{
  "decision": "approve",
  "direction": "buy|sell|short",
  "confidence": 0.70,
  "entry_price": 195.50,
  "stop_loss_price": 189.00,
  "take_profit_price": 210.00,
  "position_size_usd": 150.00,
  "leverage": 1.0,
  "timeframe": "1w",
  "expected_return_pct": 0.075,
  "risk_reward_ratio": 2.2,
  "max_holding_hours": 240,
  "reasoning": "Detailed reasoning combining technical, fundamental, and catalyst analysis...",
  "key_risks": [
    "Broader market sell-off could drag the stock down regardless of fundamentals",
    "Earnings in 12 days -- could gap down on a miss"
  ],
  "catalysts": [
    "Analyst upgrades this week with raised price targets",
    "Product launch event scheduled next Tuesday"
  ],
  "invalidation_conditions": [
    "Close below $189 on daily candle",
    "SPY breaks below 200-day MA",
    "Insider selling exceeds $10M in a single week"
  ]
}}
```

If you REJECT the trade:

```json
{{
  "decision": "reject",
  "reasoning": "Detailed reasoning for rejection..."
}}
```

Be rigorous. Stocks are the most efficiently priced of our three markets. Only approve trades where you see a genuine informational or analytical edge that the market has not yet discounted.
