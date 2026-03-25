import { Routes, Route, NavLink } from "react-router-dom";
import { lazy, Suspense } from "react";

const Overview = lazy(() => import("./pages/Overview"));
const Polymarket = lazy(() => import("./pages/Polymarket"));
const Crypto = lazy(() => import("./pages/Crypto"));
const Stocks = lazy(() => import("./pages/Stocks"));
const AIDecisions = lazy(() => import("./pages/AIDecisions"));
const CostTracker = lazy(() => import("./pages/CostTracker"));
const RiskDashboard = lazy(() => import("./pages/RiskDashboard"));
const Settings = lazy(() => import("./pages/Settings"));

const NAV_ITEMS = [
  { to: "/", label: "Overview", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0a1 1 0 01-1-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 01-1 1" },
  { to: "/polymarket", label: "Polymarket", icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" },
  { to: "/crypto", label: "Crypto", icon: "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" },
  { to: "/stocks", label: "Stocks", icon: "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" },
  { to: "/ai-decisions", label: "AI Decisions", icon: "M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" },
  { to: "/costs", label: "Costs", icon: "M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z" },
  { to: "/risk", label: "Risk", icon: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" },
  { to: "/settings", label: "Settings", icon: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" },
];

function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center h-96">
      <div className="text-terminal-muted animate-pulse text-sm">Loading...</div>
    </div>
  );
}

export default function App() {
  return (
    <div className="flex h-screen bg-[#0f172a]">
      {/* Sidebar */}
      <nav className="w-56 shrink-0 bg-[#0f172a] border-r border-terminal-border flex flex-col">
        <div className="px-4 py-5 border-b border-terminal-border">
          <h1 className="text-lg font-bold tracking-tight">
            <span className="text-terminal-green">AI</span>
            <span className="text-gray-300"> Trader</span>
          </h1>
          <p className="text-[10px] text-terminal-muted mt-0.5 uppercase tracking-widest">
            Trading Terminal
          </p>
        </div>

        <div className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                  isActive
                    ? "bg-terminal-blue/10 text-terminal-blue border border-terminal-blue/20"
                    : "text-gray-400 hover:text-gray-200 hover:bg-white/[0.03] border border-transparent"
                }`
              }
            >
              <svg
                className="w-4 h-4 shrink-0"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                strokeWidth={1.5}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d={item.icon} />
              </svg>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </div>

        <div className="px-4 py-3 border-t border-terminal-border">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-terminal-green animate-pulse" />
            <span className="text-xs text-terminal-muted">System Online</span>
          </div>
        </div>
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto bg-[#0f172a]">
        <div className="max-w-7xl mx-auto px-6 py-6">
          <Suspense fallback={<LoadingSpinner />}>
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/polymarket" element={<Polymarket />} />
              <Route path="/crypto" element={<Crypto />} />
              <Route path="/stocks" element={<Stocks />} />
              <Route path="/ai-decisions" element={<AIDecisions />} />
              <Route path="/costs" element={<CostTracker />} />
              <Route path="/risk" element={<RiskDashboard />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </Suspense>
        </div>
      </main>
    </div>
  );
}
