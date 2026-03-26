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

// ── Strategist logic ──

const SONNET = 'claude-sonnet-4-6';
const TRADER_NAME = 'strategist';

interface StrategistPlan {
  allocations: {
    crypto: number;
    stocks: number;
    polymarket: number;
    cash: number;
  };
  risk_posture: 'aggressive' | 'moderate' | 'conservative' | 'defensive';
  daily_pnl_target_usd: number;

  safety_rails: {
    max_daily_drawdown_pct: number;       // Pause all trading if daily losses exceed this %
    max_single_trade_pct: number;         // Max % of total capital in any single trade
    max_concurrent_positions: number;     // Max open positions across all traders
    max_daily_inference_cost_usd: number; // Max AI spend per day
    max_leverage: number;                 // Max leverage for crypto
    mandatory_stop_loss: boolean;         // Every trade must have a stop-loss
    max_stop_loss_pct: number;            // Widest allowed stop-loss
    kill_switch_drawdown_pct: number;     // Emergency stop if total drawdown exceeds this
    max_losing_streak_before_pause: number; // Pause trader after N consecutive losses
    cool_down_hours_after_pause: number;  // Hours to wait before resuming after pause
  };

  trader_directives: {
    crypto: {
      enabled: boolean;
      max_position_pct: number;
      confidence_threshold: number;
      focus_assets: string[];
      strategy_notes: string;
    };
    stocks: {
      enabled: boolean;
      max_position_pct: number;
      confidence_threshold: number;
      focus_assets: string[];
      strategy_notes: string;
    };
    polymarket: {
      enabled: boolean;
      max_position_pct: number;
      confidence_threshold: number;
      max_event_horizon_days: number;
      focus_categories: string[];
      strategy_notes: string;
    };
  };

  reasoning: string;
  goal_feasibility: 'on_track' | 'at_risk' | 'unreachable';
}

// HARD LIMITS — the AI can NEVER exceed these, no matter what
const HARD_LIMITS = {
  max_single_trade_pct: 25,          // Never >25% on one trade
  max_single_market_allocation: 60,  // Never >60% in one market
  kill_switch_drawdown_pct: 50,      // Emergency stop at 50% total drawdown
  max_daily_drawdown_pct: 15,        // Never allow >15% daily drawdown
  max_leverage: 5,                   // Never >5x leverage
  max_stop_loss_pct: 20,             // Stop-loss can't be wider than 20%
  max_concurrent_positions: 50,      // Never >50 simultaneous positions
  max_daily_inference_cost_usd: 25,  // Never spend >$25/day on AI
};

function enforceHardLimits(plan: StrategistPlan): StrategistPlan {
  const sr = plan.safety_rails;
  sr.max_single_trade_pct = Math.min(sr.max_single_trade_pct, HARD_LIMITS.max_single_trade_pct);
  sr.kill_switch_drawdown_pct = Math.min(sr.kill_switch_drawdown_pct, HARD_LIMITS.kill_switch_drawdown_pct);
  sr.max_daily_drawdown_pct = Math.min(sr.max_daily_drawdown_pct, HARD_LIMITS.max_daily_drawdown_pct);
  sr.max_leverage = Math.min(sr.max_leverage, HARD_LIMITS.max_leverage);
  sr.max_stop_loss_pct = Math.min(sr.max_stop_loss_pct, HARD_LIMITS.max_stop_loss_pct);
  sr.max_concurrent_positions = Math.min(sr.max_concurrent_positions, HARD_LIMITS.max_concurrent_positions);
  sr.max_daily_inference_cost_usd = Math.min(sr.max_daily_inference_cost_usd, HARD_LIMITS.max_daily_inference_cost_usd);

  // Enforce max market allocation
  for (const market of ['crypto', 'stocks', 'polymarket'] as const) {
    if (plan.allocations[market] > HARD_LIMITS.max_single_market_allocation) {
      plan.allocations[market] = HARD_LIMITS.max_single_market_allocation;
    }
  }

  return plan;
}

