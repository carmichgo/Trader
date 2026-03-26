import type { VercelRequest, VercelResponse } from '@vercel/node';
import { createClient } from '@supabase/supabase-js';

// ── Inlined: Supabase client ──
const supabaseUrl = process.env.STORAGE_SUPABASE_URL || process.env.VITE_SUPABASE_URL || '';
const supabaseKey = process.env.STORAGE_SUPABASE_SERVICE_ROLE_KEY || '';
const supabase = createClient(supabaseUrl, supabaseKey);

// ── Inlined: Types ──
interface ClaudeResponse {
  content: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
  model: string;
}

interface ScreenerOpportunity {
  asset: string;
  direction: 'buy' | 'sell' | 'short';
  score: number;
  estimated_edge_pct: number;
  win_probability: number;
  rationale: string;
}

interface AnalystDecision {
  action: 'buy' | 'reject';
  size_pct: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  confidence: number;
  reasoning: string;
}

interface CronResult {
  trader: string;
  timestamp: string;
  opportunities_found: number;
  trades_opened: number;
  decisions_logged: number;
  errors: string[];
}

interface MarketData {
  symbol: string;
  price: number;
  change_24h_pct: number | null;
  volume_24h: number | null;
  market_cap: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
}

// ── Inlined: Claude helpers ──
const ANTHROPIC_API_URL = 'https://api.anthropic.com/v1/messages';

const MODEL_PRICING: Record<string, { input: number; output: number }> = {
  'claude-sonnet-4-6': { input: 3, output: 15 },
  'claude-opus-4-6': { input: 15, output: 75 },
};

async function callClaude(
  model: string,
  systemPrompt: string,
  userPrompt: string,
  maxTokens: number = 4096
): Promise<ClaudeResponse> {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    throw new Error('ANTHROPIC_API_KEY is not set');
  }

  const start = Date.now();

  const response = await fetch(ANTHROPIC_API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model,
      max_tokens: maxTokens,
      system: systemPrompt,
      messages: [{ role: 'user', content: userPrompt }],
    }),
  });

  const latencyMs = Date.now() - start;

  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`Anthropic API error ${response.status}: ${errorBody}`);
  }

  const data = await response.json();

  const inputTokens: number = data.usage?.input_tokens ?? 0;
  const outputTokens: number = data.usage?.output_tokens ?? 0;

  const pricing = MODEL_PRICING[model] ?? { input: 3, output: 15 };
  const costUsd =
    (inputTokens * pricing.input) / 1_000_000 +
    (outputTokens * pricing.output) / 1_000_000;

  const content =
    data.content
      ?.filter((block: { type: string }) => block.type === 'text')
      .map((block: { text: string }) => block.text)
      .join('') ?? '';

  return {
    content,
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    cost_usd: costUsd,
    latency_ms: latencyMs,
    model,
  };
}

function extractJSON<T = unknown>(raw: string): T {
  const fenceMatch = raw.match(/```(?:json)?\s*([\s\S]*?)```/);
  const toParse = fenceMatch ? fenceMatch[1]!.trim() : raw.trim();
  return JSON.parse(toParse) as T;
}

// ── Stock trader logic ──

const SONNET = 'claude-sonnet-4-6';
const OPUS = 'claude-opus-4-6';
const TRADER_NAME = 'stocks';

// Top liquid tickers to monitor
const STOCK_SYMBOLS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'SPY', 'QQQ', 'AMD'];

const SCREENER_SYSTEM_PROMPT = `You are a stock market screener for an autonomous AI trading system. You identify short-term equity trading opportunities.

Your behavior is driven by the STRATEGIST DIRECTIVES below. Follow them exactly — they set your focus tickers, risk posture, and approach.

OUTPUT FORMAT — respond ONLY with a JSON array:
[{"asset":"AAPL","direction":"buy","score":78,"estimated_edge_pct":1.2,"win_probability":0.68,"rationale":"..."}]

Rules:
- Follow the strategist's focus_assets and strategy_notes
- Look for: momentum, earnings plays, sector rotation, unusual volume, relative strength
- Always find at least 1-2 opportunities from the provided data`;

