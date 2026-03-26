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

const SCREENER_SYSTEM_PROMPT_BASE = `You are a crypto market screener for an autonomous AI trading system. You receive market data, open positions, and strategist directives.

You have TWO jobs:
1. FIND new trading opportunities (direction: "buy" or "sell")
2. RECOMMEND closing existing positions if conditions have changed (direction: "close")

Your behavior is driven by the STRATEGIST DIRECTIVES below. Follow them exactly.

OUTPUT FORMAT — respond ONLY with a JSON array:
[
  {"asset":"BTC","direction":"buy","score":75,"estimated_edge_pct":1.5,"win_probability":0.65,"rationale":"Momentum breakout..."},
  {"asset":"SOL","direction":"close","score":82,"estimated_edge_pct":0,"win_probability":0,"rationale":"Momentum fading, close existing long to lock in gains"}
]

Rules:
- direction "buy" or "sell" = open a NEW position
- direction "close" = close an EXISTING open position (only use for assets listed in CURRENT OPEN POSITIONS)
- score 0-100 reflects your confidence
- For close recommendations: consider whether the original thesis still holds, if stop-loss is about to be hit, or if better opportunities exist
- Always review open positions and recommend closing any that no longer make sense
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

// ── News, Macro, and DeFi data fetching ──

interface NewsArticle {
  source: { name: string };
  title: string;
}

async function fetchCryptoNews(): Promise<NewsArticle[]> {
  try {
    const apiKey = process.env.NEWSAPI_KEY;
    if (!apiKey) return [];
    const url = `https://newsapi.org/v2/everything?q=bitcoin OR ethereum OR crypto&sortBy=publishedAt&pageSize=5&apiKey=${apiKey}`;
    const resp = await fetch(url);
    if (!resp.ok) return [];
    const data = await resp.json();
    return (data?.articles ?? []).slice(0, 5) as NewsArticle[];
  } catch {
    return [];
  }
}

interface FredObservation {
  date: string;
  value: string;
}

async function fetchCryptoMacroData(): Promise<{ fedFundsRate: string | null; vix: string | null }> {
  try {
    const apiKey = process.env.FRED_API_KEY;
    if (!apiKey) return { fedFundsRate: null, vix: null };

    const seriesIds = ['DFF', 'VIXCLS'];
    const results = await Promise.all(
      seriesIds.map(async (id) => {
        try {
          const url = `https://api.stlouisfed.org/fred/series/observations?series_id=${id}&limit=1&sort_order=desc&api_key=${apiKey}&file_type=json`;
          const resp = await fetch(url);
          if (!resp.ok) return null;
          const data = await resp.json();
          const obs = data?.observations?.[0] as FredObservation | undefined;
          return obs?.value !== '.' ? (obs?.value ?? null) : null;
        } catch {
          return null;
        }
      })
    );

    return { fedFundsRate: results[0] ?? null, vix: results[1] ?? null };
  } catch {
    return { fedFundsRate: null, vix: null };
  }
}

interface DeFiProtocol {
  name: string;
  tvl: number;
}

