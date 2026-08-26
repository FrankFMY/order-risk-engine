from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, DecimalException, localcontext
from typing import Literal, cast

Side = Literal["long", "short"]
_MAX_ABS = Decimal("1e50")
_MAX_SIGNIFICANT_DIGITS = 100
_MAX_EXPONENT_ABS = 100
_CALCULATION_PRECISION = 256
_HUNDRED = Decimal("100")
_INSTRUMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}")


@dataclass(frozen=True, slots=True)
class TradeSignal:
    instrument: str
    side: str
    entry: Decimal
    stop: Decimal
    targets: tuple[Decimal, ...]
    score: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class AccountState:
    equity: Decimal
    daily_realized_pnl: Decimal = Decimal("0")
    open_positions: int = 0
    open_notional: Decimal = Decimal("0")
    open_risk: Decimal = Decimal("0")
    available_entry_notional: Decimal | None = None


@dataclass(frozen=True, slots=True)
class InstrumentRules:
    quantity_step: Decimal
    minimum_quantity: Decimal
    maximum_quantity: Decimal
    price_tick: Decimal = Decimal("0")
    min_notional: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class RiskLimits:
    risk_percent: Decimal = Decimal("0.25")
    max_risk: Decimal | None = Decimal("5")
    max_daily_loss_percent: Decimal = Decimal("1")
    max_open_positions: int = 1
    max_position_notional_percent: Decimal = Decimal("50")
    max_total_notional_percent: Decimal = Decimal("150")
    max_total_risk_percent: Decimal = Decimal("9")
    min_score: Decimal = Decimal("75")
    allowed_instruments: frozenset[str] = frozenset()
    allow_shorts: bool = False


@dataclass(frozen=True, slots=True)
class OrderIntent:
    instrument: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    notional: Decimal
    stop_risk: Decimal


@dataclass(frozen=True, slots=True)
class RiskDecision:
    accepted: bool
    code: str
    reason: str
    intent: OrderIntent | None = None


