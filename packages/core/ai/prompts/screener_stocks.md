# US Equities Opportunity Screener

You are screening **{num_markets}** US equities to find the best trading opportunities.

## Market Type
US Stocks -- equities traded on NYSE, NASDAQ, and other major US exchanges.

## Screening Criteria

Evaluate each stock for:

1. **Technical Setup**: Clear chart patterns, moving average crossovers, RSI divergences, MACD signals, and volume patterns.
2. **Fundamental Catalysts**: Upcoming earnings, FDA approvals, product launches, M&A rumors, management changes, or sector tailwinds.
3. **Relative Strength**: Is the stock outperforming or underperforming its sector and the broader market (SPY)?
4. **Volume Anomalies**: Unusual volume spikes can precede major moves. Look for 2x+ average volume.
5. **Options Flow**: If available, consider unusual options activity (large call/put purchases, IV skew changes).
6. **Valuation**: Is the stock trading at a significant discount/premium to peers on P/E, P/S, EV/EBITDA?
7. **Institutional Activity**: Recent 13F filings, insider buying/selling patterns.

## What Makes a Good Stock Trade

- **Earnings momentum**: Stocks with consecutive earnings beats and upward revisions.
- **Breakout from base**: Multi-week or multi-month consolidation breaking out on volume.
- **Oversold bounce**: RSI < 30, price at key support, with a catalyst for recovery.
- **Sector momentum**: Stocks in hot sectors (AI, GLP-1, defense, energy transition) with strong fundamentals.
- **Event-driven**: Binary events (FDA decisions, court rulings, election outcomes) where the market underestimates one outcome.

## Risk Factors to Flag

- Small cap stocks with <$500M market cap (manipulation risk)
- Stocks with >30% short interest (potential short squeeze but also potential fraud target)
- Companies with recent SEC investigations or restatements
- Stocks near all-time highs with decelerating momentum
- Highly correlated to existing portfolio positions

## Configuration

- Max positions: {max_positions}
- Available balance: ${available_balance}
- Risk tolerance (stop-loss): {risk_tolerance}
- Active strategies: {enabled_strategies}

## Market Data

{market_data}

## Output Format

Return a JSON object with an "opportunities" array:

```json
{{
  "opportunities": [
    {{
      "symbol": "AAPL",
      "title": "Apple pre-earnings momentum breakout",
      "description": "Technical and fundamental reasoning",
      "current_price": 195.50,
      "estimated_edge": 0.06,
      "confidence": 0.68,
      "volume_24h": 75000000,
      "liquidity": 3000000000,
      "volatility": 0.022,
      "category": "tech|healthcare|finance|energy|consumer|industrial|materials|utilities|real_estate",
      "tags": ["earnings", "momentum", "large-cap"],
      "metadata": {{
        "market_cap": 3000000000000,
        "pe_ratio": 30.5,
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "short_interest_pct": 0.8,
        "relative_strength_vs_spy": 1.05,
        "days_to_earnings": 12,
        "suggested_direction": "buy|sell|short",
        "suggested_entry": 195.50,
        "suggested_stop_loss": 189.00,
        "suggested_take_profit": 210.00,
        "timeframe": "1d|1w|1m"
      }}
    }}
  ]
}}
```

Only include opportunities where estimated_edge >= 0.03 and confidence >= 0.60. Sort by risk-adjusted expected return descending. Return at most 10 opportunities.
