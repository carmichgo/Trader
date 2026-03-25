import { useState } from "react";
import { useTraderPortfolio } from "../hooks/usePortfolio";
import { useTrades, useTradeDetail } from "../hooks/useTrades";
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

export default function Stocks() {
  const { data: traderData, isLoading } = useTraderPortfolio("stocks", 14);
  const { data: tradesData } = useTrades({ trader: "stocks", limit: 50 });
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);
  const { data: tradeDetail } = useTradeDetail(selectedTrade?.id ?? null);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-terminal-muted animate-pulse">Loading Stocks data...</div>
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
    crypto_capital: null,
    stocks_capital: d.net_pnl,
  }));

  const dailyPnlData = dailyPerf.map((d) => ({
    date: d.date.slice(5),
    pnl: d.net_pnl,
    winRate: d.win_rate ?? 0,
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">Stocks</h2>
          <p className="text-sm text-terminal-muted">Stock positions and options flow</p>
        </div>
        <div className="flex items-center gap-4">
          <span className="badge badge-blue">{openTrades.length} open positions</span>
          {summary && (
            <span
              className={`text-sm font-bold tabular-nums ${
                summary.total_pnl >= 0 ? "text-terminal-green" : "text-terminal-red"
              }`}
            >
              {summary.total_pnl >= 0 ? "+" : ""}${summary.total_pnl.toFixed(2)}
            </span>
          )}
        </div>
      </div>

      {/* Summary + Equity Curve */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div>
          {summary && (
            <TraderCard
              trader="stocks"
              summary={summary}
              todayPerformance={dailyPerf[dailyPerf.length - 1]}
              openTradesCount={openTrades.length}
            />
          )}
          {/* Performance Stats */}
          <div className="card mt-4">
            <div className="card-header">Performance</div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-terminal-muted">Win Rate</span>
                <span className="tabular-nums">
                  {summary?.win_rate_pct.toFixed(1) ?? "0"}%
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-terminal-muted">Total Trades</span>
                <span className="tabular-nums">{summary?.total_trades ?? 0}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-terminal-muted">Wins / Losses</span>
                <span className="tabular-nums">
                  <span className="text-terminal-green">{summary?.total_wins ?? 0}</span>
                  {" / "}
                  <span className="text-terminal-red">{summary?.total_losses ?? 0}</span>
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
                name === "pnl" ? "Net P&L" : "Win Rate",
              ]}
            />
            <Bar dataKey="pnl" name="Net P&L" radius={[2, 2, 0, 0]} fill="#2979ff" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Open Positions */}
      {openTrades.length > 0 && (
        <div className="card">
          <div className="card-header">Open Positions</div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {openTrades.map((trade: Trade) => (
              <div
                key={trade.id}
                className="bg-terminal-bg border border-terminal-border rounded-lg p-3 hover:border-gray-600 transition-colors cursor-pointer"
                onClick={() => setSelectedTrade(trade)}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium text-sm">{trade.asset}</span>
                  <span
                    className={`badge ${
                      trade.direction === "buy" ? "badge-green" : "badge-red"
                    }`}
                  >
                    {trade.direction.toUpperCase()}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-terminal-muted">Size:</span>{" "}
                    <span className="tabular-nums">${trade.position_size_usd.toFixed(2)}</span>
                  </div>
                  <div>
                    <span className="text-terminal-muted">Entry:</span>{" "}
                    <span className="tabular-nums">{trade.entry_price?.toFixed(2) ?? "-"}</span>
                  </div>
                  <div>
                    <span className="text-terminal-muted">SL:</span>{" "}
                    <span className="tabular-nums text-terminal-red">
                      {trade.stop_loss?.toFixed(2) ?? "-"}
                    </span>
                  </div>
                  <div>
                    <span className="text-terminal-muted">TP:</span>{" "}
                    <span className="tabular-nums text-terminal-green">
                      {trade.take_profit?.toFixed(2) ?? "-"}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Trade Detail Panel */}
      {selectedTrade && tradeDetail && (
        <div className="card border-terminal-blue/30">
          <div className="flex items-center justify-between mb-3">
            <div className="card-header mb-0">Trade Detail</div>
            <button
              onClick={() => setSelectedTrade(null)}
              className="text-terminal-muted hover:text-gray-300 text-xs"
            >
              Close
            </button>
          </div>
          <div className="grid grid-cols-4 gap-4 text-sm mb-4">
            <div>
              <span className="text-terminal-muted text-xs">Asset:</span>
              <div className="font-medium">{tradeDetail.asset}</div>
            </div>
            <div>
              <span className="text-terminal-muted text-xs">Confidence:</span>
              <div className="font-medium tabular-nums">
                {tradeDetail.ai_confidence
                  ? `${(tradeDetail.ai_confidence * 100).toFixed(0)}%`
                  : "-"}
              </div>
            </div>
            <div>
              <span className="text-terminal-muted text-xs">Model:</span>
              <div className="font-medium text-xs">{tradeDetail.ai_model_used ?? "-"}</div>
            </div>
            <div>
              <span className="text-terminal-muted text-xs">AI Cost:</span>
              <div className="font-medium tabular-nums text-terminal-amber">
                ${tradeDetail.total_cost?.toFixed(4) ?? "-"}
              </div>
            </div>
          </div>
          {tradeDetail.ai_decisions && tradeDetail.ai_decisions.length > 0 && (
            <div>
              <div className="text-xs text-terminal-muted mb-2">AI Reasoning:</div>
              {tradeDetail.ai_decisions.map((d) => (
                <div key={d.id} className="mb-2">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="badge badge-blue">{d.decision_type}</span>
                    <span className="text-xs text-terminal-muted">{d.model}</span>
                  </div>
                  <pre className="bg-terminal-bg border border-terminal-border rounded p-2 text-xs text-gray-300 overflow-x-auto max-h-40 overflow-y-auto whitespace-pre-wrap">
                    {d.output_raw ?? d.input_summary ?? "No output"}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Trade History */}
      <div className="card">
        <div className="card-header">Trade History</div>
        <TradeTable
          trades={allTrades}
          showTrader={false}
          onSelectTrade={setSelectedTrade}
        />
      </div>
    </div>
  );
}
