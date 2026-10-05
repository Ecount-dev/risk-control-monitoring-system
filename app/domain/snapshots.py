"""把可变业务实体转换成不可变事件载荷。

Order/Position 仍由旧 Service 更新，但事件不能持有它们的引用。
以下快照仅包含不可变字段，平仓或撤单不会改写此前记录的事实。
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.domain.entities import Order, Position
from app.domain.enums import OrderSide, OrderStatus, PositionStatus
from app.domain.market import InstrumentId


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    id: UUID
    account_id: UUID
    instrument_id: InstrumentId
    side: OrderSide
    volume: Decimal
    requested_price: Decimal
    status: OrderStatus
    filled_price: Decimal | None
    reject_reason: str | None
    strategy_id: str | None
    signal_id: UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_order(cls, order: Order) -> "OrderSnapshot":
        return cls(
            id=order.id, account_id=order.account_id,
            instrument_id=order.instrument_id, side=order.side,
            volume=order.volume, requested_price=order.requested_price,
            status=order.status, filled_price=order.filled_price,
            reject_reason=order.reject_reason, strategy_id=order.strategy_id,
            signal_id=order.signal_id, created_at=order.created_at,
            updated_at=order.updated_at,
        )


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    id: UUID
    account_id: UUID
    opening_order_id: UUID
    instrument_id: InstrumentId
    side: OrderSide
    volume: Decimal
    open_price: Decimal
    status: PositionStatus
    close_price: Decimal | None
    realized_pnl: Decimal | None
    opened_at: datetime
    closed_at: datetime | None
    strategy_id: str | None

    @classmethod
    def from_position(cls, position: Position) -> "PositionSnapshot":
        return cls(
            id=position.id, account_id=position.account_id,
            opening_order_id=position.opening_order_id,
            instrument_id=position.instrument_id, side=position.side,
            volume=position.volume, open_price=position.open_price,
            status=position.status, close_price=position.close_price,
            realized_pnl=position.realized_pnl, opened_at=position.opened_at,
            closed_at=position.closed_at, strategy_id=position.strategy_id,
        )


@dataclass(frozen=True, slots=True)
class AccountSettlement:
    """一次平仓造成的余额变化；不是完整的账户账本。"""

    account_id: UUID
    position_id: UUID
    realized_pnl_delta: Decimal
    balance: Decimal
    realized_pnl: Decimal
