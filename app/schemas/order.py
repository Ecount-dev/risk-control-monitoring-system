"""订单 API 的请求与响应模型。"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import OrderSide, OrderStatus


PositiveTradingDecimal = Annotated[
    Decimal,
    Field(gt=0, max_digits=18, decimal_places=6),
]


class OrderCreate(BaseModel):
    """提交新订单时的字段级约束。

    这里只检查通用格式；账户是否可用、是否超过账户限额由 RiskService 检查。
    """

    symbol: str = Field(min_length=1, max_length=20)
    side: OrderSide
    volume: PositiveTradingDecimal
    requested_price: PositiveTradingDecimal

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        """将 xauusd 等输入标准化为 XAUUSD。"""
        value = value.strip().upper()
        if not value:
            raise ValueError("交易品种不能为空")
        return value


class OrderResponse(BaseModel):
    """订单的完整查询结果。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    symbol: str
    side: OrderSide
    volume: Decimal
    requested_price: Decimal
    status: OrderStatus
    reject_reason: str | None
    filled_price: Decimal | None
    created_at: datetime
    updated_at: datetime


class FillOrderResponse(BaseModel):
    """模拟成交后，同时返回终态订单和新建持仓。"""

    order: OrderResponse
    position: "PositionResponse"


# 放在类定义后导入，避免类型声明阶段的循环引用问题。
from app.schemas.position import PositionResponse  # noqa: E402
