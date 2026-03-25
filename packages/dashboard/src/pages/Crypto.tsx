import { useState } from "react";
import { useTraderPortfolio } from "../hooks/usePortfolio";
import { useTrades, useTradeDetail } from "../hooks/useTrades";
import TradeTable from "../components/TradeTable";
import type { Trade } from "../lib/types";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export default function Crypto() {
  const { data: portfolio } = useTraderPortfolio("crypto", 30);
  const { data: tradesData } = useTrades({
    trader: "crypto",
    since_hours: 168,
    limit: 200,
  });
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);
  const { data: tradeDetail } = useTradeDetail(selectedTrade?.id ?? null);

  const dailyPerf = portfolio?.daily_performance ?? [];
  const cumPnl = dailyPerf.reduce<{ date: string; cumulative: number }[]>(
    (acc, d) => {
      const prev = acc.length > 0 ? acc[acc.length - 1]!.cumulative : 0;
      acc.push({ date: d.date.slice(5), cumulative: prev + d.net_pnl });
      return acc;
    },
    []
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Crypto Trading</h1>
          <p className="text-terminal-muted text-sm">
            Cryptocurrency positions, funding rates, and trades
          </p>
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
          </div>
        )}
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card">
          <div className="stat-label">Open Positions</div>
          <div className="stat-value">{portfolio?.open_trades.length ?? 0}</div>
        </div>
        <div className="card">
          <div className="stat-label">Total Trades</div>
          <div className="stat-value">{portfolio?.summary.total_trades ?? 0}</div>
        </div>
        <div className="card">
          <div className="stat-label">Win / Loss</div>
          <div className="stat-value text-lg">
            <span className="text-terminal-green">{portfolio?.summary.total_wins ?? 0}</span>
            <span className="text-terminal-muted mx-1">/</span>
            <span className="text-terminal-red">{portfolio?.summary.total_losses ?? 0}</span>
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Today Inference Cost</div>
          <div className="stat-value text-lg text-terminal-amber">
            ${dailyPerf.length > 0
              ? dailyPerf[dailyPerf.length - 1]!.total_inference_cost.toFixed(4)
              : "0.00"}
          </div>
        </div>
      </div>

      {/* Open positions */}
      {portfolio && portfolio.open_trades.length > 0 && (
        <div className="card">
          <div className="card-header">
            Open Positions ({portfolio.open_trades.length})
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-terminal-muted text-xs uppercase tracking-wider border-b border-terminal-border">
                  <th className="text-left py-2 px-2">Asset</th>
                  <th className="text-left py-2 px-2">Direction</th>
                  <th className="text-right py-2 px-2">Size</th>
                  <th className="text-right py-2 px-2">Entry</th>
                  <th className="text-right py-2 px-2">Stop Loss</th>
                  <th className="text-right py-2 px-2">Take Profit</th>
                  <th className="text-right py-2 px-2">Opened</th>
                </tr>
              </thead>
              <tbody>
                {portfolio.open_trades.map((t) => (
                  <tr
                    key={t.id}
                    className="table-row cursor-pointer"
                    onClick={() => setSelectedTrade(t)}
                  >
                    <td className="py-2 px-2 font-medium">{t.asset}</td>
                    <td className="py-2 px-2">
                      <span
                        className={`text-xs font-semibold ${
                          t.direction === "long"
                            ? "text-terminal-green"
                            : "text-terminal-red"
                        }`}
                      >
                        {t.direction.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums">
                      ${t.position_size_usd.toFixed(2)}
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums text-xs">
                      {t.entry_price?.toFixed(2) ?? "-"}
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums text-xs text-terminal-red">
                      {t.stop_loss?.toFixed(2) ?? "-"}
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums text-xs text-terminal-green">
                      {t.take_profit?.toFixed(2) ?? "-"}
                    </td>
                    <td className="py-2 px-2 text-right text-xs text-terminal-muted">
                      {t.opened_at
                        ? new Date(t.opened_at).toLocaleDateString()
                        : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Cumulative P&L chart */}
      {cumPnl.length > 0 && (
        <div className="card">
          <div className="card-header">Cumulative P&L</div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={cumPnl}>
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
                formatter={(value: number) => [`$${value.toFixed(2)}`, "Cumulative P&L"]}
              />
              <Line
                type="monotone"
                dataKey="cumulative"
                stroke="#ffab00"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Trade detail */}
      {selectedTrade && tradeDetail && (
        <div className="card border-terminal-amber/30">
          <div className="flex items-center justify-between mb-3">
            <div className="card-header mb-0">Trade Detail: {tradeDetail.asset}</div>
            <button
              onClick={() => setSelectedTrade(null)}
              className="text-terminal-muted hover:text-gray-300 text-xs"
            >
              Close
            </button>
          </div>
          <div className="grid grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-terminal-muted text-xs">Direction:</span>
              <div className="font-medium capitalize">{tradeDetail.direction}</div>
            </div>
            <div>
              <span className="text-terminal-muted text-xs">P&L:</span>
              <div
                className={`font-bold tabular-nums ${
                  (tradeDetail.net_pnl ?? 0) >= 0
                    ? "text-terminal-green"
                    : "text-terminal-red"
                }`}
              >
                ${tradeDetail.net_pnl?.toFixed(2) ?? "-"}
              </div>
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
          </div>
          {tradeDetail.analyst_output && (
            <div className="mt-3">
              <div className="text-xs text-terminal-muted mb-1">Analyst Output:</div>
              <pre className="bg-terminal-bg border border-terminal-border rounded p-2 text-xs text-gray-300 overflow-x-auto max-h-40 overflow-y-auto whitespace-pre-wrap">
                {tradeDetail.analyst_output}
              </pre>
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
