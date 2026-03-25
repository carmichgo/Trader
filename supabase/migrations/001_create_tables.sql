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

-- ── Seed Data ───────────────────────────────────────────────────────────────

-- Goal
INSERT INTO goals (starting_capital, target_capital, time_horizon_days, start_date, is_active)
VALUES (10000, 50000, 180, CURRENT_DATE - INTERVAL '14 days', true);

-- Portfolio snapshots (last 7 days, showing growth)
INSERT INTO portfolio_snapshots (time, total_capital, polymarket_capital, crypto_capital, stocks_capital, total_unrealized_pnl, total_realized_pnl_today, open_positions_count, daily_inference_cost, daily_trading_fees, drawdown_from_peak) VALUES
(NOW() - INTERVAL '7 days', 10000.00, 2800.00, 5200.00, 2000.00, 0, 0, 0, 0.85, 2.10, 0),
(NOW() - INTERVAL '6 days', 10120.50, 2850.00, 5270.50, 2000.00, 45.20, 120.50, 3, 1.20, 3.40, 0),
(NOW() - INTERVAL '5 days', 10045.00, 2810.00, 5185.00, 2050.00, -30.00, -75.50, 2, 0.95, 2.80, 0.74),
(NOW() - INTERVAL '4 days', 10280.00, 2920.00, 5310.00, 2050.00, 85.50, 235.00, 5, 1.45, 4.20, 0),
(NOW() - INTERVAL '3 days', 10415.75, 2980.00, 5385.75, 2050.00, 120.00, 135.75, 4, 1.80, 5.10, 0),
(NOW() - INTERVAL '2 days', 10350.00, 2950.00, 5350.00, 2050.00, -45.00, -65.75, 3, 1.10, 3.50, 0.63),
(NOW() - INTERVAL '1 day',  10520.30, 3020.00, 5420.30, 2080.00, 95.30, 170.30, 6, 1.65, 4.80, 0),
(NOW() - INTERVAL '6 hours', 10685.00, 3080.00, 5505.00, 2100.00, 150.00, 164.70, 7, 2.10, 5.50, 0),
(NOW() - INTERVAL '3 hours', 10750.00, 3100.00, 5540.00, 2110.00, 180.00, 65.00, 7, 2.40, 6.20, 0),
(NOW() - INTERVAL '1 hour',  10850.00, 3150.00, 5580.00, 2120.00, 210.50, 100.00, 8, 2.80, 7.10, 0);

-- Sample closed trades
INSERT INTO trades (trader, asset, direction, position_size_usd, quantity, entry_price, exit_price, stop_loss, take_profit, status, close_reason, gross_pnl, net_pnl, exchange_fee, slippage, screener_cost, analyst_cost, total_cost, ai_confidence, ai_model_used, opened_at, closed_at, screener_output, analyst_output) VALUES
-- Crypto wins
('crypto', 'BTC/USDT', 'buy', 2500.00, 0.038, 65800.00, 66450.00, 65200.00, 67000.00, 'closed', 'take_profit', 95.50, 88.20, 2.50, 1.80, 0.003, 0.12, 7.30, 0.82, 'sonnet+opus', NOW() - INTERVAL '6 days' + INTERVAL '3 hours', NOW() - INTERVAL '6 days' + INTERVAL '9 hours',
 '{"asset":"BTC/USDT","score":85,"direction":"buy","estimated_edge_pct":1.2,"win_probability":0.72}',
 '{"action":"buy","size_pct":0.08,"confidence":0.82,"reasoning":"Strong momentum with funding rates turning negative suggesting short squeeze potential"}'),
('crypto', 'ETH/USDT', 'buy', 1800.00, 0.52, 3450.00, 3520.00, 3400.00, 3600.00, 'closed', 'take_profit', 72.80, 66.50, 1.80, 1.50, 0.003, 0.11, 6.30, 0.78, 'sonnet+opus', NOW() - INTERVAL '4 days' + INTERVAL '2 hours', NOW() - INTERVAL '4 days' + INTERVAL '14 hours',
 '{"asset":"ETH/USDT","score":78,"direction":"buy","estimated_edge_pct":0.9,"win_probability":0.68}',
 '{"action":"buy","size_pct":0.06,"confidence":0.78,"reasoning":"ETH showing relative strength vs BTC, on-chain activity spiking"}'),