def _decimal(value: object, name: str, *, minimum: Decimal | None = None, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    if value.copy_abs() > _MAX_ABS:
        raise ValueError(f"{name} exceeds the supported magnitude")
    parts = value.as_tuple()
    exponent = parts.exponent
    if not isinstance(exponent, int):
        raise ValueError(f"{name} has an unsupported exponent")
    if len(parts.digits) > _MAX_SIGNIFICANT_DIGITS or abs(exponent) > _MAX_EXPONENT_ABS:
        raise ValueError(f"{name} exceeds the supported precision")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _percentage(value: object, name: str, *, allow_zero: bool = False, maximum: Decimal | None = None) -> Decimal:
    parsed = _decimal(value, name, minimum=Decimal("0"))
    if not allow_zero and parsed == 0:
        raise ValueError(f"{name} must be positive")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return parsed


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    value = _decimal(value, "value", minimum=Decimal("0"))
    step = _decimal(step, "step", positive=True)
    with localcontext() as context:
        context.prec = _CALCULATION_PRECISION
        context.rounding = ROUND_DOWN
        units = (value / step).to_integral_value(rounding=ROUND_DOWN)
        result = units * step
        if result > value:
            raise ArithmeticError("step flooring exceeded the input")
        return result


def _validate(
    signal: TradeSignal,
    account: AccountState,
    rules: InstrumentRules,
    limits: RiskLimits,
) -> tuple[str, Side]:
    if not isinstance(signal.instrument, str) or not isinstance(signal.side, str):
        raise ValueError("instrument and side must be strings")
    if not isinstance(signal.targets, tuple):
        raise ValueError("targets must be a tuple")
    instrument = signal.instrument.strip().upper()
    if _INSTRUMENT.fullmatch(instrument) is None:
        raise ValueError("instrument must be a bounded portable identifier")
    side = signal.side.strip().lower()
    if side not in {"long", "short"}:
        raise ValueError("side must be long or short")
    validated_side = cast(Side, side)
    entry = _decimal(signal.entry, "entry", positive=True)
    stop = _decimal(signal.stop, "stop", positive=True)
    _decimal(signal.score, "score")
    if entry == stop:
        raise ValueError("stop distance must be non-zero")
    if not signal.targets:
        raise ValueError("at least one target is required")
    targets = tuple(_decimal(target, "target", positive=True) for target in signal.targets)
    if validated_side == "long":
        if (
            stop >= entry
            or targets[0] <= entry
            or any(left > right for left, right in zip(targets, targets[1:], strict=False))
        ):
            raise ValueError("long stop and targets are inconsistent")
    else:
        if (
            stop <= entry
            or targets[0] >= entry
            or any(left < right for left, right in zip(targets, targets[1:], strict=False))
        ):
            raise ValueError("short stop and targets are inconsistent")

    _decimal(account.equity, "equity", positive=True)
    _decimal(account.daily_realized_pnl, "daily_realized_pnl")
    _decimal(account.open_notional, "open_notional", minimum=Decimal("0"))
    _decimal(account.open_risk, "open_risk", minimum=Decimal("0"))
    if account.available_entry_notional is not None:
        _decimal(account.available_entry_notional, "available_entry_notional", minimum=Decimal("0"))
    if type(account.open_positions) is not int or account.open_positions < 0:
        raise ValueError("open_positions must be a non-negative integer")

    step = _decimal(rules.quantity_step, "quantity_step", positive=True)
    minimum_quantity = _decimal(rules.minimum_quantity, "minimum_quantity", positive=True)
    maximum_quantity = _decimal(rules.maximum_quantity, "maximum_quantity", positive=True)
    _decimal(rules.price_tick, "price_tick", minimum=Decimal("0"))
    _decimal(rules.min_notional, "min_notional", minimum=Decimal("0"))
    if minimum_quantity > maximum_quantity or step > maximum_quantity:
        raise ValueError("quantity rules are contradictory")

    _percentage(limits.risk_percent, "risk_percent", maximum=_HUNDRED)
    if limits.max_risk is not None:
        _decimal(limits.max_risk, "max_risk", positive=True)
    _percentage(limits.max_daily_loss_percent, "max_daily_loss_percent", allow_zero=True, maximum=_HUNDRED)
    _percentage(limits.max_position_notional_percent, "max_position_notional_percent")
    _percentage(limits.max_total_notional_percent, "max_total_notional_percent")
    _percentage(limits.max_total_risk_percent, "max_total_risk_percent", allow_zero=True)
    _decimal(limits.min_score, "min_score")
    if type(limits.max_open_positions) is not int or limits.max_open_positions < 1:
        raise ValueError("max_open_positions must be a positive integer")
    if not isinstance(limits.allowed_instruments, frozenset) or any(
        not isinstance(item, str) for item in limits.allowed_instruments
    ):
        raise ValueError("allowed_instruments must be a frozenset of strings")
    if type(limits.allow_shorts) is not bool:
        raise ValueError("allow_shorts must be a boolean")
    normalized_allowed = frozenset(item.strip().upper() for item in limits.allowed_instruments)
    if any(_INSTRUMENT.fullmatch(item) is None for item in normalized_allowed):
        raise ValueError("allowed_instruments contains an invalid identifier")
    return instrument, validated_side


def _reject(code: str, reason: str) -> RiskDecision:
    return RiskDecision(False, code, reason)


def evaluate_entry(
    signal: TradeSignal,
    account: AccountState,
    rules: InstrumentRules,
    limits: RiskLimits,
) -> RiskDecision:
    try:
        if not isinstance(signal, TradeSignal) or not isinstance(account, AccountState):
            raise ValueError("signal and account must use the declared contracts")
        if not isinstance(rules, InstrumentRules) or not isinstance(limits, RiskLimits):
            raise ValueError("rules and limits must use the declared contracts")
        instrument, side = _validate(signal, account, rules, limits)
        normalized_allowed = frozenset(item.strip().upper() for item in limits.allowed_instruments)
        if normalized_allowed and instrument not in normalized_allowed:
            return _reject("instrument_not_allowed", "instrument is not allowed")
        if side == "short" and not limits.allow_shorts:
            return _reject("shorts_disabled", "short entries are disabled")
        if signal.score < limits.min_score:
            return _reject("score_below_minimum", "signal score is below the configured minimum")
        if account.open_positions >= limits.max_open_positions:
            return _reject("position_limit", "open position limit reached")

        with localcontext() as context:
            context.prec = _CALCULATION_PRECISION
            context.rounding = ROUND_DOWN
            if limits.max_daily_loss_percent > 0:
                daily_limit = account.equity * limits.max_daily_loss_percent / _HUNDRED
                if account.daily_realized_pnl <= -daily_limit:
                    return _reject("daily_loss_limit", "daily realized loss limit reached")

            risk_distance = abs(signal.entry - signal.stop)
            risk_budget = account.equity * limits.risk_percent / _HUNDRED
            if limits.max_risk is not None:
                risk_budget = min(risk_budget, limits.max_risk)
            if limits.max_total_risk_percent > 0:
                maximum_total_risk = account.equity * limits.max_total_risk_percent / _HUNDRED
                available_risk = maximum_total_risk - account.open_risk
                if available_risk <= 0:
                    return _reject("total_risk_limit", "aggregate stop-risk limit reached")
                risk_budget = min(risk_budget, available_risk)

            position_notional_cap = account.equity * limits.max_position_notional_percent / _HUNDRED
            total_notional_cap = account.equity * limits.max_total_notional_percent / _HUNDRED
            available_total_notional = total_notional_cap - account.open_notional
            if available_total_notional <= 0:
                return _reject("total_notional_limit", "aggregate notional limit reached")
            caps = [position_notional_cap, available_total_notional]
            if account.available_entry_notional is not None:
                if account.available_entry_notional <= 0:
                    return _reject("no_available_notional", "no entry notional is available")
                caps.append(account.available_entry_notional)

            raw_quantity = min(
                risk_budget / risk_distance, *(cap / signal.entry for cap in caps), rules.maximum_quantity
            )
            quantity = floor_to_step(raw_quantity, rules.quantity_step)
            if quantity <= 0:
                return _reject("below_min_quantity", "quantity must be positive")
            if quantity < rules.minimum_quantity:
                return _reject("below_min_quantity", "quantity is below the instrument minimum")
            if quantity > rules.maximum_quantity or quantity % rules.quantity_step != 0:
                return _reject("invalid_input", "quantity violates the instrument step or maximum")
            notional = quantity * signal.entry
            stop_risk = quantity * risk_distance
            if stop_risk > risk_budget:
                return _reject("risk_limit", "sized stop risk exceeds the available risk budget")
            if notional > position_notional_cap or notional > available_total_notional:
                return _reject("notional_limit", "sized notional exceeds a configured cap")
            if account.available_entry_notional is not None and notional > account.available_entry_notional:
                return _reject("notional_limit", "sized notional exceeds available entry notional")
            if notional < rules.min_notional:
                return _reject("below_min_notional", "notional is below the instrument minimum")
            return RiskDecision(
                True,
                "accepted",
                "entry satisfies all configured risk limits",
                OrderIntent(
                    instrument=instrument,
                    side="buy" if side == "long" else "sell",
                    quantity=quantity,
                    notional=notional,
                    stop_risk=stop_risk,
                ),
            )
    except (AttributeError, DecimalException, TypeError, ValueError, ArithmeticError):
        return _reject("invalid_input", "one or more inputs violate the numeric or structural contract")


__all__ = [
    "AccountState",
    "InstrumentRules",
    "OrderIntent",
    "RiskDecision",
    "RiskLimits",
    "TradeSignal",
    "evaluate_entry",
    "floor_to_step",
]
