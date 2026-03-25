import type { TraderPortfolioSummary, DailyPerformance } from "../lib/types";

interface Props {
  trader: string;
  summary: TraderPortfolioSummary;
  todayPerformance?: DailyPerformance;
  openTradesCount: number;
}

const TRADER_ICONS: Record<string, string> = {
  polymarket: "PM",
  crypto: "CR",
  stocks: "ST",
};

const TRADER_COLORS: Record<string, string> = {
  polymarket: "terminal-purple",
  crypto: "terminal-amber",
  stocks: "terminal-blue",
};

export default function TraderCard({
  trader,
  summary,
  todayPerformance,
  openTradesCount,
}: Props) {
  const color = TRADER_COLORS[trader] ?? "terminal-cyan";
  const todayPnl = todayPerformance?.net_pnl ?? 0;
  const tradesToday = todayPerformance?.trades_count ?? 0;

  return (
    <div className="card hover:border-gray-600 transition-colors">
      <div className="flex items-center gap-3 mb-3">
        <div
          className={`w-10 h-10 rounded-lg bg-${color}/20 border border-${color}/30 flex items-center justify-center text-${color} font-bold text-sm`}
        >
          {TRADER_ICONS[trader] ?? trader.slice(0, 2).toUpperCase()}
        </div>
        <div>
          <h3 className="font-semibold capitalize">{trader}</h3>
          <span className="text-xs text-terminal-muted">
            {openTradesCount} open position{openTradesCount !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="stat-label">Total P&L</div>
          <div
            className={`text-lg font-bold tabular-nums ${
              summary.total_pnl >= 0 ? "text-terminal-green" : "text-terminal-red"
            }`}
          >
            {summary.total_pnl >= 0 ? "+" : ""}${summary.total_pnl.toFixed(2)}
          </div>
        </div>
        <div>
          <div className="stat-label">Today</div>
          <div
            className={`text-lg font-bold tabular-nums ${
              todayPnl >= 0 ? "text-terminal-green" : "text-terminal-red"
            }`}
          >
            {todayPnl >= 0 ? "+" : ""}${todayPnl.toFixed(2)}
          </div>
        </div>
        <div>
          <div className="stat-label">Win Rate</div>
          <div className="text-sm font-semibold tabular-nums">
            {summary.win_rate_pct.toFixed(1)}%
          </div>
        </div>
        <div>
          <div className="stat-label">Trades Today</div>
          <div className="text-sm font-semibold tabular-nums">{tradesToday}</div>
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-terminal-border flex justify-between text-xs text-terminal-muted">
        <span>{summary.total_trades} total trades</span>
        <span>
          {summary.total_wins}W / {summary.total_losses}L
        </span>
      </div>
    </div>
  );
}