-- Crypto loss
('crypto', 'SOL/USDT', 'buy', 1200.00, 7.5, 160.00, 155.00, 154.00, 170.00, 'closed', 'stop_loss', -56.25, -62.10, 1.20, 1.65, 0.003, 0.12, 5.85, 0.71, 'sonnet+opus', NOW() - INTERVAL '5 days' + INTERVAL '6 hours', NOW() - INTERVAL '5 days' + INTERVAL '8 hours',
 '{"asset":"SOL/USDT","score":72,"direction":"buy","estimated_edge_pct":0.8,"win_probability":0.65}',
 '{"action":"buy","size_pct":0.05,"confidence":0.71,"reasoning":"Breakout pattern forming, but BTC correlation risk noted"}'),
-- Polymarket wins
('polymarket', 'fed-rate-hold-june', 'buy', 800.00, 1200, 0.67, 0.82, 0.55, 0.90, 'closed', 'take_profit', 180.00, 175.80, 1.60, 0.60, 0.003, 0.10, 4.20, 0.88, 'sonnet+opus', NOW() - INTERVAL '5 days', NOW() - INTERVAL '3 days',
 '{"asset":"fed-rate-hold-june","score":90,"direction":"buy","estimated_edge_pct":3.5,"win_probability":0.82}',
 '{"action":"buy","size_pct":0.10,"confidence":0.88,"reasoning":"CPI data came in soft, market pricing lagging behind Fed fund futures"}'),
('polymarket', 'btc-above-70k-july', 'buy', 600.00, 1500, 0.40, 0.52, 0.30, 0.65, 'closed', 'take_profit', 180.00, 176.20, 1.20, 0.60, 0.003, 0.08, 3.80, 0.75, 'sonnet+opus', NOW() - INTERVAL '4 days', NOW() - INTERVAL '2 days',
 '{"asset":"btc-above-70k-july","score":76,"direction":"buy","estimated_edge_pct":2.8,"win_probability":0.70}',
 '{"action":"buy","size_pct":0.08,"confidence":0.75,"reasoning":"BTC ETF inflows accelerating, halving narrative building momentum"}'),
-- Polymarket loss
('polymarket', 'uk-election-labor-majority', 'buy', 500.00, 600, 0.83, 0.78, 0.70, 0.95, 'closed', 'manual', -30.00, -33.50, 1.00, 0.50, 0.003, 0.08, 3.50, 0.69, 'sonnet+opus', NOW() - INTERVAL '3 days', NOW() - INTERVAL '1 day',
 '{"asset":"uk-election-labor-majority","score":70,"direction":"buy","estimated_edge_pct":1.5,"win_probability":0.65}',
 '{"action":"buy","size_pct":0.06,"confidence":0.69,"reasoning":"Polling consensus strong, but market already pricing in most upside"}'),
-- Stock wins
('stocks', 'NVDA', 'buy', 1500.00, 12.5, 120.00, 126.50, 116.00, 130.00, 'closed', 'take_profit', 81.25, 74.80, 0, 2.45, 0.003, 0.12, 6.45, 0.84, 'sonnet+opus', NOW() - INTERVAL '5 days' + INTERVAL '14 hours', NOW() - INTERVAL '4 days' + INTERVAL '16 hours',
 '{"asset":"NVDA","score":86,"direction":"buy","estimated_edge_pct":1.8,"win_probability":0.75}',
 '{"action":"buy","size_pct":0.10,"confidence":0.84,"reasoning":"Pre-earnings momentum, unusual call buying detected at 130 strike"}'),
('stocks', 'AAPL', 'buy', 1000.00, 5.5, 182.00, 186.50, 178.00, 190.00, 'closed', 'take_profit', 24.75, 20.50, 0, 1.25, 0.003, 0.10, 4.25, 0.76, 'sonnet+opus', NOW() - INTERVAL '3 days' + INTERVAL '10 hours', NOW() - INTERVAL '2 days' + INTERVAL '15 hours',
 '{"asset":"AAPL","score":77,"direction":"buy","estimated_edge_pct":1.2,"win_probability":0.70}',
 '{"action":"buy","size_pct":0.06,"confidence":0.76,"reasoning":"Positive analyst revision cycle, services revenue beat expectations"}'),
