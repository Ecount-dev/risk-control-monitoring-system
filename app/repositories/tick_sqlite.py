"""采集阶段的轻量 SQLite Tick 存储，不冒充完整 Event Journal。

保留 MT5 原始毫秒时间、按 UTC 解释的事件时间和本机接收时间。
相同品种、券商代码、原始时间、bid、ask 的重复轮询不会产生重复记录。
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.domain.market import InstrumentId, Tick
from app.domain.validation import clean_text


@dataclass(frozen=True, slots=True)
class StoredTick:
    tick: Tick
    broker_symbol: str


class SQLiteTickRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS mt5_ticks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    broker_symbol TEXT NOT NULL,
                    source_time_msc INTEGER NOT NULL,
                    event_time TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    bid TEXT NOT NULL,
                    ask TEXT NOT NULL,
                    UNIQUE(symbol, broker_symbol, source_time_msc, bid, ask)
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS mt5_ticks_symbol_id "
                "ON mt5_ticks(symbol, id DESC)"
            )

    @contextmanager
    def _connect(self):
        # 每次操作独立连接，后台写入线程与 API 查询线程不共享连接对象。
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA busy_timeout=5000")
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _source_time_msc(tick: Tick) -> int:
        if tick.source_time_msc is not None:
            return tick.source_time_msc
        # 测试 Adapter 可只给事件时间；用整数运算避免 float 毫秒误差。
        delta = tick.event_time - datetime(1970, 1, 1, tzinfo=timezone.utc)
        return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000

    def insert(self, tick: Tick, broker_symbol: str) -> bool:
        if tick.instrument_id.venue != "MT5":
            raise ValueError("Tick 仓储只接受 MT5 行情")
        broker_symbol = clean_text(broker_symbol, "broker_symbol")
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO mt5_ticks
                (symbol, broker_symbol, source_time_msc, event_time, received_at, bid, ask)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    tick.instrument_id.symbol,
                    broker_symbol,
                    self._source_time_msc(tick),
                    tick.event_time.isoformat(),
                    tick.received_at.isoformat(),
                    str(tick.bid),
                    str(tick.ask),
                ),
            )
            return cursor.rowcount == 1

    def latest(self, symbol: str) -> StoredTick | None:
        symbol = clean_text(symbol, "symbol", upper=True)
        with self._connect() as connection:
            row = connection.execute(
                """SELECT broker_symbol, source_time_msc, event_time, received_at, bid, ask
                FROM mt5_ticks WHERE symbol = ? ORDER BY id DESC LIMIT 1""",
                (symbol,),
            ).fetchone()
        if row is None:
            return None
        broker_symbol, source_time_msc, event_time, received_at, bid, ask = row
        return StoredTick(
            tick=Tick(
                instrument_id=InstrumentId(symbol, "MT5"),
                bid=Decimal(bid), ask=Decimal(ask),
                event_time=datetime.fromisoformat(event_time),
                received_at=datetime.fromisoformat(received_at),
                source_time_msc=source_time_msc,
            ),
            broker_symbol=broker_symbol,
        )

    def count(self, symbol: str) -> int:
        symbol = clean_text(symbol, "symbol", upper=True)
        with self._connect() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM mt5_ticks WHERE symbol = ?", (symbol,),
            ).fetchone()[0]
