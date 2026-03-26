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
  high_24h?: number | null;
  low_24h?: number | null;
  funding_rate?: string | null;
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

// ── Crypto trader logic ──

const SONNET = 'claude-sonnet-4-6';
const OPUS = 'claude-opus-4-6';
const TRADER_NAME = 'crypto';

const COIN_IDS = [
  'bitcoin', 'ethereum', 'solana', 'avalanche-2', 'binancecoin',
  'ripple', 'cardano', 'dogecoin', 'polkadot', 'chainlink',
  'avalanche-2', 'uniswap', 'litecoin', 'near', 'arbitrum',
  'render-token', 'injective-protocol', 'sui', 'aptos', 'celestia',
];
const COIN_SYMBOLS: Record<string, string> = {
  bitcoin: 'BTC', ethereum: 'ETH', solana: 'SOL', 'avalanche-2': 'AVAX',
  binancecoin: 'BNB', ripple: 'XRP', cardano: 'ADA', dogecoin: 'DOGE',
  polkadot: 'DOT', chainlink: 'LINK', uniswap: 'UNI', litecoin: 'LTC',
  near: 'NEAR', arbitrum: 'ARB', 'render-token': 'RNDR',
  'injective-protocol': 'INJ', sui: 'SUI', aptos: 'APT', celestia: 'TIA',
};

const SCREENER_SYSTEM_PROMPT_BASE = `You are a crypto market screener for an autonomous AI trading system. You receive market data and strategist directives, and identify trading opportunities.

Your behavior is driven by the STRATEGIST DIRECTIVES below. Follow them exactly — they set your risk posture, focus assets, and strategy approach.

OUTPUT FORMAT — respond ONLY with a JSON array:
[{"asset":"BTC","direction":"buy","score":75,"estimated_edge_pct":1.5,"win_probability":0.65,"rationale":"..."}]

Rules:
- score 0-100 reflects your confidence in the opportunity
- Always find at least 1-2 opportunities unless the market is completely dead
- Look for: momentum, mean reversion, relative strength, volatility
- Follow the strategist's focus_assets and strategy_notes closely`;

const ANALYST_SYSTEM_PROMPT = `You are a senior crypto trading analyst AI. You receive a trading opportunity and must decide whether to take the trade.

Respond ONLY with a JSON object:
- action: "buy" | "reject"
- size_pct: number (percentage of available capital to allocate, 1-10)
- entry_price: number (current/suggested entry price)
- stop_loss: number (stop loss price)
- take_profit: number (take profit price)
- confidence: number 0-100
- reasoning: string (detailed analysis)`;

// ── Data fetching from multiple free APIs ──

interface BinanceTicker {
  symbol: string;
  lastPrice: string;
  priceChangePercent: string;
  highPrice: string;
  lowPrice: string;
  volume: string;
  quoteVolume: string;
}

interface BinanceFunding {
  symbol: string;
  fundingRate: string;
  fundingTime: number;
}

interface FearGreedData {
  value: string;
  value_classification: string;
  timestamp: string;
}

async function fetchBinanceTickers(): Promise<Record<string, BinanceTicker>> {
  try {
    const symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'AVAXUSDT', 'BNBUSDT',
      'XRPUSDT', 'ADAUSDT', 'DOGEUSDT', 'DOTUSDT', 'LINKUSDT',
      'UNIUSDT', 'LTCUSDT', 'NEARUSDT', 'ARBUSDT', 'RNDRUSDT',
      'INJUSDT', 'SUIUSDT', 'APTUSDT', 'TIAUSDT'];
    const url = `https://api.binance.com/api/v3/ticker/24hr?symbols=${JSON.stringify(symbols)}`;
    const resp = await fetch(url);
    if (!resp.ok) return {};
    const data = await resp.json() as BinanceTicker[];
    const map: Record<string, BinanceTicker> = {};
    for (const t of data) {
      const sym = t.symbol.replace('USDT', '');
      map[sym] = t;
    }
    return map;
  } catch {
    return {};
  }
}

