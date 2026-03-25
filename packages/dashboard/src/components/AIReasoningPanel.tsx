import { useState } from "react";
import type { AIDecision } from "../lib/types";

interface Props {
  decisions: AIDecision[];
}

function DecisionRow({ decision }: { decision: AIDecision }) {
  const [expanded, setExpanded] = useState(false);

  const typeColors: Record<string, string> = {
    screener: "badge-blue",
    analyst: "badge-amber",
    strategist: "badge-green",
  };

  return (
    <div className="border-b border-terminal-border last:border-0">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left py-3 px-4 hover:bg-white/[0.02] transition-colors flex items-center gap-3"
      >
        <span className="text-terminal-muted text-xs tabular-nums w-16 shrink-0">
          {new Date(decision.created_at).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          })}
        </span>
        <span className={`badge ${typeColors[decision.decision_type] ?? "badge-blue"} shrink-0`}>
          {decision.decision_type}
        </span>
        <span className="text-xs capitalize text-terminal-muted shrink-0">
          {decision.trader}
        </span>
        <span className="text-xs text-gray-400 truncate flex-1">
          {decision.input_summary ?? "No summary"}
        </span>
        <span className="text-xs text-terminal-muted tabular-nums shrink-0">
          {decision.model}
        </span>
        <span className="text-xs text-terminal-amber tabular-nums shrink-0">
          ${decision.cost_usd.toFixed(4)}
        </span>
        <span className="text-xs text-terminal-muted tabular-nums shrink-0">
          {decision.latency_ms}ms
        </span>
        <svg
          className={`w-4 h-4 text-terminal-muted transition-transform shrink-0 ${
            expanded ? "rotate-180" : ""
          }`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          <div className="grid grid-cols-4 gap-4 text-xs">
            <div>
              <span className="text-terminal-muted">Tokens In:</span>{" "}
              <span className="tabular-nums">{decision.prompt_tokens.toLocaleString()}</span>
            </div>
            <div>
              <span className="text-terminal-muted">Tokens Out:</span>{" "}
              <span className="tabular-nums">{decision.completion_tokens.toLocaleString()}</span>
            </div>
            <div>
              <span className="text-terminal-muted">Cost:</span>{" "}
              <span className="text-terminal-amber tabular-nums">
                ${decision.cost_usd.toFixed(6)}
              </span>
            </div>
            <div>
              <span className="text-terminal-muted">Latency:</span>{" "}
              <span className="tabular-nums">{decision.latency_ms}ms</span>
            </div>
          </div>
          {decision.related_trade_id && (
            <div className="text-xs">
              <span className="text-terminal-muted">Related Trade:</span>{" "}
              <span className="text-terminal-blue">{decision.related_trade_id}</span>
            </div>
          )}
          {decision.output_raw && (
            <div>
              <div className="text-xs text-terminal-muted mb-1">AI Output:</div>
              <pre className="bg-terminal-bg border border-terminal-border rounded-md p-3 text-xs text-gray-300 overflow-x-auto max-h-64 overflow-y-auto whitespace-pre-wrap">
                {decision.output_raw}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function AIReasoningPanel({ decisions }: Props) {
  if (decisions.length === 0) {
    return (
      <div className="card">
        <div className="card-header">AI Decision Log</div>
        <p className="text-terminal-muted text-sm py-8 text-center">
          No AI decisions recorded yet
        </p>
      </div>
    );
  }

  return (
    <div className="card p-0 overflow-hidden">
      <div className="card-header px-4 pt-4">AI Decision Log</div>
      <div className="max-h-[600px] overflow-y-auto">
        {decisions.map((d) => (
          <DecisionRow key={d.id} decision={d} />
        ))}
      </div>
    </div>
  );
}
