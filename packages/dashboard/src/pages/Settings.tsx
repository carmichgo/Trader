import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getGoal, updateGoal, resetSystem } from "../lib/api";
import type { Goal, GoalProgress } from "../lib/types";

export default function Settings() {
  const { data: goalData, isLoading } = useQuery({
    queryKey: ["goal"],
    queryFn: getGoal,
  });

  const goal = goalData?.goal;
  const progress = goalData?.progress;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold">Settings</h2>
        <p className="text-sm text-terminal-muted">
          Goal configuration, API keys, and safety rails
        </p>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <div className="text-terminal-muted animate-pulse">Loading settings...</div>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Goal Configuration */}
          <GoalConfigPanel goal={goal ?? null} progress={progress ?? null} />

          {/* Safety Rails */}
          <SafetyRailsPanel />

          {/* API Keys */}
          <APIKeysPanel />

          {/* System Info */}
          <SystemInfoPanel />

          {/* Reset System */}
          <ResetPanel />
        </div>
      )}
    </div>
  );
}

// ── Goal Configuration ──────────────────────────────────────────────────

function GoalConfigPanel({
  goal,
  progress,
}: {
  goal: Goal | null;
  progress: GoalProgress | null;
}) {
  const queryClient = useQueryClient();
  const [startingCapital, setStartingCapital] = useState(
    goal?.starting_capital?.toString() ?? ""
  );
  const [targetCapital, setTargetCapital] = useState(
    goal?.target_capital?.toString() ?? ""
  );
  const [timeHorizon, setTimeHorizon] = useState(
    goal?.time_horizon_days?.toString() ?? ""
  );

  const mutation = useMutation({
    mutationFn: updateGoal,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["goal"] });
      queryClient.invalidateQueries({ queryKey: ["pace"] });
    },
  });

  function handleSave() {
    mutation.mutate({
      starting_capital: startingCapital ? Number(startingCapital) : undefined,
      target_capital: targetCapital ? Number(targetCapital) : undefined,
      time_horizon_days: timeHorizon ? Number(timeHorizon) : undefined,
    });
  }

  return (
    <div className="card">
      <div className="card-header">Goal Configuration</div>
      <div className="space-y-4">
        <div>
          <label className="text-xs text-terminal-muted block mb-1">
            Starting Capital ($)
          </label>
          <input
            type="number"
            value={startingCapital}
            onChange={(e) => setStartingCapital(e.target.value)}
            placeholder="e.g. 1000"
            className="w-full bg-terminal-bg border border-terminal-border rounded-md px-3 py-2 text-sm text-gray-300 focus:outline-none focus:border-terminal-blue placeholder-gray-600"
          />
        </div>
        <div>
          <label className="text-xs text-terminal-muted block mb-1">
            Target Capital ($)
          </label>
          <input
            type="number"
            value={targetCapital}
            onChange={(e) => setTargetCapital(e.target.value)}
            placeholder="e.g. 100000"
            className="w-full bg-terminal-bg border border-terminal-border rounded-md px-3 py-2 text-sm text-gray-300 focus:outline-none focus:border-terminal-blue placeholder-gray-600"
          />
        </div>
        <div>
          <label className="text-xs text-terminal-muted block mb-1">
            Time Horizon (days)
          </label>
          <input
            type="number"
            value={timeHorizon}
            onChange={(e) => setTimeHorizon(e.target.value)}
            placeholder="e.g. 365"
            className="w-full bg-terminal-bg border border-terminal-border rounded-md px-3 py-2 text-sm text-gray-300 focus:outline-none focus:border-terminal-blue placeholder-gray-600"
          />
        </div>

        {progress && (
          <div className="bg-terminal-bg border border-terminal-border rounded-md p-3 space-y-2 text-xs">
            <div className="flex justify-between">
              <span className="text-terminal-muted">Progress</span>
              <span className="tabular-nums">{progress.progress_pct.toFixed(1)}%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-terminal-muted">Days Elapsed</span>
              <span className="tabular-nums">{progress.days_elapsed}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-terminal-muted">Days Remaining</span>
              <span className="tabular-nums">{progress.days_remaining}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-terminal-muted">Required Daily Return</span>
              <span className="tabular-nums text-terminal-amber">
                {progress.required_daily_return_pct.toFixed(3)}%
              </span>
            </div>
          </div>
        )}

        <button
          onClick={handleSave}
          disabled={mutation.isPending}
          className="w-full py-2 rounded-md bg-terminal-blue/20 border border-terminal-blue/30 text-terminal-blue font-semibold text-sm hover:bg-terminal-blue/30 transition-colors disabled:opacity-50"
        >
          {mutation.isPending ? "Saving..." : "Update Goal"}
        </button>

        {mutation.isSuccess && (
          <p className="text-terminal-green text-xs text-center">
            Goal updated successfully
          </p>
        )}
        {mutation.isError && (
          <p className="text-terminal-red text-xs text-center">
            Failed to update goal
          </p>
        )}
      </div>
    </div>
  );
}

