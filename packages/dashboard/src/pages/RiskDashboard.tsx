import { useQuery } from "@tanstack/react-query";
import { getRiskOverview, getCorrelations } from "../lib/api";
import RiskGauge from "../components/RiskGauge";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export default function RiskDashboard() {
  const { data: riskData, isLoading } = useQuery({
    queryKey: ["risk"],
    queryFn: getRiskOverview,
    refetchInterval: 15_000,
  });

  const { data: corrData } = useQuery({
    queryKey: ["correlations"],
    queryFn: () => getCorrelations(30),
    refetchInterval: 60_000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-terminal-muted animate-pulse">Loading risk data...</div>
      </div>
    );
  }

  const drawdown = riskData?.drawdown;
  const exposure = riskData?.exposure;
  const largestPositions = riskData?.largest_positions ?? [];
  const assetCorr = corrData?.asset_correlations ?? [];
  const marketCorr = corrData?.market_correlations ?? [];

  // Drawdown history chart data
  const drawdownHistory = (drawdown?.history ?? []).map((h) => ({
    time: h.time.slice(5, 16),
    drawdown: h.drawdown_pct,
    capital: h.capital,
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold">Risk Dashboard</h2>
        <p className="text-sm text-terminal-muted">
          Exposure, correlations, and drawdown monitoring
        </p>
      </div>

      {/* Top Gauges */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <RiskGauge
          label="Current Drawdown"
          value={drawdown?.current_pct ?? 0}
          max={20}
          warnAt={5}
          dangerAt={10}
          format={(v) => `${v.toFixed(2)}%`}
        />
        <RiskGauge
          label="Total Exposure"
          value={exposure?.total_usd ?? 0}
          max={(drawdown?.total_capital ?? 1000) * 2}
          warnAt={(drawdown?.total_capital ?? 1000) * 1.2}
          dangerAt={(drawdown?.total_capital ?? 1000) * 1.6}
          format={(v) => `$${v.toFixed(0)}`}
        />
        <RiskGauge
          label="Open Positions"
          value={
            exposure?.by_trader.reduce((s, t) => s + t.open_positions, 0) ?? 0
          }
          max={30}
          warnAt={20}
          dangerAt={25}
          format={(v) => v.toFixed(0)}
        />
        <RiskGauge
          label="Avg Confidence"
          value={
            exposure?.by_trader.length
              ? exposure.by_trader.reduce((s, t) => s + t.avg_confidence, 0) /
                exposure.by_trader.length
              : 0
          }
          max={1}
          warnAt={0.3}
          dangerAt={0.2}
          format={(v) => `${(v * 100).toFixed(0)}%`}
        />
      </div>

      {/* Drawdown Chart */}
      {drawdownHistory.length > 0 && (
        <div className="card">
          <div className="card-header">Drawdown History</div>
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart data={drawdownHistory}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis
                dataKey="time"
                stroke="#6b7280"
                fontSize={10}
                tickLine={false}
              />
              <YAxis
                stroke="#6b7280"
                fontSize={10}
                tickLine={false}
                tickFormatter={(v: number) => `${v.toFixed(1)}%`}
                reversed
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#111827",
                  border: "1px solid #1f2937",
                  borderRadius: "8px",
                  fontSize: "12px",
                }}
                formatter={(value: number, name: string) => [
                  name === "drawdown"
                    ? `${value.toFixed(2)}%`
                    : `$${value.toFixed(2)}`,
                  name === "drawdown" ? "Drawdown" : "Capital",
                ]}
              />
              <Area
                type="monotone"
                dataKey="drawdown"
                stroke="#ff5252"
                fill="#ff5252"
                fillOpacity={0.15}
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Exposure by Trader + Direction */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* By Trader */}
        <div className="card">
          <div className="card-header">Exposure by Trader</div>
          <div className="space-y-3">
            {(exposure?.by_trader ?? []).map((t) => {
              const pct =
                exposure?.total_usd && exposure.total_usd > 0
                  ? (t.total_exposure_usd / exposure.total_usd) * 100
                  : 0;
              return (
                <div key={t.trader}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm capitalize">{t.trader}</span>
                    <div className="flex items-center gap-3 text-xs tabular-nums">
                      <span className="text-terminal-muted">
                        {t.open_positions} positions
                      </span>
                      <span>${t.total_exposure_usd.toFixed(2)}</span>
                    </div>
                  </div>
                  <div className="w-full h-1.5 bg-terminal-bg rounded-full overflow-hidden">
                    <div
                      className="h-full bg-terminal-blue rounded-full transition-all duration-500"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
            {(exposure?.by_trader ?? []).length === 0 && (
              <p className="text-terminal-muted text-sm text-center py-4">
                No exposure data
              </p>
            )}
          </div>
        </div>

        {/* By Direction */}
        <div className="card">
          <div className="card-header">Exposure by Direction</div>
          <div className="space-y-3">
            {(exposure?.by_direction ?? []).map((d) => {
              const pct =
                exposure?.total_usd && exposure.total_usd > 0
                  ? (d.exposure_usd / exposure.total_usd) * 100
                  : 0;
              const color =
                d.direction === "buy"
                  ? "bg-terminal-green"
                  : d.direction === "sell" || d.direction === "short"
                  ? "bg-terminal-red"
                  : "bg-terminal-blue";
              return (
                <div key={d.direction}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm uppercase">{d.direction}</span>
                    <div className="flex items-center gap-3 text-xs tabular-nums">
                      <span className="text-terminal-muted">{d.count} trades</span>
                      <span>${d.exposure_usd.toFixed(2)}</span>
                    </div>
                  </div>
                  <div className="w-full h-1.5 bg-terminal-bg rounded-full overflow-hidden">
                    <div
                      className={`h-full ${color} rounded-full transition-all duration-500`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
            {(exposure?.by_direction ?? []).length === 0 && (
              <p className="text-terminal-muted text-sm text-center py-4">
                No direction data
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Largest Positions */}
      {largestPositions.length > 0 && (
        <div className="card">
          <div className="card-header">Largest Positions</div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-terminal-muted border-b border-terminal-border">
                  <th className="pb-2 pr-4">Asset</th>
                  <th className="pb-2 pr-4">Trader</th>
                  <th className="pb-2 pr-4">Direction</th>
                  <th className="pb-2 pr-4 text-right">Size</th>
                  <th className="pb-2 pr-4 text-right">Entry</th>
                  <th className="pb-2 pr-4 text-right">Stop Loss</th>
                  <th className="pb-2 text-right">Opened</th>
                </tr>
              </thead>
              <tbody>
                {largestPositions.map((p) => (
                  <tr
                    key={p.id}
                    className="border-b border-terminal-border/50 last:border-0 hover:bg-white/[0.02]"
                  >
                    <td className="py-2 pr-4 font-medium">{p.asset}</td>
                    <td className="py-2 pr-4 capitalize text-terminal-muted">
                      {p.trader}
                    </td>
                    <td className="py-2 pr-4">
                      <span
                        className={`badge ${
                          p.direction === "buy" ? "badge-green" : "badge-red"
                        }`}
                      >
                        {p.direction.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums">
                      ${p.size_usd.toFixed(2)}
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums text-terminal-muted">
                      {p.entry_price?.toFixed(2) ?? "-"}
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums text-terminal-red">
                      {p.stop_loss?.toFixed(2) ?? "-"}
                    </td>
                    <td className="py-2 text-right text-terminal-muted text-xs">
                      {p.opened_at
                        ? new Date(p.opened_at).toLocaleDateString()
                        : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Correlations */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Market Correlations */}
        <div className="card">
          <div className="card-header">Market Correlations</div>
          {marketCorr.length > 0 ? (
            <div className="space-y-2">
              {marketCorr.map((c, i) => {
                const absCorr = Math.abs(c.correlation);
                const color =
                  absCorr > 0.7
                    ? "text-terminal-red"
                    : absCorr > 0.4
                    ? "text-terminal-amber"
                    : "text-terminal-green";
                return (
                  <div
                    key={i}
                    className="flex items-center justify-between py-1.5 border-b border-terminal-border/50 last:border-0"
                  >
                    <span className="text-sm capitalize">
                      {c.trader_a} / {c.trader_b}
                    </span>
                    <div className="flex items-center gap-3 text-xs">
                      <span className="text-terminal-muted tabular-nums">
                        {c.observations} obs
                      </span>
                      <span className={`font-bold tabular-nums ${color}`}>
                        {c.correlation.toFixed(3)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-terminal-muted text-sm text-center py-4">
              Insufficient data for market correlations
            </p>
          )}
        </div>

        {/* Asset Correlations */}
        <div className="card">
          <div className="card-header">Asset Correlations (Top Pairs)</div>
          {assetCorr.length > 0 ? (
            <div className="space-y-2 max-h-[300px] overflow-y-auto">
              {assetCorr
                .slice()
                .sort((a, b) => Math.abs(b.correlation) - Math.abs(a.correlation))
                .slice(0, 15)
                .map((c, i) => {
                  const absCorr = Math.abs(c.correlation);
                  const color =
                    absCorr > 0.7
                      ? "text-terminal-red"
                      : absCorr > 0.4
                      ? "text-terminal-amber"
                      : "text-terminal-green";
                  return (
                    <div
                      key={i}
                      className="flex items-center justify-between py-1.5 border-b border-terminal-border/50 last:border-0"
                    >
                      <span className="text-sm">
                        {c.asset_a} / {c.asset_b}
                      </span>
                      <div className="flex items-center gap-3 text-xs">
                        <span className="text-terminal-muted tabular-nums">
                          {c.observations} obs
                        </span>
                        <span className={`font-bold tabular-nums ${color}`}>
                          {c.correlation.toFixed(3)}
                        </span>
                      </div>
                    </div>
                  );
                })}
            </div>
          ) : (
            <p className="text-terminal-muted text-sm text-center py-4">
              Insufficient data for asset correlations
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
