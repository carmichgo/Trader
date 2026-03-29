import { useState } from "react";
import { useTraderPortfolio } from "../hooks/usePortfolio";
import { useTrades, useTradeDetail } from "../hooks/useTrades";
import TradeTable from "../components/TradeTable";
import type { Trade } from "../lib/types";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export default function Polymarket() {
  const { data: portfolio } = useTraderPortfolio("polymarket", 30);
  const { data: tradesData } = useTrades({
    trader: "polymarket",
    since_hours: 168,
    limit: 200,
  });
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);
  const { data: tradeDetail } = useTradeDetail(selectedTrade?.id ?? null);

  const dailyPerf = portfolio?.daily_performance ?? [];
  const chartData = dailyPerf.map((d) => ({
    date: d.date.slice(5),
    pnl: d.net_pnl,
    trades: d.trades_count,
  }));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Polymarket</h1>
          <p className="text-terminal-muted text-sm">Prediction market positions and trades</p>
        </div>
        {portfolio && (
          <div className="flex items-center gap-6">
            <div className="text-right">
              <div className="stat-label">Total P&L</div>
              <div
                className={`text-lg font-bold tabular-nums ${
                  portfolio.summary.total_pnl >= 0
                    ? "text-terminal-green"
                    : "text-terminal-red"
                }`}
              >
                {portfolio.summary.total_pnl >= 0 ? "+" : ""}$
                {portfolio.summary.total_pnl.toFixed(2)}
              </div>
            </div>
            <div className="text-right">
              <div className="stat-label">Win Rate</div>
              <div className="text-lg font-bold tabular-nums">
                {portfolio.summary.win_rate_pct.toFixed(1)}%
              </div>
            </div>
            <div className="text-right">
              <div className="stat-label">Total Trades</div>
              <div className="text-lg font-bold tabular-nums">
                {portfolio.summary.total_trades}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Open positions */}
      {portfolio && portfolio.open_trades.length > 0 && (
        <div className="card">
          <div className="card-header">Active Positions ({portfolio.open_trades.length})</div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {portfolio.open_trades.map((t) => (
              <div
                key={t.id}
                className="bg-terminal-bg border border-terminal-border rounded-lg p-3 hover:border-gray-600 transition-colors cursor-pointer"
                onClick={() => setSelectedTrade(t)}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium text-sm">{t.asset}</span>
                  <span
                    className={`badge ${
                      t.direction === "long" ? "badge-green" : "badge-red"
                    }`}
                  >
                    {t.direction.toUpperCase()}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-terminal-muted">Size:</span>{" "}
                    <span className="tabular-nums">${t.position_size_usd.toFixed(2)}</span>
                  </div>
                  <div>
                    <span className="text-terminal-muted">Entry:</span>{" "}
                    <span className="tabular-nums">{t.entry_price?.toFixed(4) ?? "-"}</span>
                  </div>
                  <div>
                    <span className="text-terminal-muted">SL:</span>{" "}
                    <span className="tabular-nums text-terminal-red">
                      {t.stop_loss?.toFixed(4) ?? "-"}
                    </span>
                  </div>
                  <div>
                    <span className="text-terminal-muted">TP:</span>{" "}
                    <span className="tabular-nums text-terminal-green">
                      {t.take_profit?.toFixed(4) ?? "-"}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Daily P&L chart */}
      {chartData.length > 0 && (
        <div className="card">
          <div className="card-header">Daily P&L</div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="date" stroke="#6b7280" fontSize={10} tickLine={false} />
              <YAxis stroke="#6b7280" fontSize={10} tickLine={false} tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#111827",
                  border: "1px solid #1f2937",
                  borderRadius: "8px",
                  fontSize: "12px",
                }}
              />
              <Bar
                dataKey="pnl"
                fill="#7c4dff"
                radius={[2, 2, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Trade detail panel */}
      {selectedTrade && tradeDetail && (
        <div className="card border-terminal-purple/30">
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

      {/* Trade history */}
      <div className="card">
        <div className="card-header">Trade History</div>
        <TradeTable
          trades={tradesData?.trades ?? []}
          showTrader={false}
          onSelectTrade={setSelectedTrade}
        />
      </div>
    </div>
  );
}
