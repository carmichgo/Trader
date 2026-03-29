import { useState } from "react";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Overview from "./pages/Overview";
import Polymarket from "./pages/Polymarket";
import Crypto from "./pages/Crypto";
import Stocks from "./pages/Stocks";
import AIDecisions from "./pages/AIDecisions";
import CostTracker from "./pages/CostTracker";
import RiskDashboard from "./pages/RiskDashboard";
import Settings from "./pages/Settings";
import { useWebSocket } from "./hooks/useWebSocket";

const NAV_ITEMS = [
  { to: "/", label: "Overview", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" },
  { to: "/polymarket", label: "Polymarket", icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" },
  { to: "/crypto", label: "Crypto", icon: "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" },
  { to: "/stocks", label: "Stocks", icon: "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" },
  { to: "/ai", label: "AI Decisions", icon: "M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" },
  { to: "/costs", label: "Costs", icon: "M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z" },
  { to: "/risk", label: "Risk", icon: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" },
  { to: "/settings", label: "Settings", icon: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" },
];

export default function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const { connected } = useWebSocket({ topics: [] });

  return (
    <BrowserRouter>
      <div className="flex h-screen overflow-hidden bg-terminal-bg">
        {/* Sidebar */}
        <aside
          className={`flex flex-col border-r border-terminal-border bg-terminal-card transition-all duration-200 shrink-0 ${
            sidebarCollapsed ? "w-16" : "w-52"
          }`}
        >
          {/* Logo */}
          <div className="flex items-center gap-2 px-4 h-14 border-b border-terminal-border shrink-0">
            <div className="w-7 h-7 rounded-md bg-terminal-blue/20 border border-terminal-blue/30 flex items-center justify-center text-terminal-blue font-bold text-xs">
              AI
            </div>
            {!sidebarCollapsed && (
              <span className="font-bold text-sm tracking-wide">TRADER</span>
            )}
          </div>

          {/* Nav */}
          <nav className="flex-1 py-3 overflow-y-auto">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-2.5 mx-2 rounded-md text-sm transition-colors ${
                    isActive
                      ? "bg-terminal-blue/10 text-terminal-blue border border-terminal-blue/20"
                      : "text-gray-400 hover:text-gray-200 hover:bg-white/[0.03] border border-transparent"
                  }`
                }
              >
                <svg
                  className="w-[18px] h-[18px] shrink-0"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  strokeWidth={1.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d={item.icon}
                  />
                </svg>
                {!sidebarCollapsed && <span>{item.label}</span>}
              </NavLink>
            ))}
          </nav>

          {/* Status footer */}
          <div className="px-4 py-3 border-t border-terminal-border shrink-0">
            <div className="flex items-center gap-2">
              <div
                className={`w-2 h-2 rounded-full ${
                  connected
                    ? "bg-terminal-green animate-pulse_slow"
                    : "bg-terminal-red"
                }`}
              />
              {!sidebarCollapsed && (
                <span className="text-xs text-terminal-muted">
                  {connected ? "Live" : "Disconnected"}
                </span>
              )}
            </div>
            <button
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              className="mt-2 text-xs text-terminal-muted hover:text-gray-300 transition-colors"
            >
              {sidebarCollapsed ? ">>" : "<< Collapse"}
            </button>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto">
          {/* Top bar */}
          <header className="h-14 border-b border-terminal-border flex items-center justify-between px-6 bg-terminal-card/50 backdrop-blur-sm sticky top-0 z-10">
            <div className="text-xs text-terminal-muted">
              AI Trading System | Paper Mode
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 text-xs">
                <div
                  className={`w-1.5 h-1.5 rounded-full ${
                    connected ? "bg-terminal-green" : "bg-terminal-red"
                  }`}
                />
                <span className="text-terminal-muted">
                  WS {connected ? "Connected" : "Disconnected"}
                </span>
              </div>
              <div className="text-xs text-terminal-muted tabular-nums">
                {new Date().toLocaleTimeString()}
              </div>
            </div>
          </header>

          {/* Page content */}
          <div className="p-6">
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/polymarket" element={<Polymarket />} />
              <Route path="/crypto" element={<Crypto />} />
              <Route path="/stocks" element={<Stocks />} />
              <Route path="/ai" element={<AIDecisions />} />
              <Route path="/costs" element={<CostTracker />} />
              <Route path="/risk" element={<RiskDashboard />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </div>
        </main>
      </div>
    </BrowserRouter>
  );
}
