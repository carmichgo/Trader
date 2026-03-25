# Polymarket Opportunity Screener

You are screening **{num_markets}** Polymarket prediction markets to find the best trading opportunities.

## Market Type
Polymarket -- binary and multi-outcome prediction markets on real-world events.

## Screening Criteria

Evaluate each market for:

1. **Mispricing**: Is the current probability significantly different from your estimated true probability? Look for at least 5% edge.
2. **Liquidity**: Is there enough liquidity to enter and exit without excessive slippage? Minimum $1,000 in orderbook depth.
3. **Volume**: Active markets with consistent volume are preferred. At least $500 daily volume.
4. **Time Value**: How far away is the resolution date? Markets resolving within 1-30 days are ideal. Avoid markets resolving in <6 hours (too risky) or >90 days (capital inefficient).
5. **Information Edge**: Can you identify an informational asymmetry? Are recent developments not yet priced in?
6. **Category**: Political, sports, crypto, weather, entertainment -- consider which categories have historically been most mispricable.

## What Makes a Good Polymarket Trade

- **Probability near extremes (0.05-0.20 or 0.80-0.95)**: Small mispricings near certainty can yield outsized returns when correct.
- **Binary events with clear catalysts**: Upcoming votes, scheduled announcements, or deadlines create predictable resolution.
- **Correlation plays**: If market A at 40% implies market B should be at 60% but B trades at 50%, there is an arbitrage.
- **Stale prices**: Markets that haven't updated after major relevant news.

## Risk Factors to Flag

- Low liquidity (wide spreads, thin books)
- Ambiguous resolution criteria
- Markets with dispute history
- Highly correlated to existing portfolio positions
- Markets where the "house" has massive positions (potential manipulation)

## Configuration

- Max positions: {max_positions}
- Available balance: ${available_balance}
- Risk tolerance (stop-loss): {risk_tolerance}
- Active strategies: {enabled_strategies}

## Market Data

{market_data}

## Output Format

Return a JSON object with an "opportunities" array. Each opportunity must have:

```json
{{
  "opportunities": [
    {{
      "symbol": "market-slug-or-id",
      "title": "Human-readable market question",
      "description": "Why this is a good opportunity",
      "current_price": 0.45,
      "estimated_edge": 0.12,
      "confidence": 0.75,
      "volume_24h": 5000,
      "liquidity": 15000,
      "volatility": 0.08,
      "category": "politics|sports|crypto|entertainment|science|other",
      "tags": ["binary", "election", "time-sensitive"],
      "url": "https://polymarket.com/event/...",
      "metadata": {{
        "estimated_true_probability": 0.57,
        "resolution_date": "2025-06-01",
        "days_to_resolution": 15,
        "suggested_direction": "buy_yes|buy_no",
        "suggested_size_pct": 0.05
      }}
    }}
  ]
}}
```

Only include opportunities where estimated_edge >= 0.05 and confidence >= 0.55. Sort by confidence * estimated_edge descending. Return at most 10 opportunities.
