import {
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Area,
  ComposedChart,
} from "recharts";
import type { Goal, GoalProgress, PortfolioSnapshot } from "../lib/types";

interface Props {
  goal: Goal | null;
  progress: GoalProgress | undefined;
  history: PortfolioSnapshot[];
}

export default function GoalProgressChart({ goal, progress, history }: Props) {
  if (!goal || !progress) {
    return (
      <div className="card h-72 flex items-center justify-center">
        <p className="text-terminal-muted">No goal configured</p>
      </div>
    );
  }

  // Build compound growth curve data
  const totalDays = goal.time_horizon_days;
  const dailyRate = Math.pow(goal.target_capital / goal.starting_capital, 1 / totalDays) - 1;

  const chartData: {
    day: number;
    date: string;
    target: number;
    actual: number | null;
  }[] = [];

  for (let d = 0; d <= totalDays; d++) {
    const targetValue = goal.starting_capital * Math.pow(1 + dailyRate, d);
    chartData.push({
      day: d,
      date: `D${d}`,
      target: Math.round(targetValue * 100) / 100,
      actual: null,
    });
  }

  // Overlay actual equity from history
  const daysElapsed = progress.days_elapsed;
  history.forEach((snap, i) => {
    const dayIndex = Math.min(Math.round((i / Math.max(history.length - 1, 1)) * daysElapsed), totalDays);
    const entry = chartData[dayIndex];
    if (entry) {
      entry.actual = snap.total_capital;
    }
  });

  // If we have current capital, set it at the current day
  if (daysElapsed <= totalDays && chartData[daysElapsed]) {
    chartData[daysElapsed]!.actual = progress.current_capital;
  }

  const isAhead = progress.current_capital >= (chartData[daysElapsed]?.target ?? 0);

  return (
    <div className="card">
      <div className="card-header flex items-center justify-between">
        <span>Goal Progress</span>
        <span className={isAhead ? "text-terminal-green" : "text-terminal-amber"}>
          {progress.progress_pct.toFixed(1)}% complete
        </span>
      </div>
      <div className="flex items-baseline gap-4 mb-4">
        <div>
          <span className="stat-value text-xl">
            ${progress.current_capital.toLocaleString()}
          </span>
          <span className="text-terminal-muted text-xs ml-2">
            / ${goal.target_capital.toLocaleString()}
          </span>
        </div>
        <div className="text-xs text-terminal-muted">
          {progress.days_remaining}d remaining | {progress.required_daily_return_pct.toFixed(2)}%/day needed
        </div>
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={chartData.filter((_, i) => i % Math.max(1, Math.floor(totalDays / 60)) === 0 || i === totalDays)}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis
            dataKey="date"
            stroke="#6b7280"
            fontSize={10}
            tickLine={false}
          />
          <YAxis
            stroke="#6b7280"
            fontSize={10}
            tickLine={false}
            tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#111827",
              border: "1px solid #1f2937",
              borderRadius: "8px",
              fontSize: "12px",
            }}
            formatter={(value: number) => [`$${value.toLocaleString()}`, ""]}
          />
          <Area
            type="monotone"
            dataKey="target"
            stroke="none"
            fill="#2979ff"
            fillOpacity={0.05}
          />
          <Line
            type="monotone"
            dataKey="target"
            stroke="#2979ff"
            strokeWidth={1.5}
            strokeDasharray="6 3"
            dot={false}
            name="Target"
          />
          <Line
            type="monotone"
            dataKey="actual"
            stroke="#00e676"
            strokeWidth={2}
            dot={false}
            connectNulls
            name="Actual"
          />
          <ReferenceLine
            y={goal.target_capital}
            stroke="#ffab00"
            strokeDasharray="3 3"
            label={{ value: "Goal", fill: "#ffab00", fontSize: 10 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
