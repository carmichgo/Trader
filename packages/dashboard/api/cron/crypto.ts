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
}

// ── Inlined: Claude helpers ──
const ANTHROPIC_API_URL = 'https://api.anthropic.com/v1/messages';

const MODEL_PRICING: Record<string, { input: number; output: number }> = {
  'claude-sonnet-4-20250514': { input: 3, output: 15 },
  'claude-opus-4-20250514': { input: 15, output: 75 },
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

const SONNET = 'claude-sonnet-4-20250514';
const OPUS = 'claude-opus-4-20250514';
const TRADER_NAME = 'crypto';

const COIN_IDS = ['bitcoin', 'ethereum', 'solana', 'avalanche-2', 'binancecoin'];
const COIN_SYMBOLS: Record<string, string> = {
  bitcoin: 'BTC',
  ethereum: 'ETH',
  solana: 'SOL',
  'avalanche-2': 'AVAX',
  binancecoin: 'BNB',
};

const SCREENER_SYSTEM_PROMPT_BASE = `You are a crypto market screener AI. Analyze the provided market data and identify trading opportunities.

Respond ONLY with a JSON array of opportunities. Each object must have:
- asset: string (ticker symbol)
- direction: "buy" | "sell" | "short"
- score: number 0-100 (confidence/opportunity score)
- estimated_edge_pct: number (estimated edge percentage)
- win_probability: number 0-1
- rationale: string (brief reasoning)

If no opportunities exist, return an empty array [].`;

const ANALYST_SYSTEM_PROMPT = `You are a senior crypto trading analyst AI. You receive a trading opportunity and must decide whether to take the trade.

Respond ONLY with a JSON object:
- action: "buy" | "reject"
- size_pct: number (percentage of available capital to allocate, 1-10)
- entry_price: number (current/suggested entry price)
- stop_loss: number (stop loss price)
- take_profit: number (take profit price)
- confidence: number 0-100
- reasoning: string (detailed analysis)`;

async function fetchCryptoData(): Promise<MarketData[]> {
  const ids = COIN_IDS.join(',');
  const url = `https://api.coingecko.com/api/v3/simple/price?ids=${ids}&vs_currencies=usd&include_24hr_change=true&include_24hr_vol=true&include_market_cap=true`;

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`CoinGecko API error: ${response.status}`);
  }
  const data = await response.json();

  const markets: MarketData[] = [];
  for (const coinId of COIN_IDS) {
    const coin = data[coinId];
    if (!coin) continue;
    markets.push({
      symbol: COIN_SYMBOLS[coinId] ?? coinId.toUpperCase(),
      price: coin.usd ?? 0,
      change_24h_pct: coin.usd_24h_change ?? null,
      volume_24h: coin.usd_24h_vol ?? null,
      market_cap: coin.usd_market_cap ?? null,
    });
  }
  return markets;
}

function buildMarketSnapshot(markets: MarketData[]): string {
  const timestamp = new Date().toISOString();
  let snapshot = `Crypto Market Snapshot (${timestamp})\n\n`;
  for (const m of markets) {
    snapshot += `${m.symbol}: $${m.price.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
    if (m.change_24h_pct !== null) {
      snapshot += ` | 24h Change: ${m.change_24h_pct.toFixed(2)}%`;
    }
    if (m.volume_24h !== null) {
      snapshot += ` | 24h Vol: $${(m.volume_24h / 1e6).toFixed(1)}M`;
    }
    if (m.market_cap !== null) {
      snapshot += ` | MCap: $${(m.market_cap / 1e9).toFixed(1)}B`;
    }
    snapshot += '\n';
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
const ANALYST_THRESHOLD = 85;

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
      `Analyze this market data and identify trading opportunities. Be very selective — only flag strong setups.\n\n${snapshot}`,
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
    const analystThreshold = directives?.confidence_threshold
      ? Math.max(directives.confidence_threshold, ANALYST_THRESHOLD)
      : ANALYST_THRESHOLD;
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