// ── Safety Rails ────────────────────────────────────────────────────────

function SafetyRailsPanel() {
  const rails = [
    { label: "Max Single Trade", value: "5%", description: "Max % of capital per trade" },
    { label: "Max Market Allocation", value: "40%", description: "Max % in one market" },
    { label: "Kill Switch Drawdown", value: "15%", description: "Auto-halt threshold" },
    { label: "Max Daily Drawdown", value: "5%", description: "Daily loss limit" },
    { label: "Mandatory Stop Loss", value: "Yes", description: "All trades require SL" },
    { label: "Max Leverage", value: "3x", description: "Maximum position leverage" },
    { label: "Max Daily Inference Cost", value: "$5.00", description: "Daily AI spending cap" },
    { label: "Max Concurrent Positions", value: "20", description: "Position count limit" },
    { label: "Max Losing Streak", value: "5", description: "Pause after N losses" },
    { label: "Cool Down Period", value: "4h", description: "Wait after pause" },
  ];

  return (
    <div className="card">
      <div className="card-header">Safety Rails</div>
      <div className="space-y-2">
        {rails.map((r) => (
          <div
            key={r.label}
            className="flex items-center justify-between py-1.5 border-b border-terminal-border/50 last:border-0"
          >
            <div>
              <span className="text-sm">{r.label}</span>
              <span className="text-xs text-terminal-muted ml-2">
                {r.description}
              </span>
            </div>
            <span className="text-sm tabular-nums font-medium text-terminal-blue">
              {r.value}
            </span>
          </div>
        ))}
      </div>
      <p className="text-xs text-terminal-muted mt-4">
        Safety rails are configured in the system config file. Contact admin to modify.
      </p>
    </div>
  );
}

// ── API Keys ────────────────────────────────────────────────────────────

function APIKeysPanel() {
  const keys = [
    { name: "Polymarket", status: "configured", masked: "poly_****...k8f2" },
    { name: "Binance", status: "configured", masked: "bnb_****...9x3a" },
    { name: "Alpaca", status: "configured", masked: "alp_****...m7d1" },
    { name: "OpenAI / Anthropic", status: "configured", masked: "sk-****...pQ4z" },
  ];

  return (
    <div className="card">
      <div className="card-header">API Keys</div>
      <div className="space-y-3">
        {keys.map((k) => (
          <div
            key={k.name}
            className="flex items-center justify-between py-2 px-3 rounded-md bg-terminal-bg border border-terminal-border"
          >
            <div className="flex items-center gap-3">
              <div className="w-2 h-2 rounded-full bg-terminal-green" />
              <span className="text-sm">{k.name}</span>
            </div>
            <span className="text-xs text-terminal-muted font-mono">{k.masked}</span>
          </div>
        ))}
      </div>
      <p className="text-xs text-terminal-muted mt-4">
        API keys are stored securely in environment variables and cannot be viewed or
        modified from the dashboard.
      </p>
    </div>
  );
}

// ── Reset System ──────────────────────────────────────────────────────