async function fetchBinanceFunding(): Promise<Record<string, string>> {
  try {
    const url = 'https://fapi.binance.com/fapi/v1/premiumIndex';
    const resp = await fetch(url);
    if (!resp.ok) return {};
    const data = await resp.json() as BinanceFunding[];
    const map: Record<string, string> = {};
    for (const f of data) {
      const sym = f.symbol.replace('USDT', '');
      map[sym] = f.fundingRate;
    }
    return map;
  } catch {
    return {};
  }
}

async function fetchFearGreed(): Promise<FearGreedData | null> {
  try {
    const resp = await fetch('https://api.alternative.me/fng/?limit=1');
    if (!resp.ok) return null;
    const data = await resp.json();
    return data?.data?.[0] ?? null;
  } catch {
    return null;
  }
}

async function fetchCoinGeckoOHLC(coinId: string): Promise<number[][] | null> {
  try {
    const url = `https://api.coingecko.com/api/v3/coins/${coinId}/ohlc?vs_currency=usd&days=7`;
    const resp = await fetch(url);
    if (!resp.ok) return null;
    return await resp.json();
  } catch {
    return null;
  }
}

async function fetchCryptoData(): Promise<MarketData[]> {
  // Fetch all data sources in parallel
  const [binanceTickers, fundingRates, fearGreed, cgSimple] = await Promise.all([
    fetchBinanceTickers(),
    fetchBinanceFunding(),
    fetchFearGreed(),
    // CoinGecko for market caps (Binance doesn't have this)
    fetch(`https://api.coingecko.com/api/v3/simple/price?ids=${COIN_IDS.join(',')}&vs_currencies=usd&include_market_cap=true`)
      .then(r => r.ok ? r.json() : {})
      .catch(() => ({})),
  ]);

  // Fetch 7d OHLC for top 5 coins (for trend analysis)
  const ohlcPromises = ['bitcoin', 'ethereum', 'solana'].map(async (id) => {
    const ohlc = await fetchCoinGeckoOHLC(id);
    return { id, ohlc };
  });
  const ohlcResults = await Promise.all(ohlcPromises);
  const ohlcMap: Record<string, number[][]> = {};
  for (const r of ohlcResults) {
    if (r.ohlc) ohlcMap[COIN_SYMBOLS[r.id] ?? r.id] = r.ohlc;
  }

  const markets: MarketData[] = [];
  const seen = new Set<string>();

  for (const coinId of COIN_IDS) {
    const symbol = COIN_SYMBOLS[coinId] ?? coinId.toUpperCase();
    if (seen.has(symbol)) continue;
    seen.add(symbol);

    const binance = binanceTickers[symbol];
    const cgCoin = (cgSimple as Record<string, Record<string, number>>)[coinId];

    if (!binance && !cgCoin) continue;

    const price = binance ? parseFloat(binance.lastPrice) : (cgCoin?.usd ?? 0);
    const change24h = binance ? parseFloat(binance.priceChangePercent) : null;
    const volume = binance ? parseFloat(binance.quoteVolume) : null;
    const high24h = binance ? parseFloat(binance.highPrice) : null;
    const low24h = binance ? parseFloat(binance.lowPrice) : null;
    const mcap = cgCoin?.usd_market_cap ?? null;
    const funding = fundingRates[symbol] ?? null;

    markets.push({
      symbol,
      price,
      change_24h_pct: change24h,
      volume_24h: volume,
      market_cap: mcap,
      high_24h: high24h,
      low_24h: low24h,
      funding_rate: funding,
    });
  }

  // Store fear/greed and OHLC for snapshot building
  (fetchCryptoData as unknown as Record<string, unknown>)._fearGreed = fearGreed;
  (fetchCryptoData as unknown as Record<string, unknown>)._ohlc = ohlcMap;

  return markets;
}

