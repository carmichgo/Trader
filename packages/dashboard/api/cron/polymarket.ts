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

// ── News data for spotting news-driven mispricing ──

interface NewsArticle {
  source: { name: string };
  title: string;
}

async function fetchNews(): Promise<NewsArticle[]> {
  try {
    const apiKey = process.env.NEWSAPI_KEY;
    if (!apiKey) return [];
    const url = `https://newsapi.org/v2/top-headlines?category=general&pageSize=10&language=en&apiKey=${apiKey}`;
    const resp = await fetch(url);
    if (!resp.ok) return [];
    const data = await resp.json();
    return (data?.articles ?? []).slice(0, 10) as NewsArticle[];
  } catch {
    return [];
  }
}

// ── Polymarket trader logic ──

const SONNET = 'claude-sonnet-4-6';
const OPUS = 'claude-opus-4-6';
const TRADER_NAME = 'polymarket';

const SCREENER_SYSTEM_PROMPT = `You are a Polymarket prediction market screener for an autonomous AI trading system. You identify mispriced events where the crowd probability is wrong.

Your behavior is driven by the STRATEGIST DIRECTIVES below. Follow them exactly — they set which event categories to focus on and the time horizon for trades.

OUTPUT FORMAT — respond ONLY with a JSON array:
[{"asset":"market-slug","direction":"buy","score":80,"estimated_edge_pct":5.0,"win_probability":0.75,"rationale":"..."}]

Rules:
- direction "buy" = bet YES, "sell" = bet NO
- Focus on events the strategist says to focus on
- Respect max_event_horizon_days — skip events resolving after that
- Look for: probability mispricing, information asymmetry, crowd overreaction, correlated events
- Always find at least 1-2 opportunities from the provided markets`;

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
  // Use /events endpoint for high-volume, real markets (politics, sports, crypto, macro)
  // Fetch multiple pages of events to get diverse categories
  const allMarkets: PolymarketMarket[] = [];

  for (const offset of [0, 10, 20]) {
    const url = `https://gamma-api.polymarket.com/events?closed=false&limit=10&order=volume&ascending=false&offset=${offset}`;
    const response = await fetch(url);
    if (!response.ok) continue;
    const events = await response.json();

    for (const event of (Array.isArray(events) ? events : [])) {
      const eventMarkets = event.markets ?? [];
      // Take top 2 markets per event (by volume) to get variety
      const sorted = [...eventMarkets].sort((a: Record<string, unknown>, b: Record<string, unknown>) =>
        Number(b.volume ?? 0) - Number(a.volume ?? 0)
      ).slice(0, 2);

      for (const m of sorted) {
        allMarkets.push({
          id: String(m.id ?? ''),
          question: String(m.question ?? event.title ?? ''),
          slug: String(m.slug ?? ''),
          outcomes: Array.isArray(m.outcomes) ? (m.outcomes as string[]) : [],
          outcomePrices: Array.isArray(m.outcomePrices)
            ? (m.outcomePrices as string[])
            : typeof m.outcomePrices === 'string'
              ? JSON.parse(m.outcomePrices)
              : [],
          volume: Number(m.volume ?? 0),
          liquidity: Number(m.liquidity ?? 0),
          endDate: String(m.endDate ?? event.endDate ?? ''),
          active: Boolean(m.active ?? true),
          closed: Boolean(m.closed ?? false),
          category: String(event.category ?? event.title ?? '').slice(0, 50),
        });
      }
    }
  }

  // Deduplicate by id and sort by volume
  const seen = new Set<string>();
  const unique = allMarkets.filter(m => {
    if (seen.has(m.id)) return false;
    seen.add(m.id);
    return !m.closed;
  });
  unique.sort((a, b) => b.volume - a.volume);

  // Return top 30 most liquid markets across all categories
  return unique.slice(0, 30);
}

function buildMarketSnapshot(markets: PolymarketMarket[], news?: NewsArticle[]): string {
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

  // Latest news headlines for spotting news-driven mispricing
  if (news && news.length > 0) {
    snapshot += `LATEST NEWS HEADLINES:\n`;
    for (const article of news) {
      snapshot += `- [${article.source?.name ?? 'Unknown'}] ${article.title}\n`;
    }
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
    const directives = traderConfigs?.polymarket as {
      enabled?: boolean;
      max_position_pct?: number;
      confidence_threshold?: number;
      max_event_horizon_days?: number;
      focus_categories?: string[];
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
        errors: ['Polymarket trader disabled by strategist'],
      });
    }

    // Fetch current open positions to avoid duplicates
    const { data: openTrades } = await supabase
      .from('trades')
      .select('asset, direction, position_size_usd, entry_price')
      .eq('status', 'open')
      .eq('trader', 'polymarket');
    const openPositions = openTrades ?? [];

    // 1. Fetch Polymarket data and news in parallel
    const [markets, newsArticles] = await Promise.all([
      fetchPolymarkets(),
      fetchNews(),
    ]);
    if (markets.length === 0) {
      result.errors.push('No markets returned from Polymarket API');
      return res.status(200).json(result);
    }

    // Filter out markets whose endDate is beyond the strategist's max horizon
    const maxHorizonDays = directives?.max_event_horizon_days;
    let filteredMarkets = markets;
    if (maxHorizonDays && maxHorizonDays > 0) {
      const horizonCutoff = new Date(Date.now() + maxHorizonDays * 24 * 60 * 60 * 1000);
      filteredMarkets = markets.filter((m) => {
        if (!m.endDate) return false; // Skip markets with no end date
        const endDate = new Date(m.endDate);
        return endDate <= horizonCutoff;
      });
      if (filteredMarkets.length === 0) {
        result.errors.push(`No markets resolve within ${maxHorizonDays}-day horizon. Skipping.`);
        return res.status(200).json(result);
      }
    }

    const snapshot = buildMarketSnapshot(filteredMarkets, newsArticles);

    // 2. Build screener prompt with strategist directives
    const strategistContext = directives
      ? `\n\nSTRATEGIST DIRECTIVES:
- Risk posture: ${plan?.risk_posture ?? 'moderate'}
- Confidence threshold: ${directives.confidence_threshold ?? 70} (only flag opportunities scoring above this)
- Max event horizon: ${directives.max_event_horizon_days ?? 'unlimited'} days (only analyze events resolving within this timeframe)
- Focus categories: ${directives.focus_categories?.join(', ') ?? 'any'}
- Strategy notes: ${directives.strategy_notes ?? 'none'}
- Daily P&L target: $${plan?.daily_target ?? 0}
- Max position size: ${directives.max_position_pct ?? 10}% of allocation per trade`
      : '';

    const openPosContext = openPositions.length > 0
      ? `\n\nCURRENT OPEN POSITIONS (DO NOT open duplicates):\n${openPositions.map((t: Record<string, unknown>) => `- ${t.asset} ${t.direction} $${t.position_size_usd} @ $${t.entry_price}`).join('\n')}`
      : '';

    const screenerSystemPrompt = SCREENER_SYSTEM_PROMPT + openPosContext + strategistContext;

    // 2. Screen with Sonnet
    const screenerResponse = await callClaude(
      SONNET,
      screenerSystemPrompt,
      `Be very selective. Only flag strong opportunities.${maxHorizonDays ? ` Only analyze events that will resolve within ${maxHorizonDays} days.` : ''}

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
        analystResponse = await callClaude(SONNET, ANALYST_SYSTEM_PROMPT, analystPrompt, 1024);
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
