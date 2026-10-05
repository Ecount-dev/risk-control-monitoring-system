"""模拟行情的写入、查询及成交前检查。"""

from decimal import Decimal
from uuid import uuid4

from app.core.errors import ConflictError, NotFoundError
from app.domain.entities import MarketQuote
from app.domain.events import QuoteUpdated
from app.repositories.memory import InMemoryDatabase


class MarketDataService:
    """维护每个交易品种的最新一条模拟报价。"""

    def __init__(self, db: InMemoryDatabase) -> None:
        self.db = db

    def update_quote(self, symbol: str, price: Decimal) -> MarketQuote:
        """标准化品种代码并覆盖其上一条报价。"""
        self._require_sim_mode()
        quote = MarketQuote(symbol=symbol, price=price)
        with self.db.lock:
            self.db.quotes[quote.symbol] = quote
            self.db.record_event(QuoteUpdated(
                event_time=quote.updated_at, source="market_service",
                correlation_id=uuid4(), payload=quote,
            ))
        return quote

    def get_quote(self, symbol: str) -> MarketQuote:
        """获取最新报价；普通查询缺失时返回 404。"""
        self._require_sim_mode()
        symbol = symbol.strip().upper()
        with self.db.lock:
            quote = self.db.quotes.get(symbol)
            if quote is None:
                raise NotFoundError(
                    code="MARKET_QUOTE_NOT_FOUND",
                    message=f"{symbol} 暂无模拟行情",
                    details={"symbol": symbol},
                )
            return quote

    def require_quote_for_execution(self, symbol: str) -> MarketQuote:
        """获取成交必需的报价。

        报价资源不存在通常是 404；但对成交动作而言，它表示当前业务条件不满足，
        因而转换成 409 Conflict，同时保留原异常作为调试原因。
        """
        try:
            return self.get_quote(symbol)
        except NotFoundError as exc:
            raise ConflictError(
                code="MARKET_QUOTE_UNAVAILABLE",
                message=f"{symbol} 暂无模拟行情，不能成交或平仓",
                details={"symbol": symbol},
            ) from exc

    def _require_sim_mode(self) -> None:
        """保护服务的直接调用者，不能把实盘 Tick 混成模拟单价格。"""
        if self.db.market_source != "sim":
            raise ConflictError(
                code="SIMULATED_MARKET_DISABLED",
                message="MT5 行情模式下不能使用模拟报价服务",
            )
