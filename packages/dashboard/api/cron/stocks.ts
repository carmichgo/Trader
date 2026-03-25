import type { VercelRequest, VercelResponse } from '@vercel/node';
import { supabase } from '../lib/supabase-server';
import { callClaude, extractJSON } from '../lib/anthropic';
import type { ScreenerOpportunity, AnalystDecision, CronResult, MarketData } from '../lib/types';

const SONNET = 'claude-sonnet-4-20250514';
const OPUS = 'claude-opus-4-20250514';
const TRADER_NAME = 'stocks';

// Top liquid tickers to monitor
const STOCK_SYMBOLS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'SPY', 'QQQ', 'AMD'];

const SCREENER_SYSTEM_PROMPT = `You are a stock market screener AI. Analyze the provided market data and identify short-term trading opportunities.

Respond ONLY with a JSON array of opportunities. Each object must have:
- asset: string (ticker symbol)
- direction: "buy" | "sell" | "short"
- score: number 0-100 (confidence/opportunity score)
- estimated_edge_pct: number (estimated edge percentage)
- win_probability: number 0-1
- rationale: string (brief reasoning)

If no opportunities exist, return an empty array [].`;

const ANALYST_SYSTEM_PROMPT = `You are a senior stock trading analyst AI. You receive a trading opportunity and must decide whether to take the trade.

Respond ONLY with a JSON object:
- action: "buy" | "reject"
- size_pct: number (percentage of available capital to allocate, 1-10)
- entry_price: number (current/suggested entry price)
- stop_loss: number (stop loss price)
- take_profit: number (take profit price)
- confidence: number 0-100
- reasoning: string (detailed analysis)`;

/**
 * Check if we're within US stock market hours (9:30-16:00 ET, Mon-Fri).
 */
function isMarketOpen(): boolean {
  const now = new Date();
  // Convert to Eastern Time
  const et = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }));
  const day = et.getDay(); // 0=Sun, 6=Sat
  if (day === 0 || day === 6) return false;

  const hours = et.getHours();
  const minutes = et.getMinutes();
  const totalMinutes = hours * 60 + minutes;

  // 9:30 AM = 570 min, 4:00 PM = 960 min
  return totalMinutes >= 570 && totalMinutes <= 960;
}

/**
 * Fetch stock quotes from Yahoo Finance v8 API (free, no key required).
 */
async function fetchStockData(): Promise<MarketData[]> {
  const symbols = STOCK_SYMBOLS.join(',');
  const url = `https://query1.finance.yahoo.com/v8/finance/spark?symbols=${symbols}&range=1d&interval=1d`;

  const response = await fetch(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0',
    },
  });

  if (!response.ok) {
    // Fallback: try the v7 quote endpoint
    return fetchStockDataFallback();
  }

  const data = await response.json();
  const markets: MarketData[] = [];

  for (const symbol of STOCK_SYMBOLS) {
    const spark = data.spark?.result?.find(
      (r: { symbol: string }) => r.symbol === symbol
    );
    if (!spark?.response?.[0]?.meta) continue;

    const meta = spark.response[0].meta;
    const price = meta.regularMarketPrice ?? 0;
    const prevClose = meta.previousClose ?? meta.chartPreviousClose ?? price;
    const changePct = prevClose > 0 ? ((price - prevClose) / prevClose) * 100 : 0;

    markets.push({
      symbol,
      price,
      change_24h_pct: changePct,
      volume_24h: null,
      market_cap: null,
    });
  }

  return markets;
}

/**
 * Fallback: fetch quotes from Yahoo Finance v7 endpoint.
 */
async function fetchStockDataFallback(): Promise<MarketData[]> {
  const symbols = STOCK_SYMBOLS.join(',');
  const url = `https://query1.finance.yahoo.com/v7/finance/quote?symbols=${symbols}`;

  const response = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0' },
  });

  if (!response.ok) {
    throw new Error(`Yahoo Finance API error: ${response.status}`);
  }

  const data = await response.json();
  const quotes = data.quoteResponse?.result ?? [];

  return quotes.map((q: Record<string, unknown>) => ({
    symbol: String(q.symbol ?? ''),
    price: Number(q.regularMarketPrice ?? 0),
    change_24h_pct: Number(q.regularMarketChangePercent ?? 0),
    volume_24h: q.regularMarketVolume ? Number(q.regularMarketVolume) : null,
    market_cap: q.marketCap ? Number(q.marketCap) : null,
  }));
}

function buildMarketSnapshot(markets: MarketData[]): string {
  const timestamp = new Date().toISOString();
  let snapshot = `US Stock Market Snapshot (${timestamp})\n\n`;
  for (const m of markets) {
    snapshot += `${m.symbol}: $${m.price.toFixed(2)}`;
    if (m.change_24h_pct !== null) {
      snapshot += ` | Day Change: ${m.change_24h_pct.toFixed(2)}%`;
    }
    if (m.volume_24h !== null) {
      snapshot += ` | Volume: ${(m.volume_24h / 1e6).toFixed(1)}M`;
    }
    if (m.market_cap !== null) {
      snapshot += ` | MCap: $${(m.market_cap / 1e9).toFixed(1)}B`;
    }
    snapshot += '\n';
  }
  return snapshot;
}

