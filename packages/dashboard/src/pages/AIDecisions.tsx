import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getAIDecisions } from "../lib/api";
import AIReasoningPanel from "../components/AIReasoningPanel";


const DECISION_TYPES: { value: string; label: string }[] = [
  { value: "", label: "All Types" },
  { value: "screener", label: "Screener" },
  { value: "analyst", label: "Analyst" },
  { value: "strategist", label: "Strategist" },
];

const TRADERS: { value: string; label: string }[] = [
  { value: "", label: "All Traders" },
  { value: "polymarket", label: "Polymarket" },
  { value: "crypto", label: "Crypto" },
  { value: "stocks", label: "Stocks" },
];

const TIME_RANGES: { value: number; label: string }[] = [
  { value: 1, label: "1 Hour" },
  { value: 6, label: "6 Hours" },
  { value: 24, label: "24 Hours" },
  { value: 72, label: "3 Days" },
  { value: 168, label: "7 Days" },
];

export default function AIDecisions() {
  const [decisionType, setDecisionType] = useState("");
  const [trader, setTrader] = useState("");
  const [sinceHours, setSinceHours] = useState(24);
  const [limit, setLimit] = useState(100);

  const { data, isLoading } = useQuery({
    queryKey: ["ai-decisions", decisionType, trader, sinceHours, limit],
    queryFn: () =>
      getAIDecisions({
        decision_type: decisionType || undefined,
        trader: trader || undefined,
        since_hours: sinceHours,
        limit,
      }),
    refetchInterval: 15_000,
  });

  const decisions = data?.decisions ?? [];

  // Compute summary stats
  const totalCost = decisions.reduce((s, d) => s + d.cost_usd, 0);
  const avgLatency =
    decisions.length > 0
      ? decisions.reduce((s, d) => s + d.latency_ms, 0) / decisions.length
      : 0;
  const totalTokens = decisions.reduce(
    (s, d) => s + d.prompt_tokens + d.completion_tokens,
    0
  );

  const typeCounts = decisions.reduce<Record<string, number>>((acc, d) => {
    acc[d.decision_type] = (acc[d.decision_type] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold">AI Decisions</h2>
        <p className="text-sm text-terminal-muted">
          Audit trail of all AI inference calls with reasoning
        </p>
      </div>

      {/* Filters */}
      <div className="card">
        <div className="flex flex-wrap items-center gap-4">
          <div>
            <label className="text-xs text-terminal-muted block mb-1">Type</label>
            <select
              value={decisionType}
              onChange={(e) => setDecisionType(e.target.value)}
              className="bg-terminal-bg border border-terminal-border rounded-md px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:border-terminal-blue"
            >
              {DECISION_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-terminal-muted block mb-1">Trader</label>
            <select
              value={trader}
              onChange={(e) => setTrader(e.target.value)}
              className="bg-terminal-bg border border-terminal-border rounded-md px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:border-terminal-blue"
            >
              {TRADERS.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-terminal-muted block mb-1">Time Range</label>
            <select
              value={sinceHours}
              onChange={(e) => setSinceHours(Number(e.target.value))}
              className="bg-terminal-bg border border-terminal-border rounded-md px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:border-terminal-blue"
            >
              {TIME_RANGES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-terminal-muted block mb-1">Limit</label>
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="bg-terminal-bg border border-terminal-border rounded-md px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:border-terminal-blue"
            >
              {[25, 50, 100, 200, 500].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="card">
          <div className="stat-label">Total Calls</div>
          <div className="stat-value tabular-nums">{decisions.length}</div>
        </div>
        <div className="card">
          <div className="stat-label">Total Cost</div>
          <div className="stat-value tabular-nums text-terminal-amber">
            ${totalCost.toFixed(4)}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Avg Latency</div>
          <div className="stat-value tabular-nums">{avgLatency.toFixed(0)}ms</div>
        </div>
        <div className="card">
          <div className="stat-label">Total Tokens</div>
          <div className="stat-value tabular-nums">{totalTokens.toLocaleString()}</div>
        </div>
        <div className="card">
          <div className="stat-label">By Type</div>
          <div className="flex flex-wrap gap-2 mt-1">
            {Object.entries(typeCounts).map(([type, count]) => (
              <span key={type} className="badge badge-blue text-xs">
                {type}: {count}
              </span>
            ))}
            {Object.keys(typeCounts).length === 0 && (
              <span className="text-terminal-muted text-xs">--</span>
            )}
          </div>
        </div>
      </div>

      {/* Decision List */}
      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <div className="text-terminal-muted animate-pulse">Loading decisions...</div>
        </div>
      ) : (
        <AIReasoningPanel decisions={decisions} />
      )}
    </div>
  );
}
