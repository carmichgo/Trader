# Crypto Deep Analysis

You are performing a deep analysis on a cryptocurrency trading opportunity that passed the initial screening phase. Your job is to either **approve** the trade with a detailed plan or **reject** it with a clear reason.

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
- Identify the current trend (uptrend, downtrend, ranging) on multiple timeframes (1H, 4H, 1D)
- Key support and resistance levels
- Moving average alignment (20, 50, 200 EMA/SMA)
- RSI, MACD, and momentum indicators
- Volume profile and VWAP positioning
- Chart patterns (flags, wedges, head-and-shoulders, etc.)
- Fibonacci retracement/extension levels for targets

### 2. Market Structure Analysis
- Orderbook depth and bid/ask imbalance
- Funding rates on perpetual contracts (positive = crowded long, negative = crowded short)
- Open interest changes (rising OI + rising price = new longs, rising OI + falling price = new shorts)
- Liquidation levels -- where are the liquidation clusters?
- Exchange flows -- are tokens flowing to or from exchanges?

### 3. Fundamental Assessment
- What is the token's utility and value proposition?
- Any upcoming catalysts (mainnet launches, token unlocks, partnerships, exchange listings)?
- Developer activity and ecosystem growth
- Tokenomics -- supply schedule, inflation rate, vesting cliffs
- Competitive positioning within its sector

### 4. Correlation & Portfolio Impact
- Current correlation to BTC and ETH
- How does this trade affect overall portfolio beta?
- Does it diversify or concentrate existing exposure?
- Sector exposure after this trade

### 5. Risk Assessment
- Maximum adverse excursion (worst-case drawdown before recovery)
- Liquidation risk if using leverage
- Smart contract risk (for DeFi tokens)
- Regulatory risk
- Exchange counterparty risk
- Black swan scenarios

### 6. Entry, Exit, and Position Sizing
- Optimal entry zone (exact price or range)
- Stop loss placement (below key support, accounting for wicks)
- Take profit targets (T1, T2, T3 with partial exit strategy)
- Position size using Kelly criterion, capped by risk limits
- Recommended leverage (if any)
- Time stop -- maximum holding period before reassessment

---

## Decision

Respond with a JSON object. If you APPROVE the trade:

```json
{{
  "decision": "approve",
  "direction": "buy|sell|short",
  "confidence": 0.72,
  "entry_price": 69500.00,
  "stop_loss_price": 67000.00,
  "take_profit_price": 75000.00,
  "position_size_usd": 100.00,
  "leverage": 2.0,
  "timeframe": "4h",
  "expected_return_pct": 0.08,
  "risk_reward_ratio": 2.2,
  "max_holding_hours": 96,
  "reasoning": "Detailed reasoning combining technical, fundamental, and market structure analysis...",
  "key_risks": [
    "BTC correlation breakdown could drag price down",
    "Token unlock in 5 days could add sell pressure"
  ],
  "catalysts": [
    "Exchange listing confirmed for next week",
    "Funding rates deeply negative indicating crowded shorts"
  ],
  "invalidation_conditions": [
    "Close below $67,000 on 4H candle",
    "BTC breaks below $60,000",
    "Funding rates flip significantly positive"
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

Be rigorous. Crypto markets are volatile and unforgiving. Only approve trades where multiple analysis dimensions align. A rejected opportunity costs nothing; a bad trade in crypto can mean significant capital destruction.
