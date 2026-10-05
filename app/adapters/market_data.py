"""行情入口契约。策略和 API 应依赖此接口，而不是依赖 MT5 包。"""

from typing import Protocol

from app.domain.market import Instrument, Tick


class MarketDataAdapter(Protocol):
    """按需读取数据源；当前是拉取最新 Tick，不承诺推送或补齐历史。"""

    def get_tick(self, symbol: str) -> Tick: ...

    def get_instrument(self, symbol: str) -> Instrument: ...

    def broker_symbol_for(self, symbol: str) -> str: ...