async function fetchDeFiData(): Promise<{ totalTvl: number | null; topProtocols: DeFiProtocol[] }> {
  try {
    const resp = await fetch('https://api.llama.fi/protocols');
    if (!resp.ok) return { totalTvl: null, topProtocols: [] };
    const protocols = await resp.json() as Array<{ name: string; tvl: number }>;
    // Sort by TVL descending, take top 5
    const sorted = [...protocols].sort((a, b) => (b.tvl ?? 0) - (a.tvl ?? 0));
    const topProtocols = sorted.slice(0, 5).map(p => ({ name: p.name, tvl: p.tvl }));
    const totalTvl = sorted.reduce((sum, p) => sum + (p.tvl ?? 0), 0);
    return { totalTvl, topProtocols };
  } catch {
    return { totalTvl: null, topProtocols: [] };
  }
}

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
  const [binanceTickers, fundingRates, fearGreed, cgSimple, cryptoNews, cryptoMacro, defiData] = await Promise.all([
    fetchBinanceTickers(),
    fetchBinanceFunding(),
    fetchFearGreed(),
    // CoinGecko for market caps (Binance doesn't have this)
    fetch(`https://api.coingecko.com/api/v3/simple/price?ids=${COIN_IDS.join(',')}&vs_currencies=usd&include_market_cap=true`)
      .then(r => r.ok ? r.json() : {})
      .catch(() => ({})),
    fetchCryptoNews(),
    fetchCryptoMacroData(),
    fetchDeFiData(),
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

  // Store auxiliary data for snapshot building
  (fetchCryptoData as unknown as Record<string, unknown>)._fearGreed = fearGreed;
  (fetchCryptoData as unknown as Record<string, unknown>)._ohlc = ohlcMap;
  (fetchCryptoData as unknown as Record<string, unknown>)._news = cryptoNews;
  (fetchCryptoData as unknown as Record<string, unknown>)._macro = cryptoMacro;
  (fetchCryptoData as unknown as Record<string, unknown>)._defi = defiData;

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

  // Latest crypto news
  const news = (fetchCryptoData as unknown as Record<string, unknown>)._news as NewsArticle[] | null;
  if (news && news.length > 0) {
    snapshot += `\nLATEST CRYPTO NEWS:\n`;
    for (const article of news) {
      snapshot += `- [${article.source?.name ?? 'Unknown'}] ${article.title}\n`;
    }
  }

  // Macro indicators (Fed Funds Rate, VIX)
  const macro = (fetchCryptoData as unknown as Record<string, unknown>)._macro as { fedFundsRate: string | null; vix: string | null } | null;
  if (macro && (macro.fedFundsRate || macro.vix)) {
    snapshot += `\nMACRO INDICATORS:\n`;
    if (macro.fedFundsRate) {
      snapshot += `Fed Funds Rate: ${macro.fedFundsRate}%\n`;
    }
    if (macro.vix) {
      const vixVal = parseFloat(macro.vix);
      const vixLabel = vixVal < 15 ? 'very low volatility — strong risk-on' :
                       vixVal < 20 ? 'low volatility — risk-on environment' :
                       vixVal < 25 ? 'moderate volatility' :
                       vixVal < 30 ? 'elevated volatility — caution' :
                       'high volatility — risk-off environment';
      snapshot += `VIX: ${macro.vix} (${vixLabel})\n`;
    }
  }

  // DeFi metrics
  const defi = (fetchCryptoData as unknown as Record<string, unknown>)._defi as { totalTvl: number | null; topProtocols: DeFiProtocol[] } | null;
  if (defi && (defi.totalTvl || defi.topProtocols.length > 0)) {
    snapshot += `\nDEFI METRICS:\n`;
    if (defi.totalTvl) {
      snapshot += `Total DeFi TVL: $${(defi.totalTvl / 1e9).toFixed(1)}B\n`;
    }
    if (defi.topProtocols.length > 0) {
      const protoStr = defi.topProtocols.map(p => `${p.name} ($${(p.tvl / 1e9).toFixed(1)}B)`).join(', ');
      snapshot += `Top protocols: ${protoStr}\n`;
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
    if (await hasRecentScan(TRADER_NAME, 5)) {
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

    // Fetch current open positions to avoid duplicates
    const { data: openTrades } = await supabase
      .from('trades')
      .select('asset, direction, position_size_usd, entry_price')
      .eq('status', 'open')
      .eq('trader', TRADER_NAME);
    const openPositions = openTrades ?? [];

    // 1. Fetch market data
    let markets: MarketData[];
    try {
      markets = await fetchCryptoData();
    } catch (err) {
      result.errors.push(`CoinGecko fetch failed: ${String(err)}`);
      return res.status(200).json(result);
    }
    const snapshot = buildMarketSnapshot(markets);

    // 2. Build screener prompt with strategist directives + open positions
    const openPosContext = openPositions.length > 0
      ? `\n\nCURRENT OPEN POSITIONS (DO NOT open duplicate positions for assets you already hold):\n${openPositions.map(t => `- ${t.asset} ${t.direction} $${t.position_size_usd} @ $${t.entry_price}`).join('\n')}`
      : '\n\nNo current open positions.';

    const strategistContext = directives
      ? `\n\nSTRATEGIST DIRECTIVES:
- Risk posture: ${plan?.risk_posture ?? 'moderate'}
- Confidence threshold: ${directives.confidence_threshold ?? 70} (only flag opportunities scoring above this)
- Focus assets: ${directives.focus_assets?.join(', ') ?? 'any'}
- Strategy notes: ${directives.strategy_notes ?? 'none'}
- Daily P&L target: $${plan?.daily_target ?? 0}`
      : '';

    const screenerSystemPrompt = SCREENER_SYSTEM_PROMPT_BASE + openPosContext + strategistContext;

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

    // Separate close recommendations from new trade opportunities
    const closeRecs = opportunities.filter((o) => o.direction === 'close' && o.score >= 50);
    const newOpps = opportunities.filter((o) => o.direction !== 'close' && o.score >= 40);

    // Process close recommendations first
    for (const rec of closeRecs) {
      // Find the matching open trade
      const matchingTrade = openPositions.find(t => t.asset === rec.asset);
      if (!matchingTrade) continue;

      // Get current price for P&L calculation
      const marketItem = markets.find(m => m.symbol === rec.asset);
      const currentPrice = marketItem?.price ?? 0;
      const entryPrice = Number(matchingTrade.entry_price) || 0;
      const posSize = Number(matchingTrade.position_size_usd) || 0;
      const pnl = entryPrice > 0 ? ((currentPrice - entryPrice) / entryPrice) * posSize : 0;

      const { error: closeErr } = await supabase
        .from('trades')
        .update({
          status: 'closed',
          close_reason: 'signal_reversal',
          exit_price: currentPrice,
          gross_pnl: pnl,
          net_pnl: pnl - (Number(matchingTrade.total_cost) || 0),
          closed_at: new Date().toISOString(),
        })
        .eq('asset', rec.asset)
        .eq('trader', TRADER_NAME)
        .eq('status', 'open')
        .limit(1);

      if (!closeErr) {
        result.errors.push(`AI closed ${rec.asset}: ${rec.rationale} (P&L: $${pnl.toFixed(2)})`);
      }
    }

    const viable = newOpps;
    result.opportunities_found = viable.length;

    // Analyst threshold from strategist (default 60)
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
