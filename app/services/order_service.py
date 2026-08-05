"""订单创建、风控编排、撤单和模拟成交。"""

from decimal import Decimal
from uuid import UUID

from app.core.errors import ConflictError, NotFoundError
from app.domain.entities import Execution, Order, Position, RiskDecision
from app.domain.enums import ExecutionKind, OrderSide, OrderStatus
from app.domain.state_machine import transition_order
from app.repositories.memory import InMemoryDatabase
from app.services.account_service import AccountService
from app.services.market_service import MarketDataService
from app.services.risk_service import RiskService


class OrderService:
    """订单用例的总协调者。

    它不亲自实现账户、行情和风控细节，而是组合对应 Service 完成一次完整用例。
    """

    def __init__(self, db: InMemoryDatabase) -> None:
        self.db = db
        # 子服务共享同一个数据库，因此看到的是同一份账户、行情和持仓状态。
        self.accounts = AccountService(db)
        self.market = MarketDataService(db)
        self.risk = RiskService(db)

    def create(
        self,
        account_id: UUID,
        *,
        symbol: str,
        side: OrderSide,
        volume: Decimal,
        requested_price: Decimal,
    ) -> Order:
        """创建订单、执行风控，并返回 ACCEPTED 或 REJECTED 订单。

        拒绝订单仍会保存，因为交易系统需要知道用户提交过什么以及拒绝原因。
        """
        # 从读取账户到写入风控结果作为一个不可被其他线程打断的整体。
        with self.db.lock:
            account = self.accounts.get(account_id)
            rule = self.accounts.get_risk_rule(account_id)

            # 新订单先进入待风控状态，不能跳过风控直接成交。
            order = Order(
                account_id=account_id,
                symbol=symbol,
                side=side,
                volume=volume,
                requested_price=requested_price,
            )
            self.db.orders[order.id] = order

            # evaluate 返回业务结果而不是抛异常；拒绝下单本身不是服务器故障。
            decision = self.risk.evaluate(
                account=account,
                order=order,
                rule=rule,
            )
            self.db.risk_decisions[order.id] = decision

            if decision.passed:
                transition_order(order, OrderStatus.ACCEPTED)
            else:
                order.reject_reason = decision.reason
                transition_order(order, OrderStatus.REJECTED)

            return order

    def get(self, order_id: UUID) -> Order:
        """按 ID 查询订单，不存在时抛出 404 业务异常。"""
        with self.db.lock:
            order = self.db.orders.get(order_id)
            if order is None:
                raise NotFoundError(
                    code="ORDER_NOT_FOUND",
                    message="订单不存在",
                    details={"order_id": str(order_id)},
                )
            return order

    def list_for_account(
        self,
        account_id: UUID,
        *,
        status: OrderStatus | None = None,
        limit: int = 20,
    ) -> list[Order]:
        """按账户、可选状态和数量上限查询最新订单。"""
        with self.db.lock:
            self.accounts.get(account_id)
            orders = [
                order
                for order in self.db.orders.values()
                if order.account_id == account_id
                and (status is None or order.status == status)
            ]
            # 最新创建的订单排在前面。
            orders.sort(key=lambda order: order.created_at, reverse=True)
            return orders[:limit]

    def get_risk_decision(self, order_id: UUID) -> RiskDecision:
        """读取订单创建时保存的风控审计结果。"""
        with self.db.lock:
            self.get(order_id)
            return self.db.risk_decisions[order_id]

    def cancel(self, order_id: UUID) -> Order:
        """撤销订单；状态机只允许 ACCEPTED -> CANCELLED。"""
        with self.db.lock:
            order = self.get(order_id)
            transition_order(order, OrderStatus.CANCELLED)
            return order

    def fill(self, order_id: UUID) -> tuple[Order, Position]:
        """按最新行情模拟成交，并为订单创建一条持仓。

        真实数据库版本中，订单状态、成交记录和持仓必须在同一个事务中提交；
        任意一步失败时都要整体回滚。
        """
        with self.db.lock:
            order = self.get(order_id)

            # 非 ACCEPTED 订单调用状态机会直接得到统一的 409 错误；这里不会修改状态。
            if order.status != OrderStatus.ACCEPTED:
                transition_order(order, OrderStatus.FILLED)

            # 这是第二层幂等保护：一个开仓订单最多对应一条持仓。
            for position in self.db.positions.values():
                if position.opening_order_id == order.id:
                    raise ConflictError(
                        code="POSITION_ALREADY_CREATED",
                        message="该订单已经生成持仓",
                        details={"order_id": str(order.id)},
                    )

            # 市价订单使用成交瞬间的最新行情，而不是提交订单时的参考价格。
            quote = self.market.require_quote_for_execution(order.symbol)
            execution = Execution(
                kind=ExecutionKind.OPEN,
                order_id=order.id,
                symbol=order.symbol,
                side=order.side,
                volume=order.volume,
                price=quote.price,
            )
            position = Position(
                account_id=order.account_id,
                opening_order_id=order.id,
                symbol=order.symbol,
                side=order.side,
                volume=order.volume,
                open_price=execution.price,
            )
            execution.position_id = position.id

            # 所有前置检查成功后才修改订单并写入成交、持仓。
            transition_order(order, OrderStatus.FILLED)
            order.filled_price = execution.price
            self.db.executions[execution.id] = execution
            self.db.positions[position.id] = position
            return order, position
