# Daily Strategy Planning Session

**Date**: {current_date}

---

## Portfolio State

| Metric | Value |
|---|---|
| Total Balance | ${total_balance:.2f} |
| Available Balance | ${available_balance:.2f} |
| Allocated Balance | ${allocated_balance:.2f} |
| Unrealized P&L | ${unrealized_pnl:.2f} |
| Realized P&L (Today) | ${realized_pnl_today:.2f} |
| Realized P&L (Total) | ${realized_pnl_total:.2f} |
| Open Positions | {open_position_count} |
| Win Rate | {win_rate:.1%} |
| Current Drawdown | {current_drawdown:.2%} |
| Max Drawdown | {max_drawdown:.2%} |
| Peak Balance | ${peak_balance:.2f} |
| Sharpe Ratio | {sharpe_ratio} |
| Sortino Ratio | {sortino_ratio} |
| Profit Factor | {profit_factor} |

### Trade Statistics
- Total Trades: {total_trades}
- Winning: {winning_trades} | Losing: {losing_trades}
- Avg Win: ${avg_win:.2f} | Avg Loss: ${avg_loss:.2f}
- Largest Win: ${largest_win:.2f} | Largest Loss: ${largest_loss:.2f}
- Current Streak: {current_streak} | Losing Streak: {losing_streak}

### Current Allocation by Market
{allocation_by_market}

### Open Positions
{open_positions}

### Daily P&L History (Last 14 Days)
{daily_pnl_history}

### Costs
- Total Fees Paid: ${total_fees_paid:.2f}
- Total Inference Cost: ${total_inference_cost:.2f}

---

## Available Opportunities ({opportunities_count})

{opportunities_summary}

## Normalized Signals ({signals_count})

{signals_summary}

---

## Recent Trade Results (Last 20)

{recent_trade_results}

---

## Configuration

- Trader: {config_name} ({config_mode} mode)
- Active Markets: {config_markets}
- Target Balance: ${target_balance}
- Target Date: {target_date}
- Max Daily Drawdown: {max_daily_drawdown_pct:.1%}
- Kill Switch Drawdown: {kill_switch_drawdown_pct:.1%}
- Max Single Trade: {max_single_trade_pct:.1%} of balance
- Max Concurrent Positions: {max_concurrent_positions}
- Max Daily Inference Cost: ${max_daily_inference_cost:.2f}
- Inference Cost Today: ${inference_cost_today:.2f}
- Budget Remaining: ${budget_remaining}

---

## Your Task

Based on the above data, produce your daily strategic plan as a JSON object. Consider:

1. **Are we on track** to reach the target balance by the target date? What daily return rate do we need?
2. **What is the current risk environment?** Are we in a drawdown? Is the losing streak concerning?
3. **Which markets** should we focus on today? Where have we had the most edge recently?
4. **Which open positions** should be closed, adjusted, or left alone?
5. **What new opportunities** look promising enough to warrant Analyst (Opus) evaluation?
6. **How aggressively** should we trade today? Set the risk posture and position sizing guidance.
7. **Budget management**: How much of the remaining inference budget should we allocate to screening vs. analysis?

Respond with ONLY valid JSON matching the schema from your system prompt.
