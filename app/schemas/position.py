"""持仓响应模型。"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import OrderSide, PositionStatus


class PositionResponse(BaseModel):
    """持仓静态信息与动态盈亏的组合视图。

    current_price 和 unrealized_pnl 不保存在 Position 实体中，而是在查询时计算。
    """

    id: UUID
    account_id: UUID
    opening_order_id: UUID
    symbol: str
    side: OrderSide
    volume: Decimal
    open_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    status: PositionStatus
    close_price: Decimal | None
    realized_pnl: Decimal | None
    opened_at: datetime
    closed_at: datetime | None
