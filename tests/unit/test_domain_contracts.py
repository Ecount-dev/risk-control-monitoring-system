"""验证契约边界，而非 HTTP：未来 Adapter/策略也必须遵守这些约束。"""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from uuid import uuid4

import pytest

from app.domain import Bar, Fill, Instrument, InstrumentId, Order, Position, Signal, Tick, VolumeUnit
from app.domain.entities import Execution, MarketQuote
from app.domain.enums import ExecutionKind, OrderSide, OrderStatus
from app.domain.events import BarClosed, FillRecorded, OrderCreated
from app.domain.snapshots import OrderSnapshot
from app.domain.validation import DomainValidationError
from app.strategy.base import Signal as LegacySignal

D = Decimal
NOW = datetime(2026, 9, 28, 10, tzinfo=timezone.utc)


def make_instrument() -> Instrument:
    """完全虚构的测试规格；不得拿来当作券商实际规格。"""
    return Instrument(
        id=InstrumentId("xauusd", "sim"), quote_currency="usd",
        volume_unit=VolumeUnit.UNIT, contract_size=D("1"),
        price_increment=D("0.05"), volume_increment=D("0.1"),
        min_volume=D("0.1"), max_volume=D("10"),
    )


def make_bar() -> Bar:
    return Bar(
        instrument_id=InstrumentId("XAUUSD"), interval=timedelta(minutes=1),
        open_time=NOW, close_time=NOW + timedelta(minutes=1),
        open=D("100"), high=D("110"), low=D("99"), close=D("105"), volume=D("0"),
    )


def make_order(**overrides) -> Order:
    values = dict(account_id=uuid4(), symbol="XAUUSD", side=OrderSide.BUY,
                  volume=D("0.1"), requested_price=D("100"))
    return Order(**(values | overrides))


def test_instrument_identity_and_explicit_contract_rules() -> None:
    instrument = make_instrument()
    assert instrument.id == InstrumentId(" XAUUSD ", "SIM")
    assert instrument.id != InstrumentId("XAUUSD", "MT5")
    instrument.validate_price(D("100.05"))
    instrument.validate_volume(D("0.2"))
    # 不能只看小数位数：0.05 的价位步长不接受 100.01。
    with pytest.raises(DomainValidationError):
        instrument.validate_price(D("100.01"))
    with pytest.raises(DomainValidationError):
        instrument.validate_volume(D("0.15"))
    with pytest.raises(DomainValidationError):
        instrument.validate_volume(D("11"))
    with pytest.raises(DomainValidationError):
        replace(instrument, min_volume=D("20"))
    with pytest.raises(FrozenInstanceError):
        instrument.contract_size = D("100")


def test_tick_has_bid_ask_and_normalizes_timezone() -> None:
    local_time = NOW.astimezone(timezone(timedelta(hours=8)))
    tick = Tick(instrument_id=InstrumentId("XAUUSD"), bid=D("100"), ask=D("100.05"),
                event_time=local_time, received_at=NOW)
    assert tick.event_time.tzinfo == timezone.utc
    assert tick.spread == D("0.05")
    with pytest.raises(DomainValidationError):
        replace(tick, ask=D("99"))
    with pytest.raises(DomainValidationError):
        replace(tick, event_time=NOW.replace(tzinfo=None))
    with pytest.raises(DomainValidationError):
        replace(tick, bid=D("NaN"))


@pytest.mark.parametrize("overrides", [
    {"high": D("99")}, {"low": D("106")}, {"open": D("0")},
    {"volume": D("-1")}, {"interval": timedelta(0)},
    {"close_time": NOW + timedelta(seconds=30)},
])
def test_bar_rejects_invalid_candle(overrides: dict) -> None:
    with pytest.raises(DomainValidationError):
        replace(make_bar(), **overrides)


def test_bar_closed_cannot_be_published_before_close() -> None:
    bar = make_bar()
    event = BarClosed(event_time=bar.close_time, source="test", correlation_id=uuid4(), payload=bar)
    assert event.to_dict()["payload"]["interval"] == 60_000_000
    with pytest.raises(DomainValidationError):
        replace(event, event_time=bar.open_time)


