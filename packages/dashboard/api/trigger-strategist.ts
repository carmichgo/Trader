import type { VercelRequest, VercelResponse } from '@vercel/node';
import { runStrategist } from './cron/strategist';

/**
 * On-demand strategist trigger — called by the frontend when a goal is
 * created or updated so the strategist immediately rethinks strategy.
 */
export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const result = await runStrategist();
    return res.status(result.success ? 200 : 500).json(result);
  } catch (err) {
    return res.status(500).json({
      trader: 'strategist',
      timestamp: new Date().toISOString(),
      success: false,
      errors: [String(err)],
    });
  }
}
