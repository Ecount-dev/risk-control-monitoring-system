"""持仓查询、动态盈亏计算和模拟平仓。"""

from decimal import Decimal
from uuid import UUID

from app.core.errors import ConflictError, NotFoundError
from app.domain.entities import Fill, Position
from app.domain.enums import ExecutionKind, OrderSide, PositionStatus
from app.domain.events import AccountSettled, FillRecorded, PositionClosed
from app.domain.snapshots import AccountSettlement, PositionSnapshot
from app.repositories.memory import InMemoryDatabase
from app.services.account_service import AccountService
from app.services.market_service import MarketDataService


class PositionService:
    """管理订单成交后形成的持仓。"""

    def __init__(self, db: InMemoryDatabase) -> None:
        self.db = db
        self.accounts = AccountService(db)
        self.market = MarketDataService(db)

    def get(self, position_id: UUID) -> Position:
        """按 ID 查询持仓，不存在时抛出 404 业务异常。"""
        with self.db.lock:
            position = self.db.positions.get(position_id)
            if position is None:
                raise NotFoundError(
                    code="POSITION_NOT_FOUND",
                    message="持仓不存在",
                    details={"position_id": str(position_id)},
                )
            return position

    def list_for_account(
        self,
        account_id: UUID,
        *,
        status: PositionStatus | None = None,
    ) -> list[Position]:
        """查询账户持仓，并可按 OPEN/CLOSED 过滤。"""
        with self.db.lock:
            self.accounts.get(account_id)
            positions = [
                position
                for position in self.db.positions.values()
                if position.account_id == account_id
                and (status is None or position.status == status)
            ]
            positions.sort(key=lambda position: position.opened_at, reverse=True)
            return positions

    def close(self, position_id: UUID) -> Position:
        """使用最新行情平仓，并把结果结算到账户。

        真实数据库版本应把平仓成交、持仓更新和账户余额更新放在同一事务中。
        """
        if self.db.market_source != "sim":
            raise ConflictError(
                code="LIVE_EXECUTION_UNAVAILABLE",
                message="当前仅接入 MT5 只读行情，尚未实现真实平仓接口",
            )
        with self.db.lock:
            position = self.get(position_id)
            if position.status != PositionStatus.OPEN:
                raise ConflictError(
                    code="POSITION_ALREADY_CLOSED",
                    message="持仓已经平仓，不能重复平仓",
                    details={"position_id": str(position.id)},
                )

            # 平仓价取执行动作发生时的最新行情。
            quote = self.market.require_quote_for_execution(position.symbol)
            # 查找依赖资源也属于前置检查，避免之后因缺账户而留下半更新状态。
            account = self.accounts.get(position.account_id)
            # 外部恢复的持仓可能暂时找不到本地开仓订单；仍可用原始 ID 串事件。
            opening_order = self.db.orders.get(position.opening_order_id)
            correlation_id = (
                (opening_order.signal_id or opening_order.id)
                if opening_order is not None else position.opening_order_id
            )
            realized_pnl = self.calculate_pnl(
                side=position.side,
                open_price=position.open_price,
                current_price=quote.price,
                volume=position.volume,
            )
            # BUY 持仓需要 SELL 才能平掉，SELL 持仓则需要反向 BUY。
            closing_side = (
                OrderSide.SELL
                if position.side == OrderSide.BUY
                else OrderSide.BUY
            )
            execution = Fill(
                kind=ExecutionKind.CLOSE,
                account_id=position.account_id,
                position_id=position.id,
                symbol=position.symbol,
                side=closing_side,
                volume=position.volume,
                price=quote.price,
                venue=position.venue,
                strategy_id=position.strategy_id,
            )

            # 持仓进入终态后记录不会删除，以便保留交易历史。
            position.status = PositionStatus.CLOSED
            position.close_price = quote.price
            position.realized_pnl = realized_pnl
            position.closed_at = execution.executed_at

            # 已实现盈亏正式进入余额；浮动盈亏则从不直接修改余额。
            account.balance += realized_pnl
            account.realized_pnl += realized_pnl
            self.db.executions[execution.id] = execution
            # 沿用开仓订单的关联 ID，以便串起信号、开仓到平仓的整条链路。
            filled = FillRecorded(
                event_time=execution.executed_at, source="position_service",
                correlation_id=correlation_id,
                payload=execution,
            )
            self.db.record_event(filled)
            closed = PositionClosed(
                event_time=position.closed_at, source="position_service",
                correlation_id=filled.correlation_id, causation_id=filled.event_id,
                payload=PositionSnapshot.from_position(position),
            )
            self.db.record_event(closed)
            self.db.record_event(AccountSettled(
                event_time=position.closed_at, source="position_service",
                correlation_id=filled.correlation_id, causation_id=closed.event_id,
                payload=AccountSettlement(
                    account_id=account.id, position_id=position.id,
                    realized_pnl_delta=realized_pnl, balance=account.balance,
                    realized_pnl=account.realized_pnl,
                ),
            ))
            return position

    def to_view(self, position: Position) -> dict:
        """把内部 Position 转换成包含当前价格和盈亏的 API 视图。

        OPEN 持仓每次查询都根据最新报价重新计算；CLOSED 持仓使用固定平仓价，
        浮动盈亏归零。这样无需在每次行情变化时更新所有持仓。
        """
        with self.db.lock:
            if position.status == PositionStatus.CLOSED:
                current_price = position.close_price or position.open_price
                unrealized_pnl = Decimal("0")
            else:
                quote = self.market.require_quote_for_execution(position.symbol)
                current_price = quote.price
                unrealized_pnl = self.calculate_pnl(
                    side=position.side,
                    open_price=position.open_price,
                    current_price=current_price,
                    volume=position.volume,
                )

            return {
                "id": position.id,
                "account_id": position.account_id,
                "opening_order_id": position.opening_order_id,
                "symbol": position.symbol,
                "side": position.side,
                "volume": position.volume,
                "open_price": position.open_price,
                "current_price": current_price,
                "unrealized_pnl": unrealized_pnl,
                "status": position.status,
                "close_price": position.close_price,
                "realized_pnl": position.realized_pnl,
                "opened_at": position.opened_at,
                "closed_at": position.closed_at,
            }

    @staticmethod
    def calculate_pnl(
        *,
        side: OrderSide,
        open_price: Decimal,
        current_price: Decimal,
        volume: Decimal,
    ) -> Decimal:
        """使用第一版简化公式计算盈亏。

        暂未纳入合约大小、点值、手续费、隔夜利息、杠杆和汇率换算。
        """
        price_change = (
            current_price - open_price
            if side == OrderSide.BUY
            else open_price - current_price
        )
        return price_change * volume