-- Stock loss
('stocks', 'TSLA', 'buy', 1200.00, 5.0, 240.00, 232.00, 230.00, 260.00, 'closed', 'stop_loss', -40.00, -44.80, 0, 1.80, 0.003, 0.12, 4.80, 0.68, 'sonnet+opus', NOW() - INTERVAL '2 days' + INTERVAL '10 hours', NOW() - INTERVAL '2 days' + INTERVAL '14 hours',
 '{"asset":"TSLA","score":69,"direction":"buy","estimated_edge_pct":0.9,"win_probability":0.62}',
 '{"action":"buy","size_pct":0.07,"confidence":0.68,"reasoning":"Delivery numbers beat, but macro headwinds and valuation concerns"}');

-- Open trades (currently active)
INSERT INTO trades (trader, asset, direction, position_size_usd, quantity, entry_price, stop_loss, take_profit, status, ai_confidence, ai_model_used, opened_at, screener_output) VALUES
('crypto', 'BTC/USDT', 'buy', 2800.00, 0.042, 66700.00, 65500.00, 69000.00, 'open', 0.80, 'sonnet+opus', NOW() - INTERVAL '5 hours',
 '{"asset":"BTC/USDT","score":82,"direction":"buy","estimated_edge_pct":1.5,"win_probability":0.74}'),
('crypto', 'AVAX/USDT', 'buy', 900.00, 25.0, 36.00, 34.00, 40.00, 'open', 0.73, 'sonnet-only', NOW() - INTERVAL '3 hours',
 '{"asset":"AVAX/USDT","score":74,"direction":"buy","estimated_edge_pct":0.7,"win_probability":0.66}'),
('polymarket', 'trump-win-2024', 'buy', 1100.00, 2000, 0.55, 0.42, 0.72, 'open', 0.77, 'sonnet+opus', NOW() - INTERVAL '8 hours',
 '{"asset":"trump-win-2024","score":79,"direction":"buy","estimated_edge_pct":2.1,"win_probability":0.71}'),
('polymarket', 'eth-etf-approval-2024', 'buy', 700.00, 1400, 0.50, 0.38, 0.70, 'open', 0.74, 'sonnet+opus', NOW() - INTERVAL '4 hours',
 '{"asset":"eth-etf-approval-2024","score":75,"direction":"buy","estimated_edge_pct":1.8,"win_probability":0.69}'),
('stocks', 'META', 'buy', 1400.00, 2.8, 500.00, 480.00, 530.00, 'open', 0.81, 'sonnet+opus', NOW() - INTERVAL '6 hours',
 '{"asset":"META","score":83,"direction":"buy","estimated_edge_pct":1.6,"win_probability":0.73}');

-- AI decisions
INSERT INTO ai_decisions (decision_type, trader, model, prompt_tokens, completion_tokens, cost_usd, latency_ms, input_summary, output_raw, created_at) VALUES
('strategist', NULL, 'claude-opus', 8200, 2100, 0.28, 12500,
 '{"type":"daily_plan","capital":10850,"goal":50000,"days_remaining":166}',
 '{"allocations":{"polymarket":0.29,"crypto":0.51,"stocks":0.20},"daily_target":85.50,"goal_feasibility":"on_track","reasoning":"System performing well with 8.5% return in 14 days. Crypto allocation increased slightly due to strong BTC momentum. Polymarket showing excellent edge on political markets. Stocks conservative pending earnings season."}',
 NOW() - INTERVAL '10 hours'),
('screener', 'crypto', 'claude-sonnet', 820, 180, 0.005, 1800,
 '{"market":"crypto","assets_scanned":45,"portfolio_size":5580}',
 '{"opportunities":[{"asset":"BTC/USDT","score":82,"direction":"buy","estimated_edge_pct":1.5},{"asset":"AVAX/USDT","score":74,"direction":"buy","estimated_edge_pct":0.7}]}',
 NOW() - INTERVAL '5 hours'),
