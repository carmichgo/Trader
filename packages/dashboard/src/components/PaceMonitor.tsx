import type { PaceStatus } from "../lib/types";

interface Props {
  pace: PaceStatus | undefined;
}

const STATUS_CONFIG: Record<
  string,
  { label: string; color: string; bg: string }
> = {
  well_ahead: {
    label: "WELL AHEAD",
    color: "text-terminal-green",
    bg: "bg-green-900/20 border-green-800/50",
  },
  on_track: {
    label: "ON TRACK",
    color: "text-terminal-green",
    bg: "bg-green-900/20 border-green-800/50",
  },
  behind: {
    label: "BEHIND",
    color: "text-terminal-amber",
    bg: "bg-amber-900/20 border-amber-800/50",
  },
  far_behind: {
    label: "FAR BEHIND",
    color: "text-terminal-red",
    bg: "bg-red-900/20 border-red-800/50",
  },
  no_target: {
    label: "NO TARGET",
    color: "text-terminal-muted",
    bg: "bg-gray-900/20 border-gray-800/50",
  },
};

export default function PaceMonitor({ pace }: Props) {
  if (!pace) {
    return (
      <div className="card">
        <div className="card-header">Daily Pace</div>
        <p className="text-terminal-muted text-sm text-center py-4">Loading...</p>
      </div>
    );
  }

  const cfg = STATUS_CONFIG[pace.status] ?? STATUS_CONFIG.no_target!;
  const progressWidth = Math.min(Math.max(pace.progress_pct, 0), 100);
  const timeWidth = Math.min(Math.max(pace.time_elapsed_pct, 0), 100);

  return (
    <div className="card">
      <div className="card-header flex items-center justify-between">
        <span>Daily Pace</span>
        <span className={`badge ${cfg.bg} ${cfg.color} border`}>
          {cfg.label}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-4">
        <div>
          <div className="stat-label">P&L Today</div>
          <div
            className={`text-lg font-bold tabular-nums ${
              pace.pnl_today >= 0 ? "text-terminal-green" : "text-terminal-red"
            }`}
          >
            {pace.pnl_today >= 0 ? "+" : ""}${pace.pnl_today.toFixed(2)}
          </div>
        </div>
        <div>
          <div className="stat-label">Target</div>
          <div className="text-lg font-bold tabular-nums text-terminal-blue">
            ${pace.daily_target_usd.toFixed(2)}
          </div>
        </div>
        <div>
          <div className="stat-label">Trades</div>
          <div className="text-lg font-bold tabular-nums">{pace.trades_today}</div>
        </div>
      </div>

      {/* Progress bar */}
      <div className="space-y-2">
        <div>
          <div className="flex justify-between text-xs text-terminal-muted mb-1">
            <span>P&L Progress</span>
            <span className="tabular-nums">{pace.progress_pct.toFixed(1)}%</span>
          </div>
          <div className="w-full h-1.5 bg-terminal-bg rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                pace.pnl_today >= 0 ? "bg-terminal-green" : "bg-terminal-red"
              }`}
              style={{ width: `${progressWidth}%` }}
            />
          </div>
        </div>
        <div>
          <div className="flex justify-between text-xs text-terminal-muted mb-1">
            <span>Time Elapsed</span>
            <span className="tabular-nums">{pace.time_elapsed_pct.toFixed(1)}%</span>
          </div>
          <div className="w-full h-1.5 bg-terminal-bg rounded-full overflow-hidden">
            <div
              className="h-full bg-terminal-blue/60 rounded-full transition-all duration-500"
              style={{ width: `${timeWidth}%` }}
            />
          </div>
        </div>
      </div>

      {/* Per-trader breakdown */}
      {pace.by_trader.length > 0 && (
        <div className="mt-4 pt-3 border-t border-terminal-border">
          <div className="text-xs text-terminal-muted mb-2">By Trader</div>
          <div className="space-y-1">
            {pace.by_trader.map((t) => (
              <div
                key={t.trader}
                className="flex items-center justify-between text-xs"
              >
                <span className="capitalize">{t.trader}</span>
                <div className="flex items-center gap-3">
                  <span className="text-terminal-muted tabular-nums">
                    {t.trades_count}T | {t.winning_trades}W
                  </span>
                  <span
                    className={`tabular-nums font-semibold ${
                      t.net_pnl >= 0 ? "text-terminal-green" : "text-terminal-red"
                    }`}
                  >
                    {t.net_pnl >= 0 ? "+" : ""}${t.net_pnl.toFixed(2)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
