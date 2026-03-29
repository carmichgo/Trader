import { useState, useMemo } from "react";
import type { Trade } from "../lib/types";

interface Props {
  trades: Trade[];
  onSelectTrade?: (trade: Trade) => void;
  showTrader?: boolean;
}

type SortKey = "opened_at" | "net_pnl" | "position_size_usd" | "ai_confidence";
type SortDir = "asc" | "desc";

export default function TradeTable({
  trades,
  onSelectTrade,
  showTrader = true,
}: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("opened_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [filterStatus, setFilterStatus] = useState<string>("all");

  const filtered = useMemo(() => {
    let list = [...trades];
    if (filterStatus !== "all") {
      list = list.filter((t) => t.status === filterStatus);
    }
    list.sort((a, b) => {
      const aVal = a[sortKey] ?? 0;
      const bVal = b[sortKey] ?? 0;
      if (typeof aVal === "string" && typeof bVal === "string") {
        return sortDir === "asc"
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }
      const diff = (aVal as number) - (bVal as number);
      return sortDir === "asc" ? diff : -diff;
    });
    return list;
  }, [trades, sortKey, sortDir, filterStatus]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  function SortIcon({ column }: { column: SortKey }) {
    if (sortKey !== column) return <span className="text-gray-600 ml-1">-</span>;
    return <span className="ml-1">{sortDir === "asc" ? "\u25B2" : "\u25BC"}</span>;
  }

  return (
    <div>
      {/* Filters */}
      <div className="flex gap-2 mb-3">
        {["all", "open", "closed", "cancelled"].map((s) => (
          <button
            key={s}
            onClick={() => setFilterStatus(s)}
            className={`px-3 py-1 text-xs rounded-md border transition-colors ${
              filterStatus === s
                ? "bg-terminal-blue/20 border-terminal-blue/50 text-terminal-blue"
                : "border-terminal-border text-terminal-muted hover:border-gray-600"
            }`}
          >
            {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-terminal-muted text-xs uppercase tracking-wider border-b border-terminal-border">
              {showTrader && <th className="text-left py-2 px-2">Trader</th>}
              <th className="text-left py-2 px-2">Asset</th>
              <th className="text-left py-2 px-2">Dir</th>
              <th
                className="text-right py-2 px-2 cursor-pointer select-none"
                onClick={() => toggleSort("position_size_usd")}
              >
                Size <SortIcon column="position_size_usd" />
              </th>
              <th className="text-right py-2 px-2">Entry</th>
              <th className="text-right py-2 px-2">Exit</th>
              <th
                className="text-right py-2 px-2 cursor-pointer select-none"
                onClick={() => toggleSort("net_pnl")}
              >
                P&L <SortIcon column="net_pnl" />
              </th>
              <th
                className="text-right py-2 px-2 cursor-pointer select-none"
                onClick={() => toggleSort("ai_confidence")}
              >
                Conf <SortIcon column="ai_confidence" />
              </th>
              <th className="text-center py-2 px-2">Status</th>
              <th
                className="text-right py-2 px-2 cursor-pointer select-none"
                onClick={() => toggleSort("opened_at")}
              >
                Time <SortIcon column="opened_at" />
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td
                  colSpan={showTrader ? 10 : 9}
                  className="text-center py-8 text-terminal-muted"
                >
                  No trades found
                </td>
              </tr>
            )}
            {filtered.map((trade) => (
              <tr
                key={trade.id}
                className="table-row cursor-pointer"
                onClick={() => onSelectTrade?.(trade)}
              >
                {showTrader && (
                  <td className="py-2 px-2 capitalize text-xs">{trade.trader}</td>
                )}
                <td className="py-2 px-2 font-medium">{trade.asset}</td>
                <td className="py-2 px-2">
                  <span
                    className={`text-xs font-semibold ${
                      trade.direction === "long" || trade.direction === "buy"
                        ? "text-terminal-green"
                        : "text-terminal-red"
                    }`}
                  >
                    {trade.direction.toUpperCase()}
                  </span>
                </td>
                <td className="py-2 px-2 text-right tabular-nums">
                  ${trade.position_size_usd.toFixed(2)}
                </td>
                <td className="py-2 px-2 text-right tabular-nums text-xs">
                  {trade.entry_price?.toFixed(4) ?? "-"}
                </td>
                <td className="py-2 px-2 text-right tabular-nums text-xs">
                  {trade.exit_price?.toFixed(4) ?? "-"}
                </td>
                <td
                  className={`py-2 px-2 text-right tabular-nums font-semibold ${
                    (trade.net_pnl ?? 0) >= 0
                      ? "text-terminal-green"
                      : "text-terminal-red"
                  }`}
                >
                  {trade.net_pnl != null
                    ? `${trade.net_pnl >= 0 ? "+" : ""}$${trade.net_pnl.toFixed(2)}`
                    : "-"}
                </td>
                <td className="py-2 px-2 text-right tabular-nums text-xs">
                  {trade.ai_confidence
                    ? `${(trade.ai_confidence * 100).toFixed(0)}%`
                    : "-"}
                </td>
                <td className="py-2 px-2 text-center">
                  <span
                    className={`badge ${
                      trade.status === "open"
                        ? "badge-blue"
                        : trade.status === "closed"
                        ? (trade.net_pnl ?? 0) >= 0
                          ? "badge-green"
                          : "badge-red"
                        : "badge-amber"
                    }`}
                  >
                    {trade.status}
                  </span>
                </td>
                <td className="py-2 px-2 text-right text-xs text-terminal-muted tabular-nums">
                  {trade.opened_at
                    ? new Date(trade.opened_at).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })
                    : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
