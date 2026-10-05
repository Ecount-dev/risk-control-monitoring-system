"""示例策略：双均线金叉/死叉。

- 快线上穿慢线（金叉）→ 发出 BUY 信号；
- 快线下穿慢线（死叉）→ 发出 SELL 信号；
- 历史数据不足或没有交叉时，不产生任何信号。

这个文件仅用于演示策略层如何与系统解耦，不代表推荐的交易方法。
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal

from app.domain.enums import OrderSide
from app.domain.validation import trading_decimal
from app.strategy.base import Signal, Strategy
from app.strategy.context import MarketContext


class MovingAverageCrossoverStrategy(Strategy):
    """根据快慢两条简单移动平均线的交叉方向给出买卖信号。"""

    def __init__(
        self,
        *,
        fast_window: int = 5,
        slow_window: int = 20,
        order_volume: Decimal = Decimal("0.1"),
    ) -> None:
        if (type(fast_window) is not int or type(slow_window) is not int
                or not 0 < fast_window < slow_window):
            raise ValueError("窗口必须是整数且满足 0 < fast_window < slow_window")
        trading_decimal(order_volume, "order_volume")
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.order_volume = order_volume

        # 保留最近 slow_window 个收盘价；滑动窗口，自动丢弃旧值。
        self._prices: deque[Decimal] = deque(maxlen=slow_window)
        # 记录上一根价格对应的两条均线，用于判断是否发生交叉。
        self._prev_fast: Decimal | None = None
        self._prev_slow: Decimal | None = None

    def on_tick(self, context: MarketContext) -> Signal | None:
        """用最新价格更新均线，并在发生交叉时返回信号。"""
        price = context.quote.price
        self._prices.append(price)

        if len(self._prices) < self.slow_window:
            # 数据不足，无法计算慢均线，也无法判断交叉。
            self._prev_fast = None
            self._prev_slow = None
            return None

        fast = self._moving_average(self.fast_window)
        slow = self._moving_average(self.slow_window)

        signal: Signal | None = None
        if self._prev_fast is not None and self._prev_slow is not None:
            if self._prev_fast <= self._prev_slow and fast > slow:
                signal = Signal(
                    side=OrderSide.BUY,
                    symbol=context.symbol,
                    volume=self.order_volume,
                    reason=f"金叉：快线 {fast} 上穿慢线 {slow}",
                )
            elif self._prev_fast >= self._prev_slow and fast < slow:
                signal = Signal(
                    side=OrderSide.SELL,
                    symbol=context.symbol,
                    volume=self.order_volume,
                    reason=f"死叉：快线 {fast} 下穿慢线 {slow}",
                )

        self._prev_fast = fast
        self._prev_slow = slow
        return signal

    def _moving_average(self, window: int) -> Decimal:
        """取最近 window 个收盘价的简单平均。"""
        recent = list(self._prices)[-window:]
        return sum(recent, start=Decimal("0")) / Decimal(window)
