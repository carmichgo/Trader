import type { VercelRequest, VercelResponse } from '@vercel/node';
import { supabase } from './lib/supabase-server';
import { callClaude } from './lib/anthropic';

export default async function handler(_req: VercelRequest, res: VercelResponse) {
  const results: Record<string, unknown> = { step: 'start' };

  try {
    // Step 1: Test Supabase
    results.step = 'supabase';
    const { data, error } = await supabase.from('goals').select('id').limit(1);
    results.supabase = error ? `ERROR: ${error.message}` : `OK (${data?.length} rows)`;

    // Step 2: Test CoinGecko
    results.step = 'coingecko';
    const cgResp = await fetch('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd');
    const cgData = await cgResp.json();
    results.coingecko = cgData;

    // Step 3: Test Anthropic (very short prompt)
    results.step = 'anthropic';
    const aiResp = await callClaude(
      'claude-sonnet-4-20250514',
      'You are a test. Respond with exactly: {"status":"ok"}',
      'Test',
      50
    );
    results.anthropic = { content: aiResp.content, cost: aiResp.cost_usd, latency: aiResp.latency_ms };

    // Step 4: Test Supabase write
    results.step = 'write';
    const { error: writeErr } = await supabase.from('portfolio_snapshots').insert({
      time: new Date().toISOString(),
      total_capital: 10000,
      polymarket_capital: 3000,
      crypto_capital: 5000,
      stocks_capital: 2000,
    });
    results.write = writeErr ? `ERROR: ${writeErr.message}` : 'OK';

    results.step = 'done';
    return res.status(200).json(results);
  } catch (err) {
    results.error = String(err);
    return res.status(500).json(results);
  }
}
