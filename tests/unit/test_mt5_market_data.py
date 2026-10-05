"""用假的官方 API 验证行情映射；测试过程不需要 MT5 终端。"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.adapters.mt5_market_data import MT5MarketDataAdapter
from app.core.errors import DomainError, NotFoundError


class FakeMT5:
    def __init__(self) -> None:
        self.connected = True
        self.selected = []
        self.tick_calls = []
        self.initialize_calls = []
        self.shutdown_calls = 0
        self.info = SimpleNamespace(
            visible=False,
            currency_profit="USD",
            trade_contract_size=100.0,
            trade_tick_size=0.01,
            volume_step=0.01,
            volume_min=0.01,
            volume_max=80.0,
        )
        self.tick = SimpleNamespace(
            bid=2400.12, ask=2400.19,
            time_msc=1_700_000_000_123, time=1_700_000_000,
        )

    def initialize(self, **kwargs):
        self.initialize_calls.append(kwargs)
        return True

    def terminal_info(self):
        return SimpleNamespace(connected=self.connected)

    def symbol_info(self, symbol):
        return self.info if symbol == "XAUUSD.m" else None

    def symbol_select(self, symbol, visible):
        self.selected.append((symbol, visible))
        return True

    def symbol_info_tick(self, symbol):
        self.tick_calls.append(symbol)
        return self.tick

    def shutdown(self):
        self.shutdown_calls += 1

    def last_error(self):
        return (0, "ok")


def test_mt5_tick_maps_bid_ask_broker_symbol_and_utc_time():
    fake = FakeMT5()
    adapter = MT5MarketDataAdapter(
        terminal_path="terminal64.exe", symbol_map={"XAUUSD": "XAUUSD.m"}, mt5_api=fake,
    )
    tick = adapter.get_tick(" xauusd ")
    assert str(tick.instrument_id) == "XAUUSD@MT5"
    assert str(tick.bid) == "2400.12"
    assert str(tick.ask) == "2400.19"
    assert str(tick.spread) == "0.07"
    assert tick.event_time == datetime.fromtimestamp(1_700_000_000.123, timezone.utc)
    assert fake.tick_calls == ["XAUUSD.m"]
    assert fake.selected == [("XAUUSD.m", True)]
    assert fake.initialize_calls == [{"timeout": 5000, "path": "terminal64.exe"}]
    adapter.close()
    assert fake.shutdown_calls == 1


def test_mt5_instrument_uses_broker_contract_values():
    adapter = MT5MarketDataAdapter(symbol_map={"XAUUSD": "XAUUSD.m"}, mt5_api=FakeMT5())
    instrument = adapter.get_instrument("xauusd")
    assert instrument.quote_currency == "USD"
    assert str(instrument.contract_size) == "100.0"
    assert str(instrument.price_increment) == "0.01"
    assert str(instrument.max_volume) == "80.0"


def test_unknown_symbol_and_missing_tick_return_explicit_errors():
    fake = FakeMT5()
    adapter = MT5MarketDataAdapter(mt5_api=fake)
    with pytest.raises(NotFoundError) as missing:
        adapter.get_tick("NO_SUCH_SYMBOL")
    assert missing.value.code == "MT5_SYMBOL_NOT_FOUND"

    mapped = MT5MarketDataAdapter(symbol_map={"XAUUSD": "XAUUSD.m"}, mt5_api=fake)
    fake.tick = None
    with pytest.raises(DomainError) as no_tick:
        mapped.get_tick("XAUUSD")
    assert no_tick.value.code == "MT5_TICK_UNAVAILABLE"


def test_offline_terminal_does_not_return_fake_quote():
    fake = FakeMT5()
    fake.connected = False
    adapter = MT5MarketDataAdapter(mt5_api=fake)
    with pytest.raises(DomainError) as offline:
        adapter.get_tick("XAUUSD")
    assert offline.value.code == "MT5_TERMINAL_OFFLINE"
    assert fake.shutdown_calls == 1


def test_adapter_reconnects_on_next_read_after_terminal_recovers():
    fake = FakeMT5()
    adapter = MT5MarketDataAdapter(symbol_map={"XAUUSD": "XAUUSD.m"}, mt5_api=fake)
    adapter.get_tick("XAUUSD")
    fake.connected = False
    with pytest.raises(DomainError):
        adapter.get_tick("XAUUSD")
    fake.connected = True
    assert adapter.get_tick("XAUUSD").source_time_msc == 1_700_000_000_123
    assert len(fake.initialize_calls) == 3


def test_invalid_bid_ask_is_rejected_before_collector_can_store_it():
    fake = FakeMT5()
    fake.tick = SimpleNamespace(
        bid=2400.20, ask=2400.10,
        time_msc=1_700_000_000_123, time=1_700_000_000,
    )
    adapter = MT5MarketDataAdapter(symbol_map={"XAUUSD": "XAUUSD.m"}, mt5_api=fake)
    with pytest.raises(DomainError) as invalid:
        adapter.get_tick("XAUUSD")
    assert invalid.value.code == "MT5_TICK_INVALID"
