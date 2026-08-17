"""策略调度器：把「行情 → 策略 → 下单」串成一条链路。"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.domain.entities import Order
from app.domain.enums import PositionStatus
from app.repositories.memory import InMemoryDatabase
from app.services.account_service import AccountService
from app.services.market_service import MarketDataService
from app.services.order_service import OrderService
from app.services.position_service import PositionService
from app.strategy.base import Signal, Strategy
from app.strategy.context import MarketContext


class StrategyRunner:
    """驱动单个账户上的一个策略。

    每个新报价调用一次 :meth:`on_quote`：

       更新行情 → 组装只读上下文 → 让策略决策 → 有信号则复用 OrderService 下单。

    信号仍要经过风控：风控拒绝时订单会被创建为 REJECTED 并留下审计记录，
    策略无法绕过这一层。
    """

    def __init__(
        self,
        db: InMemoryDatabase,
        strategy: Strategy,
        account_id: UUID,
    ) -> None:
        self.db = db
        self.strategy = strategy
        self.account_id = account_id

        self.accounts = AccountService(db)
        self.market = MarketDataService(db)
        self.orders = OrderService(db)
        self.positions = PositionService(db)

    def on_quote(self, symbol: str, price: Decimal) -> Order | None:
        """处理一条新报价；若策略产生信号，返回创建出的订单，否则返回 None。

        真实接 MT5 后，这里改成由行情订阅回调触发，其余逻辑不变。
        """
        # 1. 写入最新报价（MarketDataService 会标准化品种代码）。
        self.market.update_quote(symbol, price)

        # 2. 组装策略看到的只读快照。
        context = self._build_context(symbol)

        # 3. 让策略做决策。
        signal = self.strategy.on_tick(context)

        # 4. 有信号就走既有的下单管道；风控在这一步把关。
        if signal is None:
            return None
        return self._place_order(signal, context.quote.price)

    def _build_context(self, symbol: str) -> MarketContext:
        quote = self.market.get_quote(symbol)
        account = self.accounts.get(self.account_id)
        rule = self.accounts.get_risk_rule(self.account_id)
        open_positions = tuple(
            self.positions.list_for_account(
                self.account_id, status=PositionStatus.OPEN
            )
        )
        return MarketContext(
            symbol=quote.symbol,
            quote=quote,
            account=account,
            open_positions=open_positions,
            risk_rule=rule,
        )

    def _place_order(self, signal: Signal, requested_price: Decimal) -> Order:
        # 市价单以当前报价作为参考价；真正的成交价仍由成交时行情决定。
        return self.orders.create(
            self.account_id,
            symbol=signal.symbol,
            side=signal.side,
            volume=signal.volume,
            requested_price=requested_price,
        )
