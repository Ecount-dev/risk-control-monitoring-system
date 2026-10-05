"""MetaTrader 5 终端的只读行情适配器。

官方 Python 包通过本机 MT5 终端取数；本模块绝不调用 order_send。
MT5 的 Python 连接是进程级资源，同一适配器的所有调用用锁串行化。
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from importlib import import_module
from threading import RLock
from types import ModuleType

from app.core.errors import DomainError, NotFoundError
from app.domain.market import Instrument, InstrumentId, Tick, VolumeUnit
from app.domain.validation import DomainValidationError, clean_text


class MT5MarketDataAdapter:
    """延迟连接已登录终端，避免 API 启动因终端暂时离线而失败。"""

    def __init__(
        self,
        *,
        terminal_path: str | None = None,
        symbol_map: dict[str, str] | None = None,
        mt5_api: ModuleType | object | None = None,
    ) -> None:
        self.terminal_path = terminal_path or None
        # 内部代码可统一为 XAUUSD，实际券商代码可能带后缀。
        self.symbol_map = {
            clean_text(key, "symbol", upper=True): clean_text(value, "broker_symbol")
            for key, value in (symbol_map or {}).items()
        }
        self._api = mt5_api
        self._connected = False
        self._lock = RLock()

    def broker_symbol_for(self, symbol: str) -> str:
        canonical = clean_text(symbol, "symbol", upper=True)
        return self.symbol_map.get(canonical, canonical)

    def _ensure_connected(self) -> None:
        """保持本进程的 MT5 IPC 连接；断线后下一次读取尝试重连。"""
        if self._api is None:
            try:
                self._api = import_module("MetaTrader5")
            except ImportError as exc:
                raise DomainError(
                    status_code=503,
                    code="MT5_PACKAGE_MISSING",
                    message="未安装 MetaTrader5；请运行 uv sync --extra mt5",
                ) from exc

        if self._connected:
            terminal = self._api.terminal_info()
            if terminal is not None and terminal.connected:
                return
            self._api.shutdown()
            self._connected = False

        options = {"timeout": 5000}
        if self.terminal_path:
            options["path"] = self.terminal_path
        if not self._api.initialize(**options):
            raise DomainError(
                status_code=503,
                code="MT5_TERMINAL_UNAVAILABLE",
                message="无法连接已登录的 MT5 终端；请检查终端路径和登录状态",
                details={"mt5_error": str(self._api.last_error())},
            )
        self._connected = True
        terminal = self._api.terminal_info()
        if terminal is None or not terminal.connected:
            self._api.shutdown()
            self._connected = False
            raise DomainError(
                status_code=503,
                code="MT5_TERMINAL_OFFLINE",
                message="MT5 终端尚未连接券商服务器",
            )

    def _select_symbol(self, symbol: str) -> tuple[InstrumentId, str, object]:
        canonical = clean_text(symbol, "symbol", upper=True)
        broker_symbol = self.broker_symbol_for(canonical)
        info = self._api.symbol_info(broker_symbol)
        if info is None:
            raise NotFoundError(
                code="MT5_SYMBOL_NOT_FOUND",
                message=f"MT5 终端找不到品种 {broker_symbol}",
                details={"symbol": canonical, "broker_symbol": broker_symbol},
            )
        if not info.visible and not self._api.symbol_select(broker_symbol, True):
            raise DomainError(
                status_code=503,
                code="MT5_SYMBOL_SELECT_FAILED",
                message=f"无法将 {broker_symbol} 加入 MT5 市场报价列表",
                details={"broker_symbol": broker_symbol},
            )
        return InstrumentId(symbol=canonical, venue="MT5"), broker_symbol, info

    def get_tick(self, symbol: str) -> Tick:
        """读取终端最新双边报价；保留券商毫秒时间和本机接收时间。"""
        with self._lock:
            self._ensure_connected()
            instrument_id, broker_symbol, _ = self._select_symbol(symbol)
            raw = self._api.symbol_info_tick(broker_symbol)
            if raw is None or not (raw.time_msc or raw.time):
                raise DomainError(
                    status_code=503,
                    code="MT5_TICK_UNAVAILABLE",
                    message=f"{broker_symbol} 暂无有效 Tick",
                    details={"broker_symbol": broker_symbol},
                )
            timestamp_ms = raw.time_msc or raw.time * 1000
            try:
                seconds, milliseconds = divmod(timestamp_ms, 1000)
                return Tick(
                    instrument_id=instrument_id,
                    bid=Decimal(str(raw.bid)),
                    ask=Decimal(str(raw.ask)),
                    event_time=(
                        datetime.fromtimestamp(seconds, tz=timezone.utc)
                        + timedelta(milliseconds=milliseconds)
                    ),
                    received_at=datetime.now(timezone.utc),
                    source_time_msc=int(timestamp_ms),
                )
            except (DomainValidationError, ValueError, OverflowError, InvalidOperation, TypeError) as exc:
                raise DomainError(
                    status_code=503,
                    code="MT5_TICK_INVALID",
                    message=f"{broker_symbol} 返回了无效报价",
                    details={"broker_symbol": broker_symbol},
                ) from exc

    def get_instrument(self, symbol: str) -> Instrument:
        """从券商终端读取合约规格；不假设黄金一手的固定合约量。"""
        with self._lock:
            self._ensure_connected()
            instrument_id, broker_symbol, info = self._select_symbol(symbol)
            try:
                return Instrument(
                    id=instrument_id,
                    quote_currency=info.currency_profit,
                    volume_unit=VolumeUnit.LOT,
                    contract_size=Decimal(str(info.trade_contract_size)),
                    price_increment=Decimal(str(info.trade_tick_size)),
                    volume_increment=Decimal(str(info.volume_step)),
                    min_volume=Decimal(str(info.volume_min)),
                    max_volume=Decimal(str(info.volume_max)),
                )
            except (DomainValidationError, ValueError, InvalidOperation, TypeError) as exc:
                raise DomainError(
                    status_code=503,
                    code="MT5_INSTRUMENT_INVALID",
                    message=f"{broker_symbol} 返回了不完整的合约规格",
                    details={"broker_symbol": broker_symbol},
                ) from exc

    def close(self) -> None:
        """应用关闭时释放本进程连接；不关闭用户的 MT5 桌面终端。"""
        with self._lock:
            if self._connected:
                self._api.shutdown()
                self._connected = False