function calculateNEV(analyst: AnalystDecision, inferenceCost: number): number {
  const potentialProfit = Math.abs(analyst.take_profit - analyst.entry_price);
  const potentialLoss = Math.abs(analyst.entry_price - analyst.stop_loss);
  const winProb = analyst.confidence / 100;
  return potentialProfit * winProb - potentialLoss * (1 - winProb) - inferenceCost;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const result: CronResult = {
    trader: TRADER_NAME,
    timestamp: new Date().toISOString(),
    opportunities_found: 0,
    trades_opened: 0,
    decisions_logged: 0,
    errors: [],
  };

  try {
    const cronSecret = process.env.CRON_SECRET;
    if (cronSecret) {
      const authHeader = req.headers['authorization'];
      if (authHeader !== `Bearer ${cronSecret}`) {
        return res.status(401).json({ error: 'Unauthorized' });
      }
    }

    // Only run during market hours
    if (!isMarketOpen()) {
      return res.status(200).json({
        ...result,
        errors: ['Market is closed — skipping stock trader run'],
      });
    }

    // 1. Fetch market data
    const markets = await fetchStockData();
    if (markets.length === 0) {
      result.errors.push('No stock data returned');
      return res.status(200).json(result);
    }

    const snapshot = buildMarketSnapshot(markets);

    // 2. Screen with Sonnet
    const screenerResponse = await callClaude(
      SONNET,
      SCREENER_SYSTEM_PROMPT,
      `Analyze this stock market data and identify trading opportunities:\n\n${snapshot}`
    );

    // Log screener decision
    await supabase.from('ai_decisions').insert({
      decision_type: 'screener',
      trader: TRADER_NAME,
      model: SONNET,
      prompt_tokens: screenerResponse.input_tokens,
      completion_tokens: screenerResponse.output_tokens,
      cost_usd: screenerResponse.cost_usd,
      latency_ms: screenerResponse.latency_ms,
      input_summary: snapshot.slice(0, 500),
      output_raw: screenerResponse.content,
    });
    result.decisions_logged++;

    let opportunities: ScreenerOpportunity[] = [];
    try {
      opportunities = extractJSON<ScreenerOpportunity[]>(screenerResponse.content);
    } catch {
      result.errors.push('Failed to parse screener JSON response');
    }

    // Filter for high confidence (>= 70)
    const viable = opportunities.filter((o) => o.score >= 70);
    result.opportunities_found = viable.length;

    // 3. Deep-analyze high-scoring opportunities with Opus
    for (const opp of viable) {
      if (opp.score < 80) continue;

      const marketItem = markets.find((m) => m.symbol === opp.asset);
      const analystPrompt = `Trading opportunity identified by screener:
Asset: ${opp.asset}
Direction: ${opp.direction}
Screener Score: ${opp.score}/100
Estimated Edge: ${opp.estimated_edge_pct}%
Win Probability: ${(opp.win_probability * 100).toFixed(1)}%
Rationale: ${opp.rationale}

Current Price: $${marketItem?.price?.toFixed(2) ?? 'unknown'}
Day Change: ${marketItem?.change_24h_pct?.toFixed(2) ?? 'N/A'}%
Volume: ${marketItem?.volume_24h ? (marketItem.volume_24h / 1e6).toFixed(1) + 'M' : 'N/A'}

Should we take this trade? Provide entry, stop-loss, and take-profit levels.`;

      let analystResponse;
      try {
        analystResponse = await callClaude(OPUS, ANALYST_SYSTEM_PROMPT, analystPrompt, 2048);
      } catch (err) {
        result.errors.push(`Analyst call failed for ${opp.asset}: ${String(err)}`);
        continue;
      }

      // Log analyst decision
      await supabase.from('ai_decisions').insert({
        decision_type: 'analyst',
        trader: TRADER_NAME,
        model: OPUS,
        prompt_tokens: analystResponse.input_tokens,
        completion_tokens: analystResponse.output_tokens,
        cost_usd: analystResponse.cost_usd,
        latency_ms: analystResponse.latency_ms,
        input_summary: analystPrompt.slice(0, 500),
        output_raw: analystResponse.content,
      });
      result.decisions_logged++;

      let analyst: AnalystDecision;
      try {
        analyst = extractJSON<AnalystDecision>(analystResponse.content);
      } catch {
        result.errors.push(`Failed to parse analyst JSON for ${opp.asset}`);
        continue;
      }

      if (analyst.action === 'reject') continue;

      // Calculate NEV
      const totalInferenceCost = screenerResponse.cost_usd + analystResponse.cost_usd;
      const nev = calculateNEV(analyst, totalInferenceCost);
      if (nev <= 0) {
        result.errors.push(`NEV negative for ${opp.asset}: ${nev.toFixed(4)}, skipping`);
        continue;
      }

      // Insert trade
      const { error: tradeError } = await supabase.from('trades').insert({
        trader: TRADER_NAME,
        asset: opp.asset,
        direction: opp.direction,
        position_size_usd: analyst.size_pct * 10,
        quantity: analyst.size_pct * 10 / analyst.entry_price,
        entry_price: analyst.entry_price,
        stop_loss: analyst.stop_loss,
        take_profit: analyst.take_profit,
        status: 'open',
        ai_confidence: analyst.confidence,
        ai_model_used: OPUS,
        screener_cost: screenerResponse.cost_usd,
        analyst_cost: analystResponse.cost_usd,
        total_cost: totalInferenceCost,
        screener_output: JSON.stringify(opp),
        analyst_output: JSON.stringify(analyst),
        opened_at: new Date().toISOString(),
      });

      if (tradeError) {
        result.errors.push(`Failed to insert trade for ${opp.asset}: ${tradeError.message}`);
      } else {
        result.trades_opened++;
      }
    }

    // 4. Insert portfolio snapshot
    await supabase.from('portfolio_snapshots').insert({
      time: new Date().toISOString(),
      stocks_capital: markets.length * 100,
      total_capital: 1000,
      daily_inference_cost: screenerResponse.cost_usd,
    });

    return res.status(200).json(result);
  } catch (err) {
    result.errors.push(String(err));
    return res.status(500).json(result);
  }
}
