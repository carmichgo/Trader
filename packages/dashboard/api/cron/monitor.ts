import type { VercelRequest, VercelResponse } from '@vercel/node';
import { supabase } from '../lib/supabase-server';

const TRADER_NAME = 'monitor';

interface OpenTrade {
  id: string;
  trader: string;
  asset: string;
  direction: string;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  position_size_usd: number;
  quantity: number;
  opened_at: string;
}

interface MonitorResult {
  trader: string;
  timestamp: string;
  open_trades_checked: number;
  trades_closed: number;
  total_pnl: number;
  errors: string[];
}

/**
 * Fetch current crypto prices from CoinGecko for a list of symbols.
 */
async function fetchCryptoPrices(symbols: string[]): Promise<Record<string, number>> {
  const symbolToCoinId: Record<string, string> = {
    BTC: 'bitcoin',
    ETH: 'ethereum',
    SOL: 'solana',
    AVAX: 'avalanche-2',
    BNB: 'binancecoin',
  };

  const coinIds = symbols
    .map((s) => symbolToCoinId[s.toUpperCase()])
    .filter(Boolean) as string[];

  if (coinIds.length === 0) return {};

  const url = `https://api.coingecko.com/api/v3/simple/price?ids=${coinIds.join(',')}&vs_currencies=usd`;
  const response = await fetch(url);
  if (!response.ok) return {};

  const data = await response.json();
  const prices: Record<string, number> = {};

  for (const symbol of symbols) {
    const coinId = symbolToCoinId[symbol.toUpperCase()];
    if (coinId && data[coinId]?.usd) {
      prices[symbol.toUpperCase()] = data[coinId].usd;
    }
  }

  return prices;
}

/**
 * Fetch current stock prices from Yahoo Finance.
 */
async function fetchStockPrices(symbols: string[]): Promise<Record<string, number>> {
  if (symbols.length === 0) return {};

  const url = `https://query1.finance.yahoo.com/v8/finance/spark?symbols=${symbols.join(',')}&range=1d&interval=1d`;
  const response = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0' },
  });

  if (!response.ok) return {};

  const data = await response.json();
  const prices: Record<string, number> = {};

  for (const result of data.spark?.result ?? []) {
    if (result?.symbol && result?.response?.[0]?.meta?.regularMarketPrice) {
      prices[result.symbol] = result.response[0].meta.regularMarketPrice;
    }
  }

  return prices;
}

/**
 * Determine if a trade's stop-loss or take-profit has been hit.
 */