('analyst', 'crypto', 'claude-opus', 4100, 950, 0.13, 8200,
 '{"asset":"BTC/USDT","screener_score":82,"position_size":2800}',
 '{"action":"buy","size_pct":0.08,"entry_price":66700,"stop_loss":65500,"take_profit":69000,"confidence":0.80,"reasoning":"BTC breaking out of consolidation with strong volume. Funding rates neutral suggesting room for upside. On-chain metrics show accumulation by large holders."}',
 NOW() - INTERVAL '5 hours'),
('screener', 'polymarket', 'claude-sonnet', 750, 160, 0.004, 1500,
 '{"market":"polymarket","events_scanned":28,"portfolio_size":3150}',
 '{"opportunities":[{"asset":"trump-win-2024","score":79,"direction":"buy","estimated_edge_pct":2.1},{"asset":"eth-etf-approval-2024","score":75,"direction":"buy","estimated_edge_pct":1.8}]}',
 NOW() - INTERVAL '8 hours'),
('screener', 'stocks', 'claude-sonnet', 880, 200, 0.005, 2100,
 '{"market":"stocks","stocks_scanned":120,"portfolio_size":2120}',
 '{"opportunities":[{"asset":"META","score":83,"direction":"buy","estimated_edge_pct":1.6}]}',
 NOW() - INTERVAL '6 hours'),
('analyst', 'stocks', 'claude-opus', 4500, 1050, 0.14, 9100,
 '{"asset":"META","screener_score":83,"position_size":1400}',
 '{"action":"buy","size_pct":0.09,"entry_price":500,"stop_loss":480,"take_profit":530,"confidence":0.81,"reasoning":"META showing strong momentum post-earnings. AI capex narrative positive. Unusual call activity at 530 strike. Risk: broader tech rotation."}',
 NOW() - INTERVAL '6 hours');

-- Link some ai_decisions to trades
UPDATE ai_decisions SET related_trade_id = (SELECT id FROM trades WHERE asset = 'BTC/USDT' AND status = 'open' LIMIT 1) WHERE decision_type = 'analyst' AND trader = 'crypto';
UPDATE ai_decisions SET related_trade_id = (SELECT id FROM trades WHERE asset = 'META' AND status = 'open' LIMIT 1) WHERE decision_type = 'analyst' AND trader = 'stocks';

