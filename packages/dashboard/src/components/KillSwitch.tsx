import { useState } from "react";

interface Props {
  onActivate: () => void;
  isPaused?: boolean;
}

export default function KillSwitch({ onActivate, isPaused = false }: Props) {
  const [confirming, setConfirming] = useState(false);
  const [countdown, setCountdown] = useState(3);

  function handleClick() {
    if (!confirming) {
      setConfirming(true);
      setCountdown(3);
      const interval = setInterval(() => {
        setCountdown((c) => {
          if (c <= 1) {
            clearInterval(interval);
            return 0;
          }
          return c - 1;
        });
      }, 1000);
      // Auto-cancel after 10s if not confirmed
      setTimeout(() => {
        setConfirming(false);
        setCountdown(3);
      }, 10000);
      return;
    }

    if (countdown <= 0) {
      onActivate();
      setConfirming(false);
    }
  }

  function handleCancel() {
    setConfirming(false);
    setCountdown(3);
  }

  if (isPaused) {
    return (
      <div className="card border-terminal-red/50 bg-red-950/20">
        <div className="flex items-center gap-3">
          <div className="w-3 h-3 rounded-full bg-terminal-red animate-pulse" />
          <div>
            <div className="text-terminal-red font-semibold text-sm">
              TRADING HALTED
            </div>
            <div className="text-xs text-terminal-muted">
              Kill switch activated. All trading is paused.
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-header">Emergency Controls</div>
      {!confirming ? (
        <button
          onClick={handleClick}
          className="w-full py-3 rounded-lg border-2 border-terminal-red/30 bg-red-950/20
                     text-terminal-red font-bold text-sm uppercase tracking-wider
                     hover:bg-red-950/40 hover:border-terminal-red/50 transition-all"
        >
          KILL SWITCH
        </button>
      ) : (
        <div className="space-y-3">
          <div className="text-center">
            <div className="text-terminal-red font-bold text-sm mb-1">
              CONFIRM KILL SWITCH
            </div>
            <div className="text-xs text-terminal-muted">
              This will immediately halt all trading and close no positions.
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleCancel}
              className="flex-1 py-2 rounded-md border border-terminal-border text-terminal-muted
                         text-sm hover:bg-white/5 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleClick}
              disabled={countdown > 0}
              className={`flex-1 py-2 rounded-md font-bold text-sm uppercase transition-all ${
                countdown > 0
                  ? "border border-terminal-red/20 text-terminal-red/50 cursor-not-allowed"
                  : "border-2 border-terminal-red bg-terminal-red/20 text-terminal-red hover:bg-terminal-red/30"
              }`}
            >
              {countdown > 0 ? `CONFIRM (${countdown}s)` : "CONFIRM HALT"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