function buildMarketSnapshot(markets: MarketData[]): string {
  const timestamp = new Date().toISOString();
  const fearGreed = (fetchCryptoData as unknown as Record<string, unknown>)._fearGreed as FearGreedData | null;
  const ohlcMap = (fetchCryptoData as unknown as Record<string, unknown>)._ohlc as Record<string, number[][]> | null;

  let snapshot = `CRYPTO MARKET SNAPSHOT (${timestamp})\n`;

  // Market sentiment
  if (fearGreed) {
    snapshot += `\nFear & Greed Index: ${fearGreed.value}/100 (${fearGreed.value_classification})\n`;
  }

  // Price table
  snapshot += `\n${'Symbol'.padEnd(8)} ${'Price'.padEnd(12)} ${'24h%'.padEnd(9)} ${'24h High'.padEnd(12)} ${'24h Low'.padEnd(12)} ${'Volume($M)'.padEnd(12)} ${'Funding'.padEnd(10)} ${'MCap($B)'.padEnd(10)}\n`;
  snapshot += '-'.repeat(95) + '\n';

  for (const m of markets) {
    const priceStr = m.price >= 1000 ? `$${m.price.toLocaleString('en-US', { maximumFractionDigits: 0 })}` :
                     m.price >= 1 ? `$${m.price.toFixed(2)}` : `$${m.price.toFixed(4)}`;
    const changeStr = m.change_24h_pct !== null ? `${m.change_24h_pct >= 0 ? '+' : ''}${m.change_24h_pct.toFixed(2)}%` : 'N/A';
    const highStr = m.high_24h != null ? `$${m.high_24h >= 1000 ? m.high_24h.toLocaleString('en-US', { maximumFractionDigits: 0 }) : m.high_24h.toFixed(2)}` : 'N/A';
    const lowStr = m.low_24h != null ? `$${m.low_24h >= 1000 ? m.low_24h.toLocaleString('en-US', { maximumFractionDigits: 0 }) : m.low_24h.toFixed(2)}` : 'N/A';
    const volStr = m.volume_24h != null ? `${(m.volume_24h / 1e6).toFixed(1)}` : 'N/A';
    const fundingStr = m.funding_rate != null ? `${(parseFloat(m.funding_rate) * 100).toFixed(4)}%` : 'N/A';
    const mcapStr = m.market_cap != null ? `${(m.market_cap / 1e9).toFixed(1)}` : 'N/A';

    snapshot += `${m.symbol.padEnd(8)} ${priceStr.padEnd(12)} ${changeStr.padEnd(9)} ${highStr.padEnd(12)} ${lowStr.padEnd(12)} ${volStr.padEnd(12)} ${fundingStr.padEnd(10)} ${mcapStr.padEnd(10)}\n`;
  }

  // 7-day trend for top coins
  if (ohlcMap && Object.keys(ohlcMap).length > 0) {
    snapshot += `\n7-DAY PRICE TREND (daily closes):\n`;
    for (const [sym, candles] of Object.entries(ohlcMap)) {
      if (!candles || candles.length < 2) continue;
      // Get daily closes (last 7 candles at daily granularity)
      const dailyCloses = candles.filter((_, i) => i % 6 === 0).slice(-7).map(c => c[4]); // close price
      if (dailyCloses.length < 2) continue;
      const weekAgo = dailyCloses[0]!;
      const now = dailyCloses[dailyCloses.length - 1]!;
      const weekChange = ((now - weekAgo) / weekAgo * 100).toFixed(2);
      const trend = dailyCloses.map(p => `$${p >= 1000 ? Math.round(p).toLocaleString() : p.toFixed(2)}`).join(' → ');
      snapshot += `${sym}: ${trend} (7d: ${Number(weekChange) >= 0 ? '+' : ''}${weekChange}%)\n`;
    }
  }

  // Funding rate analysis
  const highFunding = markets.filter(m => m.funding_rate != null && Math.abs(parseFloat(m.funding_rate!)) > 0.0005);
  if (highFunding.length > 0) {
    snapshot += `\nNOTABLE FUNDING RATES (potential mean reversion signals):\n`;
    for (const m of highFunding) {
      const rate = parseFloat(m.funding_rate!) * 100;
      const signal = rate > 0.05 ? 'VERY BULLISH (crowded long → potential short squeeze risk)' :
                     rate > 0.01 ? 'Bullish bias' :
                     rate < -0.05 ? 'VERY BEARISH (crowded short → potential short squeeze)' :
                     rate < -0.01 ? 'Bearish bias' : 'Neutral';
      snapshot += `  ${m.symbol}: ${rate.toFixed(4)}% — ${signal}\n`;
    }
  }

  return snapshot;
}