function ResetPanel() {
  const queryClient = useQueryClient();
  const [confirmStep, setConfirmStep] = useState(0);
  const [countdown, setCountdown] = useState(0);

  const mutation = useMutation({
    mutationFn: resetSystem,
    onSuccess: () => {
      queryClient.invalidateQueries();
      setConfirmStep(0);
      setCountdown(0);
    },
  });

  function handleReset() {
    if (confirmStep === 0) {
      setConfirmStep(1);
      return;
    }
    if (confirmStep === 1) {
      setConfirmStep(2);
      setCountdown(5);
      const interval = setInterval(() => {
        setCountdown((c) => {
          if (c <= 1) {
            clearInterval(interval);
            return 0;
          }
          return c - 1;
        });
      }, 1000);
      return;
    }
    if (confirmStep === 2 && countdown === 0) {
      mutation.mutate();
    }
  }

  function handleCancel() {
    setConfirmStep(0);
    setCountdown(0);
  }

  return (
    <div className="card border-terminal-red/30">
      <div className="card-header text-terminal-red">Reset System</div>
      <p className="text-sm text-terminal-muted mb-4">
        Delete all trades, AI decisions, portfolio snapshots, strategist plans,
        performance data, and goals. Start completely fresh.
      </p>

      {mutation.isSuccess && (
        <div className="bg-terminal-green/10 border border-terminal-green/30 rounded-md p-3 mb-4">
          <p className="text-terminal-green text-sm font-medium">
            System reset complete. All data has been deleted.
          </p>
          <p className="text-xs text-terminal-muted mt-1">
            Set a new goal to begin trading again.
          </p>
        </div>
      )}

      {mutation.isError && (
        <p className="text-terminal-red text-xs mb-4">
          Reset failed: {String((mutation.error as Error)?.message ?? mutation.error)}
        </p>
      )}

      <div className="space-y-3">
        {confirmStep === 0 && (
          <button
            onClick={handleReset}
            className="w-full py-2.5 rounded-md bg-terminal-red/10 border border-terminal-red/30 text-terminal-red font-semibold text-sm hover:bg-terminal-red/20 transition-colors"
          >
            Reset Everything
          </button>
        )}

        {confirmStep === 1 && (
          <div className="space-y-2">
            <p className="text-terminal-amber text-sm font-medium">
              Are you sure? This will permanently delete ALL data.
            </p>
            <div className="flex gap-2">
              <button
                onClick={handleReset}
                className="flex-1 py-2 rounded-md bg-terminal-red/20 border border-terminal-red/50 text-terminal-red font-semibold text-sm hover:bg-terminal-red/30 transition-colors"
              >
                Yes, I'm sure
              </button>
              <button
                onClick={handleCancel}
                className="flex-1 py-2 rounded-md bg-terminal-bg border border-terminal-border text-terminal-muted text-sm hover:text-gray-300 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {confirmStep === 2 && (
          <div className="space-y-2">
            <p className="text-terminal-red text-sm font-bold">
              FINAL WARNING: This cannot be undone.
            </p>
            <div className="flex gap-2">
              <button
                onClick={handleReset}
                disabled={countdown > 0 || mutation.isPending}
                className="flex-1 py-2.5 rounded-md bg-red-600 text-white font-bold text-sm hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {mutation.isPending
                  ? "Deleting..."
                  : countdown > 0
                  ? `Wait ${countdown}s...`
                  : "DELETE EVERYTHING"}
              </button>
              <button
                onClick={handleCancel}
                disabled={mutation.isPending}
                className="flex-1 py-2.5 rounded-md bg-terminal-bg border border-terminal-border text-terminal-muted text-sm hover:text-gray-300 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── System Info ─────────────────────────────────────────────────────────

function SystemInfoPanel() {
  return (
    <div className="card">
      <div className="card-header">System Information</div>
      <div className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-terminal-muted">Version</span>
          <span className="tabular-nums">1.0.0</span>
        </div>
        <div className="flex justify-between">
          <span className="text-terminal-muted">Mode</span>
          <span className="badge badge-amber">Paper Trading</span>
        </div>
        <div className="flex justify-between">
          <span className="text-terminal-muted">Backend</span>
          <span className="text-terminal-green">Connected</span>
        </div>
        <div className="flex justify-between">
          <span className="text-terminal-muted">WebSocket</span>
          <span className="text-terminal-green">Connected</span>
        </div>
        <div className="flex justify-between">
          <span className="text-terminal-muted">Database</span>
          <span className="text-terminal-green">Online</span>
        </div>
      </div>
    </div>
  );
}