function checkTradeTargets(
  trade: OpenTrade,
  currentPrice: number
): { shouldClose: boolean; reason: string; pnl: number } {
  const isLong = trade.direction === 'buy';
  let pnl: number;

  if (isLong) {
    pnl = (currentPrice - trade.entry_price) * trade.quantity;
  } else {
    // Short / sell
    pnl = (trade.entry_price - currentPrice) * trade.quantity;
  }

  // Check stop-loss
  if (isLong && currentPrice <= trade.stop_loss) {
    return { shouldClose: true, reason: 'stop_loss', pnl };
  }
  if (!isLong && currentPrice >= trade.stop_loss) {
    return { shouldClose: true, reason: 'stop_loss', pnl };
  }

  // Check take-profit
  if (isLong && currentPrice >= trade.take_profit) {
    return { shouldClose: true, reason: 'take_profit', pnl };
  }
  if (!isLong && currentPrice <= trade.take_profit) {
    return { shouldClose: true, reason: 'take_profit', pnl };
  }

  return { shouldClose: false, reason: '', pnl };
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const result: MonitorResult = {
    trader: TRADER_NAME,
    timestamp: new Date().toISOString(),
    open_trades_checked: 0,
    trades_closed: 0,
    total_pnl: 0,
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

    // 1. Fetch all open trades
    const { data: openTrades, error: fetchError } = await supabase
      .from('trades')
      .select('*')
      .eq('status', 'open');

    if (fetchError) {
      result.errors.push(`Failed to fetch open trades: ${fetchError.message}`);
      return res.status(500).json(result);
    }

    if (!openTrades || openTrades.length === 0) {
      return res.status(200).json({ ...result, message: 'No open trades to monitor' });
    }

    result.open_trades_checked = openTrades.length;

    // 2. Group trades by type to batch price fetches
    const cryptoSymbols = new Set<string>();
    const stockSymbols = new Set<string>();
    const cryptoTickers = ['BTC', 'ETH', 'SOL', 'AVAX', 'BNB'];

    for (const trade of openTrades) {
      const symbol = String(trade.asset).toUpperCase();
      if (cryptoTickers.includes(symbol)) {
        cryptoSymbols.add(symbol);
      } else if (trade.trader === 'stocks') {
        stockSymbols.add(symbol);
      }
      // Polymarket trades don't have real-time price feeds for monitoring
    }

    // 3. Fetch current prices
    const [cryptoPrices, stockPrices] = await Promise.all([
      fetchCryptoPrices(Array.from(cryptoSymbols)),
      fetchStockPrices(Array.from(stockSymbols)),
    ]);

    const allPrices: Record<string, number> = { ...cryptoPrices, ...stockPrices };

    // 4. Check each trade against stop-loss and take-profit
    let dailyPnl = 0;

    for (const trade of openTrades) {
      const symbol = String(trade.asset).toUpperCase();
      const currentPrice = allPrices[symbol];

      // Skip if no price available (e.g., Polymarket trades)
      if (currentPrice === undefined) continue;

      const typedTrade: OpenTrade = {
        id: trade.id,
        trader: trade.trader,
        asset: trade.asset,
        direction: trade.direction,
        entry_price: Number(trade.entry_price),
        stop_loss: Number(trade.stop_loss),
        take_profit: Number(trade.take_profit),
        position_size_usd: Number(trade.position_size_usd),
        quantity: Number(trade.quantity),
        opened_at: trade.opened_at,
      };

      const { shouldClose, reason, pnl } = checkTradeTargets(typedTrade, currentPrice);

      if (shouldClose) {
        // Close the trade
        const { error: updateError } = await supabase
          .from('trades')
          .update({
            status: 'closed',
            exit_price: currentPrice,
            pnl_usd: pnl,
            close_reason: reason,
            closed_at: new Date().toISOString(),
          })
          .eq('id', trade.id);

        if (updateError) {
          result.errors.push(`Failed to close trade ${trade.id}: ${updateError.message}`);
        } else {
          result.trades_closed++;
          dailyPnl += pnl;
        }
      }
    }

    result.total_pnl = dailyPnl;

    // 5. Update daily performance
    const today = new Date().toISOString().split('T')[0];

    // Fetch existing daily performance row
    const { data: existingPerf } = await supabase
      .from('daily_performance')
      .select('*')
      .eq('date', today)
      .limit(1);

    if (existingPerf && existingPerf.length > 0) {
      const existing = existingPerf[0];
      await supabase
        .from('daily_performance')
        .update({
          total_pnl: Number(existing.total_pnl ?? 0) + dailyPnl,
          trades_closed: Number(existing.trades_closed ?? 0) + result.trades_closed,
        })
        .eq('date', today);
    } else {
      await supabase.from('daily_performance').insert({
        date: today,
        total_pnl: dailyPnl,
        trades_closed: result.trades_closed,
        total_trades: openTrades.length,
      });
    }

    // 6. Insert portfolio snapshot
    const { data: latestSnapshot } = await supabase
      .from('portfolio_snapshots')
      .select('total_capital')
      .order('time', { ascending: false })
      .limit(1);

    const totalCapital = (latestSnapshot?.[0]?.total_capital ?? 1000) + dailyPnl;

    await supabase.from('portfolio_snapshots').insert({
      time: new Date().toISOString(),
      total_capital: totalCapital,
      daily_inference_cost: 0,
    });

    return res.status(200).json(result);
  } catch (err) {
    result.errors.push(String(err));
    return res.status(500).json(result);
  }
}
