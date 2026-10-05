"""策略抽象接口与交易信号类型。

策略层只负责「决策」：根据市场上下文产出买卖意图（Signal），
不直接下单、不直接修改持仓。真正的下单、风控、成交由 services 层完成。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

# 兼容原有 from app.strategy.base import Signal；全项目只有一个 Signal 定义。
from app.domain.signals import Signal

if TYPE_CHECKING:
    from app.strategy.context import MarketContext


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
