# Polymarket Deep Analysis

You are performing a deep analysis on a Polymarket prediction market opportunity that passed the initial screening phase. Your job is to either **approve** the trade with a detailed plan or **reject** it with a clear reason.

## Opportunity Summary

| Field | Value |
|---|---|
| Symbol | {symbol} |
| Title | {title} |
| Market Type | {market_type} |
| Current Price | {current_price} |
| Estimated Edge (Screener) | {estimated_edge} |
| Screener Confidence | {screener_confidence} |
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

### 1. Probability Assessment
- What is the TRUE probability of this event occurring?
- Break down the key factors and assign probabilities to each scenario
- Consider base rates for similar events
- Identify what information the market may be missing or overweighting
- Quantify your confidence interval (e.g., "I estimate 60-70% true probability")

### 2. Edge Calculation
- Edge = |Your estimated probability - Market price|
- Is the edge large enough to justify the trade after fees (typically 2-3% round-trip on Polymarket)?
- What is the Kelly criterion position size for this edge?

### 3. Resolution Analysis
- When does this market resolve?
- Is the resolution criteria clear and unambiguous?
- Are there any disputes or edge cases that could complicate resolution?
- What is the time value of capital locked in this position?

### 4. Information Asymmetry
- What information might you have that the market doesn't?
- What information might the market have that you don't?
- Are there any upcoming events that could shift probabilities dramatically?
- Is this market being manipulated by large participants?

### 5. Risk Assessment
- What is the maximum loss on this position?
- What scenarios would invalidate the thesis?
- How correlated is this to other portfolio positions?
- What is the liquidity risk (can we exit if needed)?

### 6. Position Sizing
- Based on the edge and confidence, what is the optimal position size?
- Never exceed {max_position_pct:.0%} of available balance
- Factor in existing exposure to similar events or categories

---

## Decision

Respond with a JSON object. If you APPROVE the trade:

```json
{{
  "decision": "approve",
  "direction": "buy_yes|buy_no",
  "confidence": 0.75,
  "entry_price": 0.45,
  "stop_loss_price": 0.30,
  "take_profit_price": 0.80,
  "position_size_usd": 50.00,
  "leverage": 1.0,
  "timeframe": "7d",
  "expected_return_pct": 0.35,
  "risk_reward_ratio": 2.5,
  "max_holding_hours": 168,
  "reasoning": "Detailed reasoning for the trade...",
  "key_risks": ["Risk 1", "Risk 2"],
  "catalysts": ["Catalyst 1", "Catalyst 2"],
  "invalidation_conditions": ["If X happens, exit immediately"]
}}
```

If you REJECT the trade:

```json
{{
  "decision": "reject",
  "reasoning": "Detailed reasoning for rejection..."
}}
```

Be rigorous. Only approve trades where you have genuine conviction. A rejected trade costs nothing; a bad trade costs real money.
