import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getAIDecisions, getLatestStrategistPlan } from "../lib/api";
import AIReasoningPanel from "../components/AIReasoningPanel";

export default function AIDecisions() {
  const [decisionType, setDecisionType] = useState<string>("");
  const [trader, setTrader] = useState<string>("");
  const [sinceHours, setSinceHours] = useState(24);

  const { data: decisionsData, isLoading } = useQuery({
    queryKey: ["ai-decisions", decisionType, trader, sinceHours],
    queryFn: () =>
      getAIDecisions({
        decision_type: decisionType || undefined,
        trader: trader || undefined,
        since_hours: sinceHours,
        limit: 100,
      }),
    refetchInterval: 15_000,
  });

  const { data: strategistData } = useQuery({
    queryKey: ["strategist-latest"],
    queryFn: getLatestStrategistPlan,
    refetchInterval: 60_000,
  });

  const decisions = decisionsData?.decisions ?? [];
  const totalCost = decisions.reduce((sum, d) => sum + d.cost_usd, 0);
  const totalTokens = decisions.reduce(
    (sum, d) => sum + d.prompt_tokens + d.completion_tokens,
    0
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold">AI Decisions</h1>
        <p className="text-terminal-muted text-sm">
          Full audit trail of all AI inference calls with reasoning
        </p>
      </div>

      {/* Filters */}
      <div className="card">
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="text-xs text-terminal-muted block mb-1">Type</label>
            <select
              value={decisionType}
              onChange={(e) => setDecisionType(e.target.value)}
              className="bg-terminal-bg border border-terminal-border rounded-md px-3 py-1.5 text-sm focus:outline-none focus:border-terminal-blue"
            >
              <option value="">All Types</option>
              <option value="screener">Screener</option>
              <option value="analyst">Analyst</option>
              <option value="strategist">Strategist</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-terminal-muted block mb-1">Trader</label>
            <select
              value={trader}
              onChange={(e) => setTrader(e.target.value)}
              className="bg-terminal-bg border border-terminal-border rounded-md px-3 py-1.5 text-sm focus:outline-none focus:border-terminal-blue"
            >
              <option value="">All Traders</option>
              <option value="polymarket">Polymarket</option>
              <option value="crypto">Crypto</option>
              <option value="stocks">Stocks</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-terminal-muted block mb-1">
              Time Window
            </label>
            <select
              value={sinceHours}
              onChange={(e) => setSinceHours(Number(e.target.value))}
              className="bg-terminal-bg border border-terminal-border rounded-md px-3 py-1.5 text-sm focus:outline-none focus:border-terminal-blue"
            >
              <option value={1}>Last hour</option>
              <option value={6}>Last 6 hours</option>
              <option value={24}>Last 24 hours</option>
              <option value={72}>Last 3 days</option>
              <option value={168}>Last 7 days</option>
            </select>
          </div>
          <div className="flex-1" />
          <div className="flex gap-4 text-xs">
            <div>
              <span className="text-terminal-muted">Decisions:</span>{" "}
              <span className="font-semibold tabular-nums">{decisions.length}</span>
            </div>
            <div>
              <span className="text-terminal-muted">Total Cost:</span>{" "}
              <span className="font-semibold tabular-nums text-terminal-amber">
                ${totalCost.toFixed(4)}
              </span>
            </div>
            <div>
              <span className="text-terminal-muted">Tokens:</span>{" "}
              <span className="font-semibold tabular-nums">
                {totalTokens.toLocaleString()}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Latest strategist plan */}
      {strategistData?.plan && (
        <div className="card border-terminal-green/20">
          <div className="card-header flex items-center justify-between">
            <span>Latest Strategist Plan</span>
            <span className="text-xs text-terminal-muted normal-case tracking-normal">
              {new Date(strategistData.plan.created_at).toLocaleString()}
            </span>
          </div>
          <div className="grid grid-cols-4 gap-4 text-sm mb-3">
            <div>
              <span className="text-terminal-muted text-xs">Daily Target:</span>
              <div className="font-bold text-terminal-green tabular-nums">
                ${strategistData.plan.daily_target.toFixed(2)}
              </div>
            </div>
            <div>
              <span className="text-terminal-muted text-xs">Feasibility:</span>
              <div className="font-bold tabular-nums">
                {strategistData.plan.goal_feasibility
                  ? `${(strategistData.plan.goal_feasibility * 100).toFixed(0)}%`
                  : "-"}
              </div>
            </div>
            <div>
              <span className="text-terminal-muted text-xs">Inference Cost:</span>
              <div className="font-bold text-terminal-amber tabular-nums">
                ${strategistData.plan.inference_cost?.toFixed(4) ?? "-"}
              </div>
            </div>
            <div>
              <span className="text-terminal-muted text-xs">Allocations:</span>
              <div className="text-xs font-medium">
                {Object.entries(strategistData.plan.allocations ?? {}).map(
                  ([k, v]) => (
                    <span key={k} className="mr-2 capitalize">
                      {k}: {typeof v === "number" ? `${(v * 100).toFixed(0)}%` : String(v)}
                    </span>
                  )
                )}
              </div>
            </div>
          </div>
          {strategistData.plan.reasoning && (
            <div>
              <div className="text-xs text-terminal-muted mb-1">Reasoning:</div>
              <pre className="bg-terminal-bg border border-terminal-border rounded p-3 text-xs text-gray-300 overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap">
                {strategistData.plan.reasoning}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Decision log */}
      {isLoading ? (
        <div className="card flex items-center justify-center py-12">
          <span className="text-terminal-muted animate-pulse">
            Loading decisions...
          </span>
        </div>
      ) : (
        <AIReasoningPanel decisions={decisions} />
      )}
    </div>
  );
}
