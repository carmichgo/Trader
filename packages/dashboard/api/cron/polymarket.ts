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

interface PolymarketMarket {
  id: string;
  question: string;
  slug: string;
  outcomes: string[];
  outcomePrices: string[];
  volume: number;
  liquidity: number;
  endDate: string;
  active: boolean;
  closed: boolean;
  category?: string;
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

// ── Polymarket trader logic ──

const SONNET = 'claude-sonnet-4-20250514';
const OPUS = 'claude-opus-4-20250514';
const TRADER_NAME = 'polymarket';

const SCREENER_SYSTEM_PROMPT = `You are a prediction markets screener AI specializing in Polymarket.
Analyze the provided markets and identify mispriced events where the crowd probability seems wrong.

Respond ONLY with a JSON array. Each object must have:
- asset: string (market slug or short identifier)
- direction: "buy" | "sell" (buy = bet YES, sell = bet NO)
- score: number 0-100 (confidence in mispricing)
- estimated_edge_pct: number (estimated edge over market price)
- win_probability: number 0-1 (your estimated true probability)
- rationale: string (why you think the market is mispriced)

If no opportunities exist, return an empty array [].`;

const ANALYST_SYSTEM_PROMPT = `You are a senior prediction markets analyst AI. You receive a Polymarket opportunity and must decide whether to take the trade.

Respond ONLY with a JSON object:
- action: "buy" | "reject"
- size_pct: number (percentage of available capital, 1-10)
- entry_price: number (current market price in cents, 0-100)
- stop_loss: number (price to cut losses)
- take_profit: number (price to take profit)
- confidence: number 0-100
- reasoning: string (detailed analysis of why market is mispriced)`;

async function fetchPolymarkets(): Promise<PolymarketMarket[]> {
  const url =
    'https://gamma-api.polymarket.com/markets?closed=false&limit=20&order=volume&ascending=false';

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Polymarket API error: ${response.status}`);
  }
  const data = await response.json();

  // The API returns an array of market objects
  const markets: PolymarketMarket[] = (Array.isArray(data) ? data : []).map(
    (m: Record<string, unknown>) => ({
      id: String(m.id ?? ''),
      question: String(m.question ?? ''),
      slug: String(m.slug ?? ''),
      outcomes: Array.isArray(m.outcomes) ? (m.outcomes as string[]) : [],
      outcomePrices: Array.isArray(m.outcomePrices)
        ? (m.outcomePrices as string[])
        : typeof m.outcomePrices === 'string'
          ? JSON.parse(m.outcomePrices)
          : [],
      volume: Number(m.volume ?? 0),
      liquidity: Number(m.liquidity ?? 0),
      endDate: String(m.endDate ?? ''),
      active: Boolean(m.active),
      closed: Boolean(m.closed),
      category: m.category ? String(m.category) : undefined,
    })
  );

  return markets;
}

function buildMarketSnapshot(markets: PolymarketMarket[]): string {
  const timestamp = new Date().toISOString();
  let snapshot = `Polymarket Active Markets Snapshot (${timestamp})\n\n`;

  for (const m of markets) {
    snapshot += `Market: ${m.question}\n`;
    snapshot += `  Slug: ${m.slug}\n`;
    if (m.outcomes.length > 0 && m.outcomePrices.length > 0) {
      for (let i = 0; i < m.outcomes.length; i++) {
        const price = m.outcomePrices[i] ?? 'N/A';
        const pricePct =
          typeof price === 'string' && !isNaN(Number(price))
            ? (Number(price) * 100).toFixed(1) + '%'
            : price;
        snapshot += `  ${m.outcomes[i]}: ${pricePct}\n`;
      }
    }
    snapshot += `  Volume: $${(m.volume / 1e6).toFixed(2)}M | Liquidity: $${(m.liquidity / 1e3).toFixed(0)}K\n`;
    if (m.endDate) snapshot += `  End Date: ${m.endDate}\n`;
    snapshot += '\n';
  }
  return snapshot;
}

function calculateNEV(
  analyst: AnalystDecision,
  inferenceCost: number
): number {
  const potentialProfit = Math.abs(analyst.take_profit - analyst.entry_price);
  const potentialLoss = Math.abs(analyst.entry_price - analyst.stop_loss);
  const winProb = analyst.confidence / 100;
  return potentialProfit * winProb - potentialLoss * (1 - winProb) - inferenceCost;
}

// Daily cost cap
const DAILY_COST_CAP_USD = 1.00;

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

    // 1. Fetch Polymarket data
    const markets = await fetchPolymarkets();
    if (markets.length === 0) {
      result.errors.push('No markets returned from Polymarket API');
      return res.status(200).json(result);
    }

    const snapshot = buildMarketSnapshot(markets);

    // 2. Screen with Sonnet
    const screenerResponse = await callClaude(
      SONNET,
      SCREENER_SYSTEM_PROMPT,
      `Be very selective. Only flag strong opportunities.

Analyze these prediction markets for mispriced events:\n\n${snapshot}`
    );

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

    const viable = opportunities.filter((o) => o.score >= 70);
    result.opportunities_found = viable.length;

    // 3. Deep-analyze high-scoring opportunities with Opus
    for (const opp of viable) {
      if (opp.score < 90) continue;

      const market = markets.find(
        (m) => m.slug === opp.asset || m.question.toLowerCase().includes(opp.asset.toLowerCase())
      );

      const analystPrompt = `Polymarket opportunity identified by screener:
Asset/Market: ${opp.asset}
Direction: ${opp.direction} (${opp.direction === 'buy' ? 'YES' : 'NO'})
Screener Score: ${opp.score}/100
Estimated Edge: ${opp.estimated_edge_pct}%
Win Probability: ${(opp.win_probability * 100).toFixed(1)}%
Rationale: ${opp.rationale}

${market ? `Market Question: ${market.question}\nOutcomes: ${market.outcomes.join(', ')}\nPrices: ${market.outcomePrices.join(', ')}\nVolume: $${(market.volume / 1e6).toFixed(2)}M\nLiquidity: $${(market.liquidity / 1e3).toFixed(0)}K` : 'No additional market data available.'}

Should we take this trade? Provide entry, stop-loss, and take-profit levels (in cents, 0-100).`;

      let analystResponse;
      try {
        analystResponse = await callClaude(SONNET, ANALYST_SYSTEM_PROMPT, analystPrompt, 2048);
      } catch (err) {
        result.errors.push(`Analyst call failed for ${opp.asset}: ${String(err)}`);
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

      const { error: tradeError } = await supabase.from('trades').insert({
        trader: TRADER_NAME,
        asset: opp.asset,
        direction: opp.direction,
        position_size_usd: analyst.size_pct * 10,
        quantity: analyst.size_pct * 10 / (analyst.entry_price || 1),
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
      polymarket_capital: 500,
      total_capital: 1000,
      daily_inference_cost: screenerResponse.cost_usd,
    });

    return res.status(200).json(result);
  } catch (err) {
    result.errors.push(String(err));
    return res.status(500).json(result);
  }
}
