import type { VercelRequest, VercelResponse } from '@vercel/node';

export default async function handler(_req: VercelRequest, res: VercelResponse) {
  const diagnostics: Record<string, unknown> = {
    timestamp: new Date().toISOString(),
    env_keys: Object.keys(process.env).filter(k =>
      k.includes('SUPABASE') || k.includes('ANTHROPIC') || k.includes('STORAGE')
    ),
    node_version: process.version,
  };

  // Test Supabase connection
  try {
    const { createClient } = await import('@supabase/supabase-js');
    const url = process.env.STORAGE_SUPABASE_URL || process.env.VITE_SUPABASE_URL || '';
    const key = process.env.STORAGE_SUPABASE_SERVICE_ROLE_KEY || '';
    diagnostics.supabase_url = url ? url.slice(0, 30) + '...' : 'NOT SET';
    diagnostics.service_key_set = key.length > 0;

    const sb = createClient(url, key);
    const { data, error } = await sb.from('goals').select('id').limit(1);
    diagnostics.supabase_query = error ? `ERROR: ${error.message}` : `OK (${data?.length ?? 0} rows)`;
  } catch (err) {
    diagnostics.supabase_error = String(err);
  }

  // Test Anthropic key
  diagnostics.anthropic_key_set = (process.env.ANTHROPIC_API_KEY || '').length > 0;

  // Test CoinGecko fetch
  try {
    const resp = await fetch('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd');
    const data = await resp.json();
    diagnostics.coingecko = data;
  } catch (err) {
    diagnostics.coingecko_error = String(err);
  }

  return res.status(200).json(diagnostics);
}
