"""MT5 模式的 API 行为：真实行情只读，模拟执行被隔离。"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.domain.market import Instrument, InstrumentId, Tick, VolumeUnit
from app.main import create_app
from app.repositories.memory import InMemoryDatabase


class FakeMarketAdapter:
    def broker_symbol_for(self, symbol):
        return "XAUUSD.m"

    def get_tick(self, symbol):
        now = datetime.now(timezone.utc)
        return Tick(
            instrument_id=InstrumentId("XAUUSD", "MT5"),
            bid=Decimal("2400.12"), ask=Decimal("2400.19"),
            event_time=now - timedelta(seconds=2), received_at=now,
        )

    def get_instrument(self, symbol):
        return Instrument(
            id=InstrumentId("XAUUSD", "MT5"),
            quote_currency="USD", volume_unit=VolumeUnit.LOT,
            contract_size=Decimal("100"), price_increment=Decimal("0.01"),
            volume_increment=Decimal("0.01"),
            min_volume=Decimal("0.01"), max_volume=Decimal("80"),
        )


class AheadTimeAdapter(FakeMarketAdapter):
    """模拟券商时间戳比本机接收时间领先数小时。"""

    def get_tick(self, symbol):
        now = datetime.now(timezone.utc)
        return Tick(
            instrument_id=InstrumentId("XAUUSD", "MT5"),
            bid=Decimal("2400.12"), ask=Decimal("2400.19"),
            event_time=now + timedelta(hours=3), received_at=now,
        )


def test_mt5_market_endpoints_and_simulation_guard():
    db = InMemoryDatabase()
    app = create_app(db, market_source="mt5", mt5_adapter=FakeMarketAdapter())
    with TestClient(app) as client:
        tick = client.get("/api/v1/market/ticks/XAUUSD")
        assert tick.status_code == 200
        body = tick.json()
        assert body["symbol"] == "XAUUSD"
        assert body["broker_symbol"] == "XAUUSD.m"
        assert body["bid"] == "2400.12"
        assert body["ask"] == "2400.19"
        assert body["spread"] == "0.07"
        assert body["is_stale"] is False
        assert body["source_time_delta_seconds"] <= 0

        instrument = client.get("/api/v1/market/instruments/XAUUSD")
        assert instrument.status_code == 200
        assert instrument.json()["contract_size"] == "100"

        manual = client.put("/api/v1/market/quotes/XAUUSD", json={"price": "2400"})
        assert manual.status_code == 409
        assert manual.json()["error"]["code"] == "SIMULATED_MARKET_DISABLED"
        assert db.quotes == {}

        account = client.post(
            "/api/v1/accounts",
            json={"name": "demo", "initial_balance": "100000"},
        )
        assert account.status_code == 201
        order = client.post(
            f"/api/v1/accounts/{account.json()['id']}/orders",
            json={"symbol": "XAUUSD", "side": "BUY", "volume": "1", "requested_price": "2400"},
        )
        assert order.status_code == 409
        assert order.json()["error"]["code"] == "LIVE_EXECUTION_UNAVAILABLE"
        assert db.orders == {}


def test_simulation_mode_cannot_silently_fall_back_to_live_tick():
    app = create_app(InMemoryDatabase(), market_source="sim")
    with TestClient(app) as client:
        response = client.get("/api/v1/market/ticks/XAUUSD")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MT5_MARKET_MODE_REQUIRED"


def test_uncomparable_broker_time_does_not_claim_quote_is_fresh():
    app = create_app(
        InMemoryDatabase(), market_source="mt5", mt5_adapter=AheadTimeAdapter(),
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/market/ticks/XAUUSD")
    assert response.status_code == 200
    assert response.json()["is_stale"] is None
    assert response.json()["source_time_delta_seconds"] == 10800
