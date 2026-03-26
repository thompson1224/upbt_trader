from apps.risk_service.guards.pre_trade_guard import AccountState, PreTradeRiskGuard


def _account_state(**overrides):
    state = {
        "total_equity": 1_000_000.0,
        "available_krw": 100_000.0,
        "daily_pnl": 0.0,
        "consecutive_losses": 0,
        "open_positions_count": 0,
        "market_warning": False,
    }
    state.update(overrides)
    return AccountState(**state)


def test_buy_is_rejected_when_daily_loss_limit_is_reached():
    guard = PreTradeRiskGuard()

    decision = guard.evaluate(
        side="buy",
        market="KRW-BTC",
        suggested_qty=1.0,
        entry_price=1_000.0,
        stop_loss=970.0,
        account=_account_state(daily_pnl=-60_000.0),
    )

    assert decision.approved is False
    assert "Daily loss limit reached" in decision.reason


def test_sell_is_not_rejected_when_daily_loss_limit_is_reached():
    guard = PreTradeRiskGuard()

    decision = guard.evaluate(
        side="sell",
        market="KRW-BTC",
        suggested_qty=1.0,
        entry_price=1_000.0,
        stop_loss=970.0,
        account=_account_state(daily_pnl=-60_000.0),
    )

    assert decision.approved is True
    assert decision.reason == "Approved"


def test_buy_is_rejected_when_max_consecutive_losses_is_reached():
    guard = PreTradeRiskGuard()

    decision = guard.evaluate(
        side="buy",
        market="KRW-BTC",
        suggested_qty=1.0,
        entry_price=1_000.0,
        stop_loss=970.0,
        account=_account_state(consecutive_losses=PreTradeRiskGuard.MAX_CONSECUTIVE_LOSSES),
    )

    assert decision.approved is False
    assert "Max consecutive losses reached" in decision.reason


def test_sell_is_not_rejected_when_max_consecutive_losses_is_reached():
    guard = PreTradeRiskGuard()

    decision = guard.evaluate(
        side="sell",
        market="KRW-BTC",
        suggested_qty=1.0,
        entry_price=1_000.0,
        stop_loss=970.0,
        account=_account_state(consecutive_losses=PreTradeRiskGuard.MAX_CONSECUTIVE_LOSSES),
    )

    assert decision.approved is True
    assert decision.reason == "Approved"
