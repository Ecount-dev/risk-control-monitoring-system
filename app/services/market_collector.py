"""进程内 MT5 后台行情采集器；只采集和保存，不驱动交易。"""

import logging
from math import isfinite
from datetime import datetime, timezone
from threading import Event, Lock, Thread

from app.adapters.market_data import MarketDataAdapter
from app.core.errors import DomainError
from app.domain.validation import clean_text
from app.repositories.tick_sqlite import SQLiteTickRepository

logger = logging.getLogger(__name__)


class MarketDataCollector:
    """按间隔读取最新 Tick，去重持久化，失败后指数退避并重连。

    轮询 symbol_info_tick 只能看到每次读取时的最新报价；无法保证逐笔无缺口。
    后续可基于已保存的 source_time_msc 使用 MT5 历史 Tick API 补采。
    """

    def __init__(
        self,
        adapter: MarketDataAdapter,
        repository: SQLiteTickRepository,
        *,
        symbol: str = "XAUUSD",
        poll_interval_seconds: float = 1.0,
        time_tolerance_seconds: int = 30,
    ) -> None:
        if not isfinite(poll_interval_seconds) or poll_interval_seconds < 0.1:
            raise ValueError("poll_interval_seconds 必须至少 0.1 秒")
        if time_tolerance_seconds <= 0:
            raise ValueError("time_tolerance_seconds 必须大于 0")
        self.adapter = adapter
        self.repository = repository
        self.symbol = clean_text(symbol, "symbol", upper=True)
        self.poll_interval_seconds = poll_interval_seconds
        self.time_tolerance_seconds = time_tolerance_seconds
        self._stop = Event()
        self._state_lock = Lock()
        self._thread: Thread | None = None
        self._state = "STOPPED"
        self._polls = 0
        self._new_ticks = 0
        self._duplicates = 0
        self._consecutive_errors = 0
        self._last_error_code: str | None = None
        self._last_poll_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_new_tick_at: datetime | None = None

    def start(self) -> None:
        """只在 FastAPI lifespan 中启动一次，不在模块导入时启动。"""
        if self._thread is not None:
            raise RuntimeError("MarketDataCollector 已启动")
        self._stop.clear()
        with self._state_lock:
            self._state = "STARTING"
        self._thread = Thread(
            target=self._run,
            name=f"mt5-market-{self.symbol.lower()}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout: float = 10.0) -> bool:
        """停止轮询；返回 False 表示 MT5 调用仍未退出，调用者不应立刻关闭连接。"""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        stopped = self._thread is None or not self._thread.is_alive()
        with self._state_lock:
            self._state = "STOPPED" if stopped else "STOPPING"
        return stopped

    def poll_once(self) -> bool:
        """执行一次可测试的采集：插入返回 True，重复报价返回 False。"""
        with self._state_lock:
            self._polls += 1
            self._last_poll_at = datetime.now(timezone.utc)
        tick = self.adapter.get_tick(self.symbol)
        inserted = self.repository.insert(
            tick, self.adapter.broker_symbol_for(self.symbol),
        )
        now = datetime.now(timezone.utc)
        with self._state_lock:
            self._state = "RUNNING" if inserted else "IDLE"
            self._consecutive_errors = 0
            self._last_error_code = None
            self._last_success_at = now
            if inserted:
                self._new_ticks += 1
                self._last_new_tick_at = now
            else:
                self._duplicates += 1
        return inserted

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
                delay = self.poll_interval_seconds
            except Exception as exc:
                # 数据源断线、报价无效、SQLite 暂时不可用都不会杀死后台线程。
                with self._state_lock:
                    self._state = "RETRYING"
                    self._consecutive_errors += 1
                    self._last_error_code = (
                        exc.code if isinstance(exc, DomainError) else type(exc).__name__
                    )
                    failures = self._consecutive_errors
                logger.warning("MT5 行情采集失败，将重试: %s", self._last_error_code)
                delay = min(30.0, max(1.0, self.poll_interval_seconds) * 2 ** min(failures - 1, 5))
            self._stop.wait(delay)

    def status(self) -> dict:
        """返回可观察状态；时间差只是实测值，不自动推定澳洲/券商时区。"""
        with self._state_lock:
            status = {
                "symbol": self.symbol,
                "state": self._state,
                "poll_interval_seconds": self.poll_interval_seconds,
                "polls": self._polls,
                "new_ticks": self._new_ticks,
                "duplicates": self._duplicates,
                "consecutive_errors": self._consecutive_errors,
                "last_error_code": self._last_error_code,
                "last_poll_at": self._last_poll_at,
                "last_success_at": self._last_success_at,
                "last_new_tick_at": self._last_new_tick_at,
            }
        latest = self.repository.latest(self.symbol)
        status["persisted_ticks"] = self.repository.count(self.symbol)
        if latest is None:
            status["latest"] = None
            status["time_basis_status"] = "NO_SAMPLE"
        else:
            tick = latest.tick
            delta = int((tick.event_time - tick.received_at).total_seconds())
            status["latest"] = {
                "broker_symbol": latest.broker_symbol,
                "source_time_msc": tick.source_time_msc,
                "event_time": tick.event_time,
                "received_at": tick.received_at,
                "bid": tick.bid,
                "ask": tick.ask,
                "source_time_delta_seconds": delta,
            }
            if delta > self.time_tolerance_seconds:
                status["time_basis_status"] = "SOURCE_AHEAD_UNVERIFIED"
            elif delta < -self.time_tolerance_seconds:
                status["time_basis_status"] = "SOURCE_OLDER_THAN_TOLERANCE"
            else:
                status["time_basis_status"] = "UTC_NEAR_RECEIPT"
        # 轮询最新 Tick 有潜在缺口；绝不声称是完整逐笔行情。
        status["complete_tick_stream"] = False
        return status