function calculateNEV(
  analyst: AnalystDecision,
  inferencesCost: number
): number {
  const potentialProfit = Math.abs(analyst.take_profit - analyst.entry_price);
  const potentialLoss = Math.abs(analyst.entry_price - analyst.stop_loss);
  const winProb = analyst.confidence / 100;
  return potentialProfit * winProb - potentialLoss * (1 - winProb) - inferencesCost;
}

// Daily cost cap: stop AI calls if we've spent more than this today
const DAILY_COST_CAP_USD = 10.00;
// Only run analyst on very high-confidence screener results
const ANALYST_THRESHOLD_DEFAULT = 60;

async function getDailyCostSoFar(): Promise<number> {
  const todayStart = new Date();
  todayStart.setUTCHours(0, 0, 0, 0);
  const { data } = await supabase
    .from('ai_decisions')
    .select('cost_usd')
    .gte('created_at', todayStart.toISOString());
  return (data ?? []).reduce((sum: number, d: { cost_usd: number }) => sum + (d.cost_usd ?? 0), 0);
}

async function hasRecentScan(traderName: string, minutesAgo: number): Promise<boolean> {
  const since = new Date(Date.now() - minutesAgo * 60 * 1000).toISOString();
  const { data } = await supabase
    .from('ai_decisions')
    .select('id')
    .eq('trader', traderName)
    .eq('decision_type', 'screener')
    .gte('created_at', since)
    .limit(1);
  return (data ?? []).length > 0;
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
    // Verify cron auth (optional)
    const cronSecret = process.env.CRON_SECRET;
    if (cronSecret) {
      const authHeader = req.headers['authorization'];
      if (authHeader !== `Bearer ${cronSecret}`) {
        return res.status(401).json({ error: 'Unauthorized' });
      }
    }

    // COST CAP: Check daily spend before making any AI calls
    const dailyCost = await getDailyCostSoFar();
    if (dailyCost >= DAILY_COST_CAP_USD) {
      return res.status(200).json({
        ...result,
        errors: [`Daily cost cap reached: $${dailyCost.toFixed(4)} >= $${DAILY_COST_CAP_USD}. Skipping.`],
      });
    }

    // DEDUP: Skip if we already scanned in the last 10 minutes
    if (await hasRecentScan(TRADER_NAME, 10)) {
      return res.status(200).json({
        ...result,
        errors: ['Recent scan exists within 10 minutes. Skipping.'],
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
    const directives = traderConfigs?.crypto as {
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
      max_losing_streak_before_pause?: number;
    } | undefined;

    // Skip if strategist disabled this trader
    if (directives && directives.enabled === false) {
      return res.status(200).json({
        ...result,
        errors: ['Crypto trader disabled by strategist'],
      });
    }

    // Enforce max concurrent positions from safety rails
    if (safetyRails?.max_concurrent_positions) {
      const { count: openCount } = await supabase
        .from('trades')
        .select('id', { count: 'exact', head: true })
        .eq('status', 'open');
      if ((openCount ?? 0) >= safetyRails.max_concurrent_positions) {
        return res.status(200).json({
          ...result,
          errors: [`Max concurrent positions (${safetyRails.max_concurrent_positions}) reached. Skipping.`],
        });
      }
    }

    // Enforce inference cost cap from safety rails
    const inferenceCap = safetyRails?.max_daily_inference_cost_usd ?? DAILY_COST_CAP_USD;
    if (dailyCost >= inferenceCap) {
      return res.status(200).json({
        ...result,
        errors: [`Strategist inference cap ($${inferenceCap}) reached. Spent: $${dailyCost.toFixed(4)}`],
      });
    }

    // 1. Fetch market data
    let markets: MarketData[];
    try {
      markets = await fetchCryptoData();
    } catch (err) {
      result.errors.push(`CoinGecko fetch failed: ${String(err)}`);
      return res.status(200).json(result);
    }
    const snapshot = buildMarketSnapshot(markets);

    // 2. Build screener prompt with strategist directives
    const strategistContext = directives
      ? `\n\nSTRATEGIST DIRECTIVES:
- Risk posture: ${plan?.risk_posture ?? 'moderate'}
- Confidence threshold: ${directives.confidence_threshold ?? 70} (only flag opportunities scoring above this)
- Focus assets: ${directives.focus_assets?.join(', ') ?? 'any'}
- Strategy notes: ${directives.strategy_notes ?? 'none'}
- Daily P&L target: $${plan?.daily_target ?? 0}`
      : '';

    const screenerSystemPrompt = SCREENER_SYSTEM_PROMPT_BASE + strategistContext;

    const screenerResponse = await callClaude(
      SONNET,
      screenerSystemPrompt,
      `Analyze this crypto market data and find trading opportunities:\n\n${snapshot}`,
      1024
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
      input_summary: { market: 'crypto', assets: Object.keys(COIN_SYMBOLS).length, cost_today: dailyCost + screenerResponse.cost_usd },
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

    // 3. Only deep-analyze high-scoring opportunities (saves cost)
    // Use strategist's threshold if available, otherwise default
    const analystThreshold = directives?.confidence_threshold ?? ANALYST_THRESHOLD_DEFAULT;
    const updatedDailyCost = dailyCost + screenerResponse.cost_usd;
    for (const opp of viable) {
      // Skip analyst if cost cap would be exceeded
      if (updatedDailyCost >= DAILY_COST_CAP_USD * 0.8) {
        result.errors.push(`Near daily cap ($${updatedDailyCost.toFixed(4)}), skipping analyst for ${opp.asset}`);
        continue;
      }
      if (opp.score < analystThreshold) continue;

      const marketItem = markets.find((m) => m.symbol === opp.asset);
      const analystPrompt = `Trading opportunity:
${opp.asset} | ${opp.direction} | Score: ${opp.score}/100 | Edge: ${opp.estimated_edge_pct}% | WinProb: ${(opp.win_probability * 100).toFixed(0)}%
Price: $${marketItem?.price ?? '?'} | 24h: ${marketItem?.change_24h_pct?.toFixed(2) ?? '?'}%
Rationale: ${opp.rationale}
Should we trade? Provide entry, stop-loss, take-profit levels.`;

      let analystResponse;
      try {
        analystResponse = await callClaude(SONNET, ANALYST_SYSTEM_PROMPT, analystPrompt, 1024);
      } catch (err) {
        result.errors.push(`Analyst failed for ${opp.asset}: ${String(err)}`);
        continue;
      }

      await supabase.from('ai_decisions').insert({
        decision_type: 'analyst',
        trader: TRADER_NAME,
        model: SONNET,
        prompt_tokens: analystResponse.input_tokens,
        completion_tokens: analystResponse.output_tokens,
        cost_usd: analystResponse.cost_usd,
        latency_ms: analystResponse.latency_ms,
        input_summary: { asset: opp.asset, score: opp.score },
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

      // NEV check
      const totalInferenceCost = screenerResponse.cost_usd + analystResponse.cost_usd;
      const nev = calculateNEV(analyst, totalInferenceCost);
      if (nev <= 0) {
        result.errors.push(`NEV negative for ${opp.asset}: ${nev.toFixed(4)}, skip`);
        continue;
      }

      // Get current goal for position sizing
      const { data: goal } = await supabase
        .from('goals')
        .select('starting_capital')
        .eq('is_active', true)
        .limit(1)
        .maybeSingle();
      const capital = (goal?.starting_capital as number) ?? 10000;
      const posSize = (analyst.size_pct / 100) * capital;

      const { error: tradeError } = await supabase.from('trades').insert({
        trader: TRADER_NAME,
        asset: opp.asset,
        direction: opp.direction,
        position_size_usd: posSize,
        quantity: posSize / analyst.entry_price,
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
        result.errors.push(`Trade insert failed: ${tradeError.message}`);
      } else {
        result.trades_opened++;
      }
    }

    return res.status(200).json(result);
  } catch (err) {
    result.errors.push(String(err));
    return res.status(500).json(result);
  }
}
