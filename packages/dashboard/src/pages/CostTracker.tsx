import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getCosts, getCostsToday } from "../lib/api";
import CostBreakdown from "../components/CostBreakdown";
import type { CostByModel } from "../lib/types";
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";

const MODEL_COLORS = [
  "#7c4dff",
  "#2979ff",
  "#ffab00",
  "#00e676",
  "#ff5252",
  "#00bcd4",
  "#ff9100",
  "#e040fb",
];

const DAYS_OPTIONS = [
  { value: 1, label: "1 Day" },
  { value: 7, label: "7 Days" },
  { value: 14, label: "14 Days" },
  { value: 30, label: "30 Days" },
];

export default function CostTracker() {
  const [days, setDays] = useState(7);

  const { data: costData, isLoading } = useQuery({
    queryKey: ["costs", days],
    queryFn: () => getCosts(days),
    refetchInterval: 30_000,
  });

  const { data: todayData } = useQuery({
    queryKey: ["costs-today"],
    queryFn: getCostsToday,
    refetchInterval: 15_000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-terminal-muted animate-pulse">Loading cost data...</div>
      </div>
    );
  }

  const summary = costData?.summary;
  const dailyCosts = costData?.daily ?? [];
  const byModel = costData?.by_model ?? [];

  // Cost totals
  const totalCosts = summary?.total_all_costs ?? 0;
  const inferenceTotal = summary?.total_inference_cost ?? 0;
  const feesTotal = summary?.total_trading_fees ?? 0;
  const slippageTotal = summary?.total_slippage ?? 0;

  // Model pie data
  const modelPieData = byModel.map((m: CostByModel) => ({
    name: m.model,
    value: m.total_cost,
    calls: m.call_count,
  }));

  // Today's breakdown by type
  const todayByType = todayData?.inference.by_type ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">Cost Tracker</h2>
          <p className="text-sm text-terminal-muted">
            Inference spending vs trading profit
          </p>
        </div>
        <div>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="bg-terminal-bg border border-terminal-border rounded-md px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:border-terminal-blue"
          >
            {DAYS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="card">
          <div className="stat-label">Total Costs</div>
          <div className="stat-value tabular-nums text-terminal-red">
            ${totalCosts.toFixed(4)}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Inference</div>
          <div className="stat-value tabular-nums text-terminal-amber">
            ${inferenceTotal.toFixed(4)}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Trading Fees</div>
          <div className="stat-value tabular-nums text-terminal-amber">
            ${feesTotal.toFixed(4)}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Slippage</div>
          <div className="stat-value tabular-nums text-terminal-amber">
            ${slippageTotal.toFixed(4)}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Today&apos;s Cost</div>
          <div className="stat-value tabular-nums text-terminal-red">
            ${(todayData?.total_all_costs ?? 0).toFixed(4)}
          </div>
        </div>
      </div>

      {/* Daily Cost Breakdown Chart */}
      <CostBreakdown dailyCosts={dailyCosts} height={280} />

      {/* Model breakdown + Today by type */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Cost by Model */}
        <div className="card">
          <div className="card-header">Cost by Model</div>
          {modelPieData.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={modelPieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={50}
                    outerRadius={75}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {modelPieData.map((_entry, idx) => (
                      <Cell
                        key={idx}
                        fill={MODEL_COLORS[idx % MODEL_COLORS.length]}
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
                    formatter={(value: number) => [`$${value.toFixed(6)}`, "Cost"]}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-1.5 mt-2">
                {byModel.map((m, idx) => (
                  <div key={m.model} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2">
                      <div
                        className="w-2 h-2 rounded-full"
                        style={{
                          backgroundColor: MODEL_COLORS[idx % MODEL_COLORS.length],
                        }}
                      />
                      <span className="text-gray-400">{m.model}</span>
                    </div>
                    <div className="flex items-center gap-4 tabular-nums">
                      <span className="text-terminal-muted">{m.call_count} calls</span>
                      <span className="text-terminal-amber">${m.total_cost.toFixed(4)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="flex items-center justify-center h-[220px] text-terminal-muted text-sm">
              No model data
            </div>
          )}
        </div>

        {/* Today's Inference by Type */}
        <div className="card">
          <div className="card-header">Today&apos;s Inference by Type</div>
          {todayByType.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={todayByType} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis
                  type="number"
                  stroke="#6b7280"
                  fontSize={10}
                  tickLine={false}
                  tickFormatter={(v: number) => `$${v.toFixed(4)}`}
                />
                <YAxis
                  type="category"
                  dataKey="decision_type"
                  stroke="#6b7280"
                  fontSize={10}
                  tickLine={false}
                  width={80}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#111827",
                    border: "1px solid #1f2937",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                  formatter={(value: number, name: string) => [
                    name === "cost" ? `$${value.toFixed(6)}` : value,
                    name === "cost" ? "Cost" : "Calls",
                  ]}
                />
                <Bar dataKey="cost" fill="#7c4dff" radius={[0, 2, 2, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-[280px] text-terminal-muted text-sm">
              No inference data today
            </div>
          )}
          {todayData && (
            <div className="grid grid-cols-3 gap-4 mt-4 text-xs">
              <div>
                <span className="text-terminal-muted">Inference Calls:</span>{" "}
                <span className="tabular-nums">{todayData.inference.call_count}</span>
              </div>
              <div>
                <span className="text-terminal-muted">Prompt Tokens:</span>{" "}
                <span className="tabular-nums">
                  {todayData.inference.prompt_tokens.toLocaleString()}
                </span>
              </div>
              <div>
                <span className="text-terminal-muted">Completion Tokens:</span>{" "}
                <span className="tabular-nums">
                  {todayData.inference.completion_tokens.toLocaleString()}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
