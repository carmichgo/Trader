-- ============================================================================
-- AI Trading System — Supabase Migration
-- Run this in the Supabase SQL Editor (or via supabase db push)
-- ============================================================================

-- ── Tables ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS goals (
    id SERIAL PRIMARY KEY,
    starting_capital DECIMAL NOT NULL,
    target_capital DECIMAL NOT NULL,
    time_horizon_days INT NOT NULL,
    start_date DATE NOT NULL DEFAULT CURRENT_DATE,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS strategist_plans (
    id SERIAL PRIMARY KEY,
    goal_id INT REFERENCES goals(id),
    plan_date DATE NOT NULL,
    allocations JSONB NOT NULL,
    trader_configs JSONB NOT NULL,
    daily_target DECIMAL NOT NULL,
    reasoning TEXT NOT NULL,
    goal_feasibility VARCHAR(20),
    inference_cost DECIMAL NOT NULL DEFAULT 0,
    tokens_in INT NOT NULL DEFAULT 0,
    tokens_out INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    trader VARCHAR(20) NOT NULL,
    asset VARCHAR(50) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    position_size_usd DECIMAL NOT NULL,
    quantity DECIMAL NOT NULL,
    entry_price DECIMAL,
    exit_price DECIMAL,
    stop_loss DECIMAL,
    take_profit DECIMAL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    close_reason VARCHAR(20),
    gross_pnl DECIMAL,
    net_pnl DECIMAL,
    exchange_fee DECIMAL DEFAULT 0,
    slippage DECIMAL DEFAULT 0,
    screener_cost DECIMAL DEFAULT 0,
    analyst_cost DECIMAL DEFAULT 0,
    total_cost DECIMAL DEFAULT 0,
    screener_output JSONB,
    analyst_output JSONB,
    ai_confidence DECIMAL,
    ai_model_used VARCHAR(30),
    opened_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    CONSTRAINT valid_status CHECK (status IN ('open', 'closed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_trades_trader ON trades(trader);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_opened ON trades(opened_at);
CREATE INDEX IF NOT EXISTS idx_trades_asset ON trades(asset);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    time TIMESTAMPTZ NOT NULL PRIMARY KEY,
    total_capital DECIMAL NOT NULL,
    polymarket_capital DECIMAL NOT NULL DEFAULT 0,
    crypto_capital DECIMAL NOT NULL DEFAULT 0,
    stocks_capital DECIMAL NOT NULL DEFAULT 0,
    total_unrealized_pnl DECIMAL NOT NULL DEFAULT 0,
    total_realized_pnl_today DECIMAL NOT NULL DEFAULT 0,
    open_positions_count INT NOT NULL DEFAULT 0,
    daily_inference_cost DECIMAL NOT NULL DEFAULT 0,
    daily_trading_fees DECIMAL NOT NULL DEFAULT 0,
    drawdown_from_peak DECIMAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ai_decisions (
    id SERIAL PRIMARY KEY,
    decision_type VARCHAR(20) NOT NULL,
    trader VARCHAR(20),
    model VARCHAR(30) NOT NULL,
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    cost_usd DECIMAL NOT NULL DEFAULT 0,
    latency_ms INT NOT NULL DEFAULT 0,
    input_summary JSONB,
    output_raw JSONB NOT NULL DEFAULT '{}',
    related_trade_id INT REFERENCES trades(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_decisions_type ON ai_decisions(decision_type);
CREATE INDEX IF NOT EXISTS idx_ai_decisions_trader ON ai_decisions(trader);
CREATE INDEX IF NOT EXISTS idx_ai_decisions_created ON ai_decisions(created_at);

CREATE TABLE IF NOT EXISTS market_data (
    time TIMESTAMPTZ NOT NULL,
    market VARCHAR(20) NOT NULL,
    asset VARCHAR(50) NOT NULL,
    open DECIMAL,
    high DECIMAL,
    low DECIMAL,
    close DECIMAL,
    volume DECIMAL,
    extra JSONB,
    PRIMARY KEY (time, market, asset)
);

CREATE TABLE IF NOT EXISTS daily_performance (
    date DATE NOT NULL,
    trader VARCHAR(20) NOT NULL,
    trades_count INT NOT NULL DEFAULT 0,
    winning_trades INT NOT NULL DEFAULT 0,
    losing_trades INT NOT NULL DEFAULT 0,
    gross_pnl DECIMAL NOT NULL DEFAULT 0,
    net_pnl DECIMAL NOT NULL DEFAULT 0,
    total_inference_cost DECIMAL NOT NULL DEFAULT 0,
    total_trading_fees DECIMAL NOT NULL DEFAULT 0,
    total_slippage DECIMAL NOT NULL DEFAULT 0,
    max_drawdown_pct DECIMAL NOT NULL DEFAULT 0,
    win_rate DECIMAL NOT NULL DEFAULT 0,
    avg_trade_pnl DECIMAL NOT NULL DEFAULT 0,
    sharpe_ratio DECIMAL,
    PRIMARY KEY (date, trader)
);

CREATE TABLE IF NOT EXISTS system_controls (
    id SERIAL PRIMARY KEY,
    trader VARCHAR(20),
    action VARCHAR(20) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Row Level Security ──────────────────────────────────────────────────────

ALTER TABLE goals ENABLE ROW LEVEL SECURITY;
ALTER TABLE strategist_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_performance ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_controls ENABLE ROW LEVEL SECURITY;

-- Allow anon/authenticated to read all tables
CREATE POLICY "Allow public read" ON goals FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON strategist_plans FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON trades FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON portfolio_snapshots FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON ai_decisions FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON market_data FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON daily_performance FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON system_controls FOR SELECT USING (true);

-- Allow anon to write to goals and system_controls (dashboard updates)
CREATE POLICY "Allow public write goals" ON goals FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow public write controls" ON system_controls FOR ALL USING (true) WITH CHECK (true);

-- Allow service_role full access (backend traders write)
CREATE POLICY "Service role full access" ON trades FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON portfolio_snapshots FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON ai_decisions FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON market_data FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON daily_performance FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON strategist_plans FOR ALL USING (true) WITH CHECK (true);

-- ── Enable Realtime ─────────────────────────────────────────────────────────

ALTER PUBLICATION supabase_realtime ADD TABLE trades;
ALTER PUBLICATION supabase_realtime ADD TABLE portfolio_snapshots;
ALTER PUBLICATION supabase_realtime ADD TABLE ai_decisions;

-- ── No seed data — real data comes from the trading backend ──────────────────