const STRATEGIST_SYSTEM_PROMPT = `You are the chief strategist AI for a goal-driven autonomous paper-trading system.

Your role is the META-BRAIN: you set the daily plan that ALL downstream traders must follow exactly. You do NOT trade yourself — you direct three trader agents (crypto, stocks, polymarket) by issuing specific directives.

THE HIERARCHY:
  Goal (dollar target + time horizon) → You (Strategist) → Trader Configs → Screener Prompts

KEY PRINCIPLES:
1. Every decision flows from the GOAL. If the goal says "turn $1,000 into $1,500 in 30 days", that implies ~1.4% daily return, which requires aggressive but not reckless positioning.
2. You must calculate feasibility. If the math is impossible (e.g. 50% daily returns needed), say so and set defensive posture.
3. Risk posture is derived from goal progress: ahead of pace → conservative, behind pace → more aggressive, far behind → assess if still feasible.
4. TIME HORIZON matters for every market:
   - Crypto: volatile, can generate returns quickly, but also large drawdowns
   - Stocks: lower volatility, more predictable, needs market hours
   - Polymarket: CRITICAL — only trade events that will RESOLVE within the goal's remaining time horizon. If you have 30 days left, do NOT bet on events resolving in 6 months.
5. For Polymarket specifically: set max_event_horizon_days to roughly match the goal's remaining days. This prevents capital from being locked in long-dated bets that cannot contribute to the goal.

6. STRATEGY NOTES ARE CRITICAL: Your strategy_notes for each trader are injected DIRECTLY into the screener's AI prompt. The screener will follow them literally. Be specific and actionable. Examples:
   - BAD: "Focus on crypto" (too vague)
   - GOOD: "BTC showing bullish momentum, look for pullback entries near $68K. ETH lagging — potential catch-up play. SOL risky but high-beta for aggressive targets. Prefer long positions in this regime."
   - GOOD: "Focus on political events resolving before April 15. US election markets have highest edge. Sell overpriced meme markets."

7. SAFETY RAILS: You must set risk limits appropriate to the goal. Conservative goals get tight rails, aggressive goals get looser rails (but never exceeding hard limits).
   - Hard limits you CANNOT exceed: max 25% per trade, max 60% per market, max 50% total drawdown, max 15% daily drawdown, max 5x leverage, max $25/day AI cost
   - Within those hard limits, YOU decide the appropriate soft limits based on the goal

Respond ONLY with a JSON object matching this exact structure:
{
  "allocations": {
    "crypto": <number 0-100>,
    "stocks": <number 0-100>,
    "polymarket": <number 0-100>,
    "cash": <number 0-100>
  },
  "risk_posture": "aggressive" | "moderate" | "conservative" | "defensive",
  "daily_pnl_target_usd": <number>,
  "safety_rails": {
    "max_daily_drawdown_pct": <number, pause trading if daily loss exceeds this %. Derive from goal: conservative=2-3%, moderate=5%, aggressive=8-10%>,
    "max_single_trade_pct": <number, max % of total capital per trade. Conservative=3-5%, moderate=8-10%, aggressive=15-20%>,
    "max_concurrent_positions": <number, how many open positions allowed. Conservative=5-8, moderate=10-15, aggressive=20-30>,
    "max_daily_inference_cost_usd": <number, AI budget per day. Scale with capital and expected profit>,
    "max_leverage": <number, 1=no leverage, up to 3 for aggressive crypto>,
    "mandatory_stop_loss": true,
    "max_stop_loss_pct": <number, widest stop-loss allowed. Conservative=3-5%, moderate=8%, aggressive=12%>,
    "kill_switch_drawdown_pct": <number, emergency stop if total portfolio drops this much from peak. Conservative=10-15%, moderate=25%, aggressive=35-40%>,
    "max_losing_streak_before_pause": <number, pause after N consecutive losses. Conservative=3, moderate=5, aggressive=8>,
    "cool_down_hours_after_pause": <number, hours to wait. Conservative=8, moderate=4, aggressive=2>
  },
  "trader_directives": {
    "crypto": {
      "enabled": <boolean>,
      "max_position_pct": <number, max % of crypto allocation in any single trade>,
      "confidence_threshold": <number 0-100, minimum screener score to send to analyst. IMPORTANT: this must be LOW ENOUGH for trades to happen. Aggressive=45-55, moderate=55-65, conservative=65-75. Do NOT set above 75 or the system will never trade.>,
      "focus_assets": [<string ticker symbols to prioritize>],
      "strategy_notes": "<specific actionable guidance for the crypto screener AI — it reads this literally>"
    },
    "stocks": {
      "enabled": <boolean>,
      "max_position_pct": <number>,
      "confidence_threshold": <number 0-100, same guidance as crypto: aggressive=45-55, moderate=55-65, conservative=65-75>,
      "focus_assets": [<string ticker symbols>],
      "strategy_notes": "<specific actionable guidance for the stocks screener AI>"
    },
    "polymarket": {
      "enabled": <boolean>,
      "max_position_pct": <number>,
      "confidence_threshold": <number 0-100, same guidance: aggressive=45-55, moderate=55-65, conservative=65-75>,
      "max_event_horizon_days": <number, only trade events resolving within this many days>,
      "focus_categories": [<string categories like "politics", "crypto", "sports">],
      "strategy_notes": "<specific actionable guidance for the polymarket screener AI>"
    }
  },
  "reasoning": "<explain your overall strategy, safety rails rationale, and how it connects to the goal>",
  "goal_feasibility": "on_track" | "at_risk" | "unreachable"
}

The allocations must sum to 100. Be specific and actionable. The safety_rails you set will be ENFORCED by the system — choose them wisely based on the goal.`;

