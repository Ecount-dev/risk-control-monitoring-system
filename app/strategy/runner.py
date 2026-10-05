"""策略调度器：把「行情 → 策略 → 下单」串成一条链路。"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from uuid import UUID, uuid4

from app.domain.entities import Order
from app.domain.enums import PositionStatus
from app.domain.events import SignalGenerated
from app.domain.market import InstrumentId
from app.domain.validation import DomainValidationError, clean_text
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
        *,
        strategy_id: str | None = None,
    ) -> None:
        self.db = db
        self.strategy = strategy
        self.account_id = account_id
        # 实例 ID 区分两个同类策略；需要跨重启稳定追踪时应显式传入。
        self.strategy_id = clean_text(
            strategy_id if strategy_id is not None else f"{type(strategy).__name__}-{uuid4()}",
            "strategy_id",
        )

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
        # 当前 Runner 仅处理 SIM 场所；不能用 A 品种行情给 B 品种订单估值。
        if signal.instrument_id != InstrumentId(context.symbol):
            raise DomainValidationError("signal.instrument_id", "必须与触发本次决策的模拟行情一致")
        if signal.strategy_id not in (None, self.strategy_id):
            raise DomainValidationError("signal.strategy_id", "必须属于当前策略实例")
        signal = replace(signal, strategy_id=self.strategy_id)
        generated = SignalGenerated(
            event_time=signal.event_time, source="strategy_runner",
            correlation_id=signal.id, payload=signal,
        )
        self.db.record_event(generated)
        return self._place_order(signal, context.quote.price, generated.event_id)

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

    def _place_order(
        self, signal: Signal, requested_price: Decimal, causation_id: UUID,
    ) -> Order:
        # 市价单以当前报价作为参考价；真正的成交价仍由成交时行情决定。
        return self.orders.create(
            self.account_id,
            symbol=signal.symbol,
            side=signal.side,
            volume=signal.volume,
            requested_price=requested_price,
            strategy_id=signal.strategy_id,
            signal_id=signal.id,
            causation_id=causation_id,
        )
