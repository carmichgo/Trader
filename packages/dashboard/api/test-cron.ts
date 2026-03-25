import type { VercelRequest, VercelResponse } from '@vercel/node';
import { createClient } from '@supabase/supabase-js';

export default async function handler(_req: VercelRequest, res: VercelResponse) {
  const results: Record<string, unknown> = { step: 'start' };

  try {
    // Step 1: Test Supabase
    results.step = 'supabase';
    const url = process.env.STORAGE_SUPABASE_URL || process.env.VITE_SUPABASE_URL || '';
    const key = process.env.STORAGE_SUPABASE_SERVICE_ROLE_KEY || '';
    const supabase = createClient(url, key);
    const { data, error } = await supabase.from('goals').select('id').limit(1);
    results.supabase = error ? `ERROR: ${error.message}` : `OK (${data?.length} rows)`;

    // Step 2: Test CoinGecko
    results.step = 'coingecko';
    const cgResp = await fetch('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd');
    results.coingecko = await cgResp.json();

    // Step 3: Write to Supabase
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
