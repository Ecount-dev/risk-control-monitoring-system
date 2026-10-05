"""采集去重、持久化、时间诊断与断线恢复均不依赖真实终端。"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from time import monotonic, sleep

from fastapi.testclient import TestClient

from app.core.errors import DomainError
from app.domain.market import InstrumentId, Tick
from app.main import create_app
from app.repositories.memory import InMemoryDatabase
from app.repositories.tick_sqlite import SQLiteTickRepository
from app.services.market_collector import MarketDataCollector


def make_tick(*, bid="2400.10", received_offset=0) -> Tick:
    received = datetime(2026, 9, 29, 7, 0, tzinfo=timezone.utc)
    return Tick(
        instrument_id=InstrumentId("XAUUSD", "MT5"),
        bid=Decimal(bid), ask=Decimal("2400.20"),
        event_time=received + timedelta(hours=3),
        received_at=received + timedelta(seconds=received_offset),
        source_time_msc=1_780_124_400_123,
    )


class SequenceAdapter:
    def __init__(self, ticks):
        self.ticks = list(ticks)
        self.calls = 0

    def broker_symbol_for(self, symbol):
        return "XAUUSD"

    def get_tick(self, symbol):
        self.calls += 1
        index = min(self.calls - 1, len(self.ticks) - 1)
        item = self.ticks[index]
        if isinstance(item, Exception):
            raise item
        return item


def test_sqlite_keeps_both_times_and_deduplicates_across_restarts(tmp_path):
    db_path = tmp_path / "ticks.sqlite3"
    repository = SQLiteTickRepository(db_path)
    assert repository.insert(make_tick(), "XAUUSD") is True
    assert repository.insert(make_tick(received_offset=1), "XAUUSD") is False
    assert repository.insert(make_tick(bid="2400.11"), "XAUUSD") is True

    reopened = SQLiteTickRepository(db_path)
    assert reopened.count("XAUUSD") == 2
    latest = reopened.latest("XAUUSD")
    assert latest.tick.source_time_msc == 1_780_124_400_123
    assert latest.tick.event_time.hour == 10
    assert latest.tick.received_at.hour == 7
    assert latest.tick.bid == Decimal("2400.11")


def test_collector_records_new_quotes_and_keeps_idle_separate_from_errors(tmp_path):
    repository = SQLiteTickRepository(tmp_path / "ticks.sqlite3")
    adapter = SequenceAdapter([make_tick(), make_tick(received_offset=1)])
    collector = MarketDataCollector(adapter, repository, poll_interval_seconds=0.1)
    assert collector.poll_once() is True
    assert collector.poll_once() is False
    status = collector.status()
    assert status["state"] == "IDLE"
    assert status["polls"] == 2
    assert status["new_ticks"] == 1
    assert status["duplicates"] == 1
    assert status["persisted_ticks"] == 1
    assert status["time_basis_status"] == "SOURCE_AHEAD_UNVERIFIED"
    assert status["complete_tick_stream"] is False


def test_background_collector_retries_after_disconnection(tmp_path):
    repository = SQLiteTickRepository(tmp_path / "ticks.sqlite3")
    adapter = SequenceAdapter([
        DomainError(status_code=503, code="MT5_TERMINAL_OFFLINE", message="offline"),
        make_tick(),
    ])
    collector = MarketDataCollector(adapter, repository, poll_interval_seconds=0.1)
    collector.start()
    try:
        deadline = monotonic() + 3
        while collector.status()["persisted_ticks"] == 0 and monotonic() < deadline:
            sleep(0.02)
        status = collector.status()
        assert status["persisted_ticks"] == 1
        assert status["consecutive_errors"] == 0
        assert adapter.calls >= 2
    finally:
        assert collector.stop()
    assert collector.status()["state"] == "STOPPED"


def test_fastapi_lifespan_starts_and_stops_collector(tmp_path, monkeypatch):
    monkeypatch.setenv("MT5_POLL_INTERVAL_SECONDS", "0.1")
    adapter = SequenceAdapter([make_tick()])
    app = create_app(
        InMemoryDatabase(), market_source="mt5", mt5_adapter=adapter,
        enable_market_collector=True, tick_db_path=tmp_path / "ticks.sqlite3",
    )
    with TestClient(app) as client:
        deadline = monotonic() + 2
        while monotonic() < deadline:
            response = client.get("/api/v1/market/collector/status")
            if response.json()["persisted_ticks"] == 1:
                break
            sleep(0.02)
        assert response.status_code == 200
        body = response.json()
        assert body["persisted_ticks"] == 1
        assert body["latest"]["source_time_msc"] == 1_780_124_400_123
        assert body["time_basis_status"] == "SOURCE_AHEAD_UNVERIFIED"
    assert app.state.market_collector.status()["state"] == "STOPPED"