const ANALYST_SYSTEM_PROMPT = `You are a senior stock trading analyst AI. You receive a trading opportunity and must decide whether to take the trade.

Respond ONLY with a JSON object:
- action: "buy" | "reject"
- size_pct: number (percentage of available capital to allocate, 1-10)
- entry_price: number (current/suggested entry price)
- stop_loss: number (stop loss price)
- take_profit: number (take profit price)
- confidence: number 0-100
- reasoning: string (detailed analysis)`;

// ── FRED Macro Data ──

interface MacroData {
  fedFundsRate: string | null;
  yieldCurve: string | null;
  vix: string | null;
}

async function fetchMacroData(): Promise<MacroData> {
  try {
    const apiKey = process.env.FRED_API_KEY;
    if (!apiKey) return { fedFundsRate: null, yieldCurve: null, vix: null };

    const seriesIds = ['DFF', 'T10Y2Y', 'VIXCLS'];
    const results = await Promise.all(
      seriesIds.map(async (id) => {
        try {
          const url = `https://api.stlouisfed.org/fred/series/observations?series_id=${id}&limit=1&sort_order=desc&api_key=${apiKey}&file_type=json`;
          const resp = await fetch(url);
          if (!resp.ok) return null;
          const data = await resp.json();
          const obs = data?.observations?.[0] as { value: string } | undefined;
          return obs?.value !== '.' ? (obs?.value ?? null) : null;
        } catch {
          return null;
        }
      })
    );

    return {
      fedFundsRate: results[0] ?? null,
      yieldCurve: results[1] ?? null,
      vix: results[2] ?? null,
    };
  } catch {
    return { fedFundsRate: null, yieldCurve: null, vix: null };
  }
}

// ── Polygon.io Stock Data ──

async function fetchStockDataPolygon(): Promise<MarketData[]> {
  try {
    const apiKey = process.env.POLYGON_API_KEY;
    if (!apiKey) return [];

    const results = await Promise.all(
      STOCK_SYMBOLS.map(async (ticker) => {
        try {
          const url = `https://api.polygon.io/v2/aggs/ticker/${ticker}/prev?adjusted=true&apiKey=${apiKey}`;
          const resp = await fetch(url);
          if (!resp.ok) return null;
          const data = await resp.json();
          const bar = data?.results?.[0];
          if (!bar) return null;
          const prevClose = bar.c ?? 0; // prev day close is the "current" price for prev-day bars
          const open = bar.o ?? null;
          const changePct = open && open > 0 ? ((prevClose - open) / open) * 100 : null;
          return {
            symbol: ticker,
            price: prevClose,
            change_24h_pct: changePct,
            volume_24h: bar.v ?? null,
            market_cap: null,
            open: open,
            high: bar.h ?? null,
            low: bar.l ?? null,
          } as MarketData;
        } catch {
          return null;
        }
      })
    );

    return results.filter((r): r is MarketData => r !== null);
  } catch {
    return [];
  }
}

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
  return totalMinutes >= 420 && totalMinutes <= 1200;
}

/**
 * Fetch stock data: try Polygon.io first (real OHLCV), fall back to Yahoo Finance.
 */
async function fetchStockData(): Promise<MarketData[]> {
  // Try Polygon.io first (better data: real OHLCV, not delayed)
  const polygonData = await fetchStockDataPolygon();
  if (polygonData.length > 0) {
    return polygonData;
  }

  // Fallback to Yahoo Finance
  return fetchStockDataYahoo();
}

/**
 * Fetch stock quotes from Yahoo Finance v8 API (free, no key required).
 */
