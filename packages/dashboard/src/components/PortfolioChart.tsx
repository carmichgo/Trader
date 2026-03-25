import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { PortfolioSnapshot } from "../lib/types";

interface Props {
  history: PortfolioSnapshot[];
  height?: number;
}

export default function PortfolioChart({ history, height = 300 }: Props) {
  if (history.length === 0) {
    return (
      <div className="card flex items-center justify-center" style={{ height }}>
        <p className="text-terminal-muted text-sm">No portfolio data available</p>
      </div>
    );
  }

  const data = history.map((s) => ({
    time: new Date(s.time).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    }),
    total: s.total_capital,
    polymarket: s.polymarket_capital ?? 0,
    crypto: s.crypto_capital ?? 0,
    stocks: s.stocks_capital ?? 0,
  }));

  const minVal = Math.min(...data.map((d) => d.total)) * 0.995;
  const maxVal = Math.max(...data.map((d) => d.total)) * 1.005;
  const isUp = data.length >= 2 && data[data.length - 1]!.total >= data[0]!.total;

  return (
    <div className="card">
      <div className="card-header">Equity Curve</div>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data}>
          <defs>
            <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="5%"
                stopColor={isUp ? "#00e676" : "#ff1744"}
                stopOpacity={0.3}
              />
              <stop
                offset="95%"
                stopColor={isUp ? "#00e676" : "#ff1744"}
                stopOpacity={0}
              />
            </linearGradient>
          </defs>
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
            domain={[minVal, maxVal]}
            tickFormatter={(v: number) => `$${v.toLocaleString()}`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#111827",
              border: "1px solid #1f2937",
              borderRadius: "8px",
              fontSize: "12px",
            }}
            formatter={(value: number, name: string) => [
              `$${value.toLocaleString()}`,
              name.charAt(0).toUpperCase() + name.slice(1),
            ]}
          />
          <Area
            type="monotone"
            dataKey="total"
            stroke={isUp ? "#00e676" : "#ff1744"}
            strokeWidth={2}
            fill="url(#equityGrad)"
            name="Total"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
