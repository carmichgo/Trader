# Crypto Market Opportunity Screener

You are screening **{num_markets}** cryptocurrency markets to find the best trading opportunities.

## Market Type
Crypto -- spot and perpetual futures across major and mid-cap tokens.

## Screening Criteria

Evaluate each token/pair for:

1. **Technical Setup**: Is there a clear technical pattern forming? Look for breakouts, reversals, support/resistance levels, and momentum signals.
2. **Volume Profile**: Is volume increasing into the move or diverging? Volume confirmation is critical.
3. **Funding Rates**: For perpetuals, are funding rates extreme? Negative funding on uptrends or positive funding on downtrends signal potential mean reversion.
4. **Volatility Regime**: Is current volatility expanding or contracting relative to the 30-day average? Breakouts from low-vol regimes are powerful.
5. **Correlation**: How correlated is this token to BTC and ETH? Uncorrelated tokens offer better diversification.
6. **Market Cap & Liquidity**: Prefer tokens with >$50M market cap and >$5M daily volume. Illiquid tokens are dangerous.
7. **On-Chain Signals**: If available, consider exchange flows, whale movements, and DeFi TVL changes.

## What Makes a Good Crypto Trade

- **Breakout from consolidation**: Range-bound tokens breaking out with volume confirmation.
- **Funding rate extremes**: When perpetual funding rates are >0.05% per 8h (short squeeze setup) or <-0.05% (long squeeze setup).
- **Sector rotation**: Capital flowing from one sector to another (e.g., L1 to L2, DeFi to AI tokens).
- **Exchange listing / airdrop catalysts**: Upcoming exchange listings or token unlocks that are not fully priced.
- **Mean reversion after overreaction**: 20%+ dumps on non-fundamental news in otherwise healthy tokens.

## Risk Factors to Flag

- Tokens with >80% of supply held by top 10 wallets
- DEX-only tokens with minimal liquidity
- Tokens in active exploit/hack recovery
- Extreme leverage in the market (high open interest relative to market cap)
- Correlated to existing portfolio positions

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
      "symbol": "BTC/USDT",
      "title": "BTC breakout above $70K resistance",
      "description": "Technical reasoning for the opportunity",
      "current_price": 69500.00,
      "estimated_edge": 0.08,
      "confidence": 0.72,
      "volume_24h": 25000000000,
      "liquidity": 500000000,
      "volatility": 0.035,
      "category": "large_cap|mid_cap|small_cap|defi|l1|l2|meme|ai",
      "tags": ["breakout", "momentum", "high-volume"],
      "metadata": {{
        "funding_rate": 0.01,
        "open_interest": 15000000000,
        "change_7d_pct": 5.2,
        "change_30d_pct": 12.8,
        "correlation_to_btc": 1.0,
        "suggested_direction": "buy|sell|short",
        "suggested_entry": 69500.00,
        "suggested_stop_loss": 67000.00,
        "suggested_take_profit": 75000.00,
        "suggested_leverage": 2.0,
        "timeframe": "4h|1d|1w"
      }}
    }}
  ]
}}
```

Only include opportunities where estimated_edge >= 0.03 and confidence >= 0.60. Sort by risk-adjusted expected return descending. Return at most 10 opportunities.
