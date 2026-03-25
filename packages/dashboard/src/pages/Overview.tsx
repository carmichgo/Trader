import { usePortfolio, useGoal, usePace } from "../hooks/usePortfolio";
import { useTraderPortfolio } from "../hooks/usePortfolio";
import GoalProgressChart from "../components/GoalProgressChart";
import PaceMonitor from "../components/PaceMonitor";
import KillSwitch from "../components/KillSwitch";
import PortfolioChart from "../components/PortfolioChart";
import TraderCard from "../components/TraderCard";
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

const MARKET_COLORS: Record<string, string> = {
  polymarket: "#7c4dff",
  crypto: "#ffab00",
  stocks: "#2979ff",
};

export default function Overview() {
  const { data: portfolio, isLoading: portfolioLoading } = usePortfolio(72);
  const { data: goalData } = useGoal();
  const { data: pace } = usePace();
  const { data: polyData } = useTraderPortfolio("polymarket", 7);
  const { data: cryptoData } = useTraderPortfolio("crypto", 7);
  const { data: stocksData } = useTraderPortfolio("stocks", 7);

  const current = portfolio?.current;

  // Allocation pie data
  const allocationData = current
    ? [
        { name: "Polymarket", value: current.polymarket_capital ?? 0 },
        { name: "Crypto", value: current.crypto_capital ?? 0 },
        { name: "Stocks", value: current.stocks_capital ?? 0 },
      ].filter((d) => d.value > 0)
    : [];

  function handleKillSwitch() {
    // In production, this would POST to /api/controls/kill-switch
    alert("Kill switch activated - all trading would be halted");
  }

  if (portfolioLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-terminal-muted animate-pulse">Loading portfolio...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header stats */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="card">
          <div className="stat-label">Total Capital</div>
          <div className="stat-value">
            ${current?.total_capital?.toLocaleString() ?? "0"}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Today&apos;s P&L</div>
          <div
            className={`stat-value ${
              (current?.total_realized_pnl_today ?? 0) >= 0
                ? "text-terminal-green"
                : "text-terminal-red"
            }`}
          >
            {(current?.total_realized_pnl_today ?? 0) >= 0 ? "+" : ""}$
            {(current?.total_realized_pnl_today ?? 0).toFixed(2)}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Unrealized P&L</div>
          <div
            className={`stat-value ${
              (current?.total_unrealized_pnl ?? 0) >= 0
                ? "text-terminal-green"
                : "text-terminal-red"
            }`}
          >
            {(current?.total_unrealized_pnl ?? 0) >= 0 ? "+" : ""}$
            {(current?.total_unrealized_pnl ?? 0).toFixed(2)}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Open Positions</div>
          <div className="stat-value">
            {current?.open_positions_count ?? portfolio?.open_trades_count ?? 0}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Drawdown</div>
          <div
            className={`stat-value ${
              (current?.drawdown_from_peak ?? 0) > 5
                ? "text-terminal-red"
                : (current?.drawdown_from_peak ?? 0) > 2
                ? "text-terminal-amber"
                : "text-terminal-green"
            }`}
          >
            {(current?.drawdown_from_peak ?? 0).toFixed(2)}%
          </div>
        </div>
      </div>

      {/* Goal + Pace row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <GoalProgressChart
            goal={goalData?.goal ?? null}
            progress={goalData?.progress}
            history={portfolio?.history ?? []}
          />
        </div>
        <div className="space-y-4">
          <PaceMonitor pace={pace} />
          <KillSwitch onActivate={handleKillSwitch} />
        </div>
      </div>

      {/* Equity + Allocation */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <PortfolioChart history={portfolio?.history ?? []} height={250} />
        </div>
        <div className="card">
          <div className="card-header">Market Allocation</div>
          {allocationData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={allocationData}
                  cx="50%"
                  cy="50%"
                  innerRadius={55}
                  outerRadius={80}
                  paddingAngle={3}
                  dataKey="value"
                >
                  {allocationData.map((entry) => (
                    <Cell
                      key={entry.name}
                      fill={
                        MARKET_COLORS[entry.name.toLowerCase()] ?? "#6b7280"
                      }
                    />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#111827",
                    border: "1px solid #1f2937",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                  formatter={(value: number) => [
                    `$${value.toLocaleString()}`,
                    "",
                  ]}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-[220px] text-terminal-muted text-sm">
              No allocation data
            </div>
          )}
          <div className="flex justify-center gap-4 text-xs">
            {allocationData.map((d) => (
              <div key={d.name} className="flex items-center gap-1.5">
                <div
                  className="w-2 h-2 rounded-full"
                  style={{
                    backgroundColor:
                      MARKET_COLORS[d.name.toLowerCase()] ?? "#6b7280",
                  }}
                />
                <span className="text-terminal-muted">{d.name}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Trader Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {polyData && (
          <TraderCard
            trader="polymarket"
            summary={polyData.summary}
            todayPerformance={polyData.daily_performance[polyData.daily_performance.length - 1]}
            openTradesCount={polyData.open_trades.length}
          />
        )}
        {cryptoData && (
          <TraderCard
            trader="crypto"
            summary={cryptoData.summary}
            todayPerformance={cryptoData.daily_performance[cryptoData.daily_performance.length - 1]}
            openTradesCount={cryptoData.open_trades.length}
          />
        )}
        {stocksData && (
          <TraderCard
            trader="stocks"
            summary={stocksData.summary}
            todayPerformance={stocksData.daily_performance[stocksData.daily_performance.length - 1]}
            openTradesCount={stocksData.open_trades.length}
          />
        )}
      </div>
    </div>
  );
}
