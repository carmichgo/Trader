import type { VercelRequest, VercelResponse } from '@vercel/node';
import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.STORAGE_SUPABASE_URL || process.env.VITE_SUPABASE_URL || '';
const supabaseKey = process.env.STORAGE_SUPABASE_SERVICE_ROLE_KEY || '';
const supabase = createClient(supabaseUrl, supabaseKey);

/**
 * On-demand strategist trigger — called when a goal is created/updated.
 * Calls the strategist cron internally via HTTP to avoid relative import issues.
 */
export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    // Call the strategist cron endpoint directly
    const host = req.headers.host || 'ai-trading-dashboard-kappa.vercel.app';
    const protocol = host.includes('localhost') ? 'http' : 'https';
    const url = `${protocol}://${host}/api/cron/strategist`;

    const response = await fetch(url, {
      method: 'GET',
      headers: {
        // Pass through any auth headers
        ...(process.env.CRON_SECRET ? { authorization: `Bearer ${process.env.CRON_SECRET}` } : {}),
      },
    });

    const result = await response.json();
    return res.status(response.status).json(result);
  } catch (err) {
    // Fallback: log that strategist was requested
    await supabase.from('ai_decisions').insert({
      decision_type: 'strategist',
      trader: 'strategist',
      model: 'trigger',
      prompt_tokens: 0,
      completion_tokens: 0,
      cost_usd: 0,
      latency_ms: 0,
      input_summary: { trigger: 'goal_update', error: String(err) },
      output_raw: { status: 'trigger_failed', error: String(err) },
    });

    return res.status(500).json({ success: false, error: String(err) });
  }
}
