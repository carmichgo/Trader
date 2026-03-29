interface Props {
  label: string;
  value: number;
  max: number;
  /** Threshold at which the gauge turns warning (amber) */
  warnAt?: number;
  /** Threshold at which the gauge turns danger (red) */
  dangerAt?: number;
  format?: (value: number) => string;
}

export default function RiskGauge({
  label,
  value,
  max,
  warnAt = max * 0.6,
  dangerAt = max * 0.8,
  format = (v) => v.toFixed(1),
}: Props) {
  const pct = Math.min((value / max) * 100, 100);
  const color =
    value >= dangerAt
      ? "terminal-red"
      : value >= warnAt
      ? "terminal-amber"
      : "terminal-green";

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-terminal-muted uppercase tracking-wider">
          {label}
        </span>
        <span className={`text-sm font-bold tabular-nums text-${color}`}>
          {format(value)}
        </span>
      </div>
      <div className="w-full h-2 bg-terminal-bg rounded-full overflow-hidden">
        <div
          className={`h-full bg-${color} rounded-full transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between mt-1 text-xs text-gray-600">
        <span>0</span>
        <span>{format(max)}</span>
      </div>
    </div>
  );
}
