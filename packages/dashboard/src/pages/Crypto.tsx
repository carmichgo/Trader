import { useTraderPortfolio } from "../hooks/usePortfolio";
import { useTrades } from "../hooks/useTrades";
import TradeTable from "../components/TradeTable";
import TraderCard from "../components/TraderCard";
import PortfolioChart from "../components/PortfolioChart";
import type { PortfolioSnapshot, Trade } from "../lib/types";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export default function Crypto() {
  const { data: traderData, isLoading } = useTraderPortfolio("crypto", 14);
  const { data: tradesData } = useTrades({ trader: "crypto", limit: 50 });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-terminal-muted animate-pulse">Loading Crypto data...</div>
      </div>
    );
  }

  const summary = traderData?.summary;
  const dailyPerf = traderData?.daily_performance ?? [];
  const openTrades = traderData?.open_trades ?? [];
  const allTrades = tradesData?.trades ?? [];

  const history: PortfolioSnapshot[] = dailyPerf.map((d) => ({
    time: d.date,
    total_capital: d.net_pnl,
    polymarket_capital: null,
    crypto_capital: d.net_pnl,
    stocks_capital: null,
  }));

  // Daily P&L bar data
  const dailyPnlData = dailyPerf.map((d) => ({
    date: d.date.slice(5),
    pnl: d.net_pnl,
    fees: d.total_trading_fees,
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">Crypto</h2>
          <p className="text-sm text-terminal-muted">Crypto positions, charts, and funding</p>
        </div>
        <span className="badge badge-amber">{openTrades.length} open positions</span>
      </div>

      {/* Summary + Equity */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div>
          {summary && (
            <TraderCard
              trader="crypto"
              summary={summary}
              todayPerformance={dailyPerf[dailyPerf.length - 1]}
              openTradesCount={openTrades.length}
            />
          )}
          {/* Funding & Fees */}
          <div className="card mt-4">
            <div className="card-header">Costs Summary</div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-terminal-muted">Total Trading Fees</span>
                <span className="tabular-nums text-terminal-amber">
                  ${dailyPerf.reduce((s, d) => s + d.total_trading_fees, 0).toFixed(4)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-terminal-muted">Total Inference Cost</span>
                <span className="tabular-nums text-terminal-amber">
                  ${dailyPerf.reduce((s, d) => s + d.total_inference_cost, 0).toFixed(4)}
                </span>
              </div>
              <div className="flex justify-between border-t border-terminal-border pt-2">
                <span className="text-terminal-muted">Sharpe Ratio (latest)</span>
                <span className="tabular-nums">
                  {dailyPerf[dailyPerf.length - 1]?.sharpe_ratio?.toFixed(2) ?? "N/A"}
                </span>
              </div>
            </div>
          </div>
        </div>
        <div className="lg:col-span-2">
          <PortfolioChart history={history} height={300} />
        </div>
      </div>

      {/* Daily P&L Chart */}
      <div className="card">
        <div className="card-header">Daily P&L</div>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={dailyPnlData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="date" stroke="#6b7280" fontSize={10} tickLine={false} />
            <YAxis
              stroke="#6b7280"
              fontSize={10}
              tickLine={false}
              tickFormatter={(v: number) => `$${v.toFixed(0)}`}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#111827",
                border: "1px solid #1f2937",
                borderRadius: "8px",
                fontSize: "12px",
              }}
              formatter={(value: number, name: string) => [
                `$${value.toFixed(4)}`,
                name === "pnl" ? "Net P&L" : "Fees",
              ]}
            />
            <Bar
              dataKey="pnl"
              name="Net P&L"
              radius={[2, 2, 0, 0]}
              fill="#ffab00"
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Open Positions */}
      {openTrades.length > 0 && (
        <div className="card">
          <div className="card-header">Open Positions</div>
          <div className="space-y-3">
            {openTrades.map((trade: Trade) => (
              <div
                key={trade.id}
                className="flex items-center justify-between py-2 px-3 rounded-md bg-terminal-bg border border-terminal-border"
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`text-xs font-semibold ${
                      trade.direction === "buy"
                        ? "text-terminal-green"
                        : "text-terminal-red"
                    }`}
                  >
                    {trade.direction.toUpperCase()}
                  </span>
                  <span className="font-medium text-sm">{trade.asset}</span>
                </div>
                <div className="flex items-center gap-4 text-sm tabular-nums">
                  <span className="text-terminal-muted">
                    ${trade.position_size_usd.toFixed(2)}
                  </span>
                  <span className="text-terminal-muted">
                    Entry: {trade.entry_price?.toFixed(2) ?? "-"}
                  </span>
                  <span className="text-terminal-muted">
                    SL: {trade.stop_loss?.toFixed(2) ?? "-"}
                  </span>
                  <span className="text-terminal-muted">
                    TP: {trade.take_profit?.toFixed(2) ?? "-"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Trade History */}
      <div className="card">
        <div className="card-header">Trade History</div>
        <TradeTable trades={allTrades} showTrader={false} />
      </div>
    </div>
  );
}
