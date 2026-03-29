# AI Trading System

Autonomous trading system powered by Claude. Screens opportunities across crypto, stocks, and prediction markets, performs deep analysis, and executes trades with built-in risk management and cost tracking.

## Architecture

- **Screener** (Sonnet) -- scans markets for opportunities at low cost
- **Analyst** (Opus) -- deep analysis on high-conviction opportunities with pre-call cost gate
- **Strategist** -- portfolio-level allocation and rebalancing decisions
- **Risk Manager** -- NEV filtering, position sizing, drawdown checks
- **Safety Rails** -- hard-coded limits that cannot be overridden by AI reasoning
- **Cost Tracker** -- real-time inference cost accounting with daily budgets

## Setup

### Prerequisites

- Python 3.12+
- Docker and Docker Compose
- Anthropic API key

### Quick Start

```bash
# Clone and enter the project
cd Trader

# Copy environment template and fill in API keys
cp .env.example .env

# Start infrastructure (Postgres, TimescaleDB, Redis)
docker compose -f infra/docker-compose.yml up -d

# Install Python dependencies
pip install -e ".[dev]"

# Run database migrations
alembic upgrade head

# Start in paper trading mode
python -m packages.trader_crypto.runner --mode paper
```

### Docker Compose (full stack)

```bash
# Start everything: database, Redis, API, trader, dashboard
docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml up -d
```

## Configuration

Configuration is loaded from `config.yaml` and environment variables (`.env`). Environment variables take precedence.

Key settings:

| Variable | Description | Default |
|---|---|---|
| `AI_ANTHROPIC_API_KEY` | Anthropic API key | (required) |
| `AI_DAILY_COST_LIMIT_USD` | Max daily inference spend | `50.00` |
| `GOAL_STARTING_CAPITAL` | Initial portfolio balance | `1000.0` |
| `GOAL_TARGET_CAPITAL` | Target portfolio balance | `10000.0` |
| `GOAL_TIME_HORIZON_DAYS` | Days to reach target | `90` |
| `DB_HOST` | PostgreSQL host | `localhost` |
| `REDIS_HOST` | Redis host | `localhost` |

## Paper Trading

Paper trading mode simulates all order execution without real money. It is the default mode and is required before live trading.

```bash
# Via Python
python -m packages.trader_crypto.runner --mode paper

# Via API
curl -X POST http://localhost:8000/api/controls/start --json '{"mode": "paper"}'
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=packages --cov-report=html

# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest tests/integration/

# Run a specific test file
pytest tests/unit/test_risk_manager.py -v
```
