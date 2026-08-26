from __future__ import annotations

import random
import unittest
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from order_risk_engine import (
    AccountState,
    InstrumentRules,
    RiskLimits,
    TradeSignal,
    evaluate_entry,
    floor_to_step,
)

D = Decimal


class OrderRiskEngineTest(unittest.TestCase):
    def test_available_cap_and_stop_distance_produce_exact_decimal_quantity(self):
        decision = evaluate_entry(
            TradeSignal("BTC-USD", "long", D("100"), D("90"), (D("110"), D("130")), D("90")),
            AccountState(D("10000"), available_entry_notional=D("1000")),
            InstrumentRules(D("0.01"), D("0.01"), D("1000"), min_notional=D("5")),
            RiskLimits(risk_percent=D("1.5"), max_risk=None, allowed_instruments=frozenset({"BTC-USD"})),
        )
        self.assertTrue(decision.accepted)
        assert decision.intent is not None
        self.assertEqual(decision.intent.quantity, D("10"))
        self.assertEqual(decision.intent.notional, D("1000"))
        self.assertEqual(decision.intent.stop_risk, D("100"))

    def test_rejects_non_finite_and_invalid_rules_before_sizing(self):
        base_signal = TradeSignal("BTC-USD", "long", D("100"), D("90"), (D("110"),), D("90"))
        cases = [
            (
                TradeSignal("BTC-USD", "long", D("NaN"), D("90"), (D("110"),), D("90")),
                AccountState(D("1000")),
                InstrumentRules(D("0.01"), D("0.01"), D("10")),
            ),
            (base_signal, AccountState(D("Infinity")), InstrumentRules(D("0.01"), D("0.01"), D("10"))),
            (base_signal, AccountState(D("1000")), InstrumentRules(D("0"), D("0.01"), D("10"))),
            (base_signal, AccountState(D("1000")), InstrumentRules(D("0.01"), D("2"), D("1"))),
        ]
        for signal, account, rules in cases:
            with self.subTest(signal=signal, account=account, rules=rules):
                decision = evaluate_entry(signal, account, rules, RiskLimits())
                self.assertFalse(decision.accepted)
                self.assertEqual(decision.code, "invalid_input")

    def test_enforces_direction_targets_short_policy_score_and_instrument_allowlist(self):
        account = AccountState(D("1000"))
        rules = InstrumentRules(D("0.01"), D("0.01"), D("100"))
        limits = RiskLimits(min_score=D("75"), allowed_instruments=frozenset({"BTC-USD"}), allow_shorts=False)
        cases = [
            TradeSignal("ETH-USD", "long", D("100"), D("90"), (D("110"),), D("90")),
            TradeSignal("BTC-USD", "sideways", D("100"), D("90"), (D("110"),), D("90")),
            TradeSignal("BTC-USD", "short", D("100"), D("110"), (D("90"),), D("90")),
            TradeSignal("BTC-USD", "long", D("100"), D("90"), (D("99"),), D("90")),
            TradeSignal("BTC-USD", "long", D("100"), D("90"), (D("110"),), D("74.99")),
        ]
        for signal in cases:
            with self.subTest(signal=signal):
                self.assertFalse(evaluate_entry(signal, account, rules, limits).accepted)

    def test_enforces_daily_loss_position_aggregate_risk_and_notional_caps(self):
        signal = TradeSignal("BTC-USD", "long", D("100"), D("90"), (D("110"),), D("100"))
        rules = InstrumentRules(D("0.01"), D("0.01"), D("100"))
        limits = RiskLimits(
            risk_percent=D("1.5"),
            max_daily_loss_percent=D("1"),
            max_open_positions=1,
            max_total_risk_percent=D("9"),
            max_total_notional_percent=D("150"),
        )
        rejected_accounts = [
            AccountState(D("1000"), daily_realized_pnl=D("-10")),
            AccountState(D("1000"), open_positions=1),
            AccountState(D("1000"), open_risk=D("90")),
            AccountState(D("1000"), open_notional=D("1500")),
            AccountState(D("1000"), available_entry_notional=D("0")),
        ]
        for account in rejected_accounts:
            with self.subTest(account=account):
                self.assertFalse(evaluate_entry(signal, account, rules, limits).accepted)

    def test_enforces_minimum_quantity_and_notional(self):
        decision = evaluate_entry(
            TradeSignal("TEST", "long", D("1"), D("0.5"), (D("1.5"),), D("100")),
            AccountState(D("10")),
            InstrumentRules(D("0.1"), D("0.1"), D("100"), min_notional=D("50")),
            RiskLimits(risk_percent=D("1"), max_risk=D("1")),
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.code, "below_min_notional")

    def test_floor_to_step_is_exact_and_never_rounds_risk_up(self):
        self.assertEqual(floor_to_step(D("1.239"), D("0.01")), D("1.23"))
        self.assertEqual(floor_to_step(D("0.0009"), D("0.001")), D("0"))

    def test_randomized_accepted_orders_never_exceed_declared_caps(self):
        randomizer = random.Random(42)
        rules = InstrumentRules(D("0.001"), D("0.001"), D("100000"), min_notional=D("1"))
        limits = RiskLimits(
            risk_percent=D("1.25"),
            max_risk=D("250"),
            max_position_notional_percent=D("40"),
            max_total_notional_percent=D("120"),
            max_total_risk_percent=D("6"),
        )
        for _ in range(500):
            equity = D(str(randomizer.randint(100, 100000)))
            entry = D(str(randomizer.randint(1, 10000)))
            distance = D(str(randomizer.randint(1, max(1, int(entry)))))
            stop = max(D("0.0001"), entry - distance)
            account = AccountState(
                equity,
                open_notional=equity * D(str(randomizer.random() * 0.5)),
                open_risk=equity * D(str(randomizer.random() * 0.02)),
            )
            decision = evaluate_entry(
                TradeSignal("ASSET", "long", entry, stop, (entry + distance,), D("100")),
                account,
                rules,
                limits,
            )
            if not decision.accepted:
                continue
            assert decision.intent is not None
            self.assertLessEqual(
                decision.intent.stop_risk + account.open_risk, equity * limits.max_total_risk_percent / D("100")
            )
            self.assertLessEqual(decision.intent.notional, equity * limits.max_position_notional_percent / D("100"))
            self.assertLessEqual(
                decision.intent.notional + account.open_notional, equity * limits.max_total_notional_percent / D("100")
            )

    def test_never_accepts_zero_quantity(self):
        decision = evaluate_entry(
            TradeSignal("BTC-USD", "long", D("100"), D("90"), (D("110"),), D("100")),
            AccountState(D("1")),
            InstrumentRules(D("1"), D("0"), D("100"), min_notional=D("0")),
            RiskLimits(risk_percent=D("0.25"), max_risk=None),
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.code, "invalid_input")

    def test_high_precision_sizing_never_exceeds_exact_caps_or_depends_on_caller_rounding(self):
        entry = D("1.000000000000000000000000000000000000000000000000001")
        step = D("0." + "1" * 49 + "55")
        signal = TradeSignal("ASSET", "long", entry, D("0.5"), (D("2"),), D("100"))
        account = AccountState(D("100"), available_entry_notional=D("1"))
        rules = InstrumentRules(step, step, D("100"))
        limits = RiskLimits(risk_percent=D("100"), max_risk=None, max_position_notional_percent=D("100"))
        with localcontext() as context:
            context.prec = 28
            context.rounding = ROUND_HALF_EVEN
            decision = evaluate_entry(signal, account, rules, limits)
        if decision.accepted:
            assert decision.intent is not None
            with localcontext() as exact:
                exact.prec = 256
                self.assertLessEqual(decision.intent.quantity * entry, D("1"))
                self.assertEqual(decision.intent.quantity % step, D("0"))
                self.assertLessEqual(decision.intent.quantity, D("1") / entry)
        with localcontext() as context:
            context.prec = 28
            context.rounding = ROUND_HALF_EVEN
            floored = floor_to_step(step, step)
        with localcontext() as exact:
            exact.prec = 256
            self.assertLessEqual(floored, step)
            self.assertEqual(floored % step, D("0"))

    def test_malformed_structural_values_return_bounded_invalid_input(self):
        signal = TradeSignal("BTC-USD", "long", D("100"), D("90"), (D("110"),), D("100"))
        account = AccountState(D("1000"))
        rules = InstrumentRules(D("0.01"), D("0.01"), D("100"))
        limits = RiskLimits()
        malformed = [
            (TradeSignal(None, "long", D("100"), D("90"), (D("110"),), D("100")), account, rules, limits),  # type: ignore[arg-type]
            (TradeSignal("BTC-USD", None, D("100"), D("90"), (D("110"),), D("100")), account, rules, limits),  # type: ignore[arg-type]
            (signal, account, rules, RiskLimits(allowed_instruments=frozenset({None}))),  # type: ignore[arg-type]
            (None, account, rules, limits),  # type: ignore[arg-type]
        ]
        for candidate_signal, candidate_account, candidate_rules, candidate_limits in malformed:
            with self.subTest(signal=candidate_signal, limits=candidate_limits):
                decision = evaluate_entry(candidate_signal, candidate_account, candidate_rules, candidate_limits)
                self.assertFalse(decision.accepted)
                self.assertEqual(decision.code, "invalid_input")


if __name__ == "__main__":
    unittest.main()