export async function runStrategist(): Promise<{
  trader: string;
  timestamp: string;
  success: boolean;
  plan?: StrategistPlan;
  ai_cost?: number;
  errors: string[];
}> {
  const timestamp = new Date().toISOString();
  const errors: string[] = [];

  // 1. Fetch active goal
  const { data: goals } = await supabase
    .from('goals')
    .select('*')
    .eq('is_active', true)
    .order('created_at', { ascending: false })
    .limit(1);

  const currentGoal = goals?.[0] ?? null;

  // Calculate goal metrics
  let daysElapsed = 0;
  let daysRemaining = 0;
  let requiredDailyReturn = 0;
  let currentCapital = 0;
  let goalId: string | null = null;

  if (currentGoal) {
    goalId = currentGoal.id;
    const startDate = new Date(currentGoal.start_date as string);
    const now = new Date();
    daysElapsed = Math.max(0, Math.floor((now.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24)));
    daysRemaining = Math.max(0, (currentGoal.time_horizon_days as number) - daysElapsed);
  }

  // 2. Fetch latest portfolio snapshot for current capital
  const { data: snapshots } = await supabase
    .from('portfolio_snapshots')
    .select('*')
    .order('time', { ascending: false })
    .limit(1);

  const latestSnapshot = snapshots?.[0] ?? null;
  currentCapital = (latestSnapshot?.total_capital as number) ?? (currentGoal?.starting_capital as number) ?? 1000;

  if (currentGoal && daysRemaining > 0) {
    const remainingPnl = (currentGoal.target_capital as number) - currentCapital;
    requiredDailyReturn = remainingPnl / daysRemaining;
  }

  // 3. Fetch recent performance (last 7 days)
  const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();

  const { data: recentPerformance } = await supabase
    .from('daily_performance')
    .select('*')
    .gte('date', sevenDaysAgo.split('T')[0])
    .order('date', { ascending: false });

  // 4. Fetch recent trades summary
  const { data: recentTrades } = await supabase
    .from('trades')
    .select('trader, status, pnl_usd, total_cost')
    .gte('opened_at', sevenDaysAgo)
    .order('opened_at', { ascending: false })
    .limit(50);

  // Build comprehensive context for the strategist
  const userPrompt = `Today is ${new Date().toISOString().split('T')[0]}.

═══ GOAL ═══
${currentGoal
  ? `Starting Capital: $${currentGoal.starting_capital}
Target Capital: $${currentGoal.target_capital}
Time Horizon: ${currentGoal.time_horizon_days} days
Start Date: ${currentGoal.start_date}
Days Elapsed: ${daysElapsed}
Days Remaining: ${daysRemaining}
Current Capital: $${currentCapital.toFixed(2)}
Required Daily P&L to Hit Target: $${requiredDailyReturn.toFixed(2)}/day
Required Daily Return: ${currentCapital > 0 ? ((requiredDailyReturn / currentCapital) * 100).toFixed(2) : '0'}%`
  : 'No active goal set. Use moderate defaults.'}

═══ CURRENT PORTFOLIO ═══
${latestSnapshot
  ? `Total Capital: $${latestSnapshot.total_capital ?? 'N/A'}
Crypto: $${latestSnapshot.crypto_capital ?? 0}
Stocks: $${latestSnapshot.stocks_capital ?? 0}
Polymarket: $${latestSnapshot.polymarket_capital ?? 0}
Cash: $${latestSnapshot.cash ?? 0}`
  : 'No portfolio snapshot available.'}

═══ RECENT PERFORMANCE (last 7 days) ═══
${recentPerformance && recentPerformance.length > 0
  ? recentPerformance.map((p: Record<string, unknown>) =>
      `${p.date}: PnL=$${Number(p.total_pnl ?? 0).toFixed(2)} | Trades=${p.total_trades ?? 0} | Win Rate=${p.win_rate ? (Number(p.win_rate) * 100).toFixed(0) + '%' : 'N/A'} | AI Cost=$${Number(p.ai_cost ?? 0).toFixed(4)}`
    ).join('\n')
  : 'No performance data available yet.'}

═══ RECENT TRADES BY TRADER ═══
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

Based on the goal and current state, create the trading plan with per-trader directives. Remember:
- Polymarket max_event_horizon_days should be <= days_remaining (${daysRemaining} days)
- If required daily return is unrealistic (>5%), set goal_feasibility to "unreachable" and go defensive
- Be specific in strategy_notes for each trader`;

  // 5. Call Claude Sonnet (NOT Opus — cost efficiency)
  const response = await callClaude(SONNET, STRATEGIST_SYSTEM_PROMPT, userPrompt, 2048);

  // Log AI decision
  await supabase.from('ai_decisions').insert({
    decision_type: 'strategist',
    trader: TRADER_NAME,
    model: SONNET,
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
    return {
      trader: TRADER_NAME,
      timestamp,
      success: false,
      errors,
    };
  }

  // Enforce hard limits the AI cannot override
  plan = enforceHardLimits(plan);

  // Validate allocations sum to 100
  const totalAlloc =
    plan.allocations.crypto +
    plan.allocations.stocks +
    plan.allocations.polymarket +
    plan.allocations.cash;

  if (Math.abs(totalAlloc - 100) > 1) {
    errors.push(`Allocations sum to ${totalAlloc}, not 100 — normalizing`);
    const factor = 100 / totalAlloc;
    plan.allocations.crypto *= factor;
    plan.allocations.stocks *= factor;
    plan.allocations.polymarket *= factor;
    plan.allocations.cash *= factor;
  }

  // 7. Insert the strategist plan with new schema
  const { error: planError } = await supabase.from('strategist_plans').insert({
    goal_id: goalId,
    plan_date: new Date().toISOString().split('T')[0],
    allocations: plan.allocations,
    trader_configs: { ...plan.trader_directives, safety_rails: plan.safety_rails },
    daily_target: plan.daily_pnl_target_usd,
    reasoning: `[${plan.risk_posture}] [${plan.goal_feasibility}] ${plan.reasoning}`,
    goal_feasibility: plan.goal_feasibility,
    inference_cost: response.cost_usd,
    tokens_in: response.input_tokens,
    tokens_out: response.output_tokens,
  });

  if (planError) {
    errors.push(`Failed to insert strategist plan: ${planError.message}`);
  }

  // 8. Insert portfolio snapshot with allocation-based capitals
  const totalCapital = currentCapital;
  await supabase.from('portfolio_snapshots').insert({
    time: new Date().toISOString(),
    crypto_capital: (plan.allocations.crypto / 100) * totalCapital,
    stocks_capital: (plan.allocations.stocks / 100) * totalCapital,
    polymarket_capital: (plan.allocations.polymarket / 100) * totalCapital,
    cash: (plan.allocations.cash / 100) * totalCapital,
    total_capital: totalCapital,
    daily_inference_cost: response.cost_usd,
  });

  return {
    trader: TRADER_NAME,
    timestamp,
    success: true,
    plan,
    ai_cost: response.cost_usd,
    errors,
  };
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  try {
    const cronSecret = process.env.CRON_SECRET;
    if (cronSecret) {
      const authHeader = req.headers['authorization'];
      if (authHeader !== `Bearer ${cronSecret}`) {
        return res.status(401).json({ error: 'Unauthorized' });
      }
    }

    const result = await runStrategist();
    return res.status(result.success ? 200 : 500).json(result);
  } catch (err) {
    return res.status(500).json({
      trader: TRADER_NAME,
      timestamp: new Date().toISOString(),
      success: false,
      errors: [String(err)],
    });
  }
}
