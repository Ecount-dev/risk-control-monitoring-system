"""账户 API 的请求与响应模型。"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import AccountStatus


# Decimal 避免 float 无法精确表示十进制金额的问题。
Money = Annotated[
    Decimal,
    Field(max_digits=18, decimal_places=6),
]


class AccountCreate(BaseModel):
    """创建账户时由客户端提交的数据。"""

    name: str = Field(min_length=1, max_length=100)
    initial_balance: Annotated[
        Decimal,
        Field(ge=0, max_digits=18, decimal_places=6),
    ]

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        """去掉首尾空格，并拒绝内容全部为空格的名称。"""
        value = value.strip()
        if not value:
            raise ValueError("账户名称不能为空")
        return value


class AccountUpdate(BaseModel):
    """第一版只允许修改账户启用状态。"""

    status: AccountStatus


class AccountResponse(BaseModel):
    """返回客户端的账户公开字段。"""

    # 允许 Pydantic 从 Account 数据类的属性读取字段，而不只接受字典。
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: AccountStatus
    balance: Money
    realized_pnl: Money
    created_at: datetime
