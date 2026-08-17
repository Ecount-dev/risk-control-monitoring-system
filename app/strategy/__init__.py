"""策略层：交易决策与执行解耦。

- base.py：策略抽象接口与 Signal 信号；
- context.py：策略看到的只读市场快照；
- ma_cross.py：示例双均线策略；
- runner.py：把行情、策略、下单管道串起来。
"""

from app.strategy.base import Signal, Strategy
from app.strategy.context import MarketContext
from app.strategy.ma_cross import MovingAverageCrossoverStrategy
from app.strategy.runner import StrategyRunner

__all__ = [
    "Signal",
    "Strategy",
    "MarketContext",
    "MovingAverageCrossoverStrategy",
    "StrategyRunner",
]
