"""策略抽象接口与交易信号类型。

策略层只负责「决策」：根据市场上下文产出买卖意图（Signal），
不直接下单、不直接修改持仓。真正的下单、风控、成交由 services 层完成。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from app.domain.enums import OrderSide

if TYPE_CHECKING:
    from app.strategy.context import MarketContext


@dataclass(frozen=True, slots=True)
class Signal:
    """策略产出的交易意图，只描述「何时、买卖方向、数量、原因」。

    它不包含成交价格、订单状态等执行细节——那些由下单管道决定。
    """

    side: OrderSide
    symbol: str
    volume: Decimal
    reason: str


class Strategy(ABC):
    """所有交易策略的抽象接口。

    实现类只需覆盖 :meth:`on_tick`：输入最新上下文，输出一个 Signal；
    不想操作时返回 None。策略应保持「只读决策」，不要修改上下文里的
    账户、持仓等对象。
    """

    @abstractmethod
    def on_tick(self, context: MarketContext) -> Signal | None:
        """根据最新行情与账户状态决定是否交易。"""
        raise NotImplementedError
