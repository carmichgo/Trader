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

// ── Strategist logic ──

const OPUS = 'claude-opus-4-20250514';
const TRADER_NAME = 'strategist';

interface StrategistPlan {
  allocations: {
    crypto_pct: number;
    stocks_pct: number;
    polymarket_pct: number;
    cash_pct: number;
  };
  risk_level: 'conservative' | 'moderate' | 'aggressive';
  daily_trade_limit: number;
  max_position_size_pct: number;
  focus_assets: string[];
  stop_loss_default_pct: number;
  take_profit_default_pct: number;
  reasoning: string;
}

const STRATEGIST_SYSTEM_PROMPT = `You are the chief strategist AI for an autonomous paper-trading system.
Your job is to review overall performance and set the daily trading plan including capital allocation.

The system trades across three markets: crypto, US stocks, and Polymarket prediction markets.
Total paper capital is approximately $1,000.

Respond ONLY with a JSON object:
- allocations: { crypto_pct: number, stocks_pct: number, polymarket_pct: number, cash_pct: number }
  (must sum to 100)
- risk_level: "conservative" | "moderate" | "aggressive"
- daily_trade_limit: number (max trades per day across all traders)
- max_position_size_pct: number (max % of capital in any single trade)
- focus_assets: string[] (up to 5 tickers or markets to prioritize today)
- stop_loss_default_pct: number (default stop loss percentage)
- take_profit_default_pct: number (default take profit percentage)
- reasoning: string (explain your strategy for today)`;

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const timestamp = new Date().toISOString();
  const errors: string[] = [];

  try {
    const cronSecret = process.env.CRON_SECRET;
    if (cronSecret) {
      const authHeader = req.headers['authorization'];
      if (authHeader !== `Bearer ${cronSecret}`) {
        return res.status(401).json({ error: 'Unauthorized' });
      }
    }

    // 1. Fetch current goal
    const { data: goals } = await supabase
      .from('goals')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(1);

    const currentGoal = goals?.[0] ?? null;

    // 2. Fetch recent performance (last 7 days)
    const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();

    const { data: recentPerformance } = await supabase
      .from('daily_performance')
      .select('*')
      .gte('date', sevenDaysAgo.split('T')[0])
      .order('date', { ascending: false });

    // 3. Fetch latest portfolio snapshot
    const { data: snapshots } = await supabase
      .from('portfolio_snapshots')
      .select('*')
      .order('time', { ascending: false })
      .limit(1);

    const latestSnapshot = snapshots?.[0] ?? null;

    // 4. Fetch recent trades summary
    const { data: recentTrades } = await supabase
      .from('trades')
      .select('trader, status, pnl_usd, total_cost')
      .gte('opened_at', sevenDaysAgo)
      .order('opened_at', { ascending: false })
      .limit(50);

    // Build context for the strategist
    const userPrompt = `Today is ${new Date().toISOString().split('T')[0]}.

CURRENT GOAL:
${currentGoal ? `Target: ${currentGoal.target_amount ?? 'N/A'} | Deadline: ${currentGoal.deadline ?? 'N/A'} | Description: ${currentGoal.description ?? 'N/A'}` : 'No goal set.'}

RECENT PERFORMANCE (last 7 days):
${recentPerformance && recentPerformance.length > 0
  ? recentPerformance.map((p: Record<string, unknown>) =>
      `${p.date}: PnL=$${Number(p.total_pnl ?? 0).toFixed(2)} | Trades=${p.total_trades ?? 0} | Win Rate=${p.win_rate ? (Number(p.win_rate) * 100).toFixed(0) + '%' : 'N/A'} | AI Cost=$${Number(p.ai_cost ?? 0).toFixed(4)}`
    ).join('\n')
  : 'No performance data available yet.'}

CURRENT PORTFOLIO:
${latestSnapshot
  ? `Total Capital: $${latestSnapshot.total_capital ?? 'N/A'} | Crypto: $${latestSnapshot.crypto_capital ?? 0} | Stocks: $${latestSnapshot.stocks_capital ?? 0} | Polymarket: $${latestSnapshot.polymarket_capital ?? 0} | Cash: $${latestSnapshot.cash ?? 0}`
  : 'No portfolio snapshot available.'}

RECENT TRADES SUMMARY:
${recentTrades && recentTrades.length > 0
  ? (() => {
      const byTrader: Record<string, { count: number; pnl: number; cost: number }> = {};
      for (const t of recentTrades) {
        const trader = String(t.trader);
        if (!byTrader[trader]) byTrader[trader] = { count: 0, pnl: 0, cost: 0 };
        byTrader[trader].count++;
        byTrader[trader].pnl += Number(t.pnl_usd ?? 0);
        byTrader[trader].cost += Number(t.total_cost ?? 0);
      }
      return Object.entries(byTrader)
        .map(([trader, s]) => `${trader}: ${s.count} trades, PnL=$${s.pnl.toFixed(2)}, AI Cost=$${s.cost.toFixed(4)}`)
        .join('\n');
    })()
  : 'No recent trades.'}

Based on the above data, create today's trading plan with capital allocations and strategy.`;

    // 5. Call Claude Opus
    const response = await callClaude(OPUS, STRATEGIST_SYSTEM_PROMPT, userPrompt, 4096);

    // Log AI decision
    await supabase.from('ai_decisions').insert({
      decision_type: 'strategist',
      trader: TRADER_NAME,
      model: OPUS,
      prompt_tokens: response.input_tokens,
      completion_tokens: response.output_tokens,
      cost_usd: response.cost_usd,
      latency_ms: response.latency_ms,
      input_summary: userPrompt.slice(0, 500),
      output_raw: response.content,
    });

    // 6. Parse the plan
    let plan: StrategistPlan;
    try {
      plan = extractJSON<StrategistPlan>(response.content);
    } catch {
      errors.push('Failed to parse strategist plan JSON');
      return res.status(200).json({
        trader: TRADER_NAME,
        timestamp,
        success: false,
        errors,
        raw_response: response.content.slice(0, 500),
      });
    }

    // Validate allocations sum to 100
    const totalAlloc =
      plan.allocations.crypto_pct +
      plan.allocations.stocks_pct +
      plan.allocations.polymarket_pct +
      plan.allocations.cash_pct;

    if (Math.abs(totalAlloc - 100) > 1) {
      errors.push(`Allocations sum to ${totalAlloc}, not 100 — normalizing`);
      const factor = 100 / totalAlloc;
      plan.allocations.crypto_pct *= factor;
      plan.allocations.stocks_pct *= factor;
      plan.allocations.polymarket_pct *= factor;
      plan.allocations.cash_pct *= factor;
    }

    // 7. Insert the plan
    const { error: planError } = await supabase.from('strategist_plans').insert({
      date: new Date().toISOString().split('T')[0],
      allocations: plan.allocations,
      risk_level: plan.risk_level,
      daily_trade_limit: plan.daily_trade_limit,
      max_position_size_pct: plan.max_position_size_pct,
      focus_assets: plan.focus_assets,
      stop_loss_default_pct: plan.stop_loss_default_pct,
      take_profit_default_pct: plan.take_profit_default_pct,
      reasoning: plan.reasoning,
      model: OPUS,
      cost_usd: response.cost_usd,
    });

    if (planError) {
      errors.push(`Failed to insert strategist plan: ${planError.message}`);
    }

    // 8. Insert portfolio snapshot
    const totalCapital = latestSnapshot?.total_capital ?? 1000;
    await supabase.from('portfolio_snapshots').insert({
      time: new Date().toISOString(),
      crypto_capital: (plan.allocations.crypto_pct / 100) * totalCapital,
      stocks_capital: (plan.allocations.stocks_pct / 100) * totalCapital,
      polymarket_capital: (plan.allocations.polymarket_pct / 100) * totalCapital,
      cash: (plan.allocations.cash_pct / 100) * totalCapital,
      total_capital: totalCapital,
      daily_inference_cost: response.cost_usd,
    });

    return res.status(200).json({
      trader: TRADER_NAME,
      timestamp,
      success: true,
      plan,
      ai_cost: response.cost_usd,
      errors,
    });
  } catch (err) {
    errors.push(String(err));
    return res.status(500).json({
      trader: TRADER_NAME,
      timestamp,
      success: false,
      errors,
    });
  }
}