async function fetchStockDataYahoo(): Promise<MarketData[]> {
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

function buildMarketSnapshot(markets: MarketData[], macroData?: MacroData | null): string {
  const timestamp = new Date().toISOString();
  let snapshot = `US Stock Market Snapshot (${timestamp})\n\n`;

  // Column headers for OHLCV data if available
  const hasOhlc = markets.some(m => m.open != null || m.high != null || m.low != null);
  if (hasOhlc) {
    snapshot += `${'Symbol'.padEnd(8)} ${'Price'.padEnd(10)} ${'Change'.padEnd(9)} ${'Open'.padEnd(10)} ${'High'.padEnd(10)} ${'Low'.padEnd(10)} ${'Volume(M)'.padEnd(10)}\n`;
    snapshot += '-'.repeat(75) + '\n';
  }

  for (const m of markets) {
    if (hasOhlc) {
      const priceStr = `$${m.price.toFixed(2)}`;
      const changeStr = m.change_24h_pct !== null ? `${m.change_24h_pct >= 0 ? '+' : ''}${m.change_24h_pct.toFixed(2)}%` : 'N/A';
      const openStr = m.open != null ? `$${m.open.toFixed(2)}` : 'N/A';
      const highStr = m.high != null ? `$${m.high.toFixed(2)}` : 'N/A';
      const lowStr = m.low != null ? `$${m.low.toFixed(2)}` : 'N/A';
      const volStr = m.volume_24h != null ? `${(m.volume_24h / 1e6).toFixed(1)}` : 'N/A';
      snapshot += `${m.symbol.padEnd(8)} ${priceStr.padEnd(10)} ${changeStr.padEnd(9)} ${openStr.padEnd(10)} ${highStr.padEnd(10)} ${lowStr.padEnd(10)} ${volStr.padEnd(10)}\n`;
    } else {
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
  }

  // Macro indicators from FRED
  if (macroData && (macroData.fedFundsRate || macroData.yieldCurve || macroData.vix)) {
    snapshot += `\nMACRO INDICATORS:\n`;
    if (macroData.fedFundsRate) {
      snapshot += `Fed Funds Rate: ${macroData.fedFundsRate}%\n`;
    }
    if (macroData.yieldCurve) {
      const ycVal = parseFloat(macroData.yieldCurve);
      const ycLabel = ycVal < 0 ? 'inverted — recession signal' :
                      ycVal < 0.2 ? 'flat — caution' :
                      'normal — no recession signal';
      snapshot += `Yield Curve (10Y-2Y): ${macroData.yieldCurve}% (${ycLabel})\n`;
    }
    if (macroData.vix) {
      const vixVal = parseFloat(macroData.vix);
      const vixLabel = vixVal < 15 ? 'very low volatility — strong risk-on' :
                       vixVal < 20 ? 'low volatility — risk-on environment' :
                       vixVal < 25 ? 'moderate volatility' :
                       vixVal < 30 ? 'elevated volatility — caution' :
                       'high volatility — risk-off environment';
      snapshot += `VIX: ${macroData.vix} (${vixLabel})\n`;
    }
  }

  return snapshot;
}

function calculateNEV(analyst: AnalystDecision, inferenceCost: number): number {
  const potentialProfit = Math.abs(analyst.take_profit - analyst.entry_price);
  const potentialLoss = Math.abs(analyst.entry_price - analyst.stop_loss);
  const winProb = analyst.confidence / 100;
  return potentialProfit * winProb - potentialLoss * (1 - winProb) - inferenceCost;
}

// Daily cost cap
const DAILY_COST_CAP_USD = 10.00;

async function getDailyCostSoFar(): Promise<number> {
  const todayStart = new Date();
  todayStart.setUTCHours(0, 0, 0, 0);
  const { data } = await supabase
    .from('ai_decisions')
    .select('cost_usd')
    .gte('created_at', todayStart.toISOString());
  return (data ?? []).reduce((sum: number, d: { cost_usd: number }) => sum + (d.cost_usd ?? 0), 0);
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

    // COST CAP: Check daily spend before making any AI calls
    const dailyCost = await getDailyCostSoFar();
    if (dailyCost >= DAILY_COST_CAP_USD) {
      return res.status(200).json({
        ...result,
        errors: [`Daily cost cap reached: $${dailyCost.toFixed(4)} >= $${DAILY_COST_CAP_USD}. Skipping.`],
      });
    }

    // Load latest strategist plan
    const { data: plans } = await supabase
      .from('strategist_plans')
      .select('trader_configs, allocations, daily_target, risk_posture')
      .order('created_at', { ascending: false })
      .limit(1);
    const plan = plans?.[0] as Record<string, unknown> | undefined;
    const traderConfigs = plan?.trader_configs as Record<string, unknown> | undefined;
    const directives = traderConfigs?.stocks as {
      enabled?: boolean;
      max_position_pct?: number;
      confidence_threshold?: number;
      focus_assets?: string[];
      strategy_notes?: string;
    } | undefined;
    const safetyRails = traderConfigs?.safety_rails as {
      max_daily_drawdown_pct?: number;
      max_single_trade_pct?: number;
      max_concurrent_positions?: number;
      max_daily_inference_cost_usd?: number;
      mandatory_stop_loss?: boolean;
      max_stop_loss_pct?: number;
    } | undefined;

    // Enforce max concurrent positions from safety rails
    if (safetyRails?.max_concurrent_positions) {
      const { count: openCount } = await supabase
        .from('trades')
        .select('id', { count: 'exact', head: true })
        .eq('status', 'open');
      if ((openCount ?? 0) >= safetyRails.max_concurrent_positions) {
        return res.status(200).json({
          ...result,
          errors: ['Max concurrent positions reached. Skipping.'],
        });
      }
    }

    // Skip if strategist disabled this trader
    if (directives && directives.enabled === false) {
      return res.status(200).json({
        ...result,
        errors: ['Stocks trader disabled by strategist'],
      });
    }

    // Fetch current open positions to avoid duplicates
    const { data: openTrades } = await supabase
      .from('trades')
      .select('asset, direction, position_size_usd, entry_price')
      .eq('status', 'open')
      .eq('trader', 'stocks');
    const openPositions = openTrades ?? [];

    // 1. Fetch market data and macro data in parallel
    const [markets, macroData] = await Promise.all([
      fetchStockData(),
      fetchMacroData(),
    ]);
    if (markets.length === 0) {
      result.errors.push('No stock data returned');
      return res.status(200).json(result);
    }

    const snapshot = buildMarketSnapshot(markets, macroData);

    // 2. Build screener prompt with strategist directives
    const strategistContext = directives
      ? `\n\nSTRATEGIST DIRECTIVES:
- Risk posture: ${plan?.risk_posture ?? 'moderate'}
- Confidence threshold: ${directives.confidence_threshold ?? 70} (only flag opportunities scoring above this)
- Focus assets: ${directives.focus_assets?.join(', ') ?? 'any'}
- Strategy notes: ${directives.strategy_notes ?? 'none'}
- Daily P&L target: $${plan?.daily_target ?? 0}
- Max position size: ${directives.max_position_pct ?? 10}% of allocation per trade`
      : '';

    const openPosContext = openPositions.length > 0
      ? `\n\nCURRENT OPEN POSITIONS (DO NOT open duplicates):\n${openPositions.map((t: Record<string, unknown>) => `- ${t.asset} ${t.direction} $${t.position_size_usd} @ $${t.entry_price}`).join('\n')}`
      : '';

    const screenerSystemPrompt = SCREENER_SYSTEM_PROMPT + openPosContext + strategistContext;

    // Screen with Sonnet
    const screenerResponse = await callClaude(
      SONNET,
      screenerSystemPrompt,
      `Be very selective. Only flag strong opportunities.

Analyze this stock market data and identify trading opportunities:\n\n${snapshot}`
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

    // Filter for high confidence using strategist threshold
    const minScore = directives?.confidence_threshold ?? 70;
    const viable = opportunities.filter((o) => o.score >= minScore);
    result.opportunities_found = viable.length;

    // 3. Deep-analyze high-scoring opportunities
    const analystThreshold = directives?.confidence_threshold
      ? directives.confidence_threshold
      : 60;
    const updatedDailyCost = dailyCost + screenerResponse.cost_usd;
    for (const opp of viable) {
      // Skip analyst if cost cap would be exceeded
      if (updatedDailyCost >= DAILY_COST_CAP_USD * 0.8) {
        result.errors.push(`Near daily cap ($${updatedDailyCost.toFixed(4)}), skipping analyst for ${opp.asset}`);
        continue;
      }
      if (opp.score < analystThreshold) continue;



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
        analystResponse = await callClaude(SONNET, ANALYST_SYSTEM_PROMPT, analystPrompt, 1024);
      } catch (err) {
        result.errors.push(`Analyst call failed for ${opp.asset}: ${String(err)}`);
        continue;
      }

      // Log analyst decision
      await supabase.from('ai_decisions').insert({
        decision_type: 'analyst',
        trader: TRADER_NAME,
        model: SONNET,
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
        ai_model_used: 'sonnet',
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
