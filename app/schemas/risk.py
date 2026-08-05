"""账户风控配置与风控决定的 API 模型。"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


PositiveDecimal = Annotated[
    Decimal,
    Field(gt=0, max_digits=18, decimal_places=6),
]


class RiskRuleUpdate(BaseModel):
    """完整替换一套账户风控规则所需的字段。"""

    max_order_volume: PositiveDecimal
    max_order_notional: PositiveDecimal
    max_open_positions: int = Field(ge=1, le=10000)
    allowed_symbols: list[str] = Field(min_length=1, max_length=100)
    daily_loss_limit: PositiveDecimal

    @field_validator("allowed_symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        """统一转为大写、去重，并拒绝空品种。"""
        symbols: list[str] = []
        for value in values:
            symbol = value.strip().upper()
            if not symbol:
                raise ValueError("允许交易的品种不能为空")
            if symbol not in symbols:
                symbols.append(symbol)
        return symbols


class RiskRuleResponse(BaseModel):
    """账户当前生效的风控规则。"""

    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    max_order_volume: Decimal
    max_order_notional: Decimal
    max_open_positions: int
    allowed_symbols: tuple[str, ...]
    daily_loss_limit: Decimal


class RiskDecisionResponse(BaseModel):
    """一次订单风控检查留下的审计结果。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    passed: bool
    failed_rule: str | None
    reason: str | None
    evaluated_at: datetime