-- Daily performance (last 7 days per trader)
INSERT INTO daily_performance (date, trader, trades_count, winning_trades, losing_trades, gross_pnl, net_pnl, total_inference_cost, total_trading_fees, total_slippage, max_drawdown_pct, win_rate, avg_trade_pnl, sharpe_ratio) VALUES
-- Crypto
(CURRENT_DATE - 7, 'crypto', 8, 5, 3, 85.00, 72.50, 0.95, 8.20, 3.35, 1.2, 0.625, 9.06, 1.8),
(CURRENT_DATE - 6, 'crypto', 12, 8, 4, 145.00, 128.30, 1.35, 11.50, 3.85, 0.8, 0.667, 10.69, 2.1),
(CURRENT_DATE - 5, 'crypto', 6, 3, 3, -42.00, -55.80, 0.85, 9.20, 3.75, 2.5, 0.500, -9.30, -0.5),
(CURRENT_DATE - 4, 'crypto', 10, 7, 3, 168.00, 150.20, 1.20, 12.80, 3.80, 0.6, 0.700, 15.02, 2.5),
(CURRENT_DATE - 3, 'crypto', 9, 6, 3, 110.00, 95.50, 1.10, 10.40, 3.00, 0.9, 0.667, 10.61, 1.9),
(CURRENT_DATE - 2, 'crypto', 7, 4, 3, -28.00, -42.50, 0.90, 9.80, 3.80, 1.8, 0.571, -6.07, -0.3),
(CURRENT_DATE - 1, 'crypto', 11, 8, 3, 195.00, 178.40, 1.50, 11.20, 3.90, 0.4, 0.727, 16.22, 2.8),
-- Polymarket
(CURRENT_DATE - 7, 'polymarket', 3, 2, 1, 45.00, 40.20, 0.30, 3.20, 1.30, 0.5, 0.667, 13.40, 1.5),
(CURRENT_DATE - 6, 'polymarket', 4, 3, 1, 92.00, 86.50, 0.45, 3.80, 1.25, 0.3, 0.750, 21.63, 2.3),
(CURRENT_DATE - 5, 'polymarket', 2, 1, 1, -15.00, -19.80, 0.25, 2.80, 1.75, 1.8, 0.500, -9.90, -0.8),
(CURRENT_DATE - 4, 'polymarket', 5, 4, 1, 135.00, 128.80, 0.55, 4.20, 1.45, 0.2, 0.800, 25.76, 3.0),
(CURRENT_DATE - 3, 'polymarket', 3, 2, 1, 68.00, 63.20, 0.35, 3.40, 1.05, 0.4, 0.667, 21.07, 2.0),
(CURRENT_DATE - 2, 'polymarket', 4, 3, 1, 55.00, 49.50, 0.40, 3.60, 1.50, 0.6, 0.750, 12.38, 1.7),
(CURRENT_DATE - 1, 'polymarket', 5, 4, 1, 125.00, 119.80, 0.50, 3.50, 1.20, 0.1, 0.800, 23.96, 2.9),
-- Stocks
(CURRENT_DATE - 7, 'stocks', 2, 1, 1, 12.00, 7.50, 0.22, 0, 4.28, 0.8, 0.500, 3.75, 0.6),
(CURRENT_DATE - 6, 'stocks', 3, 2, 1, 48.00, 42.80, 0.32, 0, 4.88, 0.5, 0.667, 14.27, 1.8),
(CURRENT_DATE - 5, 'stocks', 2, 2, 0, 65.00, 60.20, 0.25, 0, 4.55, 0, 1.000, 30.10, 3.2),
(CURRENT_DATE - 4, 'stocks', 3, 2, 1, 38.00, 32.50, 0.30, 0, 5.20, 0.7, 0.667, 10.83, 1.4),
(CURRENT_DATE - 3, 'stocks', 2, 1, 1, -18.00, -23.80, 0.28, 0, 5.52, 1.5, 0.500, -11.90, -0.9),
(CURRENT_DATE - 2, 'stocks', 3, 2, 1, 42.00, 36.50, 0.35, 0, 5.15, 0.6, 0.667, 12.17, 1.6),
(CURRENT_DATE - 1, 'stocks', 4, 3, 1, 72.00, 65.80, 0.45, 0, 5.75, 0.3, 0.750, 16.45, 2.2);

-- Strategist plan
INSERT INTO strategist_plans (goal_id, plan_date, allocations, trader_configs, daily_target, reasoning, goal_feasibility, inference_cost, tokens_in, tokens_out)
VALUES (
    (SELECT id FROM goals WHERE is_active = true LIMIT 1),
    CURRENT_DATE,
    '{"polymarket": 0.29, "crypto": 0.51, "stocks": 0.20}',
    '{"crypto": {"max_position_pct": 0.08, "max_concurrent_positions": 12, "target_trades_per_day": [10, 30], "scan_interval_seconds": 30, "max_daily_drawdown_pct": 0.05, "confidence_threshold": 0.70, "stop_loss_pct": 0.03, "use_opus_for_analysis": true, "opus_threshold_usd": 500, "max_inference_budget": 5.00}, "polymarket": {"max_position_pct": 0.12, "max_concurrent_positions": 8, "target_trades_per_day": [3, 10], "scan_interval_seconds": 120, "max_daily_drawdown_pct": 0.04, "confidence_threshold": 0.72, "stop_loss_pct": 0.10, "use_opus_for_analysis": true, "opus_threshold_usd": 300, "max_inference_budget": 3.00}, "stocks": {"max_position_pct": 0.10, "max_concurrent_positions": 5, "target_trades_per_day": [2, 6], "scan_interval_seconds": 300, "max_daily_drawdown_pct": 0.03, "confidence_threshold": 0.75, "stop_loss_pct": 0.04, "use_opus_for_analysis": true, "opus_threshold_usd": 800, "max_inference_budget": 2.00}}',
    85.50,
    'System performing well with 8.5% return in 14 days, tracking ahead of compound growth curve. Crypto allocation increased to 51% due to strong BTC momentum and favorable funding rates. Polymarket at 29% — excellent edge on political and macro event markets. Stocks conservative at 20% pending earnings season clarity. Daily target of $85.50 achievable at current win rates. Inference budget well within 2% of daily target.',
    'on_track',
    0.28, 8200, 2100
);
