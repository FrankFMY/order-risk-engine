# Order Risk Engine

A dependency-free, Decimal-only Python library for deterministic pre-trade sizing and portfolio risk gates. It converts a caller-supplied trade proposal into an accepted order intent or a bounded rejection code.

## What it enforces

- finite positive entry/stop/target geometry;
- long/short direction and ordered target invariants;
- instrument allowlists, minimum score, and short-entry policy;
- daily realized-loss and open-position limits;
- per-entry and aggregate stop-risk caps;
- per-position, aggregate, and available-entry notional caps;
- exact quantity-step flooring that never rounds risk upward;
- minimum/maximum quantity and minimum notional;
- malformed, non-finite, contradictory, and excessive-magnitude inputs.

All monetary, price, quantity, percentage, and risk values are `decimal.Decimal`. Runtime dependencies: none.

## Installation

```bash
pip install https://github.com/FrankFMY/order-risk-engine/releases/download/v0.1.0/order_risk_engine-0.1.0-py3-none-any.whl
```

## Example

```python
from decimal import Decimal as D
from order_risk_engine import AccountState, InstrumentRules, RiskLimits, TradeSignal, evaluate_entry

decision = evaluate_entry(
    TradeSignal(
        instrument="BTC-USD",
        side="long",
        entry=D("100"),
        stop=D("90"),
        targets=(D("110"), D("130")),
        score=D("90"),
    ),
    AccountState(equity=D("10000"), available_entry_notional=D("1000")),
    InstrumentRules(
        quantity_step=D("0.01"),
        minimum_quantity=D("0.01"),
        maximum_quantity=D("1000"),
        min_notional=D("5"),
    ),
    RiskLimits(
        risk_percent=D("1.5"),
        max_risk=None,
        allowed_instruments=frozenset({"BTC-USD"}),
    ),
)

if decision.accepted:
    print(decision.intent)
else:
    print(decision.code)
```

## Design boundaries

- The library never contacts an exchange, reads balances, sends an order, places a stop, or stores a journal.
- Inputs are facts supplied by the caller. The engine cannot prove that account state, margin, prices, rules, or proposed stops are current.
- Quantity is floored to the declared step. Exchange-specific price ticks, fee reserves, leverage tiers, liquidation models, contract multipliers, and margin modes remain adapter-owned.
- An accepted intent is not proof that an exchange will accept or fill it.
- This package is not a trading strategy, signal generator, backtest, profit forecast, financial advice, or guarantee against loss.

## Verification

The suite includes exact Decimal examples, malformed/non-finite input cases, direction and aggregate-limit gates, minimum quantity/notional behavior, and 500 seeded randomized accepted-order invariants proving declared caps are never exceeded.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --editable . ruff build twine
python -m ruff format --check .
python -m ruff check .
python -m unittest discover -s tests -v
python -m build
python -m twine check dist/*
```

## Author

**Artem Prianishnikov** — https://github.com/FrankFMY

## License

MIT © 2026 Artem Prianishnikov.