@pytest.mark.parametrize("bad", [D("0"), D("-0.1"), D("NaN"), D("sNaN"), D("Infinity"), 0.1])
@pytest.mark.parametrize("kind", ["signal", "order", "fill", "position", "quote"])
def test_all_entry_models_reject_invalid_amounts(kind: str, bad) -> None:
    """float/非有限数/非正数不因绕过 Pydantic 而进入领域层。"""
    with pytest.raises(DomainValidationError):
        if kind == "signal":
            Signal(side=OrderSide.BUY, symbol="XAUUSD", volume=bad, reason="test")
        elif kind == "order":
            make_order(volume=bad)
        elif kind == "fill":
            Fill(kind=ExecutionKind.OPEN, account_id=uuid4(), order_id=uuid4(),
                 symbol="XAUUSD", side=OrderSide.BUY, volume=bad, price=D("100"))
        elif kind == "position":
            Position(account_id=uuid4(), opening_order_id=uuid4(), symbol="XAUUSD",
                     side=OrderSide.BUY, volume=bad, open_price=D("100"))
        else:
            MarketQuote(symbol="XAUUSD", price=bad)


def test_order_normalization_and_legacy_imports_share_models() -> None:
    assert LegacySignal is Signal
    assert Execution is Fill
    order = make_order(symbol=" xauusd ")
    assert order.instrument_id == InstrumentId("XAUUSD", "SIM")
    with pytest.raises(DomainValidationError):
        make_order(side="HOLD")
    with pytest.raises(DomainValidationError):
        make_order(symbol=" ")


def test_fill_requires_link_and_unambiguous_fee_currency() -> None:
    values = dict(kind=ExecutionKind.OPEN, account_id=uuid4(), symbol="XAUUSD",
                  side=OrderSide.BUY, volume=D("0.1"), price=D("100"))
    with pytest.raises(DomainValidationError):
        Fill(**values)
    with pytest.raises(DomainValidationError):
        Fill(**values, order_id=uuid4(), commission=D("0.2"))
    fill = Fill(**values, order_id=uuid4(), commission=D("0.2"), commission_currency="usd")
    assert fill.commission_currency == "USD"
    with pytest.raises(FrozenInstanceError):
        fill.position_id = uuid4()


def test_event_snapshot_survives_later_order_mutation_and_is_json_safe() -> None:
    order = make_order(requested_price=D("123.123456"))
    event = OrderCreated(event_time=NOW, source="test", correlation_id=order.id,
                         payload=OrderSnapshot.from_order(order))
    order.status = OrderStatus.CANCELLED
    order.volume = D("9")
    assert event.payload.status == OrderStatus.PENDING_RISK
    assert event.payload.volume == D("0.1")
    with pytest.raises(FrozenInstanceError):
        event.payload.volume = D("8")
    with pytest.raises(FrozenInstanceError):
        event.payload.instrument_id.symbol = "EURUSD"
    encoded = json.loads(json.dumps(event.to_dict()))
    assert encoded["event_type"] == "order.created"
    assert encoded["schema_version"] == 1
    assert encoded["payload"]["requested_price"] == "123.123456"
    assert encoded["correlation_id"] == str(order.id)
    assert encoded["payload"]["status"] == "PENDING_RISK"


def test_event_rejects_mutable_payload_and_missing_timezone() -> None:
    order = make_order()
    with pytest.raises(DomainValidationError):
        OrderCreated(event_time=NOW, source="test", correlation_id=order.id, payload=order)
    with pytest.raises(DomainValidationError):
        OrderCreated(event_time=NOW.replace(tzinfo=None), source="test",
                     correlation_id=order.id, payload=OrderSnapshot.from_order(order))


def test_fill_event_preserves_exact_price_and_identity() -> None:
    fill = Fill(kind=ExecutionKind.CLOSE, account_id=uuid4(), position_id=uuid4(),
                symbol="XAUUSD", side=OrderSide.SELL, volume=D("0.100000"),
                price=D("123.123456"))
    event = FillRecorded(event_time=fill.executed_at, source="test", correlation_id=uuid4(), payload=fill)
    assert event.to_dict()["payload"]["id"] == str(fill.id)
    assert event.to_dict()["payload"]["price"] == "123.123456"
