"""标准领域事件与旧 API/Service 的集成验收。"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.errors import ConflictError
from app.domain import Signal
from app.domain.enums import AccountStatus, OrderSide, OrderStatus, PositionStatus
from app.domain.events import (
    AccountSettled, FillRecorded, OrderCreated, PositionClosed, PositionOpened,
    RiskEvaluated, SignalGenerated,
)
from app.domain.validation import DomainValidationError
from app.repositories.memory import InMemoryDatabase
from app.services.account_service import AccountService
from app.services.market_service import MarketDataService
from app.services.order_service import OrderService
from app.services.position_service import PositionService
from app.strategy.base import Strategy
from app.strategy.ma_cross import MovingAverageCrossoverStrategy
from app.strategy.runner import StrategyRunner

D = Decimal


def make_services():
    db = InMemoryDatabase()
    account = AccountService(db).create(name="event-test", initial_balance=D("100000"))
    return db, account, OrderService(db), MarketDataService(db), PositionService(db)


def create_order(orders, account):
    return orders.create(account.id, symbol="XAUUSD", side=OrderSide.BUY,
                         volume=D("0.1"), requested_price=D("100"))


def test_strategy_to_settlement_keeps_identity_causality_and_historical_state() -> None:
    db, account, orders, market, positions = make_services()
    runner = StrategyRunner(db, MovingAverageCrossoverStrategy(fast_window=2, slow_window=3),
                            account.id, strategy_id="ma-xau-1")
    for price in ("100", "100", "100"):
        assert runner.on_quote("XAUUSD", D(price)) is None
    order = runner.on_quote("XAUUSD", D("110"))
    assert order is not None
    _, position = orders.fill(order.id)
    market.update_quote("XAUUSD", D("120"))
    positions.close(position.id)

    chain = [e for e in db.events if e.correlation_id == order.signal_id]
    assert [e.event_type for e in chain] == [
        "strategy.signal_generated", "order.created", "risk.evaluated",
        "order.state_changed", "execution.fill_recorded", "order.state_changed",
        "position.opened", "execution.fill_recorded", "position.closed", "account.settled",
    ]
    assert len({e.event_id for e in db.events}) == len(db.events)
    signal, created, risk, accepted = chain[:4]
    assert created.causation_id == signal.event_id
    assert risk.causation_id == created.event_id
    assert accepted.causation_id == risk.event_id
    assert signal.payload.id == order.signal_id
    assert order.strategy_id == position.strategy_id == "ma-xau-1"
    assert created.payload.status == OrderStatus.PENDING_RISK
    assert accepted.payload.status == OrderStatus.ACCEPTED
    assert order.status == OrderStatus.FILLED

    open_event = next(e for e in chain if isinstance(e, PositionOpened))
    close_event = next(e for e in chain if isinstance(e, PositionClosed))
    assert open_event.payload.status == PositionStatus.OPEN
    assert open_event.payload.close_price is None
    assert close_event.payload.status == PositionStatus.CLOSED
    assert open_event.payload.opened_at == open_event.event_time
    fills = [e.payload for e in chain if isinstance(e, FillRecorded)]
    assert len(fills) == 2
    assert all(f.account_id == account.id and f.position_id == position.id for f in fills)
    assert fills[0].order_id == order.id
    # 旧平仓 API 没有独立平仓订单，因此不能伪造 order_id 或复用开仓 ID。
    assert fills[1].order_id is None
    assert fills[1].side == OrderSide.SELL
    settled = chain[-1]
    assert isinstance(settled, AccountSettled)
    assert settled.payload.balance == D("100001") == account.balance


def test_rejected_order_is_recorded_but_cannot_emit_fills() -> None:
    db, account, orders, market, _ = make_services()
    AccountService(db).update_status(account.id, AccountStatus.DISABLED)
    market.update_quote("XAUUSD", D("100"))
    order = create_order(orders, account)
    chain = [e for e in db.events if e.correlation_id == order.id]
    assert isinstance(chain[0], OrderCreated)
    assert isinstance(chain[1], RiskEvaluated)
    assert chain[1].payload.passed is False
    assert chain[-1].payload.status == OrderStatus.REJECTED
    before = db.events
    with pytest.raises(ConflictError):
        orders.fill(order.id)
    assert db.events == before
    assert not db.positions and not db.executions


def test_missing_quote_and_duplicate_fill_do_not_emit_false_events() -> None:
    db, account, orders, market, _ = make_services()
    order = create_order(orders, account)
    before = db.events
    with pytest.raises(ConflictError):
        orders.fill(order.id)
    assert db.events == before
    assert order.status == OrderStatus.ACCEPTED
    market.update_quote("XAUUSD", D("100"))
    orders.fill(order.id)
    before = db.events
    with pytest.raises(ConflictError):
        orders.fill(order.id)
    assert db.events == before
    assert len(db.executions) == len(db.positions) == 1


def test_cancel_event_is_terminal_and_duplicate_close_is_quiet() -> None:
    db, account, orders, market, positions = make_services()
    cancelled = create_order(orders, account)
    orders.cancel(cancelled.id)
    assert db.events[-1].payload.status == OrderStatus.CANCELLED
    before = db.events
    with pytest.raises(ConflictError):
        orders.cancel(cancelled.id)
    assert db.events == before
    market.update_quote("XAUUSD", D("100"))
    order = create_order(orders, account)
    _, position = orders.fill(order.id)
    positions.close(position.id)
    before, balance = db.events, account.balance
    with pytest.raises(ConflictError):
        positions.close(position.id)
    assert db.events == before and account.balance == balance


def test_direct_service_validation_happens_before_any_write() -> None:
    db, account, orders, market, _ = make_services()
    with pytest.raises(DomainValidationError):
        orders.create(account.id, symbol="XAUUSD", side=OrderSide.BUY,
                      volume=D("-0.1"), requested_price=D("100"))
    with pytest.raises(DomainValidationError):
        market.update_quote("XAUUSD", D("NaN"))
    assert not db.orders and not db.quotes and not db.events


class FixedSignalStrategy(Strategy):
    def __init__(self, signal: Signal) -> None:
        self.signal = signal

    def on_tick(self, context) -> Signal:
        return self.signal


@pytest.mark.parametrize("fields", [
    {"symbol": "EURUSD"}, {"venue": "MT5"}, {"strategy_id": "another-strategy"},
])
def test_runner_rejects_wrong_instrument_or_strategy(fields: dict) -> None:
    db, account, _, _, _ = make_services()
    signal = Signal(**(dict(side=OrderSide.BUY, symbol="XAUUSD", volume=D("0.1"), reason="test") | fields))
    runner = StrategyRunner(db, FixedSignalStrategy(signal), account.id, strategy_id="local")
    with pytest.raises(DomainValidationError):
        runner.on_quote("XAUUSD", D("100"))
    assert not db.orders
    assert not any(isinstance(e, SignalGenerated) for e in db.events)


def test_event_buffer_is_bounded_and_returns_stable_readonly_view() -> None:
    db = InMemoryDatabase(event_capacity=2)
    market = MarketDataService(db)
    market.update_quote("XAUUSD", D("100"))
    old_view = db.events
    market.update_quote("XAUUSD", D("101"))
    market.update_quote("XAUUSD", D("102"))
    assert isinstance(old_view, tuple)
    assert old_view[0].payload.price == D("100")
    assert [e.payload.price for e in db.events] == [D("101"), D("102")]


@pytest.mark.parametrize("fast,slow", [(0, 3), (-1, 3), (3, 3), (True, 3)])
def test_ma_windows_must_be_positive_integers(fast, slow) -> None:
    with pytest.raises(ValueError):
        MovingAverageCrossoverStrategy(fast_window=fast, slow_window=slow)


def test_ma_rejects_negative_volume_at_configuration_time() -> None:
    with pytest.raises(DomainValidationError):
        MovingAverageCrossoverStrategy(order_volume=D("-0.1"))


def test_api_retains_public_order_shape_while_recording_events(client: TestClient, account_id: str) -> None:
    response = client.post(f"/api/v1/accounts/{account_id}/orders", json={
        "symbol": "xauusd", "side": "BUY", "volume": "0.1", "requested_price": "100",
    })
    assert response.status_code == 201
    assert set(response.json()) == {
        "id", "account_id", "symbol", "side", "volume", "requested_price", "status",
        "reject_reason", "filled_price", "created_at", "updated_at",
    }
    assert [e.event_type for e in client.app.state.db.events] == [
        "order.created", "risk.evaluated", "order.state_changed",
    ]


def test_blank_quote_symbol_maps_domain_error_to_http_422(client: TestClient) -> None:
    response = client.put("/api/v1/market/quotes/%20", json={"price": "100"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_DOMAIN_VALUE"
