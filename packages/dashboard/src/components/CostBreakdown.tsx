import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import type { DailyCostSummary } from "../lib/types";

interface Props {
  dailyCosts: DailyCostSummary[];
  height?: number;
}

export default function CostBreakdown({ dailyCosts, height = 280 }: Props) {
  if (dailyCosts.length === 0) {
    return (
      <div className="card flex items-center justify-center" style={{ height }}>
        <p className="text-terminal-muted text-sm">No cost data available</p>
      </div>
    );
  }

  const data = dailyCosts.map((d) => ({
    date: d.date.slice(5), // MM-DD
    inference: d.inference_cost,
    fees: d.trading_fees,
    slippage: d.slippage,
  }));

  return (
    <div className="card">
      <div className="card-header">Daily Costs Breakdown</div>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis dataKey="date" stroke="#6b7280" fontSize={10} tickLine={false} />
          <YAxis
            stroke="#6b7280"
            fontSize={10}
            tickLine={false}
            tickFormatter={(v: number) => `$${v.toFixed(2)}`}
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
              name.charAt(0).toUpperCase() + name.slice(1),
            ]}
          />
          <Legend
            wrapperStyle={{ fontSize: "11px", color: "#6b7280" }}
          />
          <Bar
            dataKey="inference"
            stackId="costs"
            fill="#7c4dff"
            name="Inference"
            radius={[0, 0, 0, 0]}
          />
          <Bar
            dataKey="fees"
            stackId="costs"
            fill="#2979ff"
            name="Trading Fees"
            radius={[0, 0, 0, 0]}
          />
          <Bar
            dataKey="slippage"
            stackId="costs"
            fill="#ffab00"
            name="Slippage"
            radius={[2, 2, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
