"""策略与交易服务共用的交易意图；Signal 不是订单，也不代表成交。"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from app.domain.entities import utc_now
from app.domain.enums import OrderSide
from app.domain.market import InstrumentId
from app.domain.validation import (
    aware_utc, clean_text, enum_value, require_uuid, trading_decimal,
)


@dataclass(frozen=True, slots=True)
class Signal:
    """保留原来的四个参数，新增身份和发生时间便于追踪。

    strategy_id 可由 StrategyRunner 补充；volume 是固定数量意图。
    目标仓位/资金分配属于后续 PortfolioEngine，本步骤不混入该职责。
    """

    side: OrderSide
    symbol: str
    volume: Decimal
    reason: str
    id: UUID = field(default_factory=uuid4)
    strategy_id: str | None = None
    venue: str = "SIM"
    event_time: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        instrument_id = InstrumentId(self.symbol, self.venue)
        object.__setattr__(self, "symbol", instrument_id.symbol)
        object.__setattr__(self, "venue", instrument_id.venue)
        object.__setattr__(self, "side", enum_value(OrderSide, self.side, "side"))
        require_uuid(self.id, "id")
        trading_decimal(self.volume, "volume")
        object.__setattr__(self, "reason", clean_text(self.reason, "reason"))
        if self.strategy_id is not None:
            object.__setattr__(self, "strategy_id", clean_text(self.strategy_id, "strategy_id"))
        object.__setattr__(self, "event_time", aware_utc(self.event_time, "event_time"))

    @property
    def instrument_id(self) -> InstrumentId:
        return InstrumentId(self.symbol, self.venue)
